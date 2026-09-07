# -*- coding: utf-8 -*-
"""진단모델 피처군 Ablation (2026-07-13, 외부감사 A-3).

질문: "지정학 이벤트 파이프라인(181만 건)이 진단 성능에 실제로 기여하는가?"
Naive → AR(y_lag1)만 → +가격 → +수입구조 → +지정학 순으로 피처군을 누적하며 동일
워크포워드(diagnosis_opt.FOLDS, Ridge 풀링+분위매핑)로 QWK·전환월 적중률을 측정한다.
마지막 증분(Δ지정학)이 파이프라인의 존재 증명이며, 0에 가깝다면 그것대로 지금 알아야
할 사실(지수의 포지셔닝을 진단 피처→독립 산출물+수입예측 exog로 전환 판단 근거).

실행: MSR_DB=<warehouse> python -m scripts.ablation_diagnosis
산출: outputs/model_opt/ablation.csv + 콘솔 표
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                   # noqa: E402
from msr.models.diagnosis_opt import (FOLDS, build_panel, stage_labels,   # noqa: E402
                                      reg_to_stage, _fit_predict_reg)

GROUPS = [
    ("AR만(y_lag1)",        ["y_lag1"]),
    ("+가격",               ["y_lag1", "volatility_12w", "spread_pct", "ref_price", "price_z52"]),
    ("+수입구조",           ["y_lag1", "volatility_12w", "spread_pct", "ref_price", "price_z52",
                             "import_hhi", "import_yoy", "import_cagr3"]),
    ("+지정학(전체 피처)",   ["y_lag1", "volatility_12w", "spread_pct", "ref_price", "price_z52",
                             "import_hhi", "import_yoy", "import_cagr3",
                             "geopolitical_risk", "geo_chg", "p_burst"]),
]


def run(db=None):
    db = db or DB_PATH
    df = build_panel(db)
    rows = []

    # 폴드 전체에 걸쳐 예측을 모아 풀링 평가(단일 폴드 운 제거 — diagnosis_opt와 동일 철학)
    def evaluate(pred_by_fold):
        yt = np.concatenate([y for y, _, _ in pred_by_fold])
        yp = np.concatenate([p for _, p, _ in pred_by_fold])
        chg = np.concatenate([c for _, _, c in pred_by_fold])
        qwk = cohen_kappa_score(yt, yp, weights="quadratic")
        chg_acc = float((yp[chg] == yt[chg]).mean()) if chg.sum() else np.nan
        return round(qwk, 3), round(chg_acc, 3), int(chg.sum())

    naive_folds, group_folds = [], {name: [] for name, _ in GROUPS}
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        yte = y_stage[te.index].values
        stage_series = pd.Series(y_stage.values, index=df.index)
        prev = stage_series.groupby(df["commodity_code"]).shift(1)[te.index]
        chg = (prev.notna() & (prev.values != yte)).values
        naive_folds.append((yte, prev.fillna(0).astype(int).values, chg))
        for name, feats in GROUPS:
            fs = [f for f in feats if f in df.columns and df[f].notna().sum() > 50]
            pred_y, _ = _fit_predict_reg("Ridge", tr, te, fs, per_commodity=False)
            group_folds[name].append((yte, reg_to_stage(pred_y, te, tr), chg))

    q0, c0, nchg = evaluate(naive_folds)
    rows.append(dict(구성="Naive(지속성)", QWK=q0, dQWK_vs_naive=0.0, 전환월적중=c0))
    for name, _ in GROUPS:
        q, c, _n = evaluate(group_folds[name])
        rows.append(dict(구성=name, QWK=q, dQWK_vs_naive=round(q - q0, 3), 전환월적중=c))
    out = pd.DataFrame(rows)
    print(f"\n=== Ablation (워크포워드 {len(naive_folds)}폴드 풀링, 전환월 {nchg}건) ===")
    print(out.to_string(index=False))
    d_geo = out.iloc[-1]["QWK"] - out.iloc[-2]["QWK"]
    d_chg = out.iloc[-1]["전환월적중"] - out.iloc[-2]["전환월적중"]
    print(f"\nΔ지정학(마지막 증분): QWK {d_geo:+.3f}, 전환월 적중 {d_chg:+.3f}")
    os.makedirs(os.path.join(str(OUT), "model_opt"), exist_ok=True)
    out.to_csv(os.path.join(str(OUT), "model_opt", "ablation.csv"), index=False)
    return out


if __name__ == "__main__":
    run()
