# -*- coding: utf-8 -*-
"""예측모델(2-4) 대안 재피팅 — 전체 외생(기존+Tier1+Tier2) × 다른 모델 계열
(2026-07-25, 사용자 지시 "기존과 다른 방식으로 전부 재피팅").

⚠ 맥락: 07-24 "모델 구조를 바꾸기 전엔 외생 추가 재시도 금지" — 이번이 바로 구조
변경(모델 계열 교체) 검정이므로 외생 재투입이 허용되는 경로.

변형: {HistGBM(현행), ElasticNet(선형·표준화), RandomForest} × {BASE(현행 FEATS),
FULL(FEATS+외생 전부 — COT·WM·PMICN·KRIP(T1 검정분)+SEMI·KIPD·KINV·CLP(T2))}
+ 계절나이브 기준선. 평가는 기존 프레임 그대로: 오리진 6개(2024-03~2025-06 분기)
× h=1..12 직접예측 WAPE(ton=수입물량, unit=수입단가).

실행: MSR_DB=<warehouse> python -m scripts.forecast_alt_refit
산출: outputs/model_opt/forecast_alt_refit.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import ElasticNetCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                   # noqa: E402
import msr.models.forecast_unit as fu                        # noqa: E402
from scripts.forecast_exog_eval import (                     # noqa: E402
    build_exog, seasonal_naive, ORIGINS, H, EXOG_GROUPS as EX1,
)
from scripts.forecast_tier2_exog_eval import (               # noqa: E402
    build_exog2, EXOG_GROUPS as EX2,
)

EXOG_ALL = sum(EX1.values(), []) + sum(EX2.values(), [])


def make_model(kind: str):
    if kind == "HistGBM":
        from sklearn.ensemble import HistGradientBoostingRegressor
        return HistGradientBoostingRegressor(max_depth=4, learning_rate=0.07,
                                             max_iter=300, random_state=0)
    if kind == "ElasticNet":
        return make_pipeline(
            StandardScaler(),
            ElasticNetCV(l1_ratio=[0.1, 0.5, 0.9], alphas=np.logspace(-4, 0, 8),
                         cv=3, max_iter=5000, random_state=0))
    return RandomForestRegressor(n_estimators=300, min_samples_leaf=3,
                                 random_state=0, n_jobs=-1)


def direct_forecast_alt(df: pd.DataFrame, target: str, base_month: pd.Timestamp,
                        feats: list[str], kind: str) -> pd.DataFrame:
    """fu._direct_forecast와 동일 골격(광종 풀링+더미·log 타깃·h별 독립 적합),
    모델 계열만 주입식으로 교체."""
    hist = df[df["month"] <= base_month].copy()
    feat = fu._features(hist, target)
    rows = []
    for h in range(1, H + 1):
        d = fu._direct_matrix(feat, h)
        d2 = pd.get_dummies(d, columns=["commodity_code"], prefix="cc")
        cc_cols = sorted(c for c in d2.columns if c.startswith("cc_"))
        cols = feats + cc_cols
        tr = d2.dropna(subset=["lag1", "y_h"])
        med = tr[cols].median(numeric_only=True)
        Xtr, ytr = tr[cols].fillna(med), tr["y_h"].values
        pr = d2[d2["month"] == base_month]
        Xpr = pr[cols].fillna(med)
        m = make_model(kind).fit(Xtr, ytr)
        yhat = np.exp(m.predict(Xpr))
        for i, idx in enumerate(pr.index):
            rows.append(dict(commodity_code=d.loc[idx, "commodity_code"],
                             month=base_month + pd.DateOffset(months=h),
                             h=h, pred=float(yhat[i])))
    return pd.DataFrame(rows)


def wape_eval_alt(df: pd.DataFrame, feats: list[str], kind: str) -> pd.DataFrame:
    actual = df.set_index(["commodity_code", "month"])
    rows = []
    for target in ["ton", "unit"]:
        preds = [direct_forecast_alt(df, target, pd.Timestamp(o), feats, kind)
                 for o in ORIGINS]
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


def main():
    db = os.environ["MSR_DB"]
    df = fu.build_panel(db)
    df = build_exog(db, df)
    df = build_exog2(db, df)
    base_feats = list(fu.FEATS)
    full_feats = base_feats + EXOG_ALL
    print(f"피처 수: BASE {len(base_feats)} → FULL {len(full_feats)}")

    all_rows = [seasonal_naive(df).assign(variant="계절나이브")]
    for kind in ["HistGBM", "ElasticNet", "RandomForest"]:
        for ftag, feats in [("BASE", base_feats), ("FULL", full_feats)]:
            name = f"{kind}+{ftag}" + ("(현행)" if kind == "HistGBM" and
                                       ftag == "BASE" else "")
            t = wape_eval_alt(df, feats, kind)
            t["variant"] = name
            all_rows.append(t)
            tot = t[t["commodity"] == "전체"]
            print(f"{name}: " + " | ".join(
                f"{r['target']} WAPE {r['WAPE']:.3f}" for _, r in tot.iterrows()))
    res = pd.concat(all_rows, ignore_index=True)
    write_report(res)


def write_report(res: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "forecast_alt_refit.md")
    L = ["# 예측모델(2-4) 대안 재피팅 — 전체 외생 × 모델 계열\n",
         "작성: 2026-07-25 · 동일 프레임(오리진 6개×h=1..12 직접예측 WAPE, "
         "광종 풀링·log 타깃) · 모델 계열만 교체(ElasticNet=표준화+CV 정칙화, "
         "RF=배깅). FULL = 현행 FEATS + 외생 12피처(COT·WM·PMICN·KRIP·SEMI·"
         "KIPD 3종·KINV·CLP).\n",
         "\n## 전체(5광종 풀링) WAPE\n",
         "| 변형 | ton WAPE | unit WAPE |", "|---|---|---|"]
    piv = res[res["commodity"] == "전체"].pivot_table(
        index="variant", columns="target", values="WAPE", sort=False)
    for v, r in piv.iterrows():
        L.append(f"| {v} | {r.get('ton', float('nan')):.4f} | "
                 f"{r.get('unit', float('nan')):.4f} |")
    L.append("\n## 광종별 ton WAPE\n")
    sub = res[(res["target"] == "ton") & (res["commodity"] != "전체")]
    pv = sub.pivot_table(index="commodity", columns="variant", values="WAPE",
                         sort=False)
    L.append("| 광종 | " + " | ".join(pv.columns) + " |")
    L.append("|---" * (len(pv.columns) + 1) + "|")
    for cc, r in pv.iterrows():
        L.append(f"| {cc} | " + " | ".join(f"{x:.4f}" for x in r.values) + " |")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[forecast_alt_refit] 리포트 → {path}")


if __name__ == "__main__":
    main()
