# -*- coding: utf-8 -*-
"""A-5(라벨 품질 검증, 수동검수) 표본 구성 — 피드백기반_수정플랜 P1(미착수 항목).

**주의**: 이 스크립트는 검수용 표본과 스프레드시트를 "준비"만 한다 — 실제 라벨 판정은
사람이 해야 하며(LLM이 대신 채우면 자기검증이라 무의미), 이 스크립트는 그 판정을 채워넣을
빈 칸이 있는 CSV를 만드는 것까지가 역할이다.

**계층표집 설계 변경 사유(실측 기반)**: 조치안 원문은 "발행처·사건유형별 계층표집"을
명시하나, 실측 결과 `geo_event.source`가 전체의 99.6%(1,808,514/1,815,194)가 공백이라
발행처 기준 표집이 사실상 불가능함을 확인[^src]. 대신 (1) commodity_code — 실측 분포
CU 73%·NI 24%·LI/REE/CO 도합 <2%로 극단적으로 쏠려 있어 광종별 균등 표집 필요, (2)
dimension(사건유형의 정규화 버전, A-2 산출) — 실측 policy 97.6%·ops 2.4%·corridor/input/
trade 도합 <0.1%로 희소범주 전수/과다표집 필요, (3) severity — 0~3 균형표집을 3개 축으로
계층화한다.

**부수 발견**: `direction` 필드에 손상된 값 5건 발견 — LLM이 프롬프트의 필드 형식
플레이스홀더를 그대로 반환한 것으로 보임(예: `evidence_quote="[Quote from text]"`,
`direction="[supply_down|supply_up|price_up|price_down|neutral]"`). Pydantic Direction
Literal 검증을 우회해 DB까지 들어간 것 — 별도 파이프라인 점검 필요(이 스크립트는 표본에서
제외만 함)[^corrupt].

표집 규모: 목표 250건 — 희소 dimension(corridor/input/trade) 전수에 가깝게 우선 배정,
나머지를 5광종 균등 예산으로 배분(광종별 ops/policy × severity 0~3 고른 커버리지 지향).

실행: MSR_DB(또는 GEO_PUBLISH_DB) 환경변수로 DB 지정 후
  python3 -m scripts.a5_label_review_sample
산출: outputs/model_opt/a5_review_sample.csv(검수 스프레드시트),
      outputs/model_opt/a5_review_sample_summary.md(표본 구성 요약)
"""
from __future__ import annotations
import os

import duckdb
import numpy as np
import pandas as pd

from msr.config import DB_PATH, OUT

SEED = 42
TOTAL_TARGET = 250
RARE_DIMS = ("corridor", "input", "trade")
RARE_DIM_CAP = 60          # corridor 706건 중 최대 60건까지만(input/trade는 전수 취해도 소량)
CORE_COMMODITIES = ("CU", "NI", "LI", "CO", "REE")
VALID_DIRECTIONS = {"supply_down", "supply_up", "price_up", "price_down", "neutral",
                     "demand_up", "demand_down"}


