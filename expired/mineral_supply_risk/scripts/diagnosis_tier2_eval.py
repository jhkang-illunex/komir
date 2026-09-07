# -*- coding: utf-8 -*-
"""Tier2 신규 피처 검정 — 칠레 생산·CO LME재고(USGS)·반도체 빌링·한국 산업생산/재고
(2026-07-25, collect_tier2_feeds.py 후속. 프레임은 diagnosis_tier1_eval과 동일).

⚠ 평가 시점 컷: 검정 패널은 발주처 제공 데이터로 산출 가능한 시점까지만
(build_panel inner join으로 자동 — 마트 2026-06-08). 자체 수집 최신분 미사용.

피처 그룹(전부 as-of 누수방지):
  CLP   : 칠레 구리 생산(Cochilco tabla21, 월간 2015~) — clp_yoy/chg3/z24, **CU만**.
          avail=+70일(2026-05 데이터가 2026-07 호 게재 실측 — 지연 ~2개월).
  COINV : CO LME 금속재고(USGS MIS T1, 월말 2018-12~) — coinv_z24/chg6, **CO만**.
          avail=+210일(202512호가 2026-07 현재 최신 = 발행지연 ~7개월 실측 —
          정직 반영. 2019-06 이전 z24 워밍업 → 실효 커버리지 2020-11~).
          ⚠부분 커버리지(폴드1 학습 일부 미커버) 교란 플래그.
  SEMI  : WSTS 세계 반도체 빌링(월간 1986~) — semi_yoy/chg3, **CU·REE만**
          (전방 전자산업). avail=+40일(SIA 익월 초 발표).
  KIP   : 한국 산업생산 원지수(ECOS 901Y032, 월간 2006~) — kip_yoy/chg3,
          광종별 전방산업 매핑(CU→전자부품, NI→1차금속, LI·CO→전기장비(이차전지),
          REE→자동차(Nd 모터)). avail=+40일(통계청 익월 말+여유).
  KINV  : 한국 1차금속 재고 원지수 — kinv_z24/chg3, **CU·NI만**(금속 재고축).
          avail=+40일.

검정축: 광종별(각 광종 현행 채택 구성 대비 신규 그룹 추가) + 풀링(채택 동작점
INV+CNINV+PMICN 대비) + 후보 부트스트랩(광종별 최대 개선 후보·풀링 최대 확장).

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_tier2_eval
산출: outputs/model_opt/diagnosis_tier2_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics                # noqa: E402
from scripts.diagnosis_aux_features_eval import (                          # noqa: E402
    build_aux, INV_F, _asof_join, e2_delta_classifier,
)
import scripts.diagnosis_exch_inventory_eval as exch                       # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                        # noqa: E402
    build_pmi, PMI_F, bootstrap_diff,
)
from scripts.diagnosis_tier1_eval import build_tier1, CNOI_F               # noqa: E402

CLP_F = ["clp_yoy", "clp_chg3", "clp_z24"]
COINV_F = ["coinv_z24", "coinv_chg6"]
SEMI_F = ["semi_yoy", "semi_chg3"]
KIP_F = ["kip_yoy", "kip_chg3"]
KINV_F = ["kinv_z24", "kinv_chg3"]

KIP_MAP = {"CU": "KIP_ELEC_M", "NI": "KIP_METAL_M", "LI": "KIP_ELEQ_M",
           "CO": "KIP_ELEQ_M", "REE": "KIP_AUTO_M"}


def _zroll(s: pd.Series, w: int, mp: int) -> pd.Series:
    return (s - s.rolling(w, min_periods=mp).mean()) \
        / s.rolling(w, min_periods=mp).std().replace(0, np.nan)


def build_tier2(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT commodity_code, indicator,
            CAST(obs_date AS DATE) obs_date, val FROM fact_indicator
        WHERE indicator IN ('CL_CU_PROD_MINE','CO_LME_STOCK_T')
        ORDER BY 1,3""").df()
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date, val
        FROM fact_series WHERE src IN ('WSTS_PUBLIC','ECOS_API')
        ORDER BY 1,2""").df()
    con.close()
    for d in (ind, ser):
        d["obs_date"] = pd.to_datetime(d["obs_date"]).astype("datetime64[ns]")
        d["val"] = pd.to_numeric(d["val"], errors="coerce")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")

    # ── CLP: 칠레 광산 생산 → CU만 ──
    clp = ind[ind["indicator"] == "CL_CU_PROD_MINE"].sort_values("obs_date").copy()
    v = clp["val"]
    clp["clp_yoy"] = v.pct_change(12)
    clp["clp_chg3"] = v.pct_change(3)
    clp["clp_z24"] = _zroll(v, 24, 12)
    clp[CLP_F] = clp[CLP_F].replace([np.inf, -np.inf], np.nan)
    clp["avail_date"] = clp["obs_date"] + pd.Timedelta(days=70)
    panel = _asof_join(panel, clp, CLP_F, by_commodity=False)
    panel.loc[panel["commodity_code"] != "CU", CLP_F] = np.nan

    # ── COINV: CO LME 재고 → CO만 ──
    co = ind[ind["indicator"] == "CO_LME_STOCK_T"].sort_values("obs_date").copy()
    v = co["val"]
    co["coinv_z24"] = _zroll(v, 24, 12)
    co["coinv_chg6"] = v.pct_change(6)
    co[COINV_F] = co[COINV_F].replace([np.inf, -np.inf], np.nan)
    co["avail_date"] = co["obs_date"] + pd.Timedelta(days=210)
    panel = _asof_join(panel, co, COINV_F, by_commodity=False)
    panel.loc[panel["commodity_code"] != "CO", COINV_F] = np.nan

    # ── SEMI: WSTS 세계 빌링 → CU·REE만 ──
    sw = ser[ser["series_code"] == "WSTS_BILL_WW_M"].sort_values("obs_date").copy()
    v = sw["val"]
    sw["semi_yoy"] = v.pct_change(12)
    sw["semi_chg3"] = v.pct_change(3)
    sw[SEMI_F] = sw[SEMI_F].replace([np.inf, -np.inf], np.nan)
    sw["avail_date"] = sw["obs_date"] + pd.Timedelta(days=40)
    panel = _asof_join(panel, sw, SEMI_F, by_commodity=False)
    panel.loc[~panel["commodity_code"].isin(["CU", "REE"]), SEMI_F] = np.nan

    # ── KIP: 광종별 전방산업 생산 ──
    frames = []
    for cc, code in KIP_MAP.items():
        x = ser[ser["series_code"] == code].sort_values("obs_date").copy()
        if len(x) == 0:
            continue
        x["commodity_code"] = cc
        v = x["val"]
        x["kip_yoy"] = v.pct_change(12)
        x["kip_chg3"] = v.pct_change(3)
        x["avail_date"] = x["obs_date"] + pd.Timedelta(days=40)
        frames.append(x)
    allx = pd.concat(frames, ignore_index=True)
    allx[KIP_F] = allx[KIP_F].replace([np.inf, -np.inf], np.nan)
    panel = _asof_join(panel, allx, KIP_F, by_commodity=True)

    # ── KINV: 한국 1차금속 재고 → CU·NI만 ──
    ki = ser[ser["series_code"] == "KINV_METAL_M"].sort_values("obs_date").copy()
    v = ki["val"]
    ki["kinv_z24"] = _zroll(v, 24, 12)
    ki["kinv_chg3"] = v.pct_change(3)
    ki[KINV_F] = ki[KINV_F].replace([np.inf, -np.inf], np.nan)
    ki["avail_date"] = ki["obs_date"] + pd.Timedelta(days=40)
    panel = _asof_join(panel, ki, KINV_F, by_commodity=False)
    panel.loc[~panel["commodity_code"].isin(["CU", "NI"]), KINV_F] = np.nan
    return panel


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    print(f"⚠ 평가 패널 종점(발주처 데이터 컷): {df['obs_date'].max().date()} — "
          f"자체 수집 최신분은 검정에 미사용(수집은 cron 지속)")
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_pmi(db, df)
    df = build_tier1(db, df)   # CU 현행 채택 구성(+CNOI)용
    df = build_tier2(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    for c in ["clp_yoy", "coinv_z24", "semi_yoy", "kip_yoy", "kinv_z24"]:
        cov = df.groupby("commodity_code")[c].apply(lambda s: float(s.notna().mean()))
        print(f"{c} 커버리지: {cov[cov > 0].round(2).to_dict()}")

    ADOPTED = nolag + INV_F + exch.CNINV_F + PMI_F   # v1.9 채택 동작점
    results = []
    per_cc_tests = {
        "CU": [("현행채택(+CNOI)", nolag + CNOI_F),
               ("+CLP(칠레생산)", nolag + CNOI_F + CLP_F),
               ("+SEMI(반도체)", nolag + CNOI_F + SEMI_F),
               ("+KIP(전자부품)", nolag + CNOI_F + KIP_F),
               ("+KINV(1차금속재고)", nolag + CNOI_F + KINV_F),
               ("+CLP+SEMI", nolag + CNOI_F + CLP_F + SEMI_F)],
        "NI": [("현행채택(INV+CNINV)", nolag + INV_F + exch.CNINV_F),
               ("+KIP(1차금속)", nolag + INV_F + exch.CNINV_F + KIP_F),
               ("+KINV(재고)", nolag + INV_F + exch.CNINV_F + KINV_F)],
        "CO": [("NOLAG", nolag),
               ("+COINV(LME재고)", nolag + COINV_F),
               ("+KIP(전기장비)", nolag + KIP_F)],
        "LI": [("NOLAG", nolag), ("+KIP(전기장비)", nolag + KIP_F)],
        "REE": [("NOLAG", nolag),
                ("+SEMI(반도체)", nolag + SEMI_F),
                ("+KIP(자동차)", nolag + KIP_F),
                ("+SEMI+KIP", nolag + SEMI_F + KIP_F)],
    }
    for cc, tests in per_cc_tests.items():
        d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
        for tag, feats in tests:
            r = e2_delta_classifier(d1, feats, "Logistic")
            results.append(dict(축=f"{cc}만", 구성=tag, **r))
    for tag, feats in [("채택 동작점(v1.9)", ADOPTED),
                        ("+SEMI", ADOPTED + SEMI_F), ("+KIP", ADOPTED + KIP_F),
                        ("+KINV", ADOPTED + KINV_F),
                        ("+전부", ADOPTED + SEMI_F + KIP_F + KINV_F)]:
        r = e2_delta_classifier(df, feats, "Logistic")
        results.append(dict(축="풀링", 구성=tag, **r))
    tab = pd.DataFrame(results)
    print(tab.round(4).to_string(index=False))

    # 부트스트랩: 풀링 최대 확장 + 광종별 QWK 최대 개선 후보
    rng = np.random.default_rng(0)
    bs_rows = []
    bs = bootstrap_diff(df, ADOPTED, ADOPTED + SEMI_F + KIP_F + KINV_F, nolag, rng)
    bs_rows.append(("풀링 +전부 vs 채택동작점", bs))
    base_by_cc = {cc: tests[0] for cc, tests in per_cc_tests.items()}
    for cc, tests in per_cc_tests.items():
        d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
        base_tag, base_feats = base_by_cc[cc]
        sub = tab[(tab["축"] == f"{cc}만") & (tab["구성"] != base_tag)]
        if sub.empty or sub["QWK"].isna().all():
            continue
        best = sub.loc[sub["QWK"].idxmax()]
        base_row = tab[(tab["축"] == f"{cc}만") & (tab["구성"] == base_tag)].iloc[0]
        if not (best["QWK"] > base_row["QWK"]):
            continue
        cand_feats = dict(tests)[best["구성"]]
        b = bootstrap_diff(d1, base_feats, cand_feats, nolag, rng)
        bs_rows.append((f"{cc} {best['구성']} vs {base_tag}", b))
    for name, b in bs_rows:
        print(f"{name}: QWK차이 CI [{b['qwk_ci'][0]:+.3f},{b['qwk_ci'][1]:+.3f}] "
              f"P={b['qwk_p']:.3f} | chg차이 CI [{b['chg_ci'][0]:+.3f},"
              f"{b['chg_ci'][1]:+.3f}] P={b['chg_p']:.3f} | 비전환오류 "
              f"{b['steady_err'][0]}→{b['steady_err'][1]}")
    write_report(df, tab, bs_rows)


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def write_report(df, tab, bs_rows):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_tier2_eval.md")
    L = []
    L.append("# Tier2 신규 피처 검정 — 칠레 생산·CO LME재고·반도체 빌링·한국 산업생산/재고\n")
    L.append(f"작성: 2026-07-25 · **평가 패널 종점 {df['obs_date'].max().date()}"
             f"(발주처 정답·마트 한계)**. 프레임: E2 Δ타깃 Logistic·워크포워드 3폴드·"
             f"as-of 누수방지(지연 실측 반영: CLP+70일·COINV+210일·SEMI/KIP/KINV+40일). "
             f"⚠COINV는 2018-12 시작+z24 워밍업(부분 커버리지 교란 플래그).\n")
    L.append("\n| 축 | 구성 | QWK | acc | chg_acc | up_acc | n_chg | FAR |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['축']} | {r['구성']} | {_fmt(r['QWK'])} | {_fmt(r['acc'])} | "
                 f"{_fmt(r['chg_acc'])} | {_fmt(r['up_acc'])} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'])} |")
    L.append("\n## 부트스트랩(4000회 주 리샘플)\n")
    for name, b in bs_rows:
        L.append(f"- **{name}**: QWK차이 95% CI [{b['qwk_ci'][0]:+.3f}, "
                 f"{b['qwk_ci'][1]:+.3f}] (P={b['qwk_p']:.3f}), chg_acc차이 CI "
                 f"[{b['chg_ci'][0]:+.3f}, {b['chg_ci'][1]:+.3f}] (P={b['chg_p']:.3f}), "
                 f"비전환주 오류 {b['steady_err'][0]}→{b['steady_err'][1]}건")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[tier2_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
