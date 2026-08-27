# -*- coding: utf-8 -*-
"""`komis_live_playwright_test.py` 결과(`komis_live_results.json`)를 대상으로
`check_particle_typos.py`의 조사 검사 로직 + `komis_dump_smoke_test.py`가
이미 콤보별로 계산해 둔 `mismatches`를 함께 집계한다 — 2026-08-26 신설
(/unlazy, GATES G6). 라이브 결과는 덤프 결과와 JSON 구조가 살짝 달라
(`per_page` 대신 평평한 `results` 리스트) 별도 스크립트로 분리했다.
"""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_particle_typos import _DOUBLE_ENDING_PATTERNS, _check_particles  # noqa: E402

RESULTS_PATH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad")) / "komis_live_results.json"


def main() -> None:
    if not RESULTS_PATH.exists():
        print(f"결과 파일 없음: {RESULTS_PATH}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    problems: list[str] = []
    checked = 0
    for entry in data["results"]:
        if entry.get("status") != "ok":
            continue
        checked += 1
        combo = entry["combo_key"]
        for mismatch in entry.get("mismatches", []):
            problems.append(f"[{combo}] 데이터 불일치: {mismatch}")
        text = entry.get("report_markdown")
        if not text:
            continue
        for pattern in _DOUBLE_ENDING_PATTERNS:
            if pattern.search(text):
                problems.append(f"[{combo}] 어미 중복 패턴 '{pattern.pattern}' 발견")
        names = {entry["request_mineral_name"]} if entry.get("request_mineral_name") else set()
        for problem in _check_particles(text, names):
            problems.append(f"[{combo}] {problem}")

    if problems:
        print(f"문제 {len(problems)}건 (검사 대상 {checked}건 중):")
        for line in problems[:100]:
            print(" -", line)
        sys.exit(1)

    print(f"검사한 성공 콤보 수: {checked}")
    print("LIVE_NO_MISMATCH_OR_TYPO")


if __name__ == "__main__":
    main()
