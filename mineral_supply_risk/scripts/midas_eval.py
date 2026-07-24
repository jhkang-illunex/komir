# -*- coding: utf-8 -*-
"""MIDAS(Mixed Data Sampling) 혼합주기 검정 — 주간→월간(예측)·월간→주간(진단)
(2026-07-25, 사용자 지시 "서로 다른 주기 데이터를 MIDAS로 혼합해 최적 피처·모델 탐색").

현행 구조의 주기 혼합은 조악하다: 예측모델은 주간 외생(가격·지수·환율)을 **월평균**
으로 뭉개고, 진단모델은 월간 피처를 **as-of 최신값 1점**으로만 쓴다. MIDAS는 이
사이를 메운다:
  [예측] 월간 타깃 ← 주간 피처의 지수감쇠 가중합(exp-Almon 근사, λ 그리드
         {0(균등), 0.2(완만), 0.6(중간), 1.5(최근집중)}, 창 13주) + U-MIDAS lite
         (마지막 주 레벨 w0 + 13주 기울기 slope). 대상 주간 시계열: LME 가격·
         지정학지수·LME/SHFE/GFEX 재고·중국 OI·COT 구리·원달러 환율.
  [진단] 주간 타깃 ← 월간 PMI의 U-MIDAS(최근 3개월 시차를 개별 피처로) —
         현행 PMI_F(레벨+3M변화 = 2점 근사)의 상위호환 검정.

모델: 예측 = HistGBM(현행 계열)·ElasticNet(MIDAS 본래의 선형 회귀 정합) ×
피처 변형. 진단 = Logistic(챔피언 계열) Δ프레임. 평가 프레임·패널 종점은 기존과
동일(WAPE 오리진 6개 / 워크포워드 3폴드). CU SHFE 재고 복구(2026-07-25) 반영 상태.

실행: MSR_DB=<warehouse> python -m scripts.midas_eval
산출: outputs/model_opt/midas_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                                # noqa: E402
import msr.models.forecast_unit as fu                                     # noqa: E402
from scripts.forecast_exog_eval import seasonal_naive                     # noqa: E402
from scripts.forecast_alt_refit import wape_eval_alt                      # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import (                          # noqa: E402
    add_dynamics, e2_delta_classifier,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F, _asof_join  # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                      # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                       # noqa: E402
    build_pmi, PMI_F, bootstrap_diff,
)

LAMBDAS = {"l0": 0.0, "l02": 0.2, "l06": 0.6, "l15": 1.5}
K = 13   # 주간 lookback 창


# ─────────────────── 주간 시계열 로드(광종별/공통) ───────────────────
def load_weekly(db: str) -> dict[str, pd.DataFrame]:
    """반환: {name: df(commodity_code|None, week, val)} — 광종 무관 시리즈는 cc=None."""
    con = duckdb.connect(db, read_only=True)
    out = {}
    out["wpx"] = con.execute("""SELECT commodity_code, CAST(obs_date AS DATE) AS wk,
        CAST(val AS DOUBLE) val FROM fact_price
        WHERE freq='W' AND price_type IN ('LME_CASH','REF') ORDER BY 1,2""").df()
    out["wgeo"] = con.execute("""SELECT commodity_code, CAST(period AS DATE) AS wk,
        CAST(idx_value AS DOUBLE) val FROM geo_index WHERE freq='W' ORDER BY 1,2""").df()
    inv1 = con.execute("""SELECT commodity_code, CAST(obs_date AS DATE) AS wk,
        CAST(val AS DOUBLE) val FROM fact_inventory ORDER BY 1,2""").df()
    inv2 = con.execute("""SELECT commodity_code, CAST(obs_date AS DATE) AS wk,
        CAST(val AS DOUBLE) val FROM fact_inventory_exch
        WHERE src IN ('SHFE_99QH_W','GFEX_OFFICIAL_W') ORDER BY 1,2""").df()
    out["winv"] = inv1          # LME 재고(CU·NI)
    out["wcninv"] = inv2        # SHFE CU/NI·GFEX LI
    oi = con.execute("""SELECT series_code, CAST(obs_date AS DATE) AS wk,
        CAST(val AS DOUBLE) val FROM fact_series
        WHERE series_code IN ('SHFE_CU_OI_W','SHFE_NI_OI_W','GFEX_LC_OI_W')
        ORDER BY 1,2""").df()
    oi["commodity_code"] = oi["series_code"].map(
        {"SHFE_CU_OI_W": "CU", "SHFE_NI_OI_W": "NI", "GFEX_LC_OI_W": "LI"})
    out["woi"] = oi[["commodity_code", "wk", "val"]]
    cot = con.execute("""SELECT CAST(obs_date AS DATE) AS wk, CAST(val AS DOUBLE) val
        FROM fact_series WHERE series_code='COT_CU_NETPCT_W' ORDER BY 1""").df()
    cot["commodity_code"] = None
    out["wcot"] = cot
    fx = con.execute("""SELECT CAST(obs_date AS DATE) AS wk, CAST(val AS DOUBLE) val
        FROM fact_series WHERE series_code='USDKRW_W' ORDER BY 1""").df()
    fx["commodity_code"] = None
    out["wfx"] = fx
    con.close()
    for d in out.values():
        d.rename(columns={"wk": "week"}, inplace=True)
        d["week"] = pd.to_datetime(d["week"])
    return out


def midas_monthly(wdf: pd.DataFrame, name: str, lambdas: dict[str, float],
                  umidas: bool, log: bool) -> pd.DataFrame:
    """주간 시계열 → 월별 MIDAS 피처. 각 월 m: 월말 이전 최근 K주 가중합.
    log=True면 log1p 변환 후 가중(재고·가격류 스케일 안정화)."""
    rows = []
    for cc, g in wdf.groupby("commodity_code", dropna=False):
        g = g.sort_values("week").reset_index(drop=True)
        v = np.log1p(g["val"].clip(lower=0)) if log else g["val"]
        v = v.to_numpy(dtype=float)
        wk = g["week"].to_numpy()
        months = pd.period_range(pd.Timestamp(wk[0]).to_period("M"),
                                 pd.Timestamp(wk[-1]).to_period("M"), freq="M")
        for m in months:
            end = m.to_timestamp(how="end")
            i = np.searchsorted(wk, np.datetime64(end), side="right")
            seg = v[max(0, i - K):i][::-1]          # seg[0]=가장 최근 주
            if len(seg) < 4:
                continue
            r = {"commodity_code": cc, "month": m.to_timestamp()}
            for tag, lam in lambdas.items():
                w = np.exp(-lam * np.arange(len(seg)))
                w /= w.sum()
                r[f"{name}_{tag}"] = float(np.nansum(w * seg))
            if umidas:
                r[f"{name}_w0"] = float(seg[0])
                r[f"{name}_slope"] = float(seg[0] - seg[-1])
            rows.append(r)
    return pd.DataFrame(rows)


def build_midas_panel(db: str, panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    wk = load_weekly(db)
    panel = panel.copy()
    panel["month"] = pd.to_datetime(panel["month"])
    groups = {}
    spec = [("wpx", True, True), ("wgeo", False, True), ("winv", True, True),
            ("wcninv", True, True), ("woi", True, True), ("wcot", False, True),
            ("wfx", True, True)]
    for name, log, umidas in spec:
        m = midas_monthly(wk[name], name, LAMBDAS, umidas, log)
        cols = [c for c in m.columns if c.startswith(name + "_")]
        if m["commodity_code"].notna().any():
            panel = panel.merge(m, on=["commodity_code", "month"], how="left")
        else:
            panel = panel.merge(m.drop(columns=["commodity_code"]),
                                on="month", how="left")
        groups[name] = cols
    return panel, groups


# ─────────────────── 진단 U-MIDAS(월간 PMI → 주간) ───────────────────
UM_PMI_F = ["pmi_um0", "pmi_um1", "pmi_um2", "pmicx_um0", "pmicx_um1"]


def build_umidas_pmi(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date,
        CAST(val AS DOUBLE) val FROM fact_series
        WHERE series_code IN ('CN_PMI_OFF_M','CN_PMI_CX_M') ORDER BY 1,2""").df()
    con.close()
    ser["obs_date"] = pd.to_datetime(ser["obs_date"])
    for code, pref, nlag in [("CN_PMI_OFF_M", "pmi_um", 3),
                             ("CN_PMI_CX_M", "pmicx_um", 2)]:
        x = ser[ser["series_code"] == code].sort_values("obs_date").copy()
        feats = []
        for j in range(nlag):
            f = f"{pref}{j}"
            x[f] = x["val"].shift(j)
            feats.append(f)
        # 발표 지연: 공식 PMI는 월말+1일 — 참조월+32일로 보수 통일(기존 build_pmi와 동일 눈금)
        x["avail_date"] = x["obs_date"] + pd.Timedelta(days=32)
        panel = _asof_join(panel, x, feats, by_commodity=False)
    return panel


