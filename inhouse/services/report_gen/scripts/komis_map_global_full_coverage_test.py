# -*- coding: utf-8 -*-
"""핵심광물지도 > 수급지도 > 글로벌(map_global) 메뉴 전종목 커버리지 회귀
테스트 — 2026-08-26 신설(사용자 요청, /unlazy).

`komis_map_korea_full_coverage_test.py`와 짝을 이룬다 — 같은 이유로 이
페이지에도 "비교광종" 컨트롤이 없음을 실측 확인(select 8개: 광종·형태구분·
세부구분·HS코드·수출국·수입국·연도·월, radio 2개: 기준연월타입만 — 대한
민국 페이지와 거의 같고 `srchIncmExp`(수입/수출 방향) 대신 국가 2종
select가 있다). 실제 존재하는 옵션(광종 73종 전부·기준연월타입 Y/M·기준
연도)만 무작위로 테스트한다.

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_map_global_full_coverage_test.py
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
from komis_dump_smoke_test import _num  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

SCRATCH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad"))
OUT_PATH = SCRATCH / "komis_map_global_full_coverage_results.json"
URL = "https://www.komis.or.kr/Komis/MnrlMap/Nation"


def _select_mineral(page, name: str) -> None:
    # 상단 네비게이션 서브메뉴가 이전 페이지에서 남은 마우스 좌표 위에서 자동으로
    # 펼쳐져 라디오 레이블 클릭을 가로채는 경우가 있음(2026-08-26 map_mineral에서
    # 최초 실측, map_global에서도 재현). goto 직후 마우스를 중립 위치로 옮기고,
    # 그래도 실패하면 force 클릭으로 재시도.
    page.mouse.move(640, 600)
    page.wait_for_timeout(200)
    try:
        page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=5000)
    except Exception:
        page.mouse.move(640, 600)
        page.wait_for_timeout(300)
        page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=10000, force=True)
    page.wait_for_timeout(500)


def _set_radio(page, name: str, value: str) -> None:
    page.evaluate(
        """([n, v]) => {
            const el = document.querySelector(`input[type=radio][name=${n}][value=${v}]`);
            el.checked = true;
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        [name, value],
    )
    page.wait_for_timeout(200)


def _search_and_capture(page) -> dict:
    with page.expect_response(lambda r: "getListDataNation" in r.url, timeout=15000) as resp_info:
        page.click("#onSearch")
    return resp_info.value.json()


def _adapt_observations(body: dict, as_of_date: str) -> list[dict]:
    """2026-08-27 재작성 — 원산국(exporter)별로 뭉개 집계하던 이전 버전은 PDF가
    요구하는 "원산지→도착지" 양자 루트 랭킹과 대한민국 자체 순위를 만들 수
    없었다(PDF 지침 점검(/unlazy)에서 발견한 gap). 실측 확인(Playwright로
    원본 응답 직접 조회) 결과 KOMIS 응답 각 행에 도착국(`incmNtnNm`/
    `incmNtnCd`)·원산국(`expNtnNm`/`expNtnCd`) 필드가 이미 쌍으로 와 있어,
    행 단위 그대로(집계 없이) 넘기면 된다."""

    rows = body.get("list") or []
    observations = []
    for row in rows:
        dest_code = row.get("incmNtnCd")
        origin_code = row.get("expNtnCd")
        if not dest_code or not origin_code:
            continue
        observations.append(
            {
                "date": as_of_date,
                "country_code": dest_code,
                "country_name": row.get("incmNtnNm") or dest_code,
                "origin_country_code": origin_code,
                "origin_country_name": row.get("expNtnNm") or origin_code,
                "import_weight": _num(row.get("weig")),
                "import_amount": _num(row.get("amt")),
            }
        )
    return observations


def run_one(service, page, trial_no, mineral_code, mineral_name):
    rng = random.Random(6000 + trial_no)
    page.goto(URL, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    _select_mineral(page, mineral_name)

    crtr_ymd = rng.choice(["Y", "M"])
    _set_radio(page, "srchCrtrYmd", crtr_ymd)
    year_opts = page.locator("#srchYearE option").evaluate_all("els => els.map(e=>e.value)")
    chosen_year = rng.choice(year_opts) if year_opts else None
    if chosen_year:
        page.select_option("#srchYearE", chosen_year)

    body = _search_and_capture(page)
    as_of_date = f"{chosen_year or '2026'}-12-31"
    observations = _adapt_observations(body, as_of_date)
    total_amount = sum(o["import_amount"] or 0.0 for o in observations)

    case = {
        "trial_no": trial_no,
        "mineral": mineral_name,
        "crtr_ymd": crtr_ymd,
        "year": chosen_year,
        "row_count": len(observations),
    }

    if not observations or total_amount <= 0:
        case["outcome"] = "SKIPPED_INSUFFICIENT_DATA"
        case["note"] = f"관측치 {len(observations)}건, 총액 {total_amount}"
        return case

    request_dict = {
        "page_id": "map_global",
        "mineral": mineral_code,
        "mineral_name": mineral_name,
        "observations": observations,
    }
    try:
        summary_request = AnalysisSummaryRequest(**request_dict)
        response = service.analyze(summary_request)
        response_dict = json.loads(response.model_dump_json())
        metrics = {m["id"]: m["value"] for m in response_dict["key_metrics"]}
        mismatches = []
        if abs((metrics.get("total_amount") or 0) - total_amount) > max(1.0, total_amount * 0.01):
            mismatches.append(f"total_amount 불일치: expected={total_amount} actual={metrics.get('total_amount')}")
        top1 = max(observations, key=lambda o: o["import_amount"] or 0.0)
        top1_share = (top1["import_amount"] or 0.0) / total_amount * 100
        if metrics.get("top1_share_pct") is not None and abs(metrics["top1_share_pct"] - top1_share) > 0.5:
            mismatches.append(f"top1_share_pct 불일치: expected={top1_share:.2f} actual={metrics.get('top1_share_pct')}")
        report_markdown = render_markdown_report(response)
        # 2026-08-27 대한민국 루트 하이라이트 회귀 확인 — 독립 재계산.
        korea_rows = [
            o for o in observations if o["country_code"] == "KR" or o["origin_country_code"] == "KR"
        ]
        if korea_rows and "대한민국은 세부현황 기준" not in report_markdown:
            mismatches.append("한국 루트가 관측치에 있는데 보고서에 '대한민국은 세부현황 기준' 문구가 없음")
        if not korea_rows and "대한민국이 포함된 개별 루트는" not in report_markdown:
            mismatches.append("한국 루트가 없는데 결측 문구('대한민국이 포함된 개별 루트는...')가 보고서에 없음")
        case["outcome"] = "ok"
        case["mismatches"] = mismatches
        case["key_metrics"] = metrics
        case["report_markdown"] = report_markdown
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
        print(f"discovered {len(minerals)} minerals on map_global")

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
            print(f"[{i}/{len(minerals)}] {m['name']} | crtrYmd={case.get('crtr_ymd')} year={case.get('year')} -> {case['outcome']}")
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
        print("MAP_GLOBAL_FULL_COVERAGE_OK")
    else:
        print("MAP_GLOBAL_FULL_COVERAGE_FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
