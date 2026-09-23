#!/usr/bin/env python3
"""YAML로 정의한 챗봇 수락 검사를 케이스 단위로 실행한다.

기본 실행은 외부 LLM 응답을 요구하지 않는 module/integration 계층이다. 라이브
질의는 비용·시간을 통제하기 위해 ``--layer live`` 또는 ``--case AC01``로 명시한다.
결과는 JSON과 사람이 읽을 수 있는 Markdown으로 남겨 재실행·추적할 수 있다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import re
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
INHOUSE = ROOT / "inhouse"
DEFAULT_CASES = Path(__file__).with_name("chatbot_acceptance_cases.yml")

# YAML의 additional_checks_required 문구와 실행 가능한 고정 입력 검사를 1:1로
# 연결한다. 이 매핑이 없으면 해당 케이스는 PASS할 수 없다.
REQUIRED_CHECKS_BY_CASE = {
    "AC42": [("parallel_source_isolation", "rag_chat.tests.test_acceptance_module_boundaries.AC42ParallelIsolationTest")],
    "AC44": [("time_aggregation_boundaries", "rag_chat.tests.test_acceptance_module_boundaries.AC44AggregationBoundaryTest")],
    "AC47": [
        ("trade_indicator_formula_zero_denominator", "rag_chat.tests.test_acceptance_module_boundaries.AC47TradeIndicatorFormulaTest"),
        ("trade_hitl_session_state", "rag_chat.tests.test_acceptance_module_boundaries.AC47TradeHitlSessionTest"),
        ("mine_clarification_regression", "rag_chat.tests.test_acceptance_module_boundaries.AC47MineClarificationTest"),
    ],
}
EXPECTED_REQUIRED_CHECK_IDS = {
    "AC42": {"parallel_source_isolation"},
    "AC44": {"time_aggregation_boundaries"},
    "AC47": {"trade_indicator_formula_zero_denominator", "trade_hitl_session_state", "mine_clarification_regression"},
}


def load_cases(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    # 현재 정본은 JSON 호환 YAML이다. PyYAML을 런타임 의존성으로 강제하지 않는다.
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases", [])
    ids = [case.get("id") for case in cases]
    if len(cases) != 48 or len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("수락 검사 케이스는 고유 ID 48건이어야 합니다")
    return raw, cases


def parse_sse(payload: bytes) -> list[dict[str, Any]]:
    """SSE ``data:`` 레코드를 엄격히 읽는다.

    수락 검사는 깨진 JSON·객체가 아닌 payload를 빈 정상 응답으로 취급하지 않는다.
    """
    events = []
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"SSE UTF-8 디코딩 실패: {exc}") from exc
    for line_no, line in enumerate(lines, start=1):
        if line.startswith("data: "):
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError as exc:
                raise ValueError(f"SSE JSON 파싱 실패({line_no}행): {exc.msg}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"SSE data payload가 객체가 아님({line_no}행)")
            events.append(event)
    return events


def ask_live(base_url: str, question: str, session_id: str, timeout: int) -> list[dict[str, Any]]:
    body = json.dumps({"user_id": "acceptance-suite", "session_id": session_id,
                       "message": question}).encode("utf-8")
    req = urllib.request.Request(base_url + "/pubchat", body,
                                 {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return parse_sse(response.read())


def has_structured(events: list[dict[str, Any]]) -> bool:
    return any(event.get("rows") or event.get("spec") for event in events)


def terminal_errors(events: list[dict[str, Any]], session_id: str) -> list[str]:
    """요청 하나의 SSE terminal 계약을 검증한다."""

    errors: list[str] = []
    done_indexes = [index for index, event in enumerate(events) if event.get("done")]
    if len(done_indexes) != 1:
        errors.append(f"done 이벤트 개수={len(done_indexes)}")
    elif done_indexes[0] != len(events) - 1:
        errors.append("done 뒤에 추가 SSE 결과가 있음")
    session_events = [event for event in events if "session_id" in event]
    if len(session_events) != 1:
        errors.append(f"session 이벤트 개수={len(session_events)}")
    elif session_events[0].get("session_id") != session_id:
        errors.append("session_id가 요청 세션과 다름")
    return errors


def _answer_errors(case: dict[str, Any], events: list[dict[str, Any]], done: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    answer = "".join(str(event.get("delta", "")) for event in events).strip()
    citations = done.get("citations") or []
    if done.get("abstained") or done.get("needs_clarification"):
        errors.append("정상 답변 대신 기권 또는 HITL")
    if not answer:
        errors.append("delta 본문이 비어 있음")
    for source in case.get("expected_sources", []):
        if source != "menu_data_catelog.yml" and not any(item.get("source") == source for item in citations):
            errors.append(f"기대 출처 인용 없음: {source}")
    page_id = case.get("expected_page_id")
    expects_page = "page" in set(case.get("sse_contracts", [])) and bool(page_id)
    if expects_page and done.get("mode") != "page":
        errors.append("page 케이스가 page mode가 아님")
    if not expects_page and done.get("mode") == "page":
        errors.append("일반 답변이 page mode로 반환됨")
    if expects_page and page_id not in {item.get("page_id") for item in done.get("recommendations", [])}:
        errors.append(f"메뉴 추천 누락: {page_id}")
    if expects_page:
        if any(item.get("login_required") for item in done.get("recommendations", [])):
            errors.append("public 메뉴 응답에 login_required 페이지가 포함됨")
    return errors


def _clarification_errors(case: dict[str, Any], events: list[dict[str, Any]], done: dict[str, Any],
                          required_slots: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    clarification = done.get("clarification") or {}
    expected_actions = set(case.get("expected_actions", []))
    if not done.get("needs_clarification"):
        errors.append("HITL 요청이 아님")
    if not "".join(str(event.get("delta", "")) for event in events).strip():
        errors.append("HITL 설명 본문이 비어 있음")
    if clarification.get("action_id") not in expected_actions:
        errors.append(f"HITL action 불일치: {clarification.get('action_id')}")
    required = required_slots if required_slots is not None else set(case.get("required_clarification_slots", []))
    missing = required - set(clarification.get("slots", []))
    if missing:
        errors.append(f"HITL 누락 슬롯: {sorted(missing)}")
    if done.get("citations") or has_structured(events):
        errors.append("HITL 응답에 인용·표·차트가 포함됨")
    return errors


def verify_live(case: dict[str, Any], base_url: str, timeout: int) -> tuple[str, list[str], dict[str, Any]]:
    session_id = str(uuid.uuid4())
    try:
        events = ask_live(base_url, case["question"], session_id, timeout)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return "BLOCKED_ENV", [f"라이브 요청 실패: {exc}"], {}
    except ValueError as exc:
        return "FAIL", [str(exc)], {}
    done_events = [event for event in events if event.get("done")]
    errors = terminal_errors(events, session_id)
    if not done_events:
        return "FAIL", errors, {"event_count": len(events)}
    # terminal 계약 위반은 어떤 데이터 사전조건보다 먼저 FAIL이다.
    if errors:
        return "FAIL", errors, {"events": events, "event_count": len(events)}
    done = done_events[0]
    outcome = case["expected_outcome"]
    expected_actions = set(case.get("expected_actions", []))
    citations = done.get("citations") or []
    cited_actions = {item.get("action_id") for item in citations}
    action_ids = set(done.get("action_ids") or []) | cited_actions
    if done.get("mode") == "page":
        action_ids.add("menu.navigate")
    # 사전 차단 기권은 의도 분석 action을 terminal payload에 노출하지 않는 현재
    # SSE 계약이다. 그런 경우에는 사전 지정된 기권 사유만 검증한다.
    if outcome != "abstain" and expected_actions and not (expected_actions & action_ids):
        # 페이지와 HITL의 action은 citations 대신 각각의 전용 payload에 있다.
        clarification = done.get("clarification") or {}
        action_ids.add(clarification.get("action_id"))
        if not (expected_actions & action_ids):
            errors.append(f"기대 action 미확인: {sorted(expected_actions)} / 실제={sorted(x for x in action_ids if x)}")
    # AC22: 첫 턴은 clarification, 같은 session_id의 보충 턴만 grounded answer다.
    if case.get("first_turn_outcome") == "clarification":
        errors.extend(_clarification_errors(case, events, done, {"reporter_country", "period"}))
        if errors:
            return "FAIL", errors, {"first_turn_events": events, "first_done": done}
        try:
            followup_events = ask_live(base_url, case["followup"], session_id, timeout)
        except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            return "BLOCKED_ENV", [f"후속 라이브 요청 실패: {exc}"], {"first_done": done}
        except ValueError as exc:
            return "FAIL", [str(exc)], {"first_done": done}
        errors = terminal_errors(followup_events, session_id)
        followup_done_events = [event for event in followup_events if event.get("done")]
        if not followup_done_events:
            return "FAIL", errors or ["후속 done 이벤트 없음"], {"first_done": done, "followup_events": followup_events}
        if errors:
            return "FAIL", errors, {"first_done": done, "followup_events": followup_events}
        followup_done = followup_done_events[0]
        errors.extend(_answer_errors(case, followup_events, followup_done))
        followup_actions = set(followup_done.get("action_ids") or []) | {
            item.get("action_id") for item in followup_done.get("citations") or []
        }
        if not (expected_actions & followup_actions):
            errors.append("후속 턴 기대 action 미확인")
        # 현재 terminal payload에는 보존된 첫 턴 슬롯과 독립 계산 입력/정답이 없다.
        # 이 상태에서 광종·기간·지표 불변성과 TSI 재계산을 PASS로 선언할 수 없다.
        errors.append("AC22 슬롯 보존·변경 거절 및 독립 계산 정답 대조 미구현")
        return ("PASS" if not errors else "FAIL"), errors, {
            "first_turn_events": events, "first_done": done,
            "followup_events": followup_events, "followup_done": followup_done,
        }
    if outcome == "answer":
        if done.get("abstained") and done.get("abstain_reason") in {"source_unavailable", "no_data_for_period"}:
            evidence = case.get("independent_precondition_evidence")
            if evidence:
                return "BLOCKED_DATA", [f"사전 데이터 조건 미충족: {done.get('abstain_reason')}"], {"done": done, "precondition_evidence": evidence}
            return "FAIL", ["source_unavailable에 대한 독립 사전조건 증거가 없음"], {"done": done}
        errors.extend(_answer_errors(case, events, done))
        if done.get("mode") != "page":
            errors.append("필수 수치·표·단위·관측기간의 독립 검증이 아직 구현되지 않음")
    elif outcome == "abstain":
        if not done.get("abstained"):
            errors.append("기권 응답이 아님")
        if done.get("abstain_reason") not in set(case.get("expected_abstain_reasons", [])):
            errors.append(f"기권 사유 불일치: {done.get('abstain_reason')}")
        if citations or has_structured(events):
            errors.append("기권 응답에 인용·표·차트가 포함됨")
        if not "".join(str(event.get("delta", "")) for event in events).strip():
            errors.append("기권 설명 본문이 비어 있음")
        message_key = case.get("expected_message_key")
        if message_key and done.get("message_key") != message_key:
            errors.append(f"메시지 키 불일치: {done.get('message_key')}")
    elif outcome == "clarification":
        errors.extend(_clarification_errors(case, events, done))
    return ("PASS" if not errors else "FAIL"), errors, {"events": events, "done": done, "event_count": len(events)}


def verify_module(case: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    additional = case.get("additional_checks_required", [])
    tests = case.get("unit_tests", [])
    required = REQUIRED_CHECKS_BY_CASE.get(case["id"], [])
    required_ids = [check_id for check_id, _ in required]
    if additional and (not required or len(required) != len(additional) or len(required_ids) != len(set(required_ids))
                       or set(required_ids) != EXPECTED_REQUIRED_CHECK_IDS.get(case["id"], set())):
        return "FAIL", [f"필수 추가 검사 미구현: {item}" for item in additional], {
            "unit_tests": tests, "additional_checks_required": additional, "required_checks": [],
        }
    base_tests = tests
    tests = [*base_tests, *(target for _, target in required)]
    if not tests:
        return "NOT_RUN", ["연결된 단위 테스트가 정의되지 않음"], {}
    env = dict(os.environ, PYTHONPATH=str(INHOUSE) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    command = [sys.executable, "-m", "unittest", *tests]
    completed = subprocess.run(command, cwd=INHOUSE, env=env, text=True, capture_output=True, timeout=180)
    ran = re.search(r"Ran\s+(\d+)\s+tests?", completed.stdout + completed.stderr)
    test_count = int(ran.group(1)) if ran else 0
    per_required = []
    for check_id, target in required:
        target_run = subprocess.run([sys.executable, "-m", "unittest", target], cwd=INHOUSE, env=env,
                                    text=True, capture_output=True, timeout=180)
        target_match = re.search(r"Ran\s+(\d+)\s+tests?", target_run.stdout + target_run.stderr)
        target_count = int(target_match.group(1)) if target_match else 0
        per_required.append({"id": check_id, "target": target,
                             "status": "PASS" if target_run.returncode == 0 and target_count > 0 else "FAIL",
                             "executed_test_count": target_count,
                             "stdout": target_run.stdout[-1000:], "stderr": target_run.stderr[-1000:]})
    detail = {
        "command": command, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:],
        "required_checks": per_required,
        "executed_test_count": test_count,
    }
    if completed.returncode != 0 or test_count <= 0 or any(item["status"] != "PASS" for item in per_required):
        return "FAIL", ["단위 테스트 실패 또는 실행 건수 0"], detail
    return "PASS", [], detail


def verify_integration(case: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    # 파일 원문(OKF)과 PageIndex를 먼저 같은 문서 키로 비교한다. DB는 read-only count로
    # 벡터 청크 존재만 확인해 인덱스를 바꾸지 않는다.
    sys.path.insert(0, str(INHOUSE))
    from common.db import pg_connect
    from common.config import get_settings
    from rag_core.retrieval import pageindex
    handler = case.get("integration_handler")
    try:
        trees = pageindex.load_trees()
    except Exception as exc:  # noqa: BLE001
        return "BLOCKED_ENV", [f"PageIndex 로드 실패: {exc}"], {}
    if case.get("id") in {"AC28", "AC29", "AC30", "AC39", "AC40", "AC41"}:
        from rag_chat.tests.acceptance_integrations import verify_case
        return verify_case(case, trees=trees, pageindex=pageindex, connect=pg_connect, settings=get_settings)
    if handler == "pageindex_lookup":
        docs = pageindex.find_documents("USGS 리튬", limit=5)
        if not docs:
            return "BLOCKED_DATA", ["USGS 리튬 PageIndex 문서 없음"], {}
        tree = pageindex.get_tree(docs[0]["doc_id"])
        if not tree or not tree.get("structure"):
            return "FAIL", ["USGS 트리 또는 구조 노드 없음"], {"document": docs[0]}
        return "FAIL", ["PageIndex 노드 범위와 OKF 본문 줄 대조가 아직 구현되지 않음"], {
            "document": docs[0], "node_count": pageindex.count_nodes(tree["structure"]),
        }
    if handler == "ocr_three_documents":
        from ingest.pageindex.build_pageindex_trees import okf_body_sha256
        failures, checked = [], []
        for relative in case["document_paths"]:
            path = Path(pageindex.OKF_DOCUMENTS_ROOT) / relative
            tree = next((t for t in trees if t.get("okf_path") == relative), None)
            if not path.is_file() or not tree or not tree.get("structure"):
                failures.append(relative + " OKF 또는 트리 없음")
                continue
            digest = okf_body_sha256(path)
            if tree.get("okf_body_sha256") != digest:
                failures.append(relative + " OKF 해시 불일치")
            vector_status, vector_errors, _ = _verify_vector_row(tree, pg_connect, get_settings)
            if vector_status != "PASS":
                failures.extend(relative + " " + error for error in vector_errors or ["벡터 청크 검증 실패"])
            checked.append(relative)
        if failures:
            return "FAIL", failures, {"checked": checked}
        return "FAIL", ["OCR 3건의 실제 원문 구간·추출 본문 대조가 아직 구현되지 않음"], {"checked": checked}
    if handler in {"document_pdf", "document_hwp", "document_excel"}:
        expected_formats = {
            "document_pdf": {"pdf"}, "document_hwp": {"hwp", "hwpx"}, "document_excel": {"xls", "xlsx"},
        }[handler]
        matches = [tree for tree in trees if str(tree.get("fmt", "")).lower() in expected_formats]
        if not matches:
            return "BLOCKED_DATA", [f"{sorted(expected_formats)} PageIndex 표본 없음"], {}
        tree = matches[0]
        original = ROOT / str(tree.get("resource", ""))
        okf = Path(pageindex.OKF_DOCUMENTS_ROOT) / tree.get("okf_path", "")
        if not original.is_file():
            return "BLOCKED_DATA", ["원본 문서가 현재 작업공간에 없음"], {"resource": tree.get("resource")}
        if not tree.get("structure") or not okf.is_file():
            return "FAIL", ["OKF 또는 PageIndex 구조 연결 실패"], {"doc_id": tree.get("doc_id")}
        status, errors, detail = _verify_vector_row(tree, pg_connect, get_settings)
        detail.update({"original_path": str(original), "okf_path": str(okf), "fmt": tree.get("fmt")})
        if status != "PASS":
            return status, errors, detail
        return "FAIL", ["원본 포맷별 실제 검색 결과와 OKF 본문 대조가 아직 구현되지 않음"], detail
    if handler == "vector_retrieval":
        # 청크 수만 확인하는 것은 YAML 계약의 "실제 dense 검색·기대 doc_id" 검증이 아니다.
        return "FAIL", ["실제 dense 검색과 기대 doc_id 검증이 아직 구현되지 않음"], {}
    return "NOT_RUN", [f"알 수 없는 integration_handler: {handler}"], {}


def _verify_vector_row(tree: dict[str, Any], connect, settings) -> tuple[str, list[str], dict[str, Any]]:
    resource = tree.get("resource", "")
    return _verify_vector_count(connect, settings, resource, {"doc_id": tree.get("doc_id"), "resource": resource})


def _verify_vector_count(connect, settings, source_path: str, detail: dict[str, Any] | None = None) -> tuple[str, list[str], dict[str, Any]]:
    detail = detail or {}
    try:
        conn = connect()
        try:
            cur = conn.cursor()
            sql = f"SELECT count(*) FROM {settings().PG_SCHEMA}.doc_chunk WHERE embedding IS NOT NULL"
            args: tuple[Any, ...] = ()
            if source_path:
                sql += " AND source_path = %s"
                args = (source_path,)
            cur.execute(sql, args)
            count = cur.fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return "BLOCKED_ENV", [f"pgvector 읽기 실패: {exc}"], detail
    detail["vector_chunk_count"] = count
    return ("PASS", [], detail) if count else ("BLOCKED_DATA", ["벡터 청크 없음"], detail)


def run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    if args.dry_run:
        status, errors, detail = "NOT_RUN", ["dry-run"], {}
    elif case["layer"] == "live":
        status, errors, detail = verify_live(case, args.base_url, args.timeout)
    elif case["layer"] == "module":
        status, errors, detail = verify_module(case)
    else:
        status, errors, detail = verify_integration(case)
    return {"id": case["id"], "title": case["title"], "layer": case["layer"], "status": status,
            "errors": errors, "detail": detail, "elapsed_seconds": round(time.monotonic() - started, 2)}


def select_cases(cases: list[dict[str, Any]], wanted: set[str], layers: set[str]) -> list[dict[str, Any]]:
    """명시 ``--case``는 기본 layer 필터를 재정의한다."""

    return [case for case in cases if case["id"] in wanted] if wanted else [
        case for case in cases if case["layer"] in layers
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", help="쉼표로 구분한 케이스 ID")
    parser.add_argument("--layer", default="module,integration", help="live,module,integration")
    parser.add_argument("--base-url", default=os.environ.get("CHAT_BASE_URL", "http://127.0.0.1:18002").rstrip("/"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "documents/산출물/acceptance_results")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    _, cases = load_cases(args.cases_file)
    wanted = {value.strip() for value in (args.case or "").split(",") if value.strip()}
    layers = {value.strip() for value in args.layer.split(",") if value.strip()}
    selected = select_cases(cases, wanted, layers)
    if args.list:
        for case in selected:
            print(f"{case['id']} [{case['layer']}] {case['title']}")
        return 0
    if not selected:
        parser.error("실행할 케이스가 없습니다")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence = args.report_dir / f"chatbot_acceptance_{stamp}.jsonl"
    results = []
    with evidence.open("w", encoding="utf-8") as evidence_file:
        for case in selected:
            result = run_case(case, args)
            result["evidence_path"] = str(evidence)
            evidence_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            evidence_file.flush()
            results.append(result)
    payload = {"suite": "komir-chatbot-acceptance-260923", "generated_at": datetime.now().isoformat(),
               "base_url": args.base_url, "evidence_jsonl": str(evidence),
               "results": results, "summary": dict(Counter(r["status"] for r in results))}
    report = args.report_dir / f"chatbot_acceptance_{stamp}.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False), f"\n결과: {report}")
    return 1 if any(result["status"] == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
