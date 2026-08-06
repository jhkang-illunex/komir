# -*- coding: utf-8 -*-
"""A-5(라벨 품질 검증, 수동검수) 표본 구성 — v2 (2026-07-27, B안 2인 교차 판정용).

**주의**: 이 스크립트는 검수용 표본과 스프레드시트를 "준비"만 한다 — 실제 라벨 판정은
사람이 해야 하며(LLM이 대신 채우면 자기검증이라 무의미), 이 스크립트는 그 판정을 채워넣을
빈 칸이 있는 CSV를 만드는 것까지가 역할이다.

## v2 변경 사유(2026-07-27 실측, A5_사람판정_진행방안_260727.md)
- 구판(07-18)은 GKG 정제 전 모집단(181만)에서 표집 — 248건 중 현행 생존 122건(49%)이라
  재표집. 구 산출물(a5_review_sample.csv 등)은 그대로 보존(신규는 _260727 접미사).
- dimension이 현행 geo_event에서 전량 None(정제 후 재발행 미보존) → 층화축을
  (광종×severity) 2축으로, 판정 항목을 severity·direction·event_type 적절성 3종으로 축소.
- B안(2인 교차): 동일 표본을 검토자 A·B가 독립 판정 → 사람간 kappa(기준선)도 산출.
  검토자 배포용 사본에는 severity_LLM·direction_LLM 열 자체를 제거(앵커링 원천 차단 —
  구판의 "열 숨김 권장"보다 강한 방식). event_type_LLM은 적절성 판정 대상이라 유지.
  LLM 값은 마스터 CSV에만 남기고 채점 시 event_id로 병합(scripts/a5_kappa_score.py).

표집 규모: 목표 250건 — 광종별 균등 예산 50건, 광종 내 severity(0~3)별 균등 배분 후
부족분은 해당 광종 잔여에서 무작위 보충. 희소 광종(CO 4,546·REE 3,641건)도 예산 충족 가능.

실행: MSR_DB(또는 GEO_PUBLISH_DB) 환경변수로 DB 지정 후
  python3 -m scripts.a5_label_review_sample
산출(outputs/model_opt/):
  a5_review_sample_260727.csv           — 마스터(LLM값 포함, 채점용 — 검토자 배포 금지)
  a5_review_A_260727.csv / a5_review_B_260727.csv — 검토자 A/B 배포용(LLM 판정값 제외)
  a5_review_sample_summary_260727.md    — 표본 구성 요약
"""
from __future__ import annotations
import os

import numpy as np
import pandas as pd
import duckdb

from msr.config import DB_PATH, OUT

SEED = 42
TOTAL_TARGET = 250
CORE_COMMODITIES = ("CU", "NI", "LI", "CO", "REE")
PER_COMMODITY = TOTAL_TARGET // len(CORE_COMMODITIES)
SEVERITIES = (0, 1, 2, 3)
VALID_DIRECTIONS = {"supply_down", "supply_up", "price_up", "price_down", "neutral",
                    "demand_up", "demand_down"}
SUFFIX = "260727"

REVIEW_COLS = ["event_id", "commodity_code", "obs_date", "country",
               "evidence_quote", "event_type_LLM"]
JUDGE_COLS = ["severity_사람판정", "direction_사람판정", "event_type_적절성(Y/N/부분)", "비고"]


