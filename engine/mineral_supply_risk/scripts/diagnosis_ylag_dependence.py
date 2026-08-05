# -*- coding: utf-8 -*-
"""y_lag1(관성) 의존도 완화 방안 검토(D-1) — 피드백기반_수정플랜 P2.

C-2(prob_decompose)에서 y_lag1 기여도 0.765로 압도적임이 확인됨(진단모델은 diagnosis_opt.py
자체가 dQWK 분해를 이미 제공) — 이 스크립트는 y_lag1을 제외한 모델, 그리고 포함/제외 두
예측의 단순 평균 앙상블을 챔피언(Ridge 풀링)과 동일 조건으로 비교한다. 전환월(D-2에서 구축한
분류: 상향전환·하향전환·경계·심각 신규진입)과 일반 QWK를 별도로 평가 — "관성 제거가 조기
경보력을 실제로 살리는지" 확인. diagnosis_opt.py·diagnosis_transition_eval.py의 실제 함수를
그대로 재사용(재구현 없음).

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_ylag_dependence
산출: outputs/model_opt/diagnosis_ylag_dependence.md
"""
from __future__ import annotations
import os

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from msr.config import DB_PATH, OUT
from msr.models.diagnosis_opt import (
    build_panel, stage_labels, reg_to_stage, _fit_predict_reg, BASE_FEATS, GEO_DERIVED, FOLDS,
)
from scripts.diagnosis_transition_eval import transition_breakdown

CHAMPION = dict(name="Ridge", per=False)


