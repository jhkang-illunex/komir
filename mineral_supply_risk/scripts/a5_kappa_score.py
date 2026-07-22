# -*- coding: utf-8 -*-
"""A-5 라벨 품질 검증 — 채점 스크립트. 검토자가 `a5_review_sample.csv`의 `_사람판정` 열을
채운 뒤 이 스크립트로 LLM 추출값과의 Cohen's kappa를 산출한다.

- severity: quadratic-weighted kappa(순서형, 프로젝트 표준 QWK와 동일 가중 방식)
- direction·dimension: 비가중(nominal) Cohen's kappa
- event_type_적절성: kappa 대상 아님(정성 신호) — Y/N/부분 비율만 집계
- "판단불가"로 표시되거나 사람판정 칸이 빈 행은 자동 제외(집계에도 별도 표기)

실행: python3 -m scripts.a5_kappa_score --input outputs/model_opt/a5_review_sample.csv
산출: outputs/model_opt/a5_kappa_report.md
"""
from __future__ import annotations
import argparse
import os

import pandas as pd
from sklearn.metrics import cohen_kappa_score

from msr.config import OUT

FIELDS = [
    ("severity", "severity_LLM", "severity_사람판정", "quadratic"),
    ("direction", "direction_LLM", "direction_사람판정", None),
    ("dimension", "dimension_LLM", "dimension_사람판정", None),
]


def kappa_interpretation(k: float) -> str:
    if k >= 0.81: return "거의 완전 일치(almost perfect)"
    if k >= 0.61: return "상당한 일치(substantial)"
    if k >= 0.41: return "보통 일치(moderate)"
    if k >= 0.21: return "약한 일치(fair)"
    if k >= 0.0: return "미미한 일치(slight)"
    return "우연보다 나쁨"


def score_field(df: pd.DataFrame, llm_col: str, human_col: str, weights):
    sub = df[[llm_col, human_col]].copy()
    sub[human_col] = sub[human_col].astype(str).str.strip()
    n_total = len(sub)
    n_blank = int((sub[human_col] == "").sum() + sub[human_col].isna().sum())
    n_na_marked = int((sub[human_col] == "판단불가").sum())
    sub = sub[~sub[human_col].isin(["", "nan", "판단불가"])]
    sub = sub.dropna(subset=[llm_col, human_col])
    n_scored = len(sub)
    if n_scored < 2:
        return dict(n_total=n_total, n_scored=n_scored, n_blank=n_blank,
                    n_na_marked=n_na_marked, kappa=None, agree_rate=None)
    if weights == "quadratic":
        # severity는 LLM측이 float("1.0")·사람판정이 int("1")로 들어올 수 있어 문자열 비교가
        # 항상 불일치로 오판정됨 — 반드시 수치로 정규화한 뒤 비교(kappa·단순일치율 둘 다).
        y_llm = sub[llm_col].astype(float).round().astype(int)
        y_human = sub[human_col].astype(float).round().astype(int)
        k = cohen_kappa_score(y_llm, y_human, weights="quadratic")
        agree = float((y_llm == y_human).mean())
    else:
        y_llm = sub[llm_col].astype(str).str.strip()
        y_human = sub[human_col].astype(str).str.strip()
        k = cohen_kappa_score(y_llm, y_human)
        agree = float((y_llm == y_human).mean())
    return dict(n_total=n_total, n_scored=n_scored, n_blank=n_blank,
                n_na_marked=n_na_marked, kappa=round(float(k), 4), agree_rate=round(agree, 4))


def disagreement_examples(df: pd.DataFrame, llm_col: str, human_col: str, weights, n=10):
    sub = df.copy()
    sub[human_col] = sub[human_col].astype(str).str.strip()
    sub = sub[~sub[human_col].isin(["", "nan", "판단불가"])]
    sub = sub.dropna(subset=[llm_col, human_col])
    if weights == "quadratic":
        # score_field와 동일하게 수치 정규화 후 비교(문자열 "1.0" vs "1" 오탐 방지)
        llm_v = sub[llm_col].astype(float).round().astype(int)
        human_v = sub[human_col].astype(float).round().astype(int)
    else:
        llm_v = sub[llm_col].astype(str).str.strip()
        human_v = sub[human_col].astype(str).str.strip()
    mism = sub[llm_v.values != human_v.values]
    cols = ["event_id", "evidence_quote", llm_col, human_col]
    return mism[cols].head(n)


