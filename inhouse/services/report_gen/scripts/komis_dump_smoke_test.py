# -*- coding: utf-8 -*-
"""`income_data/komis/`의 실 KOMIS 덤프로 report_gen 결정론적 경로를 전수
회귀 테스트하는 하네스 — 2026-08-26 신설(사용자 요청, /unlazy).

**범위**: 데이터 원천이 있는 7개 page_id(indicator_market·indicator_supply·
indicator_composite·map_mineral·price·map_korea·map_global)만 다룬다.
`forecast_price`는 KOMIS 덤프에 대응 원천이 없어 제외(기존에도 알려진 갭,
WORKLOG/메모리 참고).

**LLM 정제는 이 하네스 범위 밖이다** — `AnalysisSummaryService(llm=None)`으로
직접 계산·검증·렌더링 파이프라인만 돈다. LLM 정제 성공/폴백 동작은 이전 턴의
스모크 테스트로 이미 별도 검증됐다(이 세션은 vLLM 미접속이라 여기서 다시
돌려도 같은 정보를 12초×수백건으로 반복할 뿐이라 의도적으로 뺐다).

**어댑터가 "덤프 레코드 → report_gen Observation dict"로 변환할 때 하는
근사**(정확성보다 파이프라인 전수 실행이 목적):
- price류(비철/희소금속): `srchAvgOpt=DAY` 콤보만 쓴다(광종/기준당 1개면
  충분 — 나머지 avgOpt는 같은 일별 원천의 다른 집계일 뿐).
- indicator_composite: "1년" 프리셋(가장 최근 관측 위주, 774행/3=258일)만
  쓴다 — "전체(2016~)"까지 쓰면 결과 JSON이 불필요하게 커진다.
- map_korea/map_global: "전체기간·수입·list" 콤보 1개만 쓴다(광종당 관측일이
  1개뿐이라 `single_snapshot` 분기를 탄다 — 정상 분기 중 하나).
- map_global은 KOMIS "list" 엔드포인트가 이미 상위 N개 양자무역 조합만 주므로,
  같은 수출국(`expNtnCd`)의 `amt`를 합산해 "그 나라의 세계 공급 총액"
  근사치로 쓴다(진짜 전체 합계가 아니라 덤프에 담긴 상위 조합의 합 — 그래도
  파이프라인이 실데이터 스케일·자리수로 정상 동작하는지 검증하기엔 충분).
- mineral_map: chart 엔드포인트(연도×국가별 매장량/생산량)에 KOMIS가 매
  행마다 반복해 주는 `totalBurudgQuty`/`TOTALPRDCTNQUTY`(대소문자 다름,
  실측 확인)로 `is_total=True` 합성 행을 연도별 1개씩 추가한다 — 덤프에
  포함된 국가만 합산하면 상위 N개국 절단 때문에 과소집계될 수 있어서다.

실행:
    cd komir/inhouse/services/report_gen
    python3 scripts/komis_dump_smoke_test.py [--summary-only] [--out PATH]
"""
from __future__ import annotations

import os
import argparse
import json
import sys
import traceback
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP_ROOT))

from app._bootstrap import ensure_shared_on_path  # noqa: E402

ensure_shared_on_path()

from app.analysis.data_sources import DataSourceError  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest  # noqa: E402
from app.analysis.report_render import render_markdown_report  # noqa: E402
from app.analysis.summary import AnalysisSummaryService  # noqa: E402

DUMP_DIR = Path("/home/nuri/dev/git/ws/mine_ws/komir/income_data/komis")
DEFAULT_OUT = Path(os.environ.get("KOMIS_HARNESS_SCRATCH", "/tmp/claude-1002/-home-nuri-dev-git-ws-mine-ws-komir/8f5c04be-95b3-4831-b723-8ff599b42842/scratchpad")) / "komis_harness_results.json"


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed


def _nonzero(value: float | None) -> float | None:
    """KOMIS는 값이 없을 때 '0.00'을 채워 보낸다(실측 확인) — 0을 결측으로 취급."""
    if value is None or value == 0:
        return None
    return value


def _dot_date(text: str) -> str:
    return text.replace(".", "-")


def _ymd8(text: str) -> str:
    text = str(text)
    return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"


def _year6(text: str) -> str:
    """'YYYYMM' -> 'YYYY-MM'."""
    text = str(text)
    return f"{text[0:4]}-{text[4:6]}"