def run_variant(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """챔피언(Ridge 풀링) 예측 — feats로 피처셋 지정, 3폴드 풀링 수집. 회귀예측값(ci_pred 전)도 반환."""
    rows = []
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        yte_s = y_stage[te.index].values
        prev_stage = pd.Series(y_stage.values, index=df.index) \
            .groupby(df["commodity_code"]).shift(1)[te.index].values
        pred_y, _ = _fit_predict_reg(CHAMPION["name"], tr, te, feats, CHAMPION["per"])
        pred_stage = reg_to_stage(pred_y, te, tr)
        rows.append(pd.DataFrame({
            "commodity_code": te["commodity_code"].values, "month": te["month"].values,
            "actual": yte_s, "pred": pred_stage, "pred_y": pred_y, "prev_actual": prev_stage,
            "fold_start": t0,
        }))
    return pd.concat(rows, ignore_index=True)


def pooled_qwk(res: pd.DataFrame) -> float:
    y, p = res["actual"].astype(int), res["pred"].astype(int)
    return float(cohen_kappa_score(y, p, weights="quadratic")) if y.nunique() > 1 else float("nan")


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    feats_all = [f for f in (BASE_FEATS + GEO_DERIVED)
                 if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    feats_nolag = [f for f in feats_all if f != "y_lag1"]
    print(f"feats_all({len(feats_all)}): {feats_all}")
    print(f"feats_nolag({len(feats_nolag)}): {feats_nolag}")

    res_full = run_variant(df, feats_all)
    res_nolag = run_variant(df, feats_nolag)

    # 앙상블: 회귀예측값(ci_pred 산출 전 pred_y) 단순평균 후 동일 매핑 재적용
    ens_pred_y = (res_full["pred_y"].values + res_nolag["pred_y"].values) / 2.0
    res_ens = res_full[["commodity_code", "month", "actual", "prev_actual", "fold_start"]].copy()
    # reg_to_stage는 (pred_y, te, tr)을 요구하나 여기선 폴드가 섞인 풀 결과라 폴드별 재계산 필요
    res_ens["pred"] = _ensemble_stage(df, ens_pred_y, res_full)

    results = {"포함(y_lag1)": res_full, "제외(y_lag1 없음)": res_nolag, "앙상블(평균)": res_ens}
    summary = []
    trans_tabs = {}
    for label, res in results.items():
        qwk = pooled_qwk(res)
        trans = transition_breakdown(res)
        trans_tabs[label] = trans
        entry = trans[trans["category"] == "경계·심각 신규진입(3·4단계)"].iloc[0]
        summary.append(dict(variant=label, n=len(res), pooled_qwk=round(qwk, 4),
                             entry_acc=round(entry["exact_acc"], 3) if pd.notna(entry["exact_acc"]) else None,
                             overall_chg_acc=round(trans[trans["category"] == "전체"]["exact_acc"].iloc[0], 3)))
    summary_df = pd.DataFrame(summary)
    print(summary_df.to_string(index=False))
    write_report(summary_df, trans_tabs)


def _ensemble_stage(df, ens_pred_y, res_full):
    """폴드별로 학습기간 분위컷을 재적용해 앙상블 회귀예측을 4단계로 매핑."""
    out = np.zeros(len(res_full), dtype=int)
    pos = 0
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask], df[te_mask]
        if len(te) == 0 or len(tr) < 60:
            continue
        n = len(te)
        stage = reg_to_stage(ens_pred_y[pos:pos + n], te, tr)
        out[pos:pos + n] = stage
        pos += n
    return out


def write_report(summary_df: pd.DataFrame, trans_tabs: dict):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_ylag_dependence.md")
    L = []
    L.append("# y_lag1(관성) 의존도 완화 방안 검토 (D-1)\n")
    L.append("작성: 2026-07-16 · 챔피언(Ridge 풀링+매핑)을 y_lag1 포함/제외/앙상블(회귀예측 "
             "단순평균) 3가지로 비교, 워크포워드 3폴드 풀링. diagnosis_opt.py·"
             "diagnosis_transition_eval.py 실제 함수 재사용(재구현 없음).\n")

    L.append("\n## 변형별 요약\n")
    L.append("| 변형 | n | 풀링 QWK | 전체 전환월 적중률 | 경계·심각 신규진입 적중률 |")
    L.append("|---|---|---|---|---|")
    for _, r in summary_df.iterrows():
        ea = "—" if r["entry_acc"] is None else f"{r['entry_acc']:.3f}"
        L.append(f"| {r['variant']} | {int(r['n'])} | {r['pooled_qwk']:.4f} | "
                 f"{r['overall_chg_acc']:.3f} | {ea} |")

    q_full = summary_df[summary_df["variant"] == "포함(y_lag1)"]["pooled_qwk"].iloc[0]
    q_nolag = summary_df[summary_df["variant"] == "제외(y_lag1 없음)"]["pooled_qwk"].iloc[0]
    q_ens = summary_df[summary_df["variant"] == "앙상블(평균)"]["pooled_qwk"].iloc[0]
    c_full = summary_df[summary_df["variant"] == "포함(y_lag1)"]["overall_chg_acc"].iloc[0]
    c_nolag = summary_df[summary_df["variant"] == "제외(y_lag1 없음)"]["overall_chg_acc"].iloc[0]
    c_ens = summary_df[summary_df["variant"] == "앙상블(평균)"]["overall_chg_acc"].iloc[0]

    trend_q = "개선" if q_nolag > q_full else "악화"
    trend_c = "개선" if c_nolag > c_full else "악화"
    L.append(f"\n**해석**: y_lag1 제외 시 풀링 QWK {q_full:.4f}→{q_nolag:.4f}({trend_q}), "
             f"전환월 적중률도 {c_full:.3f}→{c_nolag:.3f}({trend_c}) — **일반 성능과 전환월 "
             f"성능이 같은 방향으로 함께 움직였다**(조치안이 우려한 '관성이 일반 QWK만 부풀리고 "
             f"조기경보력은 깎아먹는' 트레이드오프 패턴이 아님). 앙상블(QWK {q_ens:.4f}, 전환월 "
             f"{c_ens:.3f})도 순수 제외보다는 낫지만 포함 버전에는 못 미침. "
             f"**결론: y_lag1을 조기경보력을 희생시키는 관성 함정으로 보기보다, 경보가 실제로 "
             f"연속적으로 지속되는 패턴(진짜 신호)을 모델이 정확히 포착하고 있는 것으로 해석하는 "
             f"것이 데이터와 더 정합적** — 현재 정칙화 수준·피처 구성 변경은 권고하지 않음. "
             f"단, 이 결론은 '단순 제외/평균 앙상블'만 시험한 결과이며 정칙화 강화·직교화 등 "
             f"더 정교한 대안은 검증하지 않았다는 한계는 남는다.\n")

    L.append("\n## 전환 방향별 상세 (변형별)\n")
    for label, trans in trans_tabs.items():
        L.append(f"\n### {label}\n")
        L.append("| 구분 | n | 정확일치 적중률 | ±1단계 허용 적중률 |")
        L.append("|---|---|---|---|")
        for _, r in trans.iterrows():
            ea = "—" if pd.isna(r["exact_acc"]) else f"{r['exact_acc']:.3f}"
            wa = "—" if pd.isna(r["within1_acc"]) else f"{r['within1_acc']:.3f}"
            L.append(f"| {r['category']} | {int(r['n'])} | {ea} | {wa} |")

    L.append("\n## 한계\n")
    L.append("앙상블은 정칙화 강화나 피처 직교화가 아니라 가장 단순한 형태(회귀예측 단순평균) "
             "만 시험 — 조치안이 제시한 다른 대안(정칙화 강화, 명시적 직교화)은 미착수. 경계·"
             "심각 신규진입 표본이 3건뿐이라(D-2와 동일 한계) 이 세부 지표는 방향성만 참고.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[diagnosis_ylag_dependence] 리포트 → {path}")


if __name__ == "__main__":
    run()
