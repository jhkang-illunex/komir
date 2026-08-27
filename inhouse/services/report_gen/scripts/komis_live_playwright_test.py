# -*- coding: utf-8 -*-
"""komis.or.kr 광물자원가격(비철금속·희소금속) 전 광종×전 가격기준 조합을
Playwright로 라이브 조회해 report_gen의 결정론적 경로에 던져 검증한다 —
2026-08-26 신설(사용자 요청, /unlazy).

`komis_dump_smoke_test.py`(정적 덤프 기반)와 짝을 이루는 라이브판이다 —
같은 어댑터/검증 로직(`_num`·`_nonzero`·`_ymd8`·`_expected_facts`·
`_check_mismatch`)을 그대로 재사용한다(같은 endpoint가 같은 shape을 주므로).

**주의**: 이 세션(개발 샌드박스)의 `curl`은 komis.or.kr에 연결이 안 되지만
(아웃바운드 방화벽 추정) Playwright가 띄우는 실제 Chromium 프로세스는
연결된다(실측 확인, 2026-08-26) — 이유는 불명이나 재현됨.

**전수 범위**: 비철금속 6광종×2가격기준=12콤보, 희소금속 34광종×광종별
가격기준 드롭다운(1~3개, 실측 60여개)=약 60콤보 — 광종 라디오 선택 →
가격기준 select 변경 → `#btnSearch` 클릭이 실제 AJAX(`getMnrlPrcByMnrkndUnqCd`)
를 트리거하는 유일한 경로임을 실측으로 확인(라디오 change 이벤트 자체는
AJAX를 안 태움, `onSearch()` 버튼 클릭이 필요).

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_live_playwright_test.py
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

from app.analysis.data_sources import DataSourceError  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402
from app.analysis.report_render import render_markdown_report  # noqa: E402
from app.analysis.summary import AnalysisSummaryService  # noqa: E402
from komis_dump_smoke_test import _check_mismatch, _expected_facts, _num, _nonzero, _ymd8  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

SCRATCH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad"))
OUT_PATH = SCRATCH / "komis_live_results.json"

BASE_METALS = [
    ("MNRL0002", "니켈"),
    ("MNRL0008", "동"),
    ("MNRL0023", "아연"),
    ("MNRL0009", "알루미늄"),
    ("MNRL0022", "연"),
    ("MNRL0016", "주석"),
]

def _adapt(resp_body: dict, mineral_code: str) -> dict:
    info = (resp_body.get("dataAvg") or {}).get("INFO") or {}
    rows = (resp_body.get("data") or {}).get("defaultMnrl") or []
    rows = sorted(rows, key=lambda row: row["crtrYmd"])
    observations = [
        {
            "date": _ymd8(row["crtrYmd"]),
            "commerce_price": _num(row.get("cmercPrc")),
            "lowest_price": _nonzero(_num(row.get("lowstPrc"))),
            "highest_price": _nonzero(_num(row.get("hghstPrc"))),
            "inventory": _num(row.get("invt")),
        }
        for row in rows
    ]
    return {
        "page_id": "price",
        "mineral": mineral_code,
        "mineral_name": info.get("mnrkndKornNm") or mineral_code,
        "price_criterion": info.get("prcCrtr"),
        "observations": observations,
    }


def _run_combo(service: AnalysisSummaryService, resp_body: dict, mineral_code: str, combo_key: str) -> dict:
    request_dict = _adapt(resp_body, mineral_code)
    entry = {"combo_key": combo_key, "request_mineral_name": request_dict["mineral_name"], "price_criterion": request_dict["price_criterion"]}
    if len(request_dict["observations"]) < 2 or request_dict["observations"][-1]["commerce_price"] is None:
        entry["status"] = "NO_DATA"
        entry["error"] = f"observations 부족(count={len(request_dict['observations'])})"
        return entry
    try:
        summary_request = AnalysisSummaryRequest(**request_dict)
        response = service.analyze(summary_request)
        response_dict = json.loads(response.model_dump_json())
        expected = _expected_facts("price", request_dict)
        mismatches = _check_mismatch("price", expected, response_dict)
        entry["status"] = "ok"
        entry["mismatches"] = mismatches
        entry["latest_price"] = expected["latest_price"]
        entry["observation_count"] = len(request_dict["observations"])
        entry["report_markdown"] = render_markdown_report(response)
    except DataSourceError as exc:
        entry["status"] = "NO_DATA"
        entry["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        entry["status"] = "INTERNAL_ERROR"
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["traceback"] = traceback.format_exc()
    return entry


def _search_and_capture(page):
    with page.expect_response(lambda r: "getMnrlPrcByMnrkndUnqCd" in r.url, timeout=15000) as resp_info:
        page.click("#btnSearch")
    return resp_info.value.json()


def _select_mineral(page, name: str) -> None:
    page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=10000)
    page.wait_for_timeout(600)


def run_base_metals(service: AnalysisSummaryService, page, log: list[str]) -> list[dict]:
    """비철금속 6광종 x 광종별 가격기준(LME CASH/3개월) 조합을 라이브 조회한다.

    2026-08-26 실측 발견·수정: `srchPrcCrtr` select의 옵션 value(내부
    serial)는 광종마다 다르다(예: 니켈은 LME CASH=502, 동은 LME CASH=501) —
    처음엔 하드코딩한 고정값(BASE_CRITERIA)을 재사용하다 두 번째 광종부터
    `select_option`이 "옵션을 못 찾음"으로 전부 실패했다. 희소금속과 똑같이
    광종 선택 직후 그 시점의 실제 옵션 value를 다시 읽어와야 한다(하드코딩
    금지 — report_gen 버그가 아니라 이 하네스 자체의 버그였음)."""

    results = []
    page.goto("https://www.komis.or.kr/Komis/RsrcPrice/BaseMetals", timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    for mineral_code, mineral_name in BASE_METALS:
        _select_mineral(page, mineral_name)
        criteria = page.locator("#srchPrcCrtr option").evaluate_all(
            "els => els.map(el => ({value: el.value, text: el.textContent.trim()}))"
        )
        for crit in criteria:
            # value(내부 serial)를 콤보키에 넣는다 — 갈륨/인듐처럼 드롭다운
            # 표시텍스트가 같아도 실제로는 서로 다른 원산지/스펙 계열인
            # 경우가 있어(2026-08-26 실측), text만으로는 콤보를 구분 못 한다.
            combo_key = f"base_metals:{mineral_name}|{crit['text']}[{crit['value']}]"
            try:
                page.select_option("#srchPrcCrtr", crit["value"])
                body = _search_and_capture(page)
                entry = _run_combo(service, body, mineral_code, combo_key)
            except Exception as exc:  # noqa: BLE001
                entry = {"combo_key": combo_key, "status": "FETCH_FAILED", "error": f"{type(exc).__name__}: {exc}"}
            results.append(entry)
            log.append(f"[base_metals] {mineral_name} | {crit['text']}[{crit['value']}] -> {entry['status']}")
            print(log[-1])
    return results


def run_minor_metals(service: AnalysisSummaryService, page, log: list[str]) -> list[dict]:
    results = []
    page.goto("https://www.komis.or.kr/Komis/RsrcPrice/MinorMetals", timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    minerals = page.locator("#srchMnrkndUnqCdRadio input[type=radio]").evaluate_all(
        "els => els.map(el => ({value: el.value, name: el.closest('label').innerText.trim()}))"
    )
    for mineral in minerals:
        mineral_code, mineral_name = mineral["value"], mineral["name"]
        _select_mineral(page, mineral_name)
        criteria = page.locator("#srchPrcCrtr option").evaluate_all(
            "els => els.map(el => ({value: el.value, text: el.textContent.trim()}))"
        )
        if not criteria:
            combo_key = f"minor_metals:{mineral_name}|(기본)"
            try:
                body = _search_and_capture(page)
                entry = _run_combo(service, body, mineral_code, combo_key)
            except Exception as exc:  # noqa: BLE001
                entry = {"combo_key": combo_key, "status": "FETCH_FAILED", "error": f"{type(exc).__name__}: {exc}"}
            results.append(entry)
            log.append(f"[minor_metals] {mineral_name} | (기본) -> {entry['status']}")
            print(log[-1])
            continue
        for crit in criteria:
            combo_key = f"minor_metals:{mineral_name}|{crit['text']}[{crit['value']}]"
            try:
                page.select_option("#srchPrcCrtr", crit["value"])
                body = _search_and_capture(page)
                entry = _run_combo(service, body, mineral_code, combo_key)
            except Exception as exc:  # noqa: BLE001
                entry = {"combo_key": combo_key, "status": "FETCH_FAILED", "error": f"{type(exc).__name__}: {exc}"}
            results.append(entry)
            log.append(f"[minor_metals] {mineral_name} | {crit['text']}[{crit['value']}] -> {entry['status']}")
            print(log[-1])
    return results


def main() -> None:
    service = AnalysisSummaryService(None, llm=None)
    log: list[str] = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        base_results = run_base_metals(service, page, log)
        minor_results = run_minor_metals(service, page, log)
        browser.close()

    all_results = base_results + minor_results
    ok = sum(1 for r in all_results if r["status"] == "ok")
    no_data = sum(1 for r in all_results if r["status"] == "NO_DATA")
    internal_error = sum(1 for r in all_results if r["status"] == "INTERNAL_ERROR")
    fetch_failed = sum(1 for r in all_results if r["status"] == "FETCH_FAILED")
    mismatches = sum(len(r.get("mismatches", [])) for r in all_results)

    summary = {
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_combos": len(all_results),
        "base_metals_combos": len(base_results),
        "minor_metals_combos": len(minor_results),
        "ok": ok,
        "no_data": no_data,
        "internal_error": internal_error,
        "fetch_failed": fetch_failed,
        "mismatches": mismatches,
    }
    output = {"summary": summary, "results": all_results, "log": log}
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"saved: {OUT_PATH}")
    if internal_error == 0 and fetch_failed == 0 and mismatches == 0 and len(all_results) >= 60:
        print("LIVE_HARNESS_OK")
    else:
        print("LIVE_HARNESS_FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
