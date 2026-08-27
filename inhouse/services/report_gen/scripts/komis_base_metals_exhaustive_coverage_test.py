# -*- coding: utf-8 -*-
"""광물자원가격 > 비철금속 메뉴 **품목 단위 전수 커버리지** 회귀 테스트 —
2026-08-26 신설(사용자 요청, /unlazy).

바로 앞서 만든 `komis_base_metals_full_coverage_test.py`(G8)는 6광종을 각
1콤보씩만 커버했다(광종당 여러 가격기준이 있다는 걸 몰랐던 게 아니라,
그때 요청은 "6광종 전부 커버"였지 "광종별 가격기준 전부"는 아니었다).
이번 요청은 희소금속(G9, `komis_minor_metals_full_coverage_test.py`)과
**같은 깊이**를 비철금속에도 요구한다 — "모든 광물의 모든 옵션을 싹 다
하나 이상"은 광종 단위가 아니라 **광종×가격기준 콤보 단위**로 읽어야
한다(비철금속은 광종당 가격기준이 2~3개라 실측 13개 콤보 — G5에서 이미
확인한 숫자와 일치). 비교광종은 G9와 동일하게 "나올 수 있는 모든 케이스"를
라운드로빈으로 결정론적 보장한다(비철금속 비교광종 풀은 자기 자신을 뺀
5광종).

이 스크립트는 G9(`komis_minor_metals_full_coverage_test.py`)와 구조가
거의 같다 — 광종 수·콤보 수만 다르다. 별개 스크립트로 둔 이유는 이미 통과한
G8/G9 게이트의 CHECK 커맨드를 건드리지 않기 위해서다(리팩터링해서 공용
모듈로 합치면 더 깔끔하겠지만, 이미 승인된 게이트의 동작을 바꿀 위험을
지지 않는 쪽을 택했다).

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_base_metals_exhaustive_coverage_test.py
"""
from __future__ import annotations

import os
import json
import random
import sys
import time
import traceback
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_APP_ROOT / "scripts"))

from app._bootstrap import ensure_shared_on_path  # noqa: E402

ensure_shared_on_path()

from app.analysis.data_sources import DataSourceError  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402
from app.analysis.report_render import render_markdown_report  # noqa: E402
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from komis_dump_smoke_test import _check_mismatch, _expected_facts  # noqa: E402
from komis_random_trial_test import _rows_to_observations, _search_and_capture  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

SCRATCH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad"))
OUT_PATH = SCRATCH / "komis_base_metals_exhaustive_coverage_results.json"

AVG_OPT_CYCLE = ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"]
URL = "https://www.komis.or.kr/Komis/RsrcPrice/BaseMetals"


def _select_mineral(page, name: str) -> None:
    page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=10000)
    page.wait_for_timeout(500)