def load_pool(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    df = con.execute("""
        SELECT event_id, doc_id, commodity_code, obs_date, country, event_type, dimension,
               direction, severity, confidence, evidence_quote, source, provider, extractor
        FROM geo_event
        WHERE evidence_quote IS NOT NULL AND trim(evidence_quote) != ''
    """).fetchdf()
    con.close()
    return df


def run():
    db = os.environ.get("GEO_PUBLISH_DB") or os.environ.get("MSR_DB", DB_PATH)
    pool = load_pool(db)
    n_before = len(pool)

    corrupt = pool[~pool["direction"].isin(VALID_DIRECTIONS)]
    n_corrupt = len(corrupt)
    pool = pool[pool["direction"].isin(VALID_DIRECTIONS)].reset_index(drop=True)
    print(f"모집단: {n_before:,}건 → 손상된 direction {n_corrupt}건 제외 → {len(pool):,}건")

    rng = np.random.default_rng(SEED)
    picked = []

    # 1) 희소 dimension 우선 확보(corridor/input/trade)
    for dim in RARE_DIMS:
        sub = pool[pool["dimension"] == dim]
        n_take = min(len(sub), RARE_DIM_CAP)
        if n_take:
            picked.append(sub.sample(n=n_take, random_state=SEED))
        print(f"  희소dimension[{dim}]: 모집단 {len(sub)}건 → 표집 {n_take}건")

    picked_ids = set(pd.concat(picked)["event_id"]) if picked else set()
    remaining_budget = TOTAL_TARGET - len(picked_ids)
    per_commodity_budget = max(1, remaining_budget // len(CORE_COMMODITIES))
    print(f"희소dimension 표집 후 잔여 예산 {remaining_budget}건 → 광종별 {per_commodity_budget}건")

    # 2) 광종별 균등 예산 — ops/policy × severity 0~3 고른 커버리지 지향(가능한 만큼)
    rest_pool = pool[~pool["event_id"].isin(picked_ids)]
    for cc in CORE_COMMODITIES:
        cc_pool = rest_pool[rest_pool["commodity_code"] == cc]
        if len(cc_pool) == 0:
            print(f"  {cc}: 모집단 0건 — 스킵"); continue
        strata = cc_pool.groupby(["dimension", "severity"], group_keys=False)
        n_strata = strata.ngroups
        per_stratum = max(1, per_commodity_budget // max(1, n_strata))
        cc_picked = strata.apply(lambda g: g.sample(n=min(len(g), per_stratum), random_state=SEED),
                                  include_groups=False)
        cc_picked = cc_picked.reset_index(drop=True)
        # include_groups=False가 그룹핑 컬럼(dimension·severity)을 제거하므로 event_id로 원본 재결합
        cc_picked = cc_pool[cc_pool["event_id"].isin(cc_picked["event_id"])]
        n_short = per_commodity_budget - len(cc_picked)
        if n_short > 0:
            leftover = cc_pool[~cc_pool["event_id"].isin(cc_picked["event_id"])]
            if len(leftover):
                cc_picked = pd.concat([cc_picked, leftover.sample(
                    n=min(len(leftover), n_short), random_state=SEED)])
        print(f"  {cc}: 모집단 {len(cc_pool):,}건({n_strata}개 세부계층) → 표집 {len(cc_picked)}건")
        picked.append(cc_picked)

    sample = pd.concat(picked, ignore_index=True).drop_duplicates(subset="event_id")
    sample = sample.sample(frac=1, random_state=SEED).reset_index(drop=True)  # 셔플(검토 순서 편향 방지)
    print(f"\n최종 표본: {len(sample)}건")

    write_outputs(sample, pool, corrupt, n_before)


def write_outputs(sample: pd.DataFrame, pool: pd.DataFrame, corrupt: pd.DataFrame, n_before: int):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)

    review = sample[["event_id", "commodity_code", "obs_date", "country", "source",
                      "evidence_quote", "event_type", "dimension", "direction", "severity"]].copy()
    review = review.rename(columns={
        "event_type": "event_type_LLM", "dimension": "dimension_LLM",
        "direction": "direction_LLM", "severity": "severity_LLM"})
    # 검토자가 채울 빈 칸(라벨링가이드_A5.md 정의 기준으로 독립 판정)
    review["severity_사람판정"] = ""
    review["direction_사람판정"] = ""
    review["dimension_사람판정"] = ""
    review["event_type_적절성(Y/N/부분)"] = ""
    review["비고"] = ""
    csv_path = os.path.join(out_dir, "a5_review_sample.csv")
    review.to_csv(csv_path, index=False, encoding="utf-8-sig")  # BOM: 엑셀 한글 깨짐 방지

    L = []
    L.append("# A-5 라벨 품질 검증 — 표본 구성 요약\n")
    L.append(f"작성: 2026-07-18 · 모집단 {n_before:,}건(evidence_quote 있는 전체 geo_event) "
             f"중 손상된 direction {len(corrupt)}건 제외 → 유효모집단 {len(pool):,}건 → "
             f"계층표집 {len(sample)}건.\n")

    L.append("\n## 표본 구성(광종×dimension)\n")
    ct = sample.groupby(["commodity_code", "dimension"]).size().unstack(fill_value=0)
    L.append(ct.to_markdown())

    L.append("\n\n## 표본 구성(severity)\n")
    L.append(sample["severity"].value_counts().sort_index().to_markdown())

    L.append(f"\n\n## 손상 데이터 발견(참고, 표본에서 제외됨)\n")
    L.append(f"direction 필드가 유효 카테고리가 아닌 행 {len(corrupt)}건 — LLM이 프롬프트의 "
             f"필드형식 플레이스홀더를 그대로 반환한 것으로 추정(예: "
             f"`evidence_quote=\"[Quote from text]\"`). 예시:\n")
    if len(corrupt):
        L.append("```")
        for _, r in corrupt.head(5).iterrows():
            L.append(f"event_id={r['event_id']} direction={r['direction']!r} "
                     f"evidence_quote={r['evidence_quote']!r}")
        L.append("```")
    L.append("\n별도 파이프라인 점검 과제로 WORKLOG에 등록 — 이 표본 구성과는 무관.\n")

    L.append("\n## 다음 단계\n")
    L.append("1. `outputs/model_opt/a5_review_sample.csv`를 검토자에게 배정(엑셀로 열람 가능, "
             "UTF-8 BOM 인코딩).\n")
    L.append("2. 검토자는 `outputs/model_opt/a5_labeling_guide.md`(라벨링 가이드)를 먼저 읽고, "
             "`evidence_quote`만 근거로 `_사람판정` 칸을 독립적으로 채운다(LLM 판정 칸을 "
             "먼저 보지 않는 것을 권장 — 앵커링 편향 방지).\n")
    L.append("3. 채운 CSV를 `python3 -m scripts.a5_kappa_score --input <채운파일>`로 채점.\n")

    with open(os.path.join(out_dir, "a5_review_sample_summary.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[a5_label_review_sample] 검수 스프레드시트 → {csv_path}")
    print(f"[a5_label_review_sample] 표본 요약 → {out_dir}/a5_review_sample_summary.md")


if __name__ == "__main__":
    run()
