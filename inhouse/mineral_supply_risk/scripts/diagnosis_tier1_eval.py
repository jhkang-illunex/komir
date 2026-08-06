# -*- coding: utf-8 -*-
"""Tier1 신규 피처 검정 — 공급국 흐름·CO/LI COT·생산국 통화·중국 OI
(2026-07-24, collect_tier1_feeds.py 후속).

⚠ 평가 시점 컷(사용자 지시): 검정 패널은 **발주처 제공 데이터로 산출 가능한
시점까지만** 사용한다 — build_panel이 발주처 정답셋(fact_diagnosis_answer)·주간
마트와 inner join하므로 패널 종점이 자동으로 발주처 한계(마트 2026-06-08)에
맞춰지며, 자체 수집분이 그보다 최신이어도 검정에는 들어가지 않는다(수집은 cron으로
계속). 리포트에 패널 종점을 실측 명기한다.

피처 그룹(전부 as-of 누수방지·세그먼트/신선도 처리):
  SUP  : 광종별 최대 공급국 물리 흐름(월간, 2016~) — NI←인니 수출, LI←호주 수출,
         CU←칠레 정광 수출, REE←중국의 미얀마산 수입. sup_yoy/chg3/z24, avail=+75일
         (칠레·호주·인니 보고 지연이 중국보다 김 — 보수적 통일).
  COT2 : CO/LI 매니지드머니 순포지션 %OI(주간) — cot2_l/chg13, avail=+5일(금요일 발표).
         ⚠2022-11 시작 — 부분 커버리지 교란 플래그(폴드1·2 학습 미커버).
  FXP  : 인니 루피아/달러 4주 변화 — **NI 행에만** 부여(물리 메커니즘이 인니 니켈
         공급 유인이므로 광종 특정), avail=+7일.
  CNOI : 중국 선물 미결제약정 z52/chg13 — NI/CU/LI 각각 자국 계약, avail=+3일.

검정축: 광종별(각 광종 현행 최적 구성 대비 신규 그룹 추가) + 풀링(채택 동작점
INV+CNINV+PMICN 대비) + 후보 개선 부트스트랩.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_tier1_eval
산출: outputs/model_opt/diagnosis_tier1_eval.md
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
    build_trd, build_pmi, PMI_F, bootstrap_diff,
)

SUP_F = ["sup_yoy", "sup_chg3", "sup_z24"]
COT2_F = ["cot2_l", "cot2_chg13"]
FXP_F = ["idr_chg4"]
CNOI_F = ["cnoi_z52", "cnoi_chg13"]

SUP_MAP = {"NI": "ID_NI_EXPORT_WGT", "LI": "AU_LI_EXPORT_WGT",
           "CU": "CL_CU_EXPORT_WGT", "REE": "CN_REE_IMPORT_MMR_WGT"}
COT2_MAP = {"CO": "COT_CO_NETPCT_W", "LI": "COT_LI_NETPCT_W"}
CNOI_MAP = {"NI": "SHFE_NI_OI_W", "CU": "SHFE_CU_OI_W", "LI": "GFEX_LC_OI_W"}


def build_tier1(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    sup = con.execute("""SELECT commodity_code, indicator,
            CAST(obs_date AS DATE) obs_date, val FROM fact_indicator
        WHERE src='UN_COMTRADE' AND indicator IN
            ('ID_NI_EXPORT_WGT','AU_LI_EXPORT_WGT','CL_CU_EXPORT_WGT',
             'CN_REE_IMPORT_MMR_WGT')
        ORDER BY 1,3""").df()
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date, val
        FROM fact_series WHERE src IN ('CFTC_SOCRATA','ECB_PUBLIC','SINA_FUTURES')
        ORDER BY 1,2""").df()
    con.close()
    for d in (sup, ser):
        d["obs_date"] = pd.to_datetime(d["obs_date"]).astype("datetime64[ns]")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")

    # ── SUP: 광종별 단일 시리즈 매핑 확인 후 월간 피처 ──
    sup = sup[[SUP_MAP.get(cc) == ind for cc, ind in
               zip(sup["commodity_code"], sup["indicator"])]]
    sup = sup.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    g = sup.groupby("commodity_code")["val"]
    sup["sup_yoy"] = g.transform(lambda s: s.pct_change(12))
    sup["sup_chg3"] = g.transform(lambda s: s.pct_change(3))
    sup["sup_z24"] = g.transform(
        lambda s: (s - s.rolling(24, min_periods=12).mean())
        / s.rolling(24, min_periods=12).std().replace(0, np.nan))
    sup[SUP_F] = sup[SUP_F].replace([np.inf, -np.inf], np.nan)
    sup["avail_date"] = sup["obs_date"] + pd.Timedelta(days=75)
    panel = _asof_join(panel, sup, SUP_F, by_commodity=True)

    # ── COT2 / CNOI: 광종 매핑 시리즈 → 주간 피처(광종별 조인) ──
    def per_cc_series(mapping: dict, feats: list[str], fns: dict, lag_days: int,
                      pan: pd.DataFrame) -> pd.DataFrame:
        frames = []
        for cc, code in mapping.items():
            x = ser[ser["series_code"] == code].sort_values("obs_date").copy()
            if len(x) == 0:
                continue
            x["commodity_code"] = cc
            for name, fn in fns.items():
                x[name] = fn(pd.to_numeric(x["val"], errors="coerce"))
            x["avail_date"] = x["obs_date"] + pd.Timedelta(days=lag_days)
            frames.append(x)
        if not frames:
            for f in feats:
                pan[f] = np.nan
            return pan
        allx = pd.concat(frames, ignore_index=True)
        allx[feats] = allx[feats].replace([np.inf, -np.inf], np.nan)
        return _asof_join(pan, allx, feats, by_commodity=True)

    panel = per_cc_series(
        COT2_MAP, COT2_F,
        {"cot2_l": lambda v: v, "cot2_chg13": lambda v: v.diff(13)}, 5, panel)
    panel = per_cc_series(
        CNOI_MAP, CNOI_F,
        {"cnoi_z52": lambda v: (v - v.rolling(52, min_periods=20).mean())
            / v.rolling(52, min_periods=20).std().replace(0, np.nan),
         "cnoi_chg13": lambda v: v.pct_change(13)}, 3, panel)

    # ── FXP: 인니 루피아 — NI 행에만 ──
    idr = ser[ser["series_code"] == "IDRUSD_W"].sort_values("obs_date").copy()
    idr["idr_chg4"] = pd.to_numeric(idr["val"], errors="coerce").pct_change(4)
    idr["avail_date"] = idr["obs_date"] + pd.Timedelta(days=7)
    panel = _asof_join(panel, idr, FXP_F, by_commodity=False)
    panel.loc[panel["commodity_code"] != "NI", "idr_chg4"] = np.nan
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
    df = build_trd(db, df)
    df = build_pmi(db, df)
    df = build_tier1(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    for c in ["sup_yoy", "cot2_l", "cnoi_z52", "idr_chg4"]:
        cov = df.groupby("commodity_code")[c].apply(lambda s: float(s.notna().mean()))
        print(f"{c} 커버리지: {cov[cov > 0].round(2).to_dict()}")

    ADOPTED = nolag + INV_F + exch.CNINV_F + PMI_F   # v1.9 채택 동작점
    results = []
    # 광종별 축
    per_cc_tests = {
        "NI": [("현행최적(INV+CNINV)", nolag + INV_F + exch.CNINV_F),
               ("+SUP(인니수출)", nolag + INV_F + exch.CNINV_F + SUP_F),
               ("+FXP(루피아)", nolag + INV_F + exch.CNINV_F + FXP_F),
               ("+CNOI(OI)", nolag + INV_F + exch.CNINV_F + CNOI_F),
               ("+SUP+FXP+CNOI", nolag + INV_F + exch.CNINV_F + SUP_F + FXP_F + CNOI_F)],
        "CU": [("NOLAG(현행무추가)", nolag),
               ("+SUP(칠레수출)", nolag + SUP_F),
               ("+CNOI(OI)", nolag + CNOI_F),
               ("+SUP+CNOI", nolag + SUP_F + CNOI_F)],
        "REE": [("NOLAG", nolag), ("+SUP(미얀마수입)", nolag + SUP_F)],
        "CO": [("NOLAG", nolag), ("+COT2(포지셔닝)", nolag + COT2_F)],
        "LI": [("NOLAG", nolag), ("+SUP+COT2+CNOI", nolag + SUP_F + COT2_F + CNOI_F)],
    }
    for cc, tests in per_cc_tests.items():
        d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
        for tag, feats in tests:
            r = e2_delta_classifier(d1, feats, "Logistic")
            results.append(dict(축=f"{cc}만", 구성=tag, **r))
    # 풀링 축
    for tag, feats in [("채택 동작점(v1.9)", ADOPTED),
                        ("+SUP", ADOPTED + SUP_F), ("+COT2", ADOPTED + COT2_F),
                        ("+CNOI", ADOPTED + CNOI_F),
                        ("+전부", ADOPTED + SUP_F + COT2_F + CNOI_F + FXP_F)]:
        r = e2_delta_classifier(df, feats, "Logistic")
        results.append(dict(축="풀링", 구성=tag, **r))
    tab = pd.DataFrame(results)
    print(tab.round(4).to_string(index=False))

    # 풀링 최대 확장 부트스트랩(채택 동작점 대비)
    rng = np.random.default_rng(0)
    bs = bootstrap_diff(df, ADOPTED, ADOPTED + SUP_F + COT2_F + CNOI_F + FXP_F, nolag, rng)
    print(f"\n풀링 +전부 vs 채택동작점: QWK차이 CI [{bs['qwk_ci'][0]:+.3f},"
          f"{bs['qwk_ci'][1]:+.3f}] P={bs['qwk_p']:.3f} | chg차이 CI "
          f"[{bs['chg_ci'][0]:+.3f},{bs['chg_ci'][1]:+.3f}] P={bs['chg_p']:.3f} | "
          f"비전환오류 {bs['steady_err'][0]}→{bs['steady_err'][1]}")
    write_report(df, tab, bs)


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def write_report(df, tab, bs):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_tier1_eval.md")
    L = []
    L.append("# Tier1 신규 피처 검정 — 공급국 흐름·CO/LI COT·생산국 통화·중국 OI\n")
    L.append(f"작성: 2026-07-24 · **평가 패널 종점 {df['obs_date'].max().date()}"
             f"(발주처 정답·마트 한계) — 사용자 지시대로 발주처 데이터로 산출 가능한 "
             f"시점까지만 검정에 사용, 자체 수집 최신분은 미사용(수집은 cron 지속)**. "
             f"프레임: E2 Δ타깃 Logistic·워크포워드 3폴드·as-of 누수방지. "
             f"⚠COT2는 2022-11 시작(부분 커버리지 — 교란 가능성 플래그).\n")
    L.append("\n| 축 | 구성 | QWK | acc | chg_acc | up_acc | n_chg | FAR |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['축']} | {r['구성']} | {_fmt(r['QWK'])} | {_fmt(r['acc'])} | "
                 f"{_fmt(r['chg_acc'])} | {_fmt(r['up_acc'])} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'])} |")
    L.append(f"\n## 부트스트랩(풀링 +전부 vs 채택 동작점)\n")
    L.append(f"- QWK차이 95% CI [{bs['qwk_ci'][0]:+.3f}, {bs['qwk_ci'][1]:+.3f}] "
             f"(P={bs['qwk_p']:.3f}), chg_acc차이 CI [{bs['chg_ci'][0]:+.3f}, "
             f"{bs['chg_ci'][1]:+.3f}] (P={bs['chg_p']:.3f}), 비전환주 오류 "
             f"{bs['steady_err'][0]}→{bs['steady_err'][1]}건")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[tier1_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