def discover_all_item_combos(page):
    page.goto(URL, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    minerals = page.locator("#srchMnrkndUnqCdRadio input[type=radio]").evaluate_all(
        "els => els.map(el => ({value: el.value, name: el.closest('label').innerText.trim()}))"
    )
    combos = []
    for m in minerals:
        _select_mineral(page, m["name"])
        criteria = page.locator("#srchPrcCrtr option").evaluate_all(
            "els => els.map(el => ({value: el.value, text: el.textContent.trim()}))"
        )
        for c in criteria:
            combos.append(
                {
                    "mineral_code": m["value"],
                    "mineral_name": m["name"],
                    "item_value": c["value"],
                    "item_text": c["text"],
                }
            )
    return combos, [(m["value"], m["name"]) for m in minerals]


def run_one(service, page, trial_no, combo, avg_opt, compare_mineral):
    rng = random.Random(4000 + trial_no)
    mineral_code, mineral_name = combo["mineral_code"], combo["mineral_name"]
    page.goto(URL, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    _select_mineral(page, mineral_name)
    page.select_option("#srchPrcCrtr", combo["item_value"])
    page.wait_for_timeout(400)

    page.select_option("#srchAvgOpt", avg_opt)

    field_radio = rng.choice(["year", "month"])
    page.evaluate(
        """(value) => {
            const el = document.querySelector(`input[type=radio][name=srchField][value=${value}]`);
            el.checked = true;
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        field_radio,
    )
    page.wait_for_timeout(300)
    start_opts = page.locator("#srchStartDate option").evaluate_all("els => els.map(e=>e.value)")
    end_opts = page.locator("#srchEndDate option").evaluate_all("els => els.map(e=>e.value)")
    period_desc = None
    if start_opts and end_opts:
        start_val = rng.choice(start_opts)
        end_candidates = [v for v in end_opts if v >= start_val] or [start_val]
        end_val = rng.choice(end_candidates)
        try:
            page.select_option("#srchStartDate", start_val)
            page.select_option("#srchEndDate", end_val)
            period_desc = f"{start_val}~{end_val}({field_radio})"
        except Exception:
            period_desc = f"(선택실패, {field_radio})"

    compare_code, compare_name = compare_mineral
    page.select_option("#srchCompareMnrkndUnqCd", compare_code)
    page.wait_for_timeout(500)
    compare_criteria = page.locator("#srchComparePrcCrtr option").evaluate_all(
        "els => els.map(el => ({value: el.value, text: el.textContent.trim()})).filter(o => o.value)"
    )
    chosen_compare_crit = rng.choice(compare_criteria) if compare_criteria else None
    if chosen_compare_crit:
        page.select_option("#srchComparePrcCrtr", chosen_compare_crit["value"])

    body = _search_and_capture(page)
    info = (body.get("dataAvg") or {}).get("INFO") or {}
    default_rows = (body.get("data") or {}).get("defaultMnrl") or []
    compare_rows = (body.get("data") or {}).get("compareMnrl") or []
    observations, ok_n, total_n = _rows_to_observations(default_rows)
    compare_observations, cmp_ok_n, cmp_total_n = _rows_to_observations(compare_rows)

    case = {
        "trial_no": trial_no,
        "mineral": mineral_name,
        "item": combo["item_text"],
        "avg_opt": avg_opt,
        "period": period_desc,
        "compare_mineral": compare_name,
        "compare_price_criterion": chosen_compare_crit["text"] if chosen_compare_crit else None,
        "raw_default_row_count": total_n,
        "raw_default_usable_row_count": ok_n,
    }

    request_dict = {
        "page_id": "price",
        "mineral": mineral_code,
        "mineral_name": info.get("mnrkndKornNm") or mineral_name,
        "price_criterion": info.get("prcCrtr"),
        "observations": observations,
        "compare_mineral": compare_code,
        "compare_mineral_name": compare_name,
        "compare_price_criterion": chosen_compare_crit["text"] if chosen_compare_crit else None,
        "compare_observations": compare_observations or None,
    }

    if len(observations) < 2 or observations[-1]["commerce_price"] is None:
        case["outcome"] = "SKIPPED_INSUFFICIENT_DATA"
        case["note"] = f"평균옵션={avg_opt}, 변환가능 관측치 {ok_n}/{total_n}건"
        return case

    try:
        summary_request = AnalysisSummaryRequest(**request_dict)
        response = service.analyze(summary_request)
        response_dict = json.loads(response.model_dump_json())
        expected = _expected_facts("price", request_dict)
        mismatches = _check_mismatch("price", expected, response_dict)
        case["outcome"] = "ok"
        case["mismatches"] = mismatches
        case["expected_latest_price"] = expected["latest_price"]
        case["key_metrics"] = {m["id"]: m["value"] for m in response_dict["key_metrics"]}
        case["report_markdown"] = render_markdown_report(response)
    except ValidationError as exc:
        case["outcome"] = "VALIDATION_ERROR"
        case["error"] = str(exc)[:1000]
    except DataSourceError as exc:
        case["outcome"] = "NO_DATA"
        case["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        case["outcome"] = "INTERNAL_ERROR"
        case["error"] = f"{type(exc).__name__}: {exc}"
        case["traceback"] = traceback.format_exc()
    return case


def main() -> None:
    service = AnalysisSummaryService(None, llm=None)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        combos, all_minerals = discover_all_item_combos(page)
        print(f"discovered {len(combos)} item combos across {len(all_minerals)} base-metal minerals")

        cases = []
        for i, combo in enumerate(combos, start=1):
            avg_opt = AVG_OPT_CYCLE[i % len(AVG_OPT_CYCLE)]
            compare_idx = i % len(all_minerals)
            compare_mineral = all_minerals[compare_idx]
            if compare_mineral[0] == combo["mineral_code"]:
                compare_mineral = all_minerals[(compare_idx + 1) % len(all_minerals)]
            try:
                case = run_one(service, page, i, combo, avg_opt, compare_mineral)
            except Exception as exc:  # noqa: BLE001
                case = {
                    "trial_no": i,
                    "mineral": combo["mineral_name"],
                    "item": combo["item_text"],
                    "avg_opt": avg_opt,
                    "compare_mineral": compare_mineral[1],
                    "outcome": "TRIAL_FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            cases.append(case)
            print(
                f"[{i}/{len(combos)}] {combo['mineral_name']} | {combo['item_text']} | avgOpt={avg_opt} "
                f"| compare={compare_mineral[1]} -> {case['outcome']}"
            )
        browser.close()

    distinct_minerals = {c["mineral"] for c in cases}
    distinct_items = {(c["mineral"], c.get("item")) for c in cases}
    compare_minerals_used = {c["compare_mineral"] for c in cases if c.get("compare_mineral")}
    all_mineral_names = {name for _, name in all_minerals}
    missing_compare = all_mineral_names - compare_minerals_used

    summary = {
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_trials": len(cases),
        "distinct_minerals_covered": len(distinct_minerals),
        "total_base_metal_minerals": len(all_minerals),
        "distinct_item_combos_covered": len(distinct_items),
        "compare_minerals_used_count": len(compare_minerals_used),
        "compare_minerals_missing": sorted(missing_compare),
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
        and summary["distinct_minerals_covered"] == summary["total_base_metal_minerals"]
        and not summary["compare_minerals_missing"]
    ):
        print("BASE_METALS_EXHAUSTIVE_COVERAGE_OK")
    else:
        print("BASE_METALS_EXHAUSTIVE_COVERAGE_FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
