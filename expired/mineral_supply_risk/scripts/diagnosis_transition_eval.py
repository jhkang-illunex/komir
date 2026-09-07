# -*- coding: utf-8 -*-
"""진단모델 전환월 방향별 평가(D-2) + NI 대체지표(D-3) — 피드백기반_수정플랜 P2.

D-2: 일반 accuracy/QWK는 "경보가 실제로 바뀌는 순간을 맞히는가"를 감추므로, 전환월을
  상향전환(악화)·하향전환(완화)·심각·경계 진입(3·4단계 신규 진입)으로 나눠 각각 적중률을
  본다 — diagnosis_opt.py의 chg_mask/chg_acc를 방향별로 세분화.
D-3: NI는 워크포워드 3폴드 중 2024·2025~ 폴드가 실제 단일클래스(0단계만 존재, 위기 사례
  없음)라 해당 폴드의 QWK가 정의 불가/무의미 — 3폴드 풀링 QWK는 계산되지만(2023 폴드가
  4클래스라 전체 풀에는 다양성 존재) 폴드별 신뢰도가 광종마다 다르다는 점을 가린다. 따라서
  폴드 단위로도 항상 계산 가능한 balanced accuracy·macro recall·event-hit rate(실제 2단계
  이상일 때 예측도 2단계 이상으로 잡는 비율)를 광종 공통 대체 지표로 채택.

기존 diagnosis_opt.py 함수(build_panel·stage_labels·후보모델·워크포워드)를 그대로 재사용 —
새 모델 구조 없음, 평가지표만 추가.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_transition_eval
산출: outputs/model_opt/diagnosis_transition_eval.md
"""
from __future__ import annotations
import os

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, recall_score, cohen_kappa_score

from msr.config import DB_PATH, OUT
from msr.models.diagnosis_opt import (
    build_panel, stage_labels, reg_to_stage, _fit_predict_reg, BASE_FEATS, GEO_DERIVED, FOLDS,
)

CHAMPION = ("Ridge(풀링)+매핑", dict(name="Ridge", per=False))