def run(input_path: str):
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    results = {}
    for name, llm_col, human_col, weights in FIELDS:
        if human_col not in df.columns:
            print(f"[warn] 컬럼 없음: {human_col} — 스킵"); continue
        results[name] = score_field(df, llm_col, human_col, weights)
        r = results[name]
        if r["kappa"] is None:
            print(f"{name}: 채점 가능 표본 부족(n_scored={r['n_scored']}) — 아직 검수 미완료로 보임")
        else:
            print(f"{name}: kappa={r['kappa']:.4f}({kappa_interpretation(r['kappa'])}), "
                  f"단순일치율={r['agree_rate']:.4f}, n_scored={r['n_scored']}/{r['n_total']} "
                  f"(빈칸 {r['n_blank']}, 판단불가 {r['n_na_marked']})")

    et_col = "event_type_적절성(Y/N/부분)"
    et_counts = None
    if et_col in df.columns:
        et_counts = df[et_col].astype(str).str.strip().value_counts()
        print("\nevent_type 적절성:\n", et_counts)

    write_report(results, df, et_counts, input_path)


def write_report(results: dict, df: pd.DataFrame, et_counts, input_path: str):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "a5_kappa_report.md")
    L = []
    L.append("# A-5 라벨 품질 검증 — 채점 결과\n")
    L.append(f"작성: 2026-07-18 · 입력: `{input_path}`\n")

    L.append("\n## 필드별 Cohen's kappa\n")
    L.append("| 필드 | kappa | 해석 | 단순일치율 | 채점 표본 | 빈칸 | 판단불가 |")
    L.append("|---|---|---|---|---|---|---|")
    for name, r in results.items():
        if r["kappa"] is None:
            L.append(f"| {name} | — | 검수 미완료 | — | {r['n_scored']}/{r['n_total']} | "
                     f"{r['n_blank']} | {r['n_na_marked']} |")
        else:
            L.append(f"| {name} | {r['kappa']:.4f} | {kappa_interpretation(r['kappa'])} | "
                     f"{r['agree_rate']:.4f} | {r['n_scored']}/{r['n_total']} | "
                     f"{r['n_blank']} | {r['n_na_marked']} |")

    if et_counts is not None and et_counts.sum() > 0:
        L.append("\n## event_type 적절성(정성)\n")
        L.append("| 판정 | 건수 |")
        L.append("|---|---|")
        for k, v in et_counts.items():
            L.append(f"| {k} | {v} |")

    L.append("\n## 불일치 사례(필드별 상위 10건, 프롬프트/추출기 개선 참고용)\n")
    for name, llm_col, human_col, weights in FIELDS:
        if human_col not in df.columns or results.get(name, {}).get("kappa") is None:
            continue
        ex = disagreement_examples(df, llm_col, human_col, weights)
        if len(ex) == 0:
            continue
        L.append(f"\n### {name}\n")
        L.append(f"| event_id | evidence_quote | LLM | 사람판정 |")
        L.append("|---|---|---|---|")
        for _, r in ex.iterrows():
            q = str(r["evidence_quote"])[:80].replace("|", "/")
            L.append(f"| {r['event_id']} | {q} | {r[llm_col]} | {r[human_col]} |")

    L.append("\n## 판정 기준(참고)\n")
    L.append("0.81+ 거의완전일치 · 0.61-0.80 상당한일치 · 0.41-0.60 보통일치 · 0.21-0.40 "
             "약한일치 · 0.00-0.20 미미한일치 · 음수 우연보다나쁨(Landis&Koch 1977 관례). "
             "0.6 미만이면 프롬프트/추출기 개선을 검토할 신호로 판단 권고(조치안 원문 기준).\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[a5_kappa_score] 리포트 → {path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    args = ap.parse_args()
    run(args.input)
