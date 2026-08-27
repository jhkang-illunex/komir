# -*- coding: utf-8 -*-
"""`komis_dump_smoke_test.py` 결과에서 렌더링된 보고서 텍스트의 공통 문법
오류를 전수 검사한다 — 2026-08-26 신설(/unlazy G3).

두 종류를 잡는다:
1. **동사 어미 중복**(예: "변동이 없었했다") — 정규식으로 알려진 이중어미
   패턴을 스캔한다.
2. **은/는·이/가·을/를 받침 조사 오류**(예: "코발트은") — 각 콤보의 요청
   바디에 실제로 등장하는 광종/국가 이름을 모두 모아, 보고서 텍스트에서 그
   이름 바로 뒤에 오는 조사가 받침 유무 규칙과 맞는지 검사한다
   (`additional_summary.py::_topic()`과 같은 규칙을 독립적으로 재구현 —
   렌더러가 실제로 그 함수를 썼는지와 무관하게 결과 텍스트만 보고 판정한다).

CHECK 계약: 문제가 0건이면 종료코드 0 + "NO_PARTICLE_TYPOS" 출력, 1건이라도
있으면 종료코드 1 + 문제 목록 출력.
"""
from __future__ import annotations

import os
import json
import re
import sys
from pathlib import Path

RESULTS_PATH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad")) / "komis_harness_results.json"

_DOUBLE_ENDING_PATTERNS = [
    re.compile(r"없었했다"),
    re.compile(r"였였다"),
    re.compile(r"했했다"),
    re.compile(r"습니다다"),
    re.compile(r"입니다다"),
    re.compile(r"다다\b"),
]


def _has_batchim(char: str) -> bool:
    codepoint = ord(char)
    if not (0xAC00 <= codepoint <= 0xD7A3):
        return False
    return (codepoint - 0xAC00) % 28 != 0


_PARTICLE_PAIRS = [("은", "는"), ("이", "가"), ("을", "를")]


def _entity_names(request: dict) -> set[str]:
    names: set[str] = set()
    if request.get("mineral_name"):
        names.add(request["mineral_name"])
    if request.get("compare_mineral_name"):
        names.add(request["compare_mineral_name"])
    for obs in request.get("observations") or []:
        if isinstance(obs, dict) and obs.get("country_name"):
            names.add(obs["country_name"])
    return {name for name in names if name and len(name) >= 2}


def _check_particles(text: str, names: set[str]) -> list[str]:
    problems = []
    for name in names:
        expects_batchim = _has_batchim(name[-1])
        for with_batchim, without_batchim in _PARTICLE_PAIRS:
            wrong = without_batchim if expects_batchim else with_batchim
            # 이름 바로 뒤에 틀린 조사가 붙어 있으면 오류 — 다른 단어의 일부일 수도
            # 있어 뒤에 조사 다음이 공백/문장부호/한글이 아닌 경우만 걸러낸다.
            pattern = re.compile(re.escape(name) + re.escape(wrong))
            for match in pattern.finditer(text):
                end = match.end()
                trailing = text[end : end + 1]
                # 조사 뒤가 공백/문장부호/문자열 끝이어야 "그 이름 하나의 조사"로
                # 확정할 수 있다(한글이 더 이어지면 다른 단어의 일부일 수 있어
                # 오탐 방지 차원에서 건너뛴다).
                if trailing != "" and not (trailing.isspace() or trailing in ".,)"):
                    continue
                problems.append(f"조사 오류 의심: '{name}{wrong}' in ...{text[max(0, match.start()-10):end+10]}...")
    return problems


def main() -> None:
    if not RESULTS_PATH.exists():
        print(f"결과 파일 없음: {RESULTS_PATH}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))

    all_problems: list[str] = []
    for page_id, entries in data["per_page"].items():
        for entry in entries:
            text = entry.get("report_markdown")
            if not text:
                continue
            combo = f"{page_id}:{entry['combo_key']}"
            for pattern in _DOUBLE_ENDING_PATTERNS:
                if pattern.search(text):
                    all_problems.append(f"[{combo}] 어미 중복 패턴 '{pattern.pattern}' 발견")
            names = _entity_names(entry["request"])
            for problem in _check_particles(text, names):
                all_problems.append(f"[{combo}] {problem}")

    if all_problems:
        print(f"문제 {len(all_problems)}건 발견:")
        for problem in all_problems[:200]:
            print(" -", problem)
        sys.exit(1)

    print("NO_PARTICLE_TYPOS")


if __name__ == "__main__":
    main()
