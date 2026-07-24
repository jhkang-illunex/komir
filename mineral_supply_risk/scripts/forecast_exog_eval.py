# -*- coding: utf-8 -*-
"""예측모델(2-4) 외생피처 검정 — COT·WoodMac·중국 PMI·한국 산업생산
(2026-07-24, 피처 인벤토리 C단계. 지금까지 검정은 전부 진단 보조신호였고
예측모델 외생피처 검정은 이번이 최초).

방법: forecast_unit의 실제 파이프라인(_features→_direct_matrix→HistGBM 풀링)을
그대로 재사용하되, 패널에 외생 월간 피처를 병합하고 FEATS를 변형별로 확장해
워크포워드 오리진 6개(2024-03~2025-06 분기별)×h=1..12 직접예측 WAPE를 비교한다.
기준선: BASE(현행 FEATS) + 계절나이브(t+h ← t+h-12 실적).

외생 변형(전부 예측 기점 base_month 이전 정보만 — as-of 시프트):
  +COT  : 구리 비상업 순포지션 %OI 월평균(당월분까지 — 주간 발표라 즉시 가용) 레벨·3M변화
          ※ CU 전용 데이터지만 풀링 모델이라 전 광종 열로 제공(타 광종은 NaN→중앙값)
  +WM   : WoodMac 연간 밸런스·재고일수 — **전년(y-1) 값**을 당해 연도 월에 매핑
          ⚠ 2026-03 단일 빈티지라 과거 연도값도 개정본 — 방향 참고 전용
  +PMICN: 중국 공식 PMI 전월값·3M변화
  +KRIP : 한국 산업생산(ECOS) 전전월 YoY(발표지연 감안 시프트 2)
  +ALL  : 전부 결합

실행: MSR_DB=<warehouse> python -m scripts.forecast_exog_eval
산출: outputs/model_opt/forecast_exog_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                      # noqa: E402
import msr.models.forecast_unit as fu                    # noqa: E402

ORIGINS = ["2024-03-01", "2024-06-01", "2024-09-01", "2024-12-01",
           "2025-03-01", "2025-06-01"]
H = 12

EXOG_GROUPS = {
    "+COT": ["cot_l", "cot_chg3"],
    "+WM": ["wm_bal_prev", "wm_days_prev"],
    "+PMICN": ["pmi_cn_l", "pmi_cn_chg3"],
    "+KRIP": ["krip_yoy"],
}


def build_exog(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    cot = con.execute("""SELECT CAST(obs_date AS DATE) d, val FROM fact_series
        WHERE series_code='COT_CU_NETPCT_W' ORDER BY 1""").df()
    pmi = con.execute("""SELECT CAST(obs_date AS DATE) d, val FROM fact_series
        WHERE series_code='CN_PMI_OFF_M' ORDER BY 1""").df()
    krip = con.execute("""SELECT period, val FROM raw_ecos
        WHERE series_name='KR_industrial_production' ORDER BY 1""").df()
    wm = con.execute("""SELECT commodity_code, indicator, CAST(obs_date AS DATE) d, val
        FROM fact_indicator WHERE src='WOODMAC_2026V'""").df()
    con.close()
    panel = panel.copy()
    panel["month"] = pd.to_datetime(panel["month"])

    # COT: 주간→월평균, 당월 레벨(발표 즉시)·3M변화
    cot["month"] = pd.to_datetime(cot["d"]).values.astype("datetime64[M]")
    cm = cot.groupby("month", as_index=False)["val"].mean().rename(columns={"val": "cot_l"})
    cm["month"] = pd.to_datetime(cm["month"])
    cm = cm.sort_values("month")
    cm["cot_chg3"] = cm["cot_l"].diff(3)
    panel = panel.merge(cm, on="month", how="left")

    # 중국 PMI: 전월값(발표가 익월 초라 base_month 시점엔 전월분까지 확실)
    pmi["month"] = pd.to_datetime(pmi["d"])
    pmi = pmi.sort_values("month").rename(columns={"val": "pmi"})
    pmi["pmi_cn_l"] = pmi["pmi"].shift(1)
    pmi["pmi_cn_chg3"] = pmi["pmi"].shift(1).diff(3)
    panel = panel.merge(pmi[["month", "pmi_cn_l", "pmi_cn_chg3"]], on="month", how="left")

    # 한국 산업생산: YYYYMM → YoY, 시프트 2(발표 지연)
    krip["month"] = pd.to_datetime(krip["period"], format="%Y%m")
    krip = krip.sort_values("month")
    krip["yoy"] = pd.to_numeric(krip["val"], errors="coerce").pct_change(12)
    krip["krip_yoy"] = krip["yoy"].shift(2)
    panel = panel.merge(krip[["month", "krip_yoy"]], on="month", how="left")

    # WoodMac: 전년 값 → 당해 연도 전체 월
    wm["yr"] = pd.to_datetime(wm["d"]).dt.year
    piv = wm.pivot_table(index=["commodity_code", "yr"], columns="indicator",
                         values="val", aggfunc="last").reset_index()
    piv = piv.rename(columns={"WM_BALANCE_A": "wm_bal_prev",
                              "WM_STOCKDAYS_A": "wm_days_prev"})
    piv["apply_yr"] = piv["yr"] + 1          # y-1 값을 y년에 적용(전년 실적만 사용)
    panel["apply_yr"] = panel["month"].dt.year
    panel = panel.merge(piv[["commodity_code", "apply_yr", "wm_bal_prev", "wm_days_prev"]],
                        on=["commodity_code", "apply_yr"], how="left")
    return panel.drop(columns=["apply_yr"])


def wape_eval(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """오리진×h 직접예측 → 실적 대비 WAPE(타깃별·광종별)."""
    fu.FEATS = feats                     # 파이프라인 전역 피처 목록 주입
    actual = df.set_index(["commodity_code", "month"])
    rows = []
    for target in ["ton", "unit"]:
        preds = []
        for o in ORIGINS:
            out = fu._direct_forecast(df, target, pd.Timestamp(o), horizon=H)
            preds.append(out)
        p = pd.concat(preds, ignore_index=True)
        p["actual"] = [actual[target].get((cc, m), np.nan)
                       for cc, m in zip(p["commodity_code"], p["month"])]
        p = p.dropna(subset=["actual"])
        for cc, g in p.groupby("commodity_code"):
            rows.append(dict(target=target, commodity=cc, n=len(g),
                             WAPE=float((g["pred"] - g["actual"]).abs().sum()
                                        / g["actual"].abs().sum())))
        rows.append(dict(target=target, commodity="전체", n=len(p),
                         WAPE=float((p["pred"] - p["actual"]).abs().sum()
                                    / p["actual"].abs().sum())))
    return pd.DataFrame(rows)


def seasonal_naive(df: pd.DataFrame) -> pd.DataFrame:
    actual = df.set_index(["commodity_code", "month"])
    rows = []
    for target in ["ton", "unit"]:
        recs = []
        for o in ORIGINS:
            o = pd.Timestamp(o)
            for cc in df["commodity_code"].unique():
                for h in range(1, H + 1):
                    m = o + pd.DateOffset(months=h)
                    a = actual[target].get((cc, m), np.nan)
                    base = actual[target].get((cc, m - pd.DateOffset(months=12)), np.nan)
                    if pd.notna(a) and pd.notna(base):
                        recs.append((cc, a, base))
        p = pd.DataFrame(recs, columns=["cc", "a", "p"])
        for cc, g in p.groupby("cc"):
            rows.append(dict(target=target, commodity=cc, n=len(g),
                             WAPE=float((g["p"] - g["a"]).abs().sum() / g["a"].abs().sum())))
        rows.append(dict(target=target, commodity="전체", n=len(p),
                         WAPE=float((p["p"] - p["a"]).abs().sum() / p["a"].abs().sum())))
    return pd.DataFrame(rows)


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = fu.build_panel(db)
    df = build_exog(db, df)
    base_feats = list(fu.FEATS)
    for c in ["cot_l", "wm_bal_prev", "pmi_cn_l", "krip_yoy"]:
        print(f"{c} 커버리지: {float(df[c].notna().mean()):.2f}")

    naive = seasonal_naive(df)
    variants = {"계절나이브": None, "BASE(현행)": base_feats}
    for name, cols in EXOG_GROUPS.items():
        variants[name] = base_feats + cols
    variants["+ALL"] = base_feats + sum(EXOG_GROUPS.values(), [])

    all_rows = []
    for name, feats in variants.items():
        t = naive.copy() if feats is None else wape_eval(df, feats)
        t["variant"] = name
        all_rows.append(t)
        tot = t[t["commodity"] == "전체"]
        print(f"{name}: " + " | ".join(
            f"{r['target']} WAPE {r['WAPE']:.3f}" for _, r in tot.iterrows()))
    fu.FEATS = base_feats                # 전역 복원
    res = pd.concat(all_rows, ignore_index=True)
    write_report(res)


def write_report(res: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "forecast_exog_eval.md")
    L = []
    L.append("# 예측모델(2-4) 외생피처 검정 — COT·WoodMac·중국 PMI·한국 산업생산\n")
    L.append("작성: 2026-07-24 · forecast_unit 실제 파이프라인 재사용, 오리진 6개"
             "(2024-03~2025-06 분기별)×h=1..12 직접예측 WAPE(낮을수록 좋음). "
             "⚠ WM은 2026-03 단일 빈티지(과거값도 개정본) — 방향 참고 전용. "
             "COT는 CU 전용 데이터를 풀링 열로 제공.\n")
    L.append("\n## 전체(5광종 풀링) WAPE\n")
    L.append("| 변형 | ton WAPE | unit WAPE |")
    L.append("|---|---|---|")
    piv = res[res["commodity"] == "전체"].pivot_table(
        index="variant", columns="target", values="WAPE", sort=False)
    for v, r in piv.iterrows():
        L.append(f"| {v} | {r.get('ton', float('nan')):.4f} | "
                 f"{r.get('unit', float('nan')):.4f} |")
    L.append("\n## 광종별 ton WAPE\n")
    sub = res[(res["target"] == "ton") & (res["commodity"] != "전체")]
    pv = sub.pivot_table(index="commodity", columns="variant", values="WAPE", sort=False)
    L.append("| 광종 | " + " | ".join(pv.columns) + " |")
    L.append("|---" * (len(pv.columns) + 1) + "|")
    for cc, r in pv.iterrows():
        L.append(f"| {cc} | " + " | ".join(f"{x:.4f}" for x in r.values) + " |")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[forecast_exog_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
