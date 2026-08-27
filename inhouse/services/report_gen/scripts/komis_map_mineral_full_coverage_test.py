# -*- coding: utf-8 -*-
"""핵심광물지도 > 광물지도(map_mineral) 메뉴 전종목 커버리지 회귀 테스트 —
2026-08-26 신설(사용자 요청, /unlazy).

`komis_map_korea_full_coverage_test.py`와 짝 — 이 페이지에도 "비교광종"
컨트롤이 없음을 실측 확인(select 4개: 국가·광종·시작연도·끝연도, radio
1개: 광종만 — 탭 2개로 매장량/생산량 전환). 실제 존재하는 옵션(광종 65종
전부·매장량/생산량 탭·시작·끝연도)만 무작위로 테스트한다. 검색 버튼은
`id` 없이 `onclick="onSearchMapMnrl(1)"`만 있어 다른 페이지들과 셀렉터가
다르다(실측 확인 — `#onSearch`가 이 페이지엔 없음).

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_map_mineral_full_coverage_test.py
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
from komis_dump_smoke_test import _ci_get, _num  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

SCRATCH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad"))
OUT_PATH = SCRATCH / "komis_map_mineral_full_coverage_results.json"
URL = "https://www.komis.or.kr/Komis/MnrlMap/MnrlMap"


def _select_mineral(page, name: str) -> None:
    # 상단 네비게이션 서브메뉴(header.open-submenu > ul.depth2-menu)가 이전 페이지에서
    # 남은 마우스 좌표 위에서 자동으로 펼쳐져 라디오 레이블 클릭을 가로채는 경우가 있음
    # (2026-08-26 실측 — 65종 중 8종 연속 TRIAL_FAILED로 재현). goto 직후 마우스를
    # 중립 위치로 옮겨 서브메뉴가 열리지 않게 한 뒤, 그래도 실패하면 force 클릭으로 재시도.
    page.mouse.move(640, 600)
    page.wait_for_timeout(200)
    try:
        page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=5000)
    except Exception:
        page.mouse.move(640, 600)
        page.wait_for_timeout(300)
        page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=10000, force=True)
    page.wait_for_timeout(500)


def _search_and_capture(page) -> dict:
    with page.expect_response(lambda r: "getListMapMnrlChartData" in r.url, timeout=15000) as resp_info:
        page.locator('button[onclick="onSearchMapMnrl(1)"]').click()
    return resp_info.value.json()


def _adapt_observations(rows: list[dict], measure: str) -> list[dict]:
    value_key = "burudgQuty" if measure == "reserves" else "prdctnQuty"
    total_keys = ("totalBurudgQuty",) if measure == "reserves" else ("TOTALPRDCTNQUTY", "totalPrdctnQuty")
    by_year: dict[int, list[dict]] = {}
    totals: dict[int, float] = {}
    for row in rows:
        year = int(row["crtrYr"])
        value = _num(row.get(value_key))
        if value is None or value <= 0:
            continue
        by_year.setdefault(year, []).append(
            {
                "year": year,
                "country_code": row.get("ntnEngCd") or row.get("ntnKornNm"),
                "country_name": row.get("ntnKornNm") or row.get("ntnEngNm"),
                "value": value,
                "is_total": False,
                "is_other": False,
            }
        )
        total_val = _num(_ci_get(row, *total_keys))
        if total_val is not None:
            totals[year] = total_val
    observations = []
    for year in sorted(by_year):
        observations.extend(by_year[year])
        if year in totals:
            observations.append(
                {
                    "year": year,
                    "country_code": "WORLD",
                    "country_name": "세계",
                    "value": totals[year],
                    "is_total": True,
                    "is_other": False,
                }
            )
    return observations


def run_one(service, page, trial_no, mineral_code, mineral_name):
    rng = random.Random(7000 + trial_no)
    page.goto(URL, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    _select_mineral(page, mineral_name)

    measure = rng.choice(["reserves", "production"])
    if measure == "production":
        page.click("#tab_prdctn")
        page.wait_for_timeout(300)
    unit = None
    start_opts = page.locator("#srchYearS option").evaluate_all("els => els.map(e=>e.value)")
    end_opts = page.locator("#srchYearE option").evaluate_all("els => els.map(e=>e.value)")
    chosen_start = chosen_end = None
    if start_opts and end_opts:
        chosen_start = rng.choice(start_opts)
        end_candidates = [v for v in end_opts if v >= chosen_start] or [chosen_start]
        chosen_end = rng.choice(end_candidates)
        page.select_option("#srchYearS", chosen_start)
        page.select_option("#srchYearE", chosen_end)

    body = _search_and_capture(page)
    rows = body.get("data") or []
    if rows:
        unit = str(rows[0].get("cdVal") or "").strip() or "단위미상"
    observations = _adapt_observations(rows, measure)
    years_present = sorted({o["year"] for o in observations})

    case = {
        "trial_no": trial_no,
        "mineral": mineral_name,
        "measure": measure,
        "start_year": chosen_start,
        "end_year": chosen_end,
        "row_count": len(rows),
        "years_present": years_present,
    }

    if len(years_present) < 2:
        case["outcome"] = "SKIPPED_INSUFFICIENT_DATA"
        case["note"] = f"연도 수 {len(years_present)}건"
        return case
    current_year_rows = [o for o in observations if o["year"] == years_present[-1] and not o["is_total"]]
    if len(current_year_rows) < 3:
        case["outcome"] = "SKIPPED_INSUFFICIENT_DATA"
        case["note"] = f"최신연도 국가 수 {len(current_year_rows)}건 (<3)"
        return case

    request_dict = {
        "page_id": "map_mineral",
        "mineral": mineral_code,
        "mineral_name": mineral_name,
        "measure": measure,
        "unit": unit or "단위미상",
        "observations": observations,
    }
    try:
        summary_request = AnalysisSummaryRequest(**request_dict)
        response = service.analyze(summary_request)
        response_dict = json.loads(response.model_dump_json())
        metrics = {m["id"]: m["value"] for m in response_dict["key_metrics"]}

        year = years_present[-1]
        rows_this_year = [o for o in observations if o["year"] == year]
        total_row = next((o for o in rows_this_year if o["is_total"]), None)
        country_rows = [o for o in rows_this_year if not o["is_total"] and not o["is_other"]]
        world_total = total_row["value"] if total_row else sum(o["value"] for o in country_rows)
        top1 = max(country_rows, key=lambda o: o["value"])

        mismatches = []
        tol = max(1.0, world_total * 0.01)
        if abs((metrics.get("current_world_total") or 0) - world_total) > tol:
            mismatches.append(f"current_world_total 불일치: expected={world_total} actual={metrics.get('current_world_total')}")
        if metrics.get("top_country") != top1["country_name"]:
            mismatches.append(f"top_country 불일치: expected={top1['country_name']} actual={metrics.get('top_country')}")

        case["outcome"] = "ok"
        case["mismatches"] = mismatches
        case["key_metrics"] = metrics
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
        page.goto(URL, timeout=40000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        minerals = page.locator("#srchMnrkndUnqCdRadio input[type=radio]").evaluate_all(
            "els => els.map(el => ({value: el.value, name: el.closest('label').innerText.trim()}))"
        )
        print(f"discovered {len(minerals)} minerals on map_mineral")

        cases = []
        for i, m in enumerate(minerals, start=1):
            try:
                case = run_one(service, page, i, m["value"], m["name"])
            except Exception as exc:  # noqa: BLE001
                case = {
                    "trial_no": i,
                    "mineral": m["name"],
                    "outcome": "TRIAL_FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            cases.append(case)
            print(
                f"[{i}/{len(minerals)}] {m['name']} | measure={case.get('measure')} "
                f"period={case.get('start_year')}~{case.get('end_year')} -> {case['outcome']}"
            )
        browser.close()

    distinct_minerals = {c["mineral"] for c in cases}
    summary = {
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_trials": len(cases),
        "distinct_minerals_covered": len(distinct_minerals),
        "total_minerals": len(minerals),
        "ok": sum(1 for c in cases if c["outcome"] == "ok"),
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
        and summary["distinct_minerals_covered"] == summary["total_minerals"]
    ):
        print("MAP_MINERAL_FULL_COVERAGE_OK")
    else:
        print("MAP_MINERAL_FULL_COVERAGE_FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
