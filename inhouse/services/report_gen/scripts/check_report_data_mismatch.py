# -*- coding: utf-8 -*-
"""`komis_dump_smoke_test.py`가 이미 각 combo마다 계산해 둔 `mismatches`
(하네스가 원본 덤프에서 독립 재계산한 정답값 vs 실제 `AnalysisSummaryResponse.
key_metrics` 대조 결과)를 전수 집계한다 — 2026-08-26 신설(/unlazy G4).
"""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path

RESULTS_PATH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad")) / "komis_harness_results.json"


def main() -> None:
    if not RESULTS_PATH.exists():
        print(f"결과 파일 없음: {RESULTS_PATH}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    all_mismatches = []
    checked = 0
    for page_id, entries in data["per_page"].items():
        for entry in entries:
            if entry["status"] != "ok":
                continue
            checked += 1
            for problem in entry.get("mismatches", []):
                all_mismatches.append(f"[{page_id}:{entry['combo_key']}] {problem}")

    if all_mismatches:
        print(f"불일치 {len(all_mismatches)}건 (검사 대상 {checked}건 중):")
        for line in all_mismatches[:100]:
            print(" -", line)
        sys.exit(1)

    print(f"검사한 성공 combo 수: {checked}")
    print("NO_MISMATCHES")


if __name__ == "__main__":
    main()