def _ci_get(row: dict, *names: str):
    """대소문자가 다른 동의 키(예: totalBurudgQuty vs TOTALPRDCTNQUTY)를 순서대로 찾는다."""
    for name in names:
        if name in row:
            return row[name]
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _load(name: str) -> dict:
    return json.loads((DUMP_DIR / name).read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────
# 어댑터: 덤프 -> (combo_key, request_dict) 리스트
# ─────────────────────────────────────────────────────────────────


def adapt_price_pages(dump: dict, source_label: str) -> list[tuple[str, dict]]:
    out = []
    for r in dump["results"]:
        if not r["endpoint"].endswith("getMnrlPrcByMnrkndUnqCd"):
            continue
        params = r["params"]
        if params.get("srchAvgOpt") != "DAY":
            continue
        resp = r["response"]
        info = (resp.get("dataAvg") or {}).get("INFO") or {}
        rows = (resp.get("data") or {}).get("defaultMnrl") or []
        rows = sorted(rows, key=lambda row: row["crtrYmd"])
        if len(rows) < 2:
            continue
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
        if observations[-1]["commerce_price"] is None:
            continue
        mineral_code = params["srchMnrkndUnqCd"]
        request = {
            "page_id": "price",
            "mineral": mineral_code,
            "mineral_name": info.get("mnrkndKornNm") or mineral_code,
            "price_criterion": info.get("prcCrtr"),
            "observations": observations,
        }
        out.append((f"{source_label}:{r['key']}", request))
    return out


def adapt_mineral_index(dump: dict) -> list[tuple[str, dict]]:
    target = next(r for r in dump["results"] if r["key"] == "광물종합지수|1년")
    table = target["response"]["data"]["tableData"]
    by_date: dict[str, dict[str, float]] = {}
    for row in table:
        by_date.setdefault(row["crtrYmd"], {})[row["indxTp"]] = row["indx"]
    observations = []
    for date_text in sorted(by_date):
        values = by_date[date_text]
        if not all(key in values for key in ("MNRL", "MAJOR", "RARE")):
            continue
        observations.append(
            {
                "date": _dot_date(date_text),
                "composite_index": values["MNRL"],
                "major_metals_index": values["MAJOR"],
                "minor_metals_index": values["RARE"],
            }
        )
    if len(observations) < 4:
        return []
    request = {"page_id": "indicator_composite", "observations": observations}
    return [("mineral_index:composite_1y", request)]


def adapt_indicator_pages(dump: dict, page_id: str, source_label: str) -> list[tuple[str, dict]]:
    score_field = "mrktPrspectIdct" if page_id == "indicator_market" else "spdmStbtIndx"
    out = []
    for r in dump["results"]:
        if not r["endpoint"].endswith(
            "getListIndcMnrk" if page_id == "indicator_market" else "getListIndxSplyBalncMnrk"
        ):
            continue
        params = r["params"]
        mineral_code = params.get("srchMnrkndUnqCd")
        rows = r["response"].get("data") or []
        parsed = []
        for row in rows:
            score = _num(row.get(score_field))
            if score is None:
                continue
            date_raw = str(row["crtrYmd"])
            month = _ymd8(date_raw)[:7] if len(date_raw) == 8 else _year6(date_raw)
            parsed.append(
                {
                    "month": month,
                    "score": max(0.0, min(100.0, score)),
                    "price": _nonzero(_num(row.get("realPrc"))),
                }
            )
        parsed = sorted(parsed, key=lambda item: item["month"])
        # 같은 달이 중복되면 마지막 값으로 덮어써 IndicatorSeries의 월 유일성 가정에 맞춘다.
        deduped: dict[str, dict] = {item["month"]: item for item in parsed}
        observations = [deduped[month] for month in sorted(deduped)]
        if len(observations) < 2:
            continue
        # 덤프의 key는 "<한글광종명>"(market) 또는 "<한글광종명>|월별지표"(supply)
        # 형태다 — mineral_name은 코드가 아니라 이 한글명을 써야 실제 캐치올
        # 호출자가 보낼 값과 비슷하다(2026-08-26 회귀 테스트에서 "MNRL1054
        # 분석 요약"처럼 코드가 그대로 제목에 나온 걸 보고 발견·수정 — report_gen
        # 자체 버그는 아니고 이 하네스 어댑터가 이름 대신 코드를 채웠던 것).
        mineral_name = r["key"].split("|")[0]
        request = {
            "page_id": page_id,
            "mineral": mineral_code,
            "mineral_name": mineral_name,
            "observations": observations,
        }
        out.append((f"{source_label}:{r['key']}", request))
    return out


def _trade_country_rows_korea(rows: list[dict], as_of_date: str) -> list[dict]:
    observations = []
    for row in rows:
        code = row.get("ntnCd")
        if not code:
            continue
        observations.append(
            {
                "date": as_of_date,
                "country_code": code,
                "country_name": row.get("ntnKornNm") or code,
                "import_weight": _num(row.get("incmWeig")),
                "import_amount": _num(row.get("incmAmt")),
                "export_weight": _num(row.get("expWeig")),
                "export_amount": _num(row.get("expAmt")),
            }
        )
    return observations


def adapt_map_korea(dump: dict) -> list[tuple[str, dict]]:
    out = []
    for r in dump["results"]:
        if not r["key"].endswith("|수입|전체기간|list"):
            continue
        params = r["params"]
        rows = r["response"].get("list") or []
        as_of = params.get("srchDateE")
        as_of_date = f"{as_of[0:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of else "2026-12-31"
        observations = _trade_country_rows_korea(rows, as_of_date)
        total_amount = sum(o["import_amount"] or 0.0 for o in observations)
        if not observations or total_amount <= 0:
            continue
        mineral_code = params["srchMnrkndUnqCd"]
        request = {
            "page_id": "map_korea",
            "mineral": mineral_code,
            "mineral_name": r["key"].split("|")[0],
            "observations": observations,
        }
        out.append((f"supply_map_korea:{r['key']}", request))
    return out


def adapt_map_global(dump: dict) -> list[tuple[str, dict]]:
    out = []
    for r in dump["results"]:
        if not r["key"].endswith("|수입|전체기간|list"):
            continue
        params = r["params"]
        rows = r["response"].get("list") or []
        as_of = params.get("srchDateE")
        as_of_date = f"{as_of[0:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of else "2026-12-31"
        # 2026-08-27 반복 루프 1회차: 08-27 루트 재설계(원산국→도착국) 이후 계산기는
        # `origin_country_*`를 요구하는데 이 어댑터는 원산국별 합산(도착국 버림) 그대로라
        # 보고서에 "출처미상→미국"이 찍혔다. KOMIS list 행이 도착국(incmNtn*)·원산국
        # (expNtn*) 쌍을 이미 주므로 행 1개 = 루트 관측 1건으로 넘긴다.
        observations = []
        for row in rows:
            dest_code, origin_code = row.get("incmNtnCd"), row.get("expNtnCd")
            if not dest_code or not origin_code:
                continue
            observations.append(
                {
                    "date": as_of_date,
                    "country_code": dest_code,
                    "country_name": row.get("incmNtnNm") or dest_code,
                    "origin_country_code": origin_code,
                    "origin_country_name": row.get("expNtnNm") or origin_code,
                    "import_weight": _num(row.get("weig")) or 0.0,
                    "import_amount": _num(row.get("amt")) or 0.0,
                }
            )
        if not observations or sum(o["import_amount"] for o in observations) <= 0:
            continue
        mineral_code = params["srchMnrkndUnqCd"]
        request = {
            "page_id": "map_global",
            "mineral": mineral_code,
            "mineral_name": r["key"].split("|")[0],
            "observations": observations,
        }
        out.append((f"supply_map_global:{r['key']}", request))
    return out


def adapt_mineral_map(dump: dict) -> list[tuple[str, dict]]:
    out = []
    for r in dump["results"]:
        if not r["key"].endswith("|chart"):
            continue
        mineral_label, measure_label, _ = r["key"].split("|")
        measure = "reserves" if measure_label == "매장량" else "production"
        rows = r["response"].get("data") or []
        if not rows:
            continue
        value_key = "burudgQuty" if measure == "reserves" else "prdctnQuty"
        total_key_candidates = (
            ("totalBurudgQuty",) if measure == "reserves" else ("TOTALPRDCTNQUTY", "totalPrdctnQuty")
        )
        unit = str(rows[0].get("cdVal") or "").strip() or "단위미상"
        mineral_code = str(rows[0].get("ntnEngCd") or mineral_label)
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
            total_val = _num(_ci_get(row, *total_key_candidates))
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
        years_present = sorted({o["year"] for o in observations})
        if len(years_present) < 2:
            continue
        current_year_rows = [o for o in observations if o["year"] == years_present[-1] and not o["is_total"]]
        if len(current_year_rows) < 3:
            continue
        request = {
            "page_id": "map_mineral",
            "mineral": mineral_label,
            "mineral_name": mineral_label,
            "measure": measure,
            "unit": unit,
            "observations": observations,
        }
        out.append((f"mineral_map:{r['key']}", request))
    return out


# ─────────────────────────────────────────────────────────────────
# 실행 + 독립 재계산(정답값) + 결과 조립
# ─────────────────────────────────────────────────────────────────


def _pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def _expected_facts(page_id: str, request: dict) -> dict:
    """어댑터 입력에서 하네스가 독립적으로 재계산한 정답값 — G4(불일치 검사)용.

    2026-08-26: 비교광종(compare_observations)이 있으면 `compare_overall_
    change_pct`도 독립 재계산한다 — 이전엔 latest_price/mineral_name만
    검증해서 "같은 조회기간 동안 OO은 X% 변동한 반면..." 문장의 숫자는 실제로
    한 번도 자동 대조되지 않았다(사용자의 "하나하나 체크" 요청으로 발견·보강)."""

    if page_id == "price":
        obs = sorted(request["observations"], key=lambda o: o["date"])
        facts = {"latest_price": obs[-1]["commerce_price"], "mineral_name": request["mineral_name"]}
        compare_obs = request.get("compare_observations")
        if compare_obs:
            c_obs = sorted(compare_obs, key=lambda o: o["date"])
            primary_overall = _pct(obs[-1]["commerce_price"], obs[0]["commerce_price"])
            compare_overall = _pct(c_obs[-1]["commerce_price"], c_obs[0]["commerce_price"])
            if primary_overall is not None and compare_overall is not None:
                facts["compare_overall_change_pct"] = (primary_overall - compare_overall) * 100
        return facts
    if page_id in ("indicator_market", "indicator_supply"):
        obs = sorted(request["observations"], key=lambda o: o["month"])
        return {"latest_score": obs[-1]["score"], "mineral_name": request["mineral_name"]}
    if page_id == "indicator_composite":
        obs = sorted(request["observations"], key=lambda o: o["date"])
        return {"latest_composite_index": obs[-1]["composite_index"]}
    if page_id == "map_mineral":
        year = max(o["year"] for o in request["observations"])
        rows = [o for o in request["observations"] if o["year"] == year]
        total_row = next((o for o in rows if o["is_total"]), None)
        country_rows = [o for o in rows if not o["is_total"] and not o["is_other"]]
        world_total = total_row["value"] if total_row else sum(o["value"] for o in country_rows)
        top1 = max(country_rows, key=lambda o: o["value"]) if country_rows else None
        return {
            "world_total": world_total,
            "top1_country": top1["country_name"] if top1 else None,
            "top1_value": top1["value"] if top1 else None,
        }
    if page_id in ("map_korea", "map_global"):
        obs = request["observations"]
        total = sum(o["import_amount"] or 0.0 for o in obs)
        top1 = max(obs, key=lambda o: o["import_amount"] or 0.0)
        return {
            "total_amount": total,
            "top1_country": top1["country_name"],
            "top1_share_pct": (top1["import_amount"] or 0.0) / total * 100 if total else None,
        }
    return {}


def _check_mismatch(page_id: str, expected: dict, response: dict) -> list[str]:
    """expected(정답값)와 실제 AnalysisSummaryResponse.key_metrics/applied_filters를 대조한다."""

    problems: list[str] = []
    metrics = {m["id"]: m["value"] for m in response["key_metrics"]}

    def _close(a: float | None, b: float | None, tol: float = 0.5) -> bool:
        if a is None or b is None:
            return a == b
        return abs(a - b) <= tol

    if page_id == "price":
        if not _close(expected["latest_price"], metrics.get("latest_price")):
            problems.append(f"latest_price 불일치: expected={expected['latest_price']} actual={metrics.get('latest_price')}")
        if response["mineral"]["name"] != expected["mineral_name"]:
            problems.append(f"mineral name 불일치: expected={expected['mineral_name']} actual={response['mineral']['name']}")
        if "compare_overall_change_pct" in expected:
            actual_cmp = metrics.get("compare_overall_change_pct")
            if not _close(expected["compare_overall_change_pct"], actual_cmp, tol=0.5):
                problems.append(
                    "compare_overall_change_pct 불일치: "
                    f"expected={expected['compare_overall_change_pct']:.4f} actual={actual_cmp}"
                )
    elif page_id in ("indicator_market", "indicator_supply"):
        if not _close(expected["latest_score"], metrics.get("current_score")):
            problems.append(f"current_score 불일치: expected={expected['latest_score']} actual={metrics.get('current_score')}")
    elif page_id == "indicator_composite":
        if not _close(expected["latest_composite_index"], metrics.get("current_composite_index")):
            problems.append(
                f"current_composite_index 불일치: expected={expected['latest_composite_index']} "
                f"actual={metrics.get('current_composite_index')}"
            )
    elif page_id == "map_mineral":
        if not _close(expected["world_total"], metrics.get("current_world_total"), tol=max(1.0, expected["world_total"] * 0.01)):
            problems.append(
                f"current_world_total 불일치: expected={expected['world_total']} actual={metrics.get('current_world_total')}"
            )
        if metrics.get("top_country") != expected["top1_country"]:
            problems.append(f"top_country 불일치: expected={expected['top1_country']} actual={metrics.get('top_country')}")
    elif page_id in ("map_korea", "map_global"):
        if not _close(expected["total_amount"], metrics.get("total_amount"), tol=max(1.0, expected["total_amount"] * 0.01)):
            problems.append(f"total_amount 불일치: expected={expected['total_amount']} actual={metrics.get('total_amount')}")
        if expected["top1_share_pct"] is not None and not _close(expected["top1_share_pct"], metrics.get("top1_share_pct"), tol=0.5):
            problems.append(
                f"top1_share_pct 불일치: expected={expected['top1_share_pct']:.2f} actual={metrics.get('top1_share_pct')}"
            )
    return problems


def run_all(out_path: Path, summary_only: bool) -> dict:
    service = AnalysisSummaryService(None, llm=None)

    combos: list[tuple[str, str, dict]] = []  # (page_id, combo_key, request)
    combos += [("price", key, req) for key, req in adapt_price_pages(_load("komis_01_base_metals.json"), "base_metals")]
    combos += [("price", key, req) for key, req in adapt_price_pages(_load("komis_02_minor_metals.json"), "minor_metals")]
    combos += [("indicator_composite", key, req) for key, req in adapt_mineral_index(_load("komis_03_mineral_index.json"))]
    combos += [
        ("indicator_market", key, req)
        for key, req in adapt_indicator_pages(_load("komis_04_market_trend.json"), "indicator_market", "market_trend")
    ]
    combos += [
        ("indicator_supply", key, req)
        for key, req in adapt_indicator_pages(_load("komis_05_supply_trend.json"), "indicator_supply", "supply_trend")
    ]
    combos += [("map_korea", key, req) for key, req in adapt_map_korea(_load("komis_06_supply_map_korea.json"))]
    combos += [("map_global", key, req) for key, req in adapt_map_global(_load("komis_07_supply_map_global.json"))]
    combos += [("map_mineral", key, req) for key, req in adapt_mineral_map(_load("komis_08_mineral_map.json"))]

    per_page: dict[str, list[dict]] = {}
    for page_id, combo_key, request in combos:
        expected = _expected_facts(page_id, request)
        entry = {"combo_key": combo_key, "page_id": page_id, "request": request, "expected": expected}
        try:
            summary_request = AnalysisSummaryRequest(**request)
            response = service.analyze(summary_request)
            response_dict = json.loads(response.model_dump_json())
            entry["status"] = "ok"
            entry["response"] = None if summary_only else response_dict
            entry["report_markdown"] = render_markdown_report(response)
            entry["mismatches"] = _check_mismatch(page_id, expected, response_dict)
            entry["key_metrics"] = {m["id"]: m["value"] for m in response_dict["key_metrics"]}
        except DataSourceError as exc:
            entry["status"] = "NO_DATA"
            entry["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 — 하네스는 실패도 기록해야 한다
            entry["status"] = "INTERNAL_ERROR"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc()
        per_page.setdefault(page_id, []).append(entry)

    summary = {
        page_id: {
            "count": len(entries),
            "ok": sum(1 for e in entries if e["status"] == "ok"),
            "no_data": sum(1 for e in entries if e["status"] == "NO_DATA"),
            "internal_error": sum(1 for e in entries if e["status"] == "INTERNAL_ERROR"),
            "mismatches": sum(len(e.get("mismatches", [])) for e in entries),
        }
        for page_id, entries in per_page.items()
    }

    result = {"summary": summary, "per_page": per_page}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--summary-only", action="store_true", help="결과 JSON에 전체 AnalysisSummaryResponse는 생략(용량 절약)")
    args = parser.parse_args()

    result = run_all(args.out, args.summary_only)
    total_combos = sum(page["count"] for page in result["summary"].values())
    total_internal_errors = sum(page["internal_error"] for page in result["summary"].values())
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"total_combos={total_combos} pages={len(result['summary'])} internal_errors={total_internal_errors}")
    print(f"saved: {args.out}")
    if total_combos >= 300 and len(result["summary"]) >= 7:
        print("HARNESS_OK")
    else:
        print("HARNESS_INSUFFICIENT_COVERAGE", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
