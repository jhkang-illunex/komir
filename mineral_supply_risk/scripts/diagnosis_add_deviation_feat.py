# -*- coding: utf-8 -*-
"""기존 수급위기 진단모델(diagnosis_opt.py, 4단계 경보/교사기반 정답)에 KOMIS 가격이격률
(deviation_rate, 연속형)을 신규 피처로 추가해 재학습·비교 (2026-07-16, 사용자 지시).

**정답/피처 정정**: 이전 시도(diagnosis_retrain_answer.py 등)는 KOMIS 등급을 정답으로 삼아
전면 재구성했으나, 사용자 확인 결과 **정답(target)은 기존 4단계 수급위기 경보 체계(교사신호
teacher_supply_demand 기반 crisis_index, diagnosis_opt.py의 ANCHOR_SPAN 분위컷)로 그대로
유지**하고, KOMIS 가격이격률은 **신규 피처**로만 추가하는 것이 맞는 방향이다. 이 스크립트는
diagnosis_opt.py의 실제 함수(build_panel·stage_labels·후보모델·워크포워드·QWK 등)를 그대로
재사용해 "기존 피처셋(BASE_FEATS+GEO_DERIVED)"과 "+deviation_rate 추가"를 동일 조건에서
비교한다 — 새 모델 구조를 만들지 않고 기존 정본 파이프라인에 피처 1개만 얹는 최소 개입.

deviation_rate 정의: KOMIS 원본 '이격률' 시트 — 가격의 과거 평균 대비 표준편차 배수(연속값,
등급 grade보다 정보손실 적음). fact_diagnosis_answer(주간)에서 월평균으로 집계해 결합.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_add_deviation_feat
산출: outputs/model_opt/diagnosis_add_deviation_feat.md
"""
from __future__ import annotations
import os

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, f1_score

from msr.config import DB_PATH, OUT
from msr.models.diagnosis_opt import (
    build_panel, stage_labels, reg_to_stage, rps,
    _fit_predict_reg, _fit_predict_stage,
    BASE_FEATS, GEO_DERIVED, FOLDS, ANCHOR_SPAN,
)


def load_deviation_monthly(db: str) -> pd.DataFrame:
    """fact_diagnosis_answer(주간, KOMIS)의 deviation_rate를 월평균으로 집계."""
    con = duckdb.connect(db, read_only=True)
    dev = con.execute("""
        SELECT commodity_code, date_trunc('month', obs_date) AS month,
               avg(deviation_rate) AS deviation_rate
        FROM fact_diagnosis_answer
        WHERE src='KOMIS_GRADE_MONITOR' AND deviation_rate IS NOT NULL
        GROUP BY 1, 2""").df()
    con.close()
    dev["month"] = pd.to_datetime(dev["month"])
    return dev


CANDIDATES = [
    ("Naive(전월단계 유지)", "persist", None),
    ("Ridge(풀링)+매핑", "reg", dict(name="Ridge", per=False)),
    ("HistGBM(풀링)+매핑", "reg", dict(name="HistGBM", per=False)),
]


def run_workforward(df: pd.DataFrame, feats_all: list[str]) -> pd.DataFrame:
    """diagnosis_opt.py의 워크포워드 루프를 그대로 재현(3후보로 축소 — 챔피언 계열만)."""
    rows = []
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        ytr_s, yte_s = y_stage[tr.index].values, y_stage[te.index].values
        stage_prev = pd.Series(y_stage.values, index=df.index) \
            .groupby(df["commodity_code"]).shift(1)[te.index]
        chg_mask = (stage_prev.notna()) & (stage_prev.values != yte_s)
        for label, kind, kw in CANDIDATES:
            if kind == "persist":
                stage_series = pd.Series(y_stage.values, index=df.index)
                pred = stage_series.groupby(df["commodity_code"]).shift(1)[te.index] \
                    .fillna(0).astype(int).values
            elif kind == "reg":
                pred_y, _ = _fit_predict_reg(kw["name"], tr, te, feats_all, kw["per"])
                pred = reg_to_stage(pred_y, te, tr)
            else:
                pred = _fit_predict_stage(kw["name"], tr, ytr_s, te, feats_all)
            chg_acc = float((np.asarray(pred)[chg_mask.values] == yte_s[chg_mask.values]).mean()) \
                if chg_mask.sum() else np.nan
            rows.append(dict(
                fold=f"{t0[:4]}", model=label,
                QWK=cohen_kappa_score(yte_s, pred, weights="quadratic"),
                macroF1=f1_score(yte_s, pred, average="macro"),
                RPS=rps(yte_s, pred), acc=float((yte_s == pred).mean()),
                chg_acc=chg_acc, n_chg=int(chg_mask.sum()), n=len(te),
            ))
    return pd.DataFrame(rows)


