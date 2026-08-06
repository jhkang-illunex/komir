# -*- coding: utf-8 -*-
"""A-5 라벨 품질 검증 — 채점 스크립트. 검토자가 판정 열을 채운 뒤 이 스크립트로
LLM 추출값과의 Cohen's kappa를 산출한다.

- severity: quadratic-weighted kappa(순서형, 프로젝트 표준 QWK와 동일 가중 방식)
- direction·dimension: 비가중(nominal) Cohen's kappa
  (v2 표본은 dimension 소실로 판정 항목에서 제외 — 열 없으면 자동 스킵)
- event_type_적절성: kappa 대상 아님(정성 신호) — Y/N/부분 비율만 집계
- "판단불가"로 표시되거나 사람판정 칸이 빈 행은 자동 제외(집계에도 별도 표기)

v2(2026-07-27, B안 2인 교차) 추가:
- --master: 검토자 배포용 CSV에는 LLM 판정값이 없으므로(앵커링 차단) 마스터 CSV를
  event_id로 병합해 LLM 열을 붙인다.
- --input2: 검토자 B의 채운 파일 — 검토자별 LLM 대비 kappa에 더해 **사람간(A vs B)
  kappa**(기준선)를 산출. LLM kappa는 사람간 kappa를 상한 참조점으로 해석한다.

실행(구판 단일 파일): python3 -m scripts.a5_kappa_score --input <채운파일>
실행(v2 2인 교차):   python3 -m scripts.a5_kappa_score --input <A채운파일> \
    --input2 <B채운파일> --master outputs/model_opt/a5_review_sample_260727.csv
산출: outputs/model_opt/a5_kappa_report.md (--out으로 변경 가능)
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
    # 실제 빈 셀은 read_csv에서 NaN→astype(str)로 "nan"이 됨 — ""만 세면 항상 0으로 표기됨
    n_blank = int(sub[human_col].isin(["", "nan"]).sum())
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


ET_COL = "event_type_적절성(Y/N/부분)"


def _load_with_master(input_path: str, master_path: str | None) -> pd.DataFrame:
    df = pd.read_csv(input_path, encoding="utf-8-sig")
    if master_path:
        m = pd.read_csv(master_path, encoding="utf-8-sig")
        llm_cols = [c for c in m.columns if c.endswith("_LLM")]
        df = df.merge(m[["event_id"] + llm_cols], on="event_id",
                      how="left", suffixes=("", "_master"))
        for c in llm_cols:   # 검토자 파일에 이미 있으면(구판) 그대로, 없으면 마스터 값
            if f"{c}_master" in df.columns:
                df[c] = df[c].where(df[c].notna(), df[f"{c}_master"])
                df = df.drop(columns=[f"{c}_master"])
    return df


def _score_one(df: pd.DataFrame, tag: str) -> dict:
    results = {}
    for name, llm_col, human_col, weights in FIELDS:
        if human_col not in df.columns or llm_col not in df.columns:
            print(f"[warn] ({tag}) 컬럼 없음: {human_col if human_col not in df.columns else llm_col} — 스킵")
            continue
        results[name] = score_field(df, llm_col, human_col, weights)
        r = results[name]
        if r["kappa"] is None:
            print(f"({tag}) {name}: 채점 가능 표본 부족(n_scored={r['n_scored']}) — 검수 미완료로 보임")
        else:
            print(f"({tag}) {name}: kappa={r['kappa']:.4f}({kappa_interpretation(r['kappa'])}), "
                  f"단순일치율={r['agree_rate']:.4f}, n_scored={r['n_scored']}/{r['n_total']} "
                  f"(빈칸 {r['n_blank']}, 판단불가 {r['n_na_marked']})")
    return results


def _inter_rater(da: pd.DataFrame, db_: pd.DataFrame) -> dict:
    """사람간(A vs B) kappa — event_id로 정렬 병합, 양쪽 다 유효 판정인 행만."""
    j = da.merge(db_, on="event_id", suffixes=("_A", "_B"))
    out = {}
    for name, _llm, human_col, weights in FIELDS:
        ca, cb = f"{human_col}_A", f"{human_col}_B"
        if ca not in j.columns or cb not in j.columns:
            continue
        sub = j[[ca, cb]].copy()
        for c in (ca, cb):
            sub[c] = sub[c].astype(str).str.strip()
        sub = sub[~sub[ca].isin(["", "nan", "판단불가"]) & ~sub[cb].isin(["", "nan", "판단불가"])]
        if len(sub) < 2:
            out[name] = dict(n_scored=len(sub), kappa=None, agree_rate=None)
            continue
        if weights == "quadratic":
            ya = sub[ca].astype(float).round().astype(int)
            yb = sub[cb].astype(float).round().astype(int)
            k = cohen_kappa_score(ya, yb, weights="quadratic")
        else:
            ya, yb = sub[ca], sub[cb]
            k = cohen_kappa_score(ya, yb)
        out[name] = dict(n_scored=len(sub), kappa=round(float(k), 4),
                         agree_rate=round(float((ya.values == yb.values).mean()), 4))
    # event_type 적절성 — 정성이라 일치율만
    ca, cb = f"{ET_COL}_A", f"{ET_COL}_B"
    if ca in j.columns and cb in j.columns:
        sub = j[[ca, cb]].copy()
        for c in (ca, cb):
            sub[c] = sub[c].astype(str).str.strip()
        sub = sub[(~sub[ca].isin(["", "nan"])) & (~sub[cb].isin(["", "nan"]))]
        if len(sub):
            out["event_type_적절성(일치율만)"] = dict(
                n_scored=len(sub), kappa=None,
                agree_rate=round(float((sub[ca] == sub[cb]).mean()), 4))
    return out


def run(input_path: str, input2_path: str | None = None,
        master_path: str | None = None, out_path: str | None = None):
    df_a = _load_with_master(input_path, master_path)
    results = {"A": _score_one(df_a, "검토자A" if input2_path else "검토자")}
    df_b = inter = None
    if input2_path:
        df_b = _load_with_master(input2_path, master_path)
        results["B"] = _score_one(df_b, "검토자B")
        inter = _inter_rater(df_a, df_b)
        print("\n사람간(A vs B):")
        for name, r in inter.items():
            k = f"kappa={r['kappa']:.4f}({kappa_interpretation(r['kappa'])}), " if r["kappa"] is not None else ""
            print(f"  {name}: {k}일치율={r['agree_rate']}, n={r['n_scored']}")

    et_counts = {}
    for tag, d in (("A", df_a), ("B", df_b)):
        if d is not None and ET_COL in d.columns:
            et_counts[tag] = d[ET_COL].astype(str).str.strip().value_counts()
            print(f"\nevent_type 적절성({tag}):\n", et_counts[tag])

    write_report(results, df_a, et_counts, input_path, inter, out_path)


def write_report(results: dict, df: pd.DataFrame, et_counts, input_path: str,
                 inter: dict | None = None, out_path: str | None = None):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = out_path or os.path.join(out_dir, "a5_kappa_report.md")
    L = []
    L.append("# A-5 라벨 품질 검증 — 채점 결과\n")
    L.append(f"입력: `{input_path}`" + (" + 검토자 B(2인 교차)" if inter is not None else "") + "\n")

    for tag, res in results.items():
        L.append(f"\n## 필드별 Cohen's kappa — LLM vs 검토자 {tag}\n" if len(results) > 1
                 else "\n## 필드별 Cohen's kappa\n")
        L.append("| 필드 | kappa | 해석 | 단순일치율 | 채점 표본 | 빈칸 | 판단불가 |")
        L.append("|---|---|---|---|---|---|---|")
        for name, r in res.items():
            if r["kappa"] is None:
                L.append(f"| {name} | — | 검수 미완료 | — | {r['n_scored']}/{r['n_total']} | "
                         f"{r['n_blank']} | {r['n_na_marked']} |")
            else:
                L.append(f"| {name} | {r['kappa']:.4f} | {kappa_interpretation(r['kappa'])} | "
                         f"{r['agree_rate']:.4f} | {r['n_scored']}/{r['n_total']} | "
                         f"{r['n_blank']} | {r['n_na_marked']} |")

    if inter is not None:
        L.append("\n## 사람간(A vs B) kappa — LLM kappa 해석의 기준선\n")
        L.append("| 필드 | kappa | 해석 | 일치율 | n |")
        L.append("|---|---|---|---|---|")
        for name, r in inter.items():
            kk = f"{r['kappa']:.4f}" if r["kappa"] is not None else "—"
            ki = kappa_interpretation(r["kappa"]) if r["kappa"] is not None else "(정성 — 일치율만)"
            L.append(f"| {name} | {kk} | {ki} | {r['agree_rate']} | {r['n_scored']} |")
        L.append("\n해석 원칙: LLM kappa는 사람간 kappa를 사실상의 상한 참조점으로 두고 "
                 "읽는다(사람끼리 0.6이면 LLM 0.6은 준수한 수준).\n")

    for tag, ec in (et_counts or {}).items():
        if ec is not None and ec.sum() > 0:
            L.append(f"\n## event_type 적절성(정성) — 검토자 {tag}\n")
            L.append("| 판정 | 건수 |")
            L.append("|---|---|")
            for k, v in ec.items():
                L.append(f"| {k} | {v} |")

    L.append("\n## 불일치 사례(검토자 A 기준 필드별 상위 10건, 프롬프트/추출기 개선 참고용)\n")
    res_a = results.get("A") or next(iter(results.values()), {})
    for name, llm_col, human_col, weights in FIELDS:
        if human_col not in df.columns or llm_col not in df.columns \
                or res_a.get(name, {}).get("kappa") is None:
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
    ap.add_argument("--input", required=True, help="검토자(또는 A)가 채운 CSV")
    ap.add_argument("--input2", help="검토자 B가 채운 CSV(2인 교차 — 사람간 kappa 추가)")
    ap.add_argument("--master", help="LLM 판정값이 든 마스터 CSV(검토자 파일에 LLM 열이 없을 때)")
    ap.add_argument("--out", help="리포트 출력 경로(기본 outputs/model_opt/a5_kappa_report.md)")
    args = ap.parse_args()
    run(args.input, args.input2, args.master, args.out)
