# -*- coding: utf-8 -*-
"""`komis_dump_smoke_test.py` 결과에서 status="INTERNAL_ERROR"(예상 못 한
코드 버그)가 0건인지 확인한다 — 2026-08-26 신설(/unlazy G2).

`NO_DATA`는 게이트 대상이 아니다 — 원본 덤프 레코드 자체에 관측치가 없거나
필터 후 비어버리는 정당한 케이스일 수 있다(어댑터가 이미 그런 레코드는
걸러내려 하지만, 완전히 배제한다고 보장하진 않는다). INTERNAL_ERROR만
"코드가 실데이터에서 죽었다"는 신호라 게이트로 삼는다.
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

    errors = []
    for page_id, entries in data["per_page"].items():
        for entry in entries:
            if entry["status"] == "INTERNAL_ERROR":
                errors.append(f"[{page_id}:{entry['combo_key']}] {entry.get('error')}")

    if errors:
        print(f"INTERNAL_ERROR {len(errors)}건:")
        for line in errors[:100]:
            print(" -", line)
        sys.exit(1)

    total = sum(len(entries) for entries in data["per_page"].values())
    print(f"검사한 combo 수: {total}")
    print("NO_INTERNAL_ERRORS")


if __name__ == "__main__":
    main()
