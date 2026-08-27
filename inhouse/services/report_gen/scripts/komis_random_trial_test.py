# -*- coding: utf-8 -*-
"""광물자원가격 페이지의 모든 검색 차원(광종·품목/가격기준·규격·평균옵션·
기간·비교광종·비교광종 가격기준)을 무작위로 조합해 komis.or.kr에서 실시간
조회하고, 그 데이터를 report_gen의 price API에 그대로 넣어 요약보고서를
만든 뒤 검증한다 — 2026-08-26 신설(사용자 요청, /unlazy).

`komis_live_playwright_test.py`(광종×가격기준 전수)와 짝을 이루되, 이번엔
"전수"가 아니라 "차원별 무작위 조합"이 목적이다 — 특히 이전 라운드에서
전혀 안 건드렸던 3개 차원(평균옵션·기간·비교광종)을 처음으로 실데이터로
태운다.

**사전 조사로 확인한 것(스크립트 안 코드 주석에도 남김)**:
- 평균옵션별 `crtrYmd` 포맷이 다르다 — DAY/WEEK는 8자리(YYYYMMDD)라 우리
  어댑터(`_ymd8`)가 그대로 되지만, MONTH는 6자리(YYYYMM), QUARTER는
  "YYYY.NQ", YEAR는 4자리(YYYY)라 `_ymd8`을 그대로 적용하면 깨진 날짜
  문자열이 되고 Pydantic `Day` 패턴 검증에서 거부된다 — **의도된 동작**으로
  본다(price 페이지 정의 자체가 "일별" 데이터라, 일별이 아닌 집계를 그대로
  먹이면 거부되는 게 맞다). 이 스크립트는 그 경계를 실제로 확인만 하고
  report_gen 코드는 고치지 않는다.
- 비교광종은 `srchCompareMnrkndUnqCd`(광종) + `srchComparePrcCrtr`(가격기준,
  광종 선택 후 옵션이 채워짐) 둘 다 골라야 응답의 `data.compareMnrl`이
  채워진다(실측: 671건, `defaultMnrl`과 같은 shape).
- `spcfct`(규격)는 독립 차원이 아니라 품목(`srchPrcCrtr`) 선택에 종속된
  단일값 표시 필드다(예: 갈륨 Gallium Metal 선택 시 규격 옵션이 항상
  1개만 뜸) — 그래서 별도로 무작위 선택하지 않고 콤보 라벨에만 붙인다.

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_random_trial_test.py
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
from komis_dump_smoke_test import _check_mismatch, _expected_facts, _num, _nonzero  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

SCRATCH = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad"))
OUT_PATH = SCRATCH / "komis_random_trial_results.json"

BASE_METALS = [
    ("MNRL0002", "니켈"), ("MNRL0008", "동"), ("MNRL0023", "아연"),
    ("MNRL0009", "알루미늄"), ("MNRL0022", "연"), ("MNRL0016", "주석"),
]

# 8회 시행 각각의 고정 계획 — 평균옵션 5종을 최소 1회씩은 반드시 태우도록
# 미리 배정하고(완전 무작위면 5종이 8회 안에 다 안 나올 수 있음), 그 밖의
# 차원(페이지/광종/품목/기간/비교광종)은 매 시행 무작위로 뽑는다.
AVG_OPT_PLAN = ["DAY", "DAY", "WEEK", "MONTH", "QUARTER", "YEAR", "DAY", "WEEK"]
PAGE_PLAN = ["base", "minor", "base", "minor", "base", "minor", "minor", "base"]


def _ymd_any(text: str) -> str | None:
    """8자리(YYYYMMDD)만 report_gen의 Day 포맷으로 변환한다. 그 밖의
    포맷(6자리/쿼터/4자리)은 None을 돌려줘 그대로 못 쓴다는 걸 명시한다
    (§모듈 docstring 참고 — 의도된 경계)."""

    text = str(text)
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return None


def _rows_to_observations(rows: list[dict]) -> tuple[list[dict], int, int]:
    """(observations, 변환성공행수, 원본행수). 8자리 아닌 crtrYmd는 건너뛴다."""

    total = len(rows)
    obs = []
    for row in rows:
        date_text = _ymd_any(row["crtrYmd"])
        if date_text is None:
            continue
        obs.append(
            {
                "date": date_text,
                "commerce_price": _num(row.get("cmercPrc")),
                "lowest_price": _nonzero(_num(row.get("lowstPrc"))),
                "highest_price": _nonzero(_num(row.get("hghstPrc"))),
                "inventory": _num(row.get("invt")),
            }
        )
    obs.sort(key=lambda o: o["date"])
    return obs, len(obs), total


def _select_mineral(page, name: str) -> None:
    page.locator("#srchMnrkndUnqCdRadio").get_by_text(name, exact=True).click(timeout=10000)
    page.wait_for_timeout(600)


def _search_and_capture(page) -> dict:
    with page.expect_response(lambda r: "getMnrlPrcByMnrkndUnqCd" in r.url, timeout=15000) as resp_info:
        page.click("#btnSearch")
    return resp_info.value.json()


def run_trial(
    service: AnalysisSummaryService,
    page,
    trial_no: int,
    page_kind: str,
    avg_opt: str,
    forced_mineral: tuple[str, str] | None = None,
) -> dict:
    """`forced_mineral`(code, name) — 2026-08-26 신설(비철금속 전종목 커버리지
    회귀 테스트용). 지정하면 광종은 무작위 대신 이 값을 쓰고, 나머지 6개
    차원(품목·규격·평균옵션 외 기간·비교광종·비교광종가격기준)은 여전히
    trial_no 고정시드로 무작위 선택한다."""

    rng = random.Random(1000 + trial_no)  # 재현 가능하도록 trial별 고정 시드
    url = (
        "https://www.komis.or.kr/Komis/RsrcPrice/BaseMetals"
        if page_kind == "base"
        else "https://www.komis.or.kr/Komis/RsrcPrice/MinorMetals"
    )
    page.goto(url, timeout=40000, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)

    if page_kind == "base":
        minerals = BASE_METALS
    else:
        minerals = page.locator("#srchMnrkndUnqCdRadio input[type=radio]").evaluate_all(
            "els => els.map(el => ({value: el.value, name: el.closest('label').innerText.trim()}))"
        )
        minerals = [(m["value"], m["name"]) for m in minerals]

    mineral_code, mineral_name = forced_mineral if forced_mineral else rng.choice(minerals)
    _select_mineral(page, mineral_name)

    criteria = page.locator("#srchPrcCrtr option").evaluate_all(
        "els => els.map(el => ({value: el.value, text: el.textContent.trim()}))"
    )
    chosen_item = rng.choice(criteria) if criteria else None
    if chosen_item:
        page.select_option("#srchPrcCrtr", chosen_item["value"])
        page.wait_for_timeout(400)
    spec_opts = page.locator("#spcfct option").evaluate_all(
        "els => els.map(el => el.textContent.trim())"
    )
    chosen_spec = rng.choice(spec_opts) if spec_opts else None

    # 평균옵션
    page.select_option("#srchAvgOpt", avg_opt)

    # 기간: srchField(year/month) 무작위 + 시작/끝 연도 무작위(시작<=끝).
    # 이 라디오도 화면 밖(오프캔버스 패널)에 있어 `.check(force=True)`조차
    # "outside of the viewport"로 실패한다(2026-08-26 실측) — JS로 직접
    # checked를 세팅하고 change 이벤트를 dispatch해 완전히 우회한다.
    field_radio = rng.choice(["year", "month"])
    page.evaluate(
        """(value) => {
            const el = document.querySelector(`input[type=radio][name=srchField][value=${value}]`);
            el.checked = true;
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new Event('click', {bubbles: true}));
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
            period_desc = f"(선택실패, 기본값 유지, {field_radio})"

    # 비교광종: 본광종과 다른 것 무작위 선택 + 비교광종 가격기준도 무작위
    compare_pool = [m for m in minerals if m[0] != mineral_code]
    compare_code, compare_name = rng.choice(compare_pool)
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
        "page_kind": page_kind,
        "mineral": mineral_name,
        "mineral_code": mineral_code,
        "item": chosen_item["text"] if chosen_item else None,
        "item_value": chosen_item["value"] if chosen_item else None,
        "spec": chosen_spec,
        "avg_opt": avg_opt,
        "period": period_desc,
        "compare_mineral": compare_name,
        "compare_price_criterion": chosen_compare_crit["text"] if chosen_compare_crit else None,
        "raw_default_row_count": total_n,
        "raw_default_usable_row_count": ok_n,
        "raw_compare_row_count": cmp_total_n,
        "raw_compare_usable_row_count": cmp_ok_n,
        "raw_first_default_row": default_rows[0] if default_rows else None,
        "raw_last_default_row": default_rows[-1] if default_rows else None,
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
        case["note"] = (
            f"평균옵션={avg_opt}이 8자리 crtrYmd가 아니라서 변환 가능한 관측치가 "
            f"{ok_n}/{total_n}건뿐 — report_gen에 넣을 수 없음(의도된 거부 대상)."
            if avg_opt not in ("DAY", "WEEK")
            else "관측치 부족"
        )
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
        case["report_markdown"] = render_markdown_report(response)
        case["applied_filters"] = response_dict["applied_filters"]
        case["key_metrics"] = {m["id"]: m["value"] for m in response_dict["key_metrics"]}
    except ValidationError as exc:
        case["outcome"] = "VALIDATION_ERROR"
        case["error"] = str(exc)[:2000]
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
    cases = []
    started = time.strftime("%Y-%m-%dT%H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for i, (page_kind, avg_opt) in enumerate(zip(PAGE_PLAN, AVG_OPT_PLAN), start=1):
            try:
                case = run_trial(service, page, i, page_kind, avg_opt)
            except Exception as exc:  # noqa: BLE001
                case = {
                    "trial_no": i,
                    "page_kind": page_kind,
                    "avg_opt": avg_opt,
                    "outcome": "TRIAL_FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            cases.append(case)
            print(
                f"[trial {i}] page={page_kind} avgOpt={avg_opt} mineral={case.get('mineral')} "
                f"item={case.get('item')} compare={case.get('compare_mineral')} -> {case['outcome']}"
            )
        browser.close()

    summary = {
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_trials": len(cases),
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
    if summary["internal_error"] == 0 and summary["trial_failed"] == 0 and summary["mismatches"] == 0:
        print("RANDOM_TRIAL_OK")
    else:
        print("RANDOM_TRIAL_FAILED", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
