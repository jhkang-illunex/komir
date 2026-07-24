# -*- coding: utf-8 -*-
"""신규 직교 피처(LME재고·거시지표)로 진단모델 전환탐지 재검정
(2026-07-24, /goal 2단계 — load_market_aux.py 적재분을 모델링에 반영해 기대효과 검증).

배경: diagnosis_ylag_deep_review.md 결론 — "병목은 피처 정보량, 외부 신규 직교
데이터가 유일한 실질 경로". 이번에 발주처 원본에서 발굴한 미활용 데이터가 그 경로를
실제로 여는지 검정한다.

피처(전부 누수 방지 as-of 규약 적용):
  INV  (CU·NI만 실존): LME재고 z52·4주변화율·13주변화율 — 주간 기록은 완결 후
       1주 뒤부터 가용(avail = 기준일+7일)으로 보수적 처리.
  CLNW (주간 거시, 2021-06~): BDI z26·4주변화, 달러인덱스·원달러·위안달러 4주변화,
       금융스트레스 수준, 장단기금리차 수준, 기준금리 13주변화 — 주간평균이라 avail=+7일.
  CLNM (월간 중국, 2016~): 경기선행지수 3개월변화, 산업생산 수준 — 발표지연 감안 avail=+45일.
  PIDX (가격지수 — 라벨 오염 경계, ablation 전용): Bloomberg 원자재지수 4주변화.

평가: diagnosis_ylag_deep_review와 동일 프레임(워크포워드 3폴드 풀링, E2 Δ타깃 분류).
핵심 비교축:
  (a) 풀링: NOLAG 단독 vs +INV vs +CLN vs +INV+CLN (+PIDX는 오염 참고)
  (b) CU·NI 한정(재고가 실존하는 광종만): NOLAG vs +INV — 재고 피처의 가장 깨끗한 검정
  (c) 개선이 있으면 게이트 D(확률임계) 스윕 + 부트스트랩으로 강건성 확인

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_aux_features_eval
산출: outputs/model_opt/diagnosis_aux_features_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.override_backtest import qwk                                # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG, FOLDS  # noqa: E402
from scripts.diagnosis_ylag_deep_review import (                         # noqa: E402
    add_dynamics, pooled_design, walkforward_collect, e2_delta_classifier, evaluate,
)

INV_F = ["inv_z52", "inv_chg4", "inv_chg13"]
CLNW_F = ["bdi_z26", "bdi_chg4", "dxy_chg4", "usdkrw_chg4", "cnyusd_chg4",
          "stlfsi", "ust10y2y", "fedfunds_chg13"]
CLNM_F = ["cn_lead_chg3", "cn_indprod"]
PIDX_F = ["pidx_bbg_chg4"]


def _asof_join(panel: pd.DataFrame, feat: pd.DataFrame, cols: list[str],
               by_commodity: bool) -> pd.DataFrame:
    """avail_date 기준 backward as-of 조인(관측 시점에 이미 가용한 최신값만 사용)."""
    feat = feat.sort_values("avail_date")
    if by_commodity:
        parts = []
        for cc, g in panel.groupby("commodity_code"):
            f = feat[feat["commodity_code"] == cc]
            g = g.sort_values("obs_date")
            if len(f) == 0:
                for c in cols:
                    g[c] = np.nan
                parts.append(g)
                continue
            merged = pd.merge_asof(g, f[["avail_date"] + cols], left_on="obs_date",
                                   right_on="avail_date", direction="backward")
            parts.append(merged.drop(columns=["avail_date"]))
        return pd.concat(parts, ignore_index=True)
    panel = panel.sort_values("obs_date")
    merged = pd.merge_asof(panel, feat[["avail_date"] + cols], left_on="obs_date",
                           right_on="avail_date", direction="backward")
    return merged.drop(columns=["avail_date"])


def build_aux(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    inv = con.execute("""SELECT commodity_code, CAST(obs_date AS DATE) AS obs_date, val
        FROM fact_inventory WHERE src='KOMIS_WEEKLY_LME' ORDER BY 1, 2""").df()
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) AS obs_date, val
        FROM fact_series WHERE src='KOMIS_MARKET_AUX' ORDER BY 1, 2""").df()
    con.close()
    inv["obs_date"] = pd.to_datetime(inv["obs_date"]).astype("datetime64[ns]")
    ser["obs_date"] = pd.to_datetime(ser["obs_date"]).astype("datetime64[ns]")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")

    # ── 재고 피처(기록 그레인에서 계산 후 가용시점 +7일) ──
    inv = inv.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    g = inv.groupby("commodity_code")["val"]
    inv["inv_z52"] = g.transform(
        lambda s: (s - s.rolling(52, min_periods=20).mean())
        / s.rolling(52, min_periods=20).std().replace(0, np.nan))
    inv["inv_chg4"] = g.transform(lambda s: s.pct_change(4))
    inv["inv_chg13"] = g.transform(lambda s: s.pct_change(13))
    inv["avail_date"] = inv["obs_date"] + pd.Timedelta(days=7)
    panel = _asof_join(panel, inv, INV_F, by_commodity=True)

    # ── 주간·월간 시리즈 피처 ──
    def series_feat(code: str, fn, name: str, lag_days: int) -> pd.DataFrame:
        s = ser[ser["series_code"] == code].sort_values("obs_date").reset_index(drop=True)
        out = pd.DataFrame({"avail_date": s["obs_date"] + pd.Timedelta(days=lag_days),
                            name: fn(s["val"])})
        return out.dropna(subset=[name])

    zscore26 = lambda v: (v - v.rolling(26, min_periods=10).mean()) / \
        v.rolling(26, min_periods=10).std().replace(0, np.nan)
    specs = [
        ("BDI_W", zscore26, "bdi_z26", 7),
        ("BDI_W", lambda v: v.pct_change(4), "bdi_chg4", 7),
        ("DXY_W", lambda v: v.pct_change(4), "dxy_chg4", 7),
        ("USDKRW_W", lambda v: v.pct_change(4), "usdkrw_chg4", 7),
        ("CNYUSD_W", lambda v: v.pct_change(4), "cnyusd_chg4", 7),
        ("STLFSI_W", lambda v: v, "stlfsi", 7),
        ("UST10Y2Y_W", lambda v: v, "ust10y2y", 7),
        ("FEDFUNDS_W", lambda v: v.diff(13), "fedfunds_chg13", 7),
        ("CN_LEADING_M", lambda v: v.diff(3), "cn_lead_chg3", 45),
        ("CN_INDPROD_M", lambda v: v, "cn_indprod", 45),
        ("PRICEIDX_BBG_W", lambda v: v.pct_change(4), "pidx_bbg_chg4", 7),
    ]
    for code, fn, name, lag in specs:
        panel = _asof_join(panel, series_feat(code, fn, name, lag), [name],
                           by_commodity=False)
    return panel.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    df = add_dynamics(df)
    df = build_aux(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    cov = {c: float(df[c].notna().mean()) for c in INV_F + CLNW_F + CLNM_F + PIDX_F}
    print("피처 커버리지(패널 내 비결측 비율):")
    for c, v in cov.items():
        print(f"  {c}: {v:.2f}")

    results = []
    # (a) 풀링 비교
    combos = [
        ("NOLAG 단독(기준)", nolag),
        ("NOLAG+INV", nolag + INV_F),
        ("NOLAG+CLN(거시)", nolag + CLNW_F + CLNM_F),
        ("NOLAG+INV+CLN", nolag + INV_F + CLNW_F + CLNM_F),
        ("NOLAG+INV+CLN+PIDX(오염참고)", nolag + INV_F + CLNW_F + CLNM_F + PIDX_F),
    ]
    for tag, feats in combos:
        for clf in ["Logistic", "HistGBM"]:
            r = e2_delta_classifier(df, feats, clf)
            results.append(dict(축="풀링", 구성=f"{tag} [{clf}]", **r))

    # (b) CU·NI 한정 — 재고 실존 광종에서의 가장 깨끗한 검정
    df_cn = df[df["commodity_code"].isin(["CU", "NI"])].reset_index(drop=True)
    for tag, feats in [("NOLAG 단독(기준)", nolag), ("NOLAG+INV", nolag + INV_F),
                        ("NOLAG+INV+CLN", nolag + INV_F + CLNW_F + CLNM_F)]:
        for clf in ["Logistic", "HistGBM"]:
            r = e2_delta_classifier(df_cn, feats, clf)
            results.append(dict(축="CU·NI만", 구성=f"{tag} [{clf}]", **r))

    tab = pd.DataFrame(results)
    print()
    print(tab.round(4).to_string(index=False))

    write_report(tab, cov, df)
    return tab, df, nolag


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def write_report(tab: pd.DataFrame, cov: dict, df: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_aux_features_eval.md")
    L = []
    L.append("# 신규 직교 피처(LME재고·거시지표) 전환탐지 재검정\n")
    L.append("작성: 2026-07-24 · load_market_aux.py로 적재한 발주처 미활용 원본"
             "(주간 LME재고 CU·NI 2007~, 거시 주간 2021-06~, 중국 월간 2016~)을 "
             "diagnosis_ylag_deep_review와 동일 프레임(E2 Δ타깃, 워크포워드 3폴드 풀링)에 "
             "투입. 전 피처 as-of 가용시점 시프트(주간 +7일, 월간 +45일)로 누수 방지.\n")
    L.append("\n## 피처 커버리지(패널 내 비결측 비율)\n")
    for c, v in cov.items():
        L.append(f"- {c}: {v:.2f}")
    L.append("\n## 결과표\n")
    L.append("| 축 | 구성 | QWK | acc | chg_acc | up_acc | n_chg | FAR |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['축']} | {r['구성']} | {_fmt(r['QWK'])} | {_fmt(r['acc'])} | "
                 f"{_fmt(r['chg_acc'])} | {_fmt(r['up_acc'])} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'])} |")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[aux_features_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
