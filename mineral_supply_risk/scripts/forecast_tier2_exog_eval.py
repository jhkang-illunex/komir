# -*- coding: utf-8 -*-
"""예측모델(2-4) Tier2 외생피처 검정 — WSTS 반도체·ECOS 세부업종·1차금속 재고·칠레 생산
(2026-07-25, forecast_exog_eval 프레임 재사용. collect_tier2_feeds.py 후속).

기존 검정(forecast_exog_eval, 07-24) 결론 = "lag 지배 — COT·WM·PMICN·KRIP 전부
채택 근거 없음". 이번엔 Tier2의 수요축(수입수요에 더 직접적)으로 동일 프레임 재검:
  +SEMI : WSTS 세계 반도체 빌링 YoY·3M변화(시프트 2 — SIA 익월 초 발표 보수 반영)
  +KIPD : ECOS 세부 업종 생산 YoY 3종(전자부품·자동차·전기장비, 시프트 2)
          — 기존 +KRIP(전산업)보다 광종 전방산업에 특정된 버전
  +KINV : 한국 1차금속 재고지수 YoY(시프트 2) — 국내 재고 소진/축적 신호
  +CLP  : 칠레 구리 생산 YoY(시프트 2, CU 전용 데이터를 풀링 열로 제공)
  +ALL  : 전부 결합

실행: MSR_DB=<warehouse> python -m scripts.forecast_tier2_exog_eval
산출: outputs/model_opt/forecast_tier2_exog_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                      # noqa: E402
import msr.models.forecast_unit as fu                    # noqa: E402
from scripts.forecast_exog_eval import wape_eval, seasonal_naive  # noqa: E402

EXOG_GROUPS = {
    "+SEMI": ["semi_yoy", "semi_chg3"],
    "+KIPD": ["kipd_elec_yoy", "kipd_auto_yoy", "kipd_eleq_yoy"],
    "+KINV": ["kinv_yoy"],
    "+CLP": ["clp_yoy_m"],
}


def build_exog2(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) d, val
        FROM fact_series WHERE series_code IN
            ('WSTS_BILL_WW_M','KIP_ELEC_M','KIP_AUTO_M','KIP_ELEQ_M','KINV_METAL_M')
        ORDER BY 1,2""").df()
    clp = con.execute("""SELECT CAST(obs_date AS DATE) d, val FROM fact_indicator
        WHERE indicator='CL_CU_PROD_MINE' ORDER BY 1""").df()
    con.close()
    panel = panel.copy()
    panel["month"] = pd.to_datetime(panel["month"])

    def monthly_feats(d: pd.DataFrame, out_prefix: str, shift: int,
                      chg3: bool = False) -> pd.DataFrame:
        d = d.sort_values("d").copy()
        d["month"] = pd.to_datetime(d["d"])
        v = pd.to_numeric(d["val"], errors="coerce")
        d[f"{out_prefix}_yoy"] = v.pct_change(12).shift(shift)
        cols = ["month", f"{out_prefix}_yoy"]
        if chg3:
            d[f"{out_prefix}_chg3"] = v.pct_change(3).shift(shift)
            cols.append(f"{out_prefix}_chg3")
        return d[cols]

    sw = ser[ser["series_code"] == "WSTS_BILL_WW_M"][["d", "val"]]
    m = monthly_feats(sw, "semi", 2, chg3=True)
    panel = panel.merge(m, on="month", how="left")

    for code, pref in [("KIP_ELEC_M", "kipd_elec"), ("KIP_AUTO_M", "kipd_auto"),
                       ("KIP_ELEQ_M", "kipd_eleq"), ("KINV_METAL_M", "kinv")]:
        m = monthly_feats(ser[ser["series_code"] == code][["d", "val"]], pref, 2)
        panel = panel.merge(m, on="month", how="left")

    m = monthly_feats(clp, "clp_m", 2)
    m = m.rename(columns={"clp_m_yoy": "clp_yoy_m"})
    panel = panel.merge(m, on="month", how="left")
    return panel


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = fu.build_panel(db)
    df = build_exog2(db, df)
    base_feats = list(fu.FEATS)
    for c in ["semi_yoy", "kipd_elec_yoy", "kinv_yoy", "clp_yoy_m"]:
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
    path = os.path.join(out_dir, "forecast_tier2_exog_eval.md")
    L = []
    L.append("# 예측모델(2-4) Tier2 외생피처 검정 — 반도체 빌링·세부업종·1차금속재고·칠레생산\n")
    L.append("작성: 2026-07-25 · forecast_unit 실제 파이프라인 재사용, 오리진 6개"
             "(2024-03~2025-06 분기별)×h=1..12 직접예측 WAPE(낮을수록 좋음). "
             "전 피처 시프트 2(발표 지연 보수 반영). CLP는 CU 전용 데이터를 풀링 열로 제공.\n")
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
    print(f"[forecast_tier2_exog_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