def main():
    db = os.environ["MSR_DB"]

    # ═══ 1) 예측: 주간→월간 MIDAS ═══
    fdf = fu.build_panel(db)
    fdf, groups = build_midas_panel(db, fdf)
    base = list(fu.FEATS)
    lam_cols = lambda name: [f"{name}_{t}" for t in LAMBDAS]  # noqa: E731
    um_cols = lambda name: [f"{name}_w0", f"{name}_slope"]    # noqa: E731
    variants = {
        "BASE(현행)": base,
        "+MIDAS가격": base + lam_cols("wpx"),
        "+MIDAS지수": base + lam_cols("wgeo"),
        "+MIDAS재고": base + lam_cols("winv") + lam_cols("wcninv"),
        "+MIDAS전부(λ)": base + sum([lam_cols(n) for n in groups], []),
        "+U-MIDAS전부(w0/slope)": base + sum(
            [um_cols(n) for n, _, u in
             [("wpx", 0, 1), ("winv", 0, 1), ("wcninv", 0, 1), ("woi", 0, 1),
              ("wfx", 0, 1)]], []),
    }
    frows = [seasonal_naive(fdf).assign(variant="계절나이브")]
    for kind in ["HistGBM", "ElasticNet"]:
        for vtag, feats in variants.items():
            # 주의: lag1·roll3 등 BASE 피처는 _features()에서 생성되므로 패널
            # 컬럼 존재 여부로 필터하면 안 됨(1차 실행에서 BASE 전체가 걸러지는
            # 버그 실측 — 필터 제거)
            t = wape_eval_alt(fdf, feats, kind)
            name = f"{kind}·{vtag}"
            t["variant"] = name
            frows.append(t)
            tot = t[t["commodity"] == "전체"]
            print(f"{name}: " + " | ".join(
                f"{r['target']} WAPE {r['WAPE']:.3f}" for _, r in tot.iterrows()))
    fres = pd.concat(frows, ignore_index=True)

    # ═══ 2) 진단: 월간→주간 U-MIDAS(PMI) ═══
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    ddf = build_panel(db)
    ddf = add_dynamics(ddf); ddf = build_aux(db, ddf)
    ddf = exch.build_cninv(db, ddf); ddf = build_pmi(db, ddf)
    ddf = build_umidas_pmi(db, ddf)
    nolag = [f for f in GEO_ONLY_NO_LAG if ddf[f].notna().sum() > 50]
    ADOPTED = nolag + INV_F + exch.CNINV_F + PMI_F
    drows = []
    for tag, feats in [
        ("채택동작점(PMI 2점 근사, 챔피언)", ADOPTED),
        ("U-MIDAS PMI(3+2시차)", nolag + INV_F + exch.CNINV_F + UM_PMI_F),
        ("채택+U-MIDAS 병행", ADOPTED + UM_PMI_F),
    ]:
        r = e2_delta_classifier(ddf, feats, "Logistic")
        drows.append(dict(구성=tag, **r))
        print(f"진단 {tag}: QWK {r['QWK']:.4f} chg {r['chg_acc']:.4f} "
              f"FAR {r['FAR']:.4f}")
    dtab = pd.DataFrame(drows)
    rng = np.random.default_rng(0)
    best = dtab.iloc[dtab["QWK"].idxmax()]
    bs_line = ""
    if best["구성"] != dtab.iloc[0]["구성"]:
        feats_map = {"U-MIDAS PMI(3+2시차)": nolag + INV_F + exch.CNINV_F + UM_PMI_F,
                     "채택+U-MIDAS 병행": ADOPTED + UM_PMI_F}
        b = bootstrap_diff(ddf, ADOPTED, feats_map[best["구성"]], nolag, rng)
        bs_line = (f"{best['구성']} vs 채택동작점: QWK CI [{b['qwk_ci'][0]:+.3f},"
                   f"{b['qwk_ci'][1]:+.3f}] P={b['qwk_p']:.3f} | 비전환오류 "
                   f"{b['steady_err'][0]}→{b['steady_err'][1]}")
        print(bs_line)
    write_report(fres, dtab, bs_line)


