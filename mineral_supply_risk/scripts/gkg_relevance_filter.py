# -*- coding: utf-8 -*-
"""GKG 관련성 필터 — 캘리브레이션 하네스(re-export wrapper).

정본 구현은 geo/gkg_relevance.py로 이전됨(2026-07-20 /goal — 파이프라인 코드인
geo/gkg_parse.py·geo/gkg_verify.py가 직접 import해서 쓰므로 그쪽이 정본).
이 파일은 기존 캘리브레이션 스크립트(__main__ 블록)와의 호환을 위해 얇게 re-export만 한다.
튜닝 이력·설계원칙 문서: geo/gkg_relevance.py 모듈 docstring,
outputs/model_opt/gkg_relevance_filter_calibration.md.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # komir root
from geo.gkg_relevance import (  # noqa: E402,F401
    is_relevant, COMMODITY_NAMES, COMMODITY_COMPANIES, GENERIC_MINING_KEYWORDS,
    OTHER_METALS, OTHER_METAL_COMPANIES, NOISE_PHRASES, NOISE_REGEX,
)

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # mineral_supply_risk
    import pandas as pd
    from scripts.srs_contamination_check import JUDGMENTS

    df = pd.read_csv("/tmp/srs_sample.csv")
    correct = wrong = skipped = 0
    fp, fn = [], []
    for i, row in df.iterrows():
        truth = JUDGMENTS.get(i)
        if truth == "U":
            skipped += 1
            continue
        text = f"{row['evidence_quote']} {row.get('event_type', '')}"
        pred_relevant = is_relevant(text, row["commodity_code"])
        truth_relevant = (truth == "R")
        if pred_relevant == truth_relevant:
            correct += 1
        else:
            wrong += 1
            entry = (i, row["event_id"], row["commodity_code"], row["evidence_quote"])
            (fp if pred_relevant else fn).append(entry)
    n = correct + wrong
    print(f"정확도(U 제외 n={n}): {correct}/{n} = {correct/n:.1%}")
    print(f"오탐(관련있다 예측, 실제 무관) {len(fp)}건:")
    for x in fp:
        print("  FP:", x)
    print(f"누락(무관 예측, 실제 관련있음) {len(fn)}건:")
    for x in fn:
        print("  FN:", x)