def run_champion(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """챔피언(Ridge 풀링) 예측을 전체 테스트기간(3폴드 풀링)에 대해 수집."""
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
        pred_y, _ = _fit_predict_reg(CHAMPION[1]["name"], tr, te, feats, CHAMPION[1]["per"])
        pred = reg_to_stage(pred_y, te, tr)
        rows.append(pd.DataFrame({
            "commodity_code": te["commodity_code"].values, "month": te["month"].values,
            "actual": yte_s, "pred": pred, "prev_actual": prev_stage, "fold_start": t0,
        }))
    return pd.concat(rows, ignore_index=True)


def transition_breakdown(res: pd.DataFrame) -> pd.DataFrame:
    """D-2: 전환 방향별 적중률."""
    r = res.dropna(subset=["prev_actual"]).copy()
    r["prev_actual"] = r["prev_actual"].astype(int)
    up = r[r["actual"] > r["prev_actual"]]          # 상향전환(악화)
    down = r[r["actual"] < r["prev_actual"]]         # 하향전환(완화)
    entry = r[(r["actual"] >= 3) & (r["prev_actual"] < 3)]  # 경계·심각 신규진입
    steady = r[r["actual"] == r["prev_actual"]]

    def hit_rate(sub):
        return dict(n=len(sub), exact_acc=float((sub["pred"] == sub["actual"]).mean()) if len(sub) else np.nan,
                    within1_acc=float((sub["pred"] - sub["actual"]).abs().le(1).mean()) if len(sub) else np.nan)

    rows = []
    for name, sub in [("상향전환(악화)", up), ("하향전환(완화)", down),
                       ("경계·심각 신규진입(3·4단계)", entry), ("비전환(유지)", steady),
                       ("전체", r)]:
        h = hit_rate(sub)
        rows.append(dict(category=name, **h))
    return pd.DataFrame(rows)


def ni_alt_metrics(res: pd.DataFrame) -> pd.DataFrame:
    """D-3: 광종별(특히 NI) 대체지표 — balanced accuracy·macro recall·event-hit rate."""
    rows = []
    for cc, g in res.groupby("commodity_code"):
        y, p = g["actual"].astype(int).values, np.asarray(g["pred"]).astype(int)
        classes_present = sorted(set(y) | set(p))
        try:
            qwk = cohen_kappa_score(y, p, weights="quadratic") if len(set(y)) > 1 else np.nan
        except Exception:
            qwk = np.nan
        bal_acc = balanced_accuracy_score(y, p)
        macro_rec = recall_score(y, p, average="macro", zero_division=0)
        # event-hit rate: 실제 2단계(주의) 이상일 때 예측도 2단계 이상을 맞히는 비율(재현율류,
        # "위기를 위기로 인식했는가"만 보는 완화된 기준 — QWK가 정의 안 되는 광종에도 항상 계산 가능)
        elevated = g[y_col_ge(g, 2)]
        event_hit = float((elevated["pred"] >= 2).mean()) if len(elevated) else np.nan
        rows.append(dict(commodity=cc, n=len(g), n_class_actual=len(set(y)),
                          QWK=round(qwk, 4) if not np.isnan(qwk) else None,
                          balanced_acc=round(bal_acc, 4), macro_recall=round(macro_rec, 4),
                          n_elevated=len(elevated), event_hit_rate=round(event_hit, 4) if not np.isnan(event_hit) else None))
    return pd.DataFrame(rows)


def y_col_ge(g, k):
    return g["actual"].astype(int) >= k


def fold_degeneracy(res: pd.DataFrame) -> pd.DataFrame:
    """광종×폴드별 실제 클래스 수 — 1이면 그 폴드는 QWK 정의 불가(퇴화)."""
    rows = []
    for (cc, t0), g in res.groupby(["commodity_code", "fold_start"]):
        rows.append(dict(commodity=cc, fold_start=t0, n=len(g),
                          n_class=g["actual"].nunique(),
                          degenerate=g["actual"].nunique() == 1))
    return pd.DataFrame(rows).sort_values(["commodity", "fold_start"])


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    feats = [f for f in (BASE_FEATS + GEO_DERIVED)
             if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    print(f"패널 {df.shape}, 피처 {feats}")

    res = run_champion(df, feats)
    print(f"챔피언(Ridge 풀링) 예측 수집: {len(res)}행")

    trans = transition_breakdown(res)
    print("\n=== D-2: 전환 방향별 적중률 ===")
    print(trans.to_string(index=False))

    alt = ni_alt_metrics(res)
    print("\n=== D-3: 광종별 대체지표(NI 포함) ===")
    print(alt.to_string(index=False))

    degen = fold_degeneracy(res)
    print("\n=== 광종×폴드별 퇴화 여부 ===")
    print(degen.to_string(index=False))

    write_report(trans, alt, degen)


def write_report(trans, alt, degen):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_transition_eval.md")
    L = []
    L.append("# 진단모델 전환월 방향별 평가(D-2) + NI 대체지표(D-3)\n")
    L.append("작성: 2026-07-16 · 챔피언(Ridge(풀링)+매핑) 예측을 워크포워드 3폴드 전체 풀링, "
             "기존 diagnosis_opt.py 방법론 그대로 재사용(모델 구조 무변경, 평가지표만 세분화).\n")

    L.append("\n## D-2: 전환 방향별 적중률\n")
    L.append("일반 chg_acc(diagnosis_opt.py의 전환월 적중, 방향 무관 정확일치)를 상향전환"
             "(위기 악화)·하향전환(완화)·경계·심각 신규진입(3·4단계 최초 진입, 가장 중요한 "
             "실무 시나리오)으로 세분화. within1_acc는 ±1단계 오차까지 허용한 완화 기준.\n")
    L.append("| 구분 | n | 정확일치 적중률 | ±1단계 허용 적중률 |")
    L.append("|---|---|---|---|")
    for _, r in trans.iterrows():
        ea = "—" if pd.isna(r["exact_acc"]) else f"{r['exact_acc']:.3f}"
        wa = "—" if pd.isna(r["within1_acc"]) else f"{r['within1_acc']:.3f}"
        L.append(f"| {r['category']} | {int(r['n'])} | {ea} | {wa} |")

    entry_row = trans[trans["category"] == "경계·심각 신규진입(3·4단계)"].iloc[0]
    up_row = trans[trans["category"] == "상향전환(악화)"].iloc[0]
    down_row = trans[trans["category"] == "하향전환(완화)"].iloc[0]

    def fmt(v):
        return "—" if pd.isna(v) else f"{v:.3f}"

    entry_ea, entry_wa = fmt(entry_row["exact_acc"]), fmt(entry_row["within1_acc"])
    up_ea, down_ea = fmt(up_row["exact_acc"]), fmt(down_row["exact_acc"])
    L.append(f"\n**해석**: 경계·심각 신규진입(n={int(entry_row['n'])}, 실무상 가장 중요 — 늦게 "
             f"잡으면 대응 시간이 없음) 정확일치 적중률 {entry_ea}, ±1단계 허용 시 {entry_wa}"
             f". 상향전환({int(up_row['n'])}건) vs 하향전환({int(down_row['n'])}건) 적중률 "
             f"{up_ea} vs {down_ea} — 두 방향 중 어느 쪽이 더 어려운지 확인.\n")

    L.append("\n## D-3: 광종별 대체지표(NI 포함)\n")
    L.append("QWK는 실제 클래스가 1종뿐인 폴드/광종에서 정의 불가(NaN) — balanced accuracy·"
             "macro recall·event-hit rate(실제 '주의'(2단계) 이상일 때 예측도 2단계 이상으로 "
             "잡는 비율)는 항상 계산 가능해 대체 지표로 채택.\n")
    L.append("| 광종 | n | 실제클래스수 | QWK | balanced_acc | macro_recall | n_elevated | event_hit_rate |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in alt.iterrows():
        qwk_s = "—(정의불가)" if r["QWK"] is None else f"{r['QWK']:.4f}"
        eh_s = "—" if r["event_hit_rate"] is None else f"{r['event_hit_rate']:.4f}"
        L.append(f"| {r['commodity']} | {int(r['n'])} | {int(r['n_class_actual'])} | {qwk_s} | "
                 f"{r['balanced_acc']:.4f} | {r['macro_recall']:.4f} | {int(r['n_elevated'])} | {eh_s} |")

    L.append("\n## 광종×폴드별 퇴화(단일클래스) 여부\n")
    L.append("폴드 단위 실제 클래스 수가 1이면 그 폴드의 QWK는 정의 불가(카파 무의미) — "
             "풀링 QWK(위 표)는 3폴드를 합쳐 계산하므로 이런 폴드별 퇴화를 가릴 수 있다.\n")
    L.append("| 광종 | 폴드시작 | n | 실제클래스수 | 퇴화 여부 |")
    L.append("|---|---|---|---|---|")
    for _, r in degen.iterrows():
        L.append(f"| {r['commodity']} | {r['fold_start']} | {int(r['n'])} | {int(r['n_class'])} | "
                 f"{'예(단일클래스)' if r['degenerate'] else '아니오'} |")

    n_degen_total = int(degen["degenerate"].sum())
    n_total = len(degen)
    L.append(f"\n**전체 관찰**: {n_total}개 광종×폴드 조합 중 {n_degen_total}개({n_degen_total}/{n_total})가 "
             f"단일클래스 퇴화 — NI만의 문제가 아니라 5개 광종 모두에서 최소 1개 폴드가 퇴화(REE·LI·CO는 "
             f"2024 폴드, NI는 2024·2025~ 폴드 모두). 폴드 평균 QWK(단순 산술평균)는 이 퇴화 폴드에서 "
             f"0 또는 NaN이 섞여 왜곡되므로, diagnosis_opt.py 계열 리포트는 풀링 QWK를 주지표로 삼는 것이 "
             f"맞으나 D-3 대체지표(광종·폴드 불문 항상 정의)를 보조지표로 병기할 필요가 있다는 것이 이 "
             f"분석의 결론.\n")

    ni_row = alt[alt["commodity"] == "NI"]
    ni_degen = degen[(degen["commodity"] == "NI") & (degen["degenerate"])]
    if len(ni_row):
        nr = ni_row.iloc[0]
        if len(ni_degen):
            qwk_note = (f"(3폴드 풀링 QWK={nr['QWK']}는 계산되나 {len(ni_degen)}/3 폴드가 "
                        f"단일클래스 — 폴드별 QWK 정의불가, 풀링값 단독 신뢰 금지)")
        else:
            qwk_note = ""
        if nr["event_hit_rate"] is not None:
            eh_note = f", event_hit_rate={nr['event_hit_rate']:.4f}(n_elevated={int(nr['n_elevated'])})"
        else:
            eh_note = "(elevated 사례 없음 — 위기 스트레스테스트 별도 필요)"
        L.append(f"\n**NI 결론**: 실제클래스수(풀링)={int(nr['n_class_actual'])}{qwk_note}. "
                 f"대체지표로 balanced_acc={nr['balanced_acc']:.4f}, "
                 f"macro_recall={nr['macro_recall']:.4f}{eh_note} 채택 — "
                 f"폴드별 퇴화 문제와 무관하게 항상 정의됨이 대체지표 채택의 핵심 이유.\n")

    L.append("\n## 표본 크기 주의\n")
    L.append("전환 카테고리별 n이 작은 경우(특히 경계·심각 신규진입)가 있어 절대 수치보다 "
             "방향성으로 해석 권장 — 광종·기간 확대 시 재검증 필요.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[diagnosis_transition_eval] 리포트 → {path}")


if __name__ == "__main__":
    run()