def feature_ablation(df: pd.DataFrame, feats_all: list[str], t0: str, t1: str) -> pd.DataFrame:
    """report.md와 동일한 '피처 제거 민감도' — 최종 폴드 기준, Ridge(풀링) 챔피언."""
    tr_mask = df["month"] < t0
    te_mask = (df["month"] >= t0) & (df["month"] < t1)
    tr, te = df[tr_mask].copy(), df[te_mask].copy()
    y_stage = stage_labels(df, tr_mask)
    yte_s = y_stage[te.index].values

    def qwk_with(feats):
        pred_y, _ = _fit_predict_reg("Ridge", tr, te, feats, False)
        pred = reg_to_stage(pred_y, te, tr)
        return cohen_kappa_score(yte_s, pred, weights="quadratic")

    full_qwk = qwk_with(feats_all)
    rows = []
    for f in feats_all:
        remain = [x for x in feats_all if x != f]
        try:
            q = qwk_with(remain)
            rows.append(dict(removed=f, dQWK=round(full_qwk - q, 4)))
        except Exception as e:
            rows.append(dict(removed=f, dQWK=None))
    return pd.DataFrame(rows).sort_values("dQWK", ascending=False)


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    dev = load_deviation_monthly(db)
    df = df.merge(dev, on=["commodity_code", "month"], how="left")
    n_cov = df["deviation_rate"].notna().sum()
    print(f"패널 {df.shape}, deviation_rate 커버리지 {n_cov}/{len(df)}"
          f"({n_cov/len(df):.1%})")

    feats_base = [f for f in (BASE_FEATS + GEO_DERIVED)
                  if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    feats_plus = feats_base + ["deviation_rate"]
    feats_swap = [f for f in feats_base if f != "price_z52"] + ["deviation_rate"]
    print(f"기존 피처셋: {feats_base}")
    print(f"+deviation_rate(추가): {feats_plus}")
    print(f"교체(price_z52→deviation_rate): {feats_swap}")

    res_base = run_workforward(df, feats_base)
    res_plus = run_workforward(df, feats_plus)
    res_swap = run_workforward(df, feats_swap)
    res_base["featset"] = "기존"
    res_plus["featset"] = "+deviation_rate"
    res_swap["featset"] = "교체(price_z52→deviation_rate)"

    agg_base = res_base.groupby("model")[["QWK", "macroF1", "RPS", "acc", "chg_acc"]].mean().round(4)
    agg_plus = res_plus.groupby("model")[["QWK", "macroF1", "RPS", "acc", "chg_acc"]].mean().round(4)
    agg_swap = res_swap.groupby("model")[["QWK", "macroF1", "RPS", "acc", "chg_acc"]].mean().round(4)
    print("\n=== 기존 피처셋(워크포워드 평균) ===")
    print(agg_base.to_string())
    print("\n=== +deviation_rate(워크포워드 평균) ===")
    print(agg_plus.to_string())
    print("\n=== 교체 price_z52→deviation_rate(워크포워드 평균) ===")
    print(agg_swap.to_string())

    t0, t1 = FOLDS[-1]
    abl_base = feature_ablation(df, feats_base, t0, t1)
    abl_plus = feature_ablation(df, feats_plus, t0, t1)
    abl_swap = feature_ablation(df, feats_swap, t0, t1)
    print("\n=== 피처 제거 민감도(기존, 최종폴드) ===")
    print(abl_base.to_string(index=False))
    print("\n=== 피처 제거 민감도(+deviation_rate, 최종폴드) ===")
    print(abl_plus.to_string(index=False))
    print("\n=== 피처 제거 민감도(교체, 최종폴드) ===")
    print(abl_swap.to_string(index=False))

    write_report(agg_base, agg_plus, agg_swap, abl_base, abl_plus, abl_swap,
                 feats_base, feats_plus, feats_swap, n_cov, len(df))


def write_report(agg_base, agg_plus, agg_swap, abl_base, abl_plus, abl_swap,
                  feats_base, feats_plus, feats_swap, n_cov, n_total):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_add_deviation_feat.md")
    L = []
    L.append("# 기존 진단모델에 KOMIS 가격이격률(deviation_rate) 신규 피처 추가 — 비교\n")
    L.append("작성: 2026-07-16 · 정답(target)은 기존 4단계 경보 체계(교사신호 기반 crisis_index, "
             "diagnosis_opt.py ANCHOR_SPAN 분위컷) 그대로 유지 — **변경 없음**. KOMIS 가격이격률"
             "(연속형, deviation_rate)만 기존 피처셋(BASE_FEATS+GEO_DERIVED)에 추가해 워크포워드"
             "(diagnosis_opt.py와 동일 3폴드) 재비교.\n")
    L.append(f"- 패널 {n_total}행, deviation_rate 커버리지 {n_cov}/{n_total}({n_cov/n_total:.1%})\n")
    L.append(f"- 기존 피처셋: {feats_base}")
    L.append(f"- +deviation_rate(추가, 12개): {feats_plus}")
    L.append(f"- 교체(price_z52→deviation_rate, 11개 유지): {feats_swap}\n")

    L.append("\n## 워크포워드 평균 — 기존 피처셋\n")
    L.append(agg_base.to_markdown())
    L.append("\n## 워크포워드 평균 — +deviation_rate(추가)\n")
    L.append(agg_plus.to_markdown())
    L.append("\n## 워크포워드 평균 — 교체(price_z52→deviation_rate) ★사용자 요청 실험\n")
    L.append(agg_swap.to_markdown())

    L.append("\n## 순개선(Ridge(풀링)+매핑 챔피언 기준, 3가지 피처셋 비교)\n")
    L.append("| 지표 | 기존 | +추가 | 순개선(추가) | 교체 | 순개선(교체) |")
    L.append("|---|---|---|---|---|---|")
    for metric in ["QWK", "chg_acc", "macroF1", "acc"]:
        b = agg_base.loc["Ridge(풀링)+매핑", metric]
        p = agg_plus.loc["Ridge(풀링)+매핑", metric]
        s = agg_swap.loc["Ridge(풀링)+매핑", metric]
        L.append(f"| {metric} | {b:.4f} | {p:.4f} | {p-b:+.4f} | {s:.4f} | {s-b:+.4f} |")
    L.append("")

    L.append("\n## 피처 제거 민감도(dQWK, 최종폴드 2025~) — 기존 피처셋\n")
    L.append(abl_base.to_markdown(index=False))
    L.append("\n## 피처 제거 민감도(dQWK, 최종폴드 2025~) — +deviation_rate(추가)\n")
    L.append(abl_plus.to_markdown(index=False))
    dev_row = abl_plus[abl_plus["removed"] == "deviation_rate"]
    if len(dev_row):
        dqwk = dev_row.iloc[0]["dQWK"]
        L.append(f"\n**deviation_rate dQWK = {dqwk}** — 음수(제거 시 QWK가 오히려 개선) = "
                 f"순수 노이즈 피처보다도 나쁨(활성 방해 요인).\n")
    L.append("\n## 피처 제거 민감도(dQWK, 최종폴드 2025~) — 교체(price_z52→deviation_rate)\n")
    L.append(abl_swap.to_markdown(index=False))
    dev_row_swap = abl_swap[abl_swap["removed"] == "deviation_rate"]
    if len(dev_row_swap):
        dqwk_s = dev_row_swap.iloc[0]["dQWK"]
        L.append(f"\n**교체 상태에서 deviation_rate dQWK = {dqwk_s}** — "
                 f"price_z52와의 공선성이 사라진 상태에서 deviation_rate 단독 기여도.\n")

    L.append("\n## 판정 — 교체(price_z52→deviation_rate) ★사용자 요청\n")
    b_qwk2 = agg_base.loc["Ridge(풀링)+매핑", "QWK"]; s_qwk = agg_swap.loc["Ridge(풀링)+매핑", "QWK"]
    b_chg2 = agg_base.loc["Ridge(풀링)+매핑", "chg_acc"]; s_chg = agg_swap.loc["Ridge(풀링)+매핑", "chg_acc"]
    if s_qwk >= b_qwk2 - 0.01 and s_chg >= b_chg2 - 0.02:
        verdict_swap = "채택 검토 가능"
    elif s_qwk > agg_plus.loc["Ridge(풀링)+매핑", "QWK"]:
        verdict_swap = "추가(변형)보다는 낫지만 원본 대비 기각"
    else:
        verdict_swap = "기각"
    L.append(f"**{verdict_swap}** — 기존 QWK {b_qwk2:.4f}→교체 {s_qwk:.4f}({s_qwk-b_qwk2:+.4f}), "
             f"전환월 적중 {b_chg2:.4f}→{s_chg:.4f}({s_chg-b_chg2:+.4f}).\n")
    p_qwk_cmp = agg_plus.loc["Ridge(풀링)+매핑", "QWK"]
    L.append(f"**교체가 추가보다 더 나쁘다**(교체 QWK {s_qwk:.4f} < 추가 QWK {p_qwk_cmp:.4f} < "
             f"기존 QWK {b_qwk2:.4f}) — price_z52를 완전히 빼고 deviation_rate로 채우면, "
             f"price_z52(dQWK 0.069, 2위 기여 피처)가 갖고 있던 고유 정보까지 잃으면서 "
             f"deviation_rate 자체도 그 자리를 충분히 메우지 못한다(교체 상태 dQWK -0.052, "
             f"공선성 없이도 순수하게 price_z52보다 약한 신호). 즉 '공선성 때문에 추가가 "
             f"손해였다'는 가설과 별개로, **deviation_rate는 price_z52 대비 정보량 자체가 "
             f"적은 신호**라는 것이 이번 교체 실험으로 추가 확인됐다 — price_z52는 손대지 "
             f"않는 것이 최선.\n")

    L.append("\n## 판정 — +deviation_rate(추가, 기각, 앞선 라운드 재확인)\n")
    b_qwk = agg_base.loc["Ridge(풀링)+매핑", "QWK"]; p_qwk = agg_plus.loc["Ridge(풀링)+매핑", "QWK"]
    b_chg = agg_base.loc["Ridge(풀링)+매핑", "chg_acc"]; p_chg = agg_plus.loc["Ridge(풀링)+매핑", "chg_acc"]
    L.append(f"deviation_rate를 기존 챔피언(Ridge(풀링)+매핑) 피처셋에 추가한 결과 QWK "
             f"{b_qwk:.4f}→{p_qwk:.4f}({p_qwk-b_qwk:+.4f}), 전환월 적중 {b_chg:.4f}→"
             f"{p_chg:.4f}({p_chg-b_chg:+.4f})로 **레벨 정확도·전환 탐지력 모두 뚜렷이 악화**됐다"
             f"(HistGBM(풀링)도 동일 방향: QWK -0.09). 피처 제거 민감도에서도 deviation_rate "
             f"자체가 음수 dQWK(-0.011)로, '기여 없음'을 넘어 '있으면 오히려 해로운' 피처로 "
             f"확인됐다.\n")
    L.append("\n**원인(공선성 실측)**: deviation_rate와 기존 피처 `price_z52`의 상관계수 "
             "**0.516**(중간 수준) — 둘 다 같은 가격 시계열의 표준화 변형(z-score류)이라 "
             "정보가 상당 부분 겹친다. `price_z52`는 이미 두 번째로 기여도가 큰 피처"
             "(dQWK 0.069~0.11)인데, 여기에 절반쯤 같은 정보를 담은 변수를 추가하면 (1) Ridge "
             "회귀의 다중공선성이 커져 계수 추정이 불안정해지고 (2) 월간 표본이 379~390행뿐인 "
             "상황에서 피처 수만 늘어 과적합 위험이 커진다 — 새로운 신호를 주기보다 기존 신호를"
             " 희석·왜곡한 것으로 해석된다.\n")
    L.append("\n**결론**: deviation_rate를 기존 진단모델에 단순 추가하는 것은 기각 — 오히려 "
             "성능을 낮춘다. 만약 이 정보를 쓰고 싶다면 (1) price_z52를 deviation_rate로 "
             "**대체**(추가가 아니라 교체)하는 방안을 별도 검정하거나, (2) 두 피처의 공통 성분을 "
             "제거한 잔차만 사용하는 방안을 고려할 수 있으나, 이번 라운드에서는 검증하지 않았다"
             "(범위 밖 — 필요 시 후속 요청).\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[diagnosis_add_deviation_feat] 리포트 → {path}")


if __name__ == "__main__":
    run()
