# -*- coding: utf-8 -*-
"""광물자원가격 > 비철금속 메뉴의 6개 광종 **전종목**을 각각 최소 1회씩
반드시 커버하면서, 그 안에서 나머지 차원(품목/가격기준·평균옵션·기간·
비교광종·비교광종가격기준)은 무작위로 조합해 report_gen price API를 검증
한다 — 2026-08-26 신설(사용자 요청, /unlazy).

`komis_random_trial_test.py`의 8회 무작위 시행(비철·희소 섞어서 표본
추출)과 달리, 이번엔 **비철금속만** 6광종 전부를 보장 커버하는 게
목적이다(`forced_mineral` 인자로 광종을 고정하고 나머지는 그대로 무작위).
평균옵션도 DAY·WEEK(정상 처리) + MONTH·QUARTER(의도된 거부, §komis_random_
trial_test.py 모듈 docstring 참고) 양쪽을 비철금속 안에서 직접 확인한다.

이 시행 전체는 단일 스레드(단일 Playwright 브라우저 프로세스)로 순차
실행한다 — 6회 시행 x 몇 초 수준이라 별도 세션/에이전트로 쪼개는 오버헤드가
이득보다 크다고 판단했다(사용자 지시의 "여러 쓰레드 혹은 단일 쓰레드"
선택권 행사, herd tab/pane은 "여러 세션일 경우"에만 요구됨).

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_base_metals_full_coverage_test.py
"""
from __future__ import annotations

import os
import json
import sys
import time
import traceback
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_APP_ROOT / "scripts"))

from app._bootstrap import ensure_shared_on_path  # noqa: E402

ensure_shared_on_path()

from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from komis_random_trial_test import BASE_METALS, run_trial  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

SCRATCH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad"))
OUT_PATH = SCRATCH / "komis_base_metals_full_coverage_results.json"

# 6광종(BASE_METALS 순서: 니켈·동·아연·알루미늄·연·주석) 전부 최소 1회 커버.
# 평균옵션은 DAY·WEEK(정상 처리 기대) + QUARTER·MONTH(의도된 거부 기대)를
# 섞어 비철금속 자체에서도 그 경계를 직접 확인한다.
AVG_OPT_PLAN = ["DAY", "WEEK", "DAY", "WEEK", "QUARTER", "MONTH"]


def main() -> None:
    service = AnalysisSummaryService(None, llm=None)
    cases = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for i, ((mineral_code, mineral_name), avg_opt) in enumerate(zip(BASE_METALS, AVG_OPT_PLAN), start=1):
            # trial_no를 2000번대로 둬서 komis_random_trial_test.py의 1000번대
            # 시드와 겹치지 않게 한다(재현성 있는 별개 무작위열).
            trial_no = 2000 + i
            try:
                case = run_trial(
                    service, page, trial_no, "base", avg_opt, forced_mineral=(mineral_code, mineral_name)
                )
            except Exception as exc:  # noqa: BLE001
                case = {
                    "trial_no": trial_no,
                    "mineral": mineral_name,
                    "avg_opt": avg_opt,
                    "outcome": "TRIAL_FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            cases.append(case)
            print(
                f"[base_metals_full] {mineral_name} avgOpt={avg_opt} item={case.get('item')} "
                f"period={case.get('period')} compare={case.get('compare_mineral')}"
                f"({case.get('compare_price_criterion')}) -> {case['outcome']}"
            )
        browser.close()

    summary = {
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_trials": len(cases),
        "distinct_minerals_covered": len({c.get("mineral") for c in cases if c.get("mineral")}),
        "ok": sum(1 for c in cases if c["outcome"] == "ok"),
        "validation_error": sum(1 for c in cases if c["outcome"] == "VALIDATION_ERROR"),
        "no_data": sum(1 for c in cases if c["outcome"] == "NO_DATA"),
        "internal_error": sum(1 for c in cases if c["outcome"] == "INTERNAL_ERROR"),
        "skipped_insufficient_data": sum(1 for c in cases if c["outcome"] == "SKIPPED_INSUFFICIENT_DATA"),
        "trial_failed": sum(1 for c in cases if c["outcome"] == "TRIAL_FAILED"),
        "mismatches": sum(len(c.get("mismatches", [])) for c in cases),
    }
    OUT_PATH.write_text(json.dumps({"summary": summary, "cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"saved: {OUT_PATH}")
    if (
        summary["internal_error"] == 0
        and summary["trial_failed"] == 0
        and summary["mismatches"] == 0
        and summary["distinct_minerals_covered"] == 6
    ):
        print("BASE_METALS_FULL_COVERAGE_OK")
    else:
        print("BASE_METALS_FULL_COVERAGE_FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