def load_pool(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    df = con.execute("""
        SELECT event_id, commodity_code, obs_date, country, event_type,
               direction, severity, evidence_quote
        FROM geo_event
        WHERE evidence_quote IS NOT NULL AND trim(evidence_quote) != ''
          AND severity IS NOT NULL
    """).fetchdf()
    con.close()
    return df


def run():
    db = os.environ.get("GEO_PUBLISH_DB") or os.environ.get("MSR_DB", DB_PATH)
    pool = load_pool(db)
    n_before = len(pool)
    pool = pool[pool["direction"].isin(VALID_DIRECTIONS)].reset_index(drop=True)
    print(f"모집단: {n_before:,}건 → direction 유효값 필터 후 {len(pool):,}건")

    picked = []
    for cc in CORE_COMMODITIES:
        cc_pool = pool[pool["commodity_code"] == cc]
        if len(cc_pool) == 0:
            print(f"  {cc}: 모집단 0건 — 스킵")
            continue
        per_sev = max(1, PER_COMMODITY // len(SEVERITIES))
        cc_picked = []
        for sev in SEVERITIES:
            cell = cc_pool[cc_pool["severity"].round().astype(int) == sev]
            n_take = min(len(cell), per_sev)
            if n_take:
                cc_picked.append(cell.sample(n=n_take, random_state=SEED))
        cc_df = pd.concat(cc_picked) if cc_picked else cc_pool.iloc[:0]
        n_short = PER_COMMODITY - len(cc_df)
        if n_short > 0:
            leftover = cc_pool[~cc_pool["event_id"].isin(cc_df["event_id"])]
            if len(leftover):
                cc_df = pd.concat([cc_df, leftover.sample(
                    n=min(len(leftover), n_short), random_state=SEED)])
        sev_dist = cc_df["severity"].round().astype(int).value_counts().sort_index().to_dict()
        print(f"  {cc}: 모집단 {len(cc_pool):,}건 → 표집 {len(cc_df)}건 (severity {sev_dist})")
        picked.append(cc_df)

    sample = pd.concat(picked, ignore_index=True).drop_duplicates(subset="event_id")
    sample = sample.sample(frac=1, random_state=SEED).reset_index(drop=True)  # 검토 순서 편향 방지
    print(f"\n최종 표본: {len(sample)}건")
    write_outputs(sample, pool, n_before)


def write_outputs(sample: pd.DataFrame, pool: pd.DataFrame, n_before: int):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)

    master = sample.rename(columns={
        "event_type": "event_type_LLM", "direction": "direction_LLM",
        "severity": "severity_LLM"}).copy()
    master["severity_LLM"] = master["severity_LLM"].round().astype(int)
    master_path = os.path.join(out_dir, f"a5_review_sample_{SUFFIX}.csv")
    master[REVIEW_COLS + ["severity_LLM", "direction_LLM"]].to_csv(
        master_path, index=False, encoding="utf-8-sig")

    # 검토자 배포용: LLM 판정값(severity·direction) 열 자체를 제거 — 앵커링 원천 차단.
    # event_type_LLM만 유지(적절성 판정의 대상이라 봐야 함).
    for rev in ("A", "B"):
        r = master[REVIEW_COLS].copy()
        for c in JUDGE_COLS:
            r[c] = ""
        r.to_csv(os.path.join(out_dir, f"a5_review_{rev}_{SUFFIX}.csv"),
                 index=False, encoding="utf-8-sig")

    L = [f"# A-5 라벨 품질 검증 — 표본 구성 요약 (v2, 2026-07-27)\n",
         f"모집단 {n_before:,}건(정제 후 geo_event, evidence_quote·severity 있는 행) 중 "
         f"direction 유효값 {len(pool):,}건 → (광종×severity) 층화표집 {len(sample)}건.\n",
         "구판(07-18, 정제 전 모집단) 표본은 생존율 49%라 폐기하지 않고 보존만 — "
         "실판정은 이 v2 표본으로 진행(A5_사람판정_진행방안_260727.md).\n",
         "\n## 표본 구성(광종×severity)\n",
         sample.assign(sev=sample["severity"].round().astype(int))
               .groupby(["commodity_code", "sev"]).size().unstack(fill_value=0).to_markdown(),
         "\n\n## 다음 단계(B안 — 2인 교차)\n",
         f"1. `a5_review_A_{SUFFIX}.csv`·`a5_review_B_{SUFFIX}.csv`를 검토자 A·B에게 각각 배포"
         "(엑셀 호환 UTF-8 BOM). 두 검토자는 서로 논의 없이 독립 판정.\n",
         f"2. 가이드는 `a5_labeling_guide_v2_{SUFFIX}.md` — 파일럿 20건 후 모호점 보정.\n",
         f"3. 채점: `python3 -m scripts.a5_kappa_score --input <A채운파일> --input2 <B채운파일> "
         f"--master a5_review_sample_{SUFFIX}.csv` → LLM vs A·B kappa + 사람간 kappa.\n"]
    with open(os.path.join(out_dir, f"a5_review_sample_summary_{SUFFIX}.md"), "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[a5_label_review_sample] 마스터 → {master_path}")
    print(f"[a5_label_review_sample] 검토자 A/B 사본·요약 → {out_dir}/a5_review_[AB]_{SUFFIX}.csv")


if __name__ == "__main__":
    run()