def write_report(fres, dtab, bs_line):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "midas_eval.md")
    L = ["# MIDAS 혼합주기 검정 — 주간→월간(예측)·월간→주간(진단)\n",
         "작성: 2026-07-25 · 예측 = 주간 시계열(가격·지수·재고·OI·COT·환율)의 "
         "지수감쇠 가중 월간화(λ∈{0,0.2,0.6,1.5}, 창 13주)+U-MIDAS lite, 프레임은 "
         "기존 WAPE(오리진 6개×h12). 진단 = 월간 PMI U-MIDAS(시차 개별 피처), "
         "Δ분류 워크포워드. CU SHFE 재고 복구 반영 상태.\n",
         "\n## 예측(전체 풀링 WAPE)\n", "| 변형 | ton | unit |", "|---|---|---|"]
    piv = fres[fres["commodity"] == "전체"].pivot_table(
        index="variant", columns="target", values="WAPE", sort=False)
    for v, r in piv.iterrows():
        L.append(f"| {v} | {r.get('ton', float('nan')):.4f} | "
                 f"{r.get('unit', float('nan')):.4f} |")
    L.append("\n## 진단(Δ분류)\n")
    L.append("| 구성 | QWK | chg_acc | FAR |")
    L.append("|---|---|---|---|")
    for _, r in dtab.iterrows():
        L.append(f"| {r['구성']} | {r['QWK']:.4f} | {r['chg_acc']:.4f} | "
                 f"{r['FAR']:.4f} |")
    if bs_line:
        L.append(f"\n- 부트스트랩: {bs_line}")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[midas_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
