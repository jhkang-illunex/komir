"""Offline latest-record QA500 audit using today's schema/planner, never Gemma.

python3 inhouse/rag_core/tests/qa500_final_audit.py
python3 inhouse/rag_core/tests/qa500_final_audit.py --self-test

Precedence is command-line input order, then line order within each file. The
entire latest case wins, including failures and incomplete turns. Within that
record qa500_actual_execution.current_plan selects the last attempt if a plan
was saved, otherwise the first current-schema-valid raw in original order.
No saved plan contents, Gold, or another run repairs the selected raw.

Three artifacts: unchanged selected raw records, explicitly marked current-code
replay input, and the semantic audit. Gold enters only the last audit stage.
Backend review uses only synthetic SQLite fixtures and the current runtime;
no model, external service, production I/O or SSE execution occurs.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
import gzip
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from inhouse.common.llm_client import parse_json_object
from inhouse.rag_core.ragkit.semantic_v2 import (
    LegacyActionLowerer, SemanticRequirementPlanV2, logical_program_from_requirements,
)
from inhouse.rag_core.tests import qa500_semantic_audit as audit
from inhouse.rag_core.tests.qa500_actual_execution import current_plan
from inhouse.rag_core.tests import qa500_actual_execution as actual


DEFAULT_INPUTS = [Path(f"/tmp/qa500-gemma-{s}.jsonl")
                  for s in ("before", "after", "after2", "recovered")]
SOURCE_FILES = [Path(__file__).resolve(), Path(audit.__file__).resolve(),
                ROOT / "inhouse/common/llm_client.py",
                ROOT / "inhouse/rag_core/ragkit/semantic_v2.py",
                ROOT / "inhouse/rag_core/tests/qa500_actual_execution.py",
                ROOT / "inhouse/rag_core/tests/qa500_backend.py",
                ROOT / "inhouse/rag_core/ragkit/live_multihop.py",
                ROOT / "inhouse/rag_core/ragkit/semantic_ir.py",
                ROOT / "inhouse/rag_core/ragkit/pipe_runtime.py",
                ROOT / "inhouse/rag_core/ragkit/action_contract.py"]


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def source_hashes():
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}


def overlay(paths):
    selected, histories, snapshots = {}, {}, []
    for source in paths:
        source = Path(source)
        rows, info = audit.read_snapshot(source)
        if info.get("missing_input") or info.get("errors") or info.get("pending_tail_bytes"):
            raise ValueError(f"Input snapshot is incomplete/invalid: {source}: {info}")
        snapshots.append({"path": str(source), "records": len(rows), **info})
        for ident, (line, record) in rows.items():
            provenance = {"source": str(source), "line": line, "record_sha256": digest(record)}
            histories.setdefault(ident, []).append(provenance)
            selected[ident] = record  # no status or score predicate
    return selected, histories, snapshots


def replay_turn(turn):
    """Discard all stored computed artifacts before attempting current replay."""
    result = {"turn": turn.get("turn"), "question": turn.get("question"),
              "backend_executed": False, "status": "PARSER_OR_SCHEMA_FAIL"}
    attempts = (turn.get("record") or {}).get("attempts") or []
    trace = {"policy": "ACTUAL_EXECUTION_CURRENT_PLAN", "stored_status": turn.get("status"),
             "stored_semantic_sha256": digest(turn.get("semantic_plan")),
             "stored_logical_sha256": digest(turn.get("logical_program")),
             "attempt_count": len(attempts), "stage": "schema", "raw_replay": True}
    result["current_replay"] = trace
    raw = None
    try:
        plan, replay = current_plan(turn)
        trace.update(replay)
        raw = attempts[replay["raw_attempt_index"]]["raw_content"]
        result["semantic_plan"] = plan.model_dump(mode="json")
        trace["current_semantic_sha256"] = digest(result["semantic_plan"])
        trace["semantic_changed"] = result["semantic_plan"] != turn.get("semantic_plan")
        # NOT a new LLM call or the old logged schema output. This record's origin
        # is explicit, and the untouched model invocation is in merged raw JSONL.
        result["record"] = {
            "origin": "OFFLINE_CURRENT_SCHEMA_REPLAY_NOT_MODEL_CALL",
            "original_record_sha256": digest(turn.get("record")),
            "attempts": [{"raw_content": raw, "parsed_output": result["semantic_plan"],
                          "original_attempt_index": replay["raw_attempt_index"]}],
        }
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        trace.update(outcome="SCHEMA_REPLAY_FAILURE", error=result["error"])
        return result
    if plan.request_class != "DATA_QUERY":
        result.update(status="UNSUPPORTED", error=plan.unsupported_reason or "normal data requirements rejected")
        trace.update(outcome="UNSUPPORTED_REQUEST", stage="classification", error=result["error"])
        return result
    try:
        trace["stage"] = "planner"
        logical = logical_program_from_requirements(plan)
        result["logical_program"] = logical.to_dict()
        trace["current_logical_sha256"] = digest(result["logical_program"])
        trace["logical_changed"] = result["logical_program"] != turn.get("logical_program")
    except Exception as exc:
        result.update(status="LOWERING_FAILURE", error=f"{type(exc).__name__}: {exc}")
        trace.update(outcome="CURRENT_PLANNER_FAILURE", error=result["error"])
        return result
    try:
        trace["stage"] = "lowering"
        calls = LegacyActionLowerer().lower(logical)
        result["lowered"] = [c.model_dump(mode="json") for c in calls]
        result["status"] = "SCHEMA_VALID_NOT_SEMANTIC_PASS"
        trace.update(outcome="CURRENT_PLAN_AND_LOWERING_AVAILABLE", stage="complete")
    except Exception as exc:
        result.update(status="LOWERING_FAILURE", error=f"{type(exc).__name__}: {exc}")
        trace.update(outcome="CURRENT_LOWERING_FAILURE", error=result["error"])
    return result


def replay_record(record):
    return {"id": record["id"], "pattern_id": record.get("pattern_id"),
            "model": record.get("model"), "multiturn_snapshot_validated": False,
            "origin": "OFFLINE_CURRENT_SCHEMA_PLANNER_REPLAY",
            "original_record_sha256": digest(record),
            "turns": [replay_turn(t) for t in record.get("turns", [])]}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def independent_check(case, turn, db):
    """Direct SQL plus explicit Gold outputs; never uses a structural fingerprint.

    Covers the observed runtime-success families. Numeric equality verifies only
    that output component. No computed oracle is fed back into the actual plan.
    """
    b = case["semantic_requirement"]["parameter_bindings"]
    m, y, month = b["m"], b["y"], b["month"]
    pattern = int(case["pattern_id"][4:])
    roots = turn.get("roots", {})
    rows = [row for root in roots.values() for row in root.get("value", []) if isinstance(row, dict)]
    nodes = (turn.get("logical_program") or {}).get("nodes", [])
    defects, gaps, queries, confirmed = [], [], [], []

    def query(sql, params):
        result = [dict(r) for r in db.execute(sql, params).fetchall()]
        queries.append({"sql": sql, "params": list(params), "expected": result})
        return result

    def equal(a, e, fields, subset=False):
        if not a or (not subset and len(a) != len(e)):
            return False
        def same(left, right):
            return all(k in left and (math.isclose(left[k], right[k], rel_tol=1e-9, abs_tol=1e-8)
                if isinstance(left.get(k), (int, float)) and isinstance(right.get(k), (int, float))
                else left.get(k) == right.get(k)) for k in fields)
        remaining = list(e)
        for row in a:
            found = next((i for i, target in enumerate(remaining) if same(row, target)), None)
            if found is None:
                return False
            remaining.pop(found)
        return subset or not remaining

    if turn.get("status") != "RUNTIME_SUCCESS_NOT_SEMANTIC_PASS":
        gaps.append("Current replay did not produce successful roots; inspect exact failure layers rather than reuse old SUCCESS.")
    elif pattern in {1, 2, 8, 38}:
        domain = "inventory" if pattern == 8 else "price"
        field = "high_price" if pattern == 1 else "low_price" if pattern == 2 else "value"
        function = "MIN" if pattern == 2 else "MAX"
        where, params = "domain=? AND mineral=? AND year=?", [domain, m, y]
        if pattern == 2:
            where += " AND month=?"
            params.append(f"{month:02d}")
        expected = query(f"SELECT date,{field},unit FROM observations WHERE {where} AND {field}="
                         f"(SELECT {function}({field}) FROM observations WHERE {where}) ORDER BY date", params + params)
        # PAT-002/008/038 do not explicitly demand ALL ties. Their older oracle
        # did; one real extremum is not a proven semantic failure on that basis.
        expected_unit = expected[0]["unit"] if expected else None
        units_ok = bool(roots) and all(root.get("unit") == expected_unit for root in roots.values())
        if equal(rows, expected, ["date", field], subset=pattern != 1) and units_ok:
            confirmed.append("numeric_extremum_dates_unit_and_requested_ties")
            if pattern == 1:
                wanted = {"date", "high_price"}
                extras = sorted(set().union(*(set(r) for r in rows)) - wanted)
                if extras:
                    defects.append({"code": "OUTPUT_PROJECTION_CONTRACT_GAP", "expected_fields": sorted(wanted),
                                    "extra_root_fields": extras, "reason": "Gold only-final date/high_price; no Project, actual roots expose unrequested ordinary/low price and other fields"})
            else:
                gaps.append("Final requested field projection/source binding is not executed; successful SQL extremum is not full answer verification.")
                if pattern == 2:
                    gaps.append("Price fixture has no NULL/zero low_price boundary rows; not all missing-observation behavior is covered. All-tie cardinality is not explicitly required by this Gold.")
        else:
            defects.append({"code": "EXTREMUM_NUMERIC_OR_DATE_MISMATCH", "actual": rows[:4], "expected": expected})
    elif pattern == 5:
        cutoff = f"{y}-{month:02d}-{calendar.monthrange(y, month)[1]}"
        expected = query("SELECT date,value FROM observations WHERE domain='price' AND mineral=? AND date<=? AND value IS NOT NULL ORDER BY date DESC LIMIT 1", [m, cutoff])
        if not equal(rows, expected, ["date", "value"]):
            defects.append({"code": "LATEST_AS_OF_NOT_RETURNED", "actual": rows[:3], "expected": expected})
        else:
            confirmed.append("latest_as_of_value_date")
            gaps.append("No-observation-in-requested-month fallback boundary remains untested.")
    elif pattern == 19:
        expected = query("SELECT month,100.0*SUM(CASE WHEN country=? THEN value ELSE 0 END)/SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY month ORDER BY month", [b["country"], m, y])
        if not equal(rows, expected, ["month", "value"]):
            defects.append({"code": "MONTHLY_PARTNER_SHARE_NOT_COMPUTED", "actual_rows": len(rows), "actual_sample": rows[:2], "expected": expected})
    elif pattern == 20:
        expected = query("SELECT SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? AND hs='RAW'", [m, y])
        if not equal(rows, expected, ["value"]) or any(r.get("hs") not in {None, "RAW"} for r in rows):
            defects.append({"code": "RAW_STAGE_FILTER_AND_TOTAL_MISSING", "actual_rows": len(rows), "actual_hs": sorted({r['hs'] for r in rows if r.get('hs')}), "expected": expected})
    elif pattern == 24:
        expected = query("SELECT SUM(value) value,COUNT(DISTINCT country) country_count FROM observations WHERE domain='production' AND mineral=? AND year=?", [m, y])
        if equal(rows, expected, ["value"]):
            confirmed.append("all_country_production_sum")
        else:
            defects.append({"code": "ALL_COUNTRY_TOTAL_MISSING", "actual": rows, "expected": expected})
        counts = [{"country_count": next((r[k] for k in ("country_count", "count", "observation_count") if k in r), None)} for r in rows]
        if (any(isinstance(r["country_count"], bool) for r in counts)
                or not equal(counts, expected, ["country_count"])):
            defects.append({"code": "REQUESTED_COUNTRY_COUNT_MISMATCH", "expected": expected[0]["country_count"],
                            "actual": counts, "reason": "Key presence, NULL, row count and a wrong number do not establish COUNT(DISTINCT country)."})
        else:
            confirmed.append("independent_distinct_country_count")
        duplicate_flags = [r.get("is_duplicate_excluded") for r in rows]
        if not duplicate_flags or any(type(flag) is not bool for flag in duplicate_flags):
            defects.append({"code": "DUPLICATE_EXCLUSION_DISCLOSURE_MISSING", "expected": "non-null boolean disclosure of total-row exclusion",
                            "actual": duplicate_flags})
        # A declared flag is not evidence that a total row was excluded. The
        # ordinary fixture lacks a total-row contamination trial, so even a
        # numerically correct count plus true flag cannot establish this clause.
        gaps.append("EVALUATION_ORACLE_GAP: total-row duplicate exclusion has not been executed against a fixture containing country rows plus their aggregate total; a boolean declaration alone is insufficient.")
        units = query("SELECT DISTINCT unit FROM observations WHERE domain='production' AND mineral=? AND year=?", [m, y])
        if len(units) != 1 or not roots or any(root.get("unit") != units[0]["unit"] for root in roots.values()):
            defects.append({"code": "PRODUCTION_UNIT_MISMATCH", "expected": units, "actual": [r.get("unit") for r in roots.values()]})
    elif pattern == 26:
        expected = query("SELECT year,value FROM observations WHERE domain='production' AND mineral=? AND country=? AND year BETWEEN ? AND ? AND value>0 ORDER BY year", [m, b["country"], b["start_year"], y])
        if not any(n.get("op") in {"Calculate", "Aggregate"} for n in nodes) or any(r.get("country") != b["country"] for r in rows):
            defects.append({"code": "POSITIVE_YEAR_COUNT_COUNTRY_SCOPE_MISSING", "expected_count": len(expected), "expected_years": [r["year"] for r in expected], "actual_rows": len(rows), "actual_countries": sorted({r['country'] for r in rows if r.get('country')})})
    elif pattern == 39:
        expected = query("WITH sums AS (SELECT country,SUM(value) v FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country), shares AS (SELECT v*1.0/SUM(v) OVER () s FROM sums) SELECT SUM(s*s)*10000 hhi FROM shares", [m, y])
        if not any(n.get("op") in {"Calculate", "Aggregate"} and str(n.get("arguments", {}).get("calculation", n.get("arguments", {}).get("aggregation", ""))).lower() == "hhi" for n in nodes):
            defects.append({"code": "SHARE_ROWS_ARE_NOT_HHI", "expected": expected, "actual_rows": len(rows)})
    elif pattern == 40:
        expected = query("SELECT month,AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month ORDER BY month", [m, y])
        if equal(rows, expected, ["month", "value"]):
            confirmed.append("all_12_monthly_means")
            gaps.append("Final month/price output mapping and unsafe external-access refusal are not rendered/executed in the fixture result.")
        else:
            defects.append({"code": "MONTHLY_MEANS_MISMATCH", "expected": expected, "actual": rows[:12]})
    elif pattern == 54:
        metrics = {r.get("metric") for r in turn.get("semantic_plan", {}).get("requirements", [])}
        if metrics == {"price"}:
            defects.append({"code": "TRADE_UNIT_VALUE_REPLACED_BY_PRICE", "expected": "country import amount / import weight, zero-weight exclusions, descending rank", "actual_metrics": sorted(metrics)})
        gaps.append("Fixture observations have no import-weight column, so no independent unit-value numeric oracle is available.")
    elif pattern == 59:
        expected = query("SELECT r.country,r.value/p.value ratio FROM observations r JOIN observations p ON r.mineral=p.mineral AND r.year=p.year AND r.country=p.country WHERE r.domain='reserves' AND p.domain='production' AND r.mineral=? AND r.year=? AND r.value IS NOT NULL AND p.value>0", [m, y])
        if not any("ratio" in r or "reserve_life" in r for r in rows) and not any(n.get("op") == "Calculate" for n in nodes):
            defects.append({"code": "RESERVE_PRODUCTION_JOIN_WITHOUT_RATIO", "expected": expected, "actual_fields": list(rows[0]) if rows else []})
    elif pattern == 119:
        cutoff = f"{y}-{month:02d}-{calendar.monthrange(y, month)[1]}"
        expected = []
        for mineral in (m, b["m2"], "아연"):
            expected.extend(query("SELECT mineral,date,value,unit FROM observations WHERE domain='price' AND mineral=? AND date<=? ORDER BY date DESC LIMIT 1", [mineral, cutoff]))
        if len(rows) != len(expected):
            defects.append({"code": "AS_OF_LATEST_PRICES_REPLACED_BY_FULL_HISTORY", "expected": expected, "actual_rows": len(rows)})
        gaps.append("No FX oracle; do not call preservation of original units a conversion failure because Gold explicitly permits it without conversion evidence.")
    else:
        gaps.append(f"No independent SQL evaluator implemented for {case['pattern_id']}: {case['result_invariant']}")
    if confirmed and not all(root.get("evidence_count", 0) > 0 and root.get("source") and root.get("provenance") and root.get("sufficient") for root in roots.values()):
        gaps.append("Independent numeric match lacks sufficient result evidence/source/provenance.")
    return {"defects": defects, "evaluator_requirements": gaps, "independent_sql": queries,
            "confirmed_components": confirmed,
            "root_evidence": {k: {"status": v.get("status"), "rows": len(v["value"]) if isinstance(v.get("value"), list) else None,
                                 "sample": v.get("value", [])[:2] if isinstance(v.get("value"), list) else v.get("value"),
                                 "unit": v.get("unit"), "source": v.get("source"), "provenance": v.get("provenance")}
                              for k, v in roots.items()},
            "full_semantic_pass": bool(confirmed) and not defects and not gaps}


async def inspect_runtime_successes(path, selected, cases):
    source_bytes = path.read_bytes()
    old_report = json.loads(source_bytes)
    candidates = [r for r in old_report["records"] if r.get("status") == "RUNTIME_SUCCESS_NOT_SEMANTIC_PASS" or r.get("gold_status") == "COMPONENT_PASS"]
    by_id = {c["id"]: c for c in cases}
    db = actual.backend.fixture()
    inspected = []
    try:
        for old in candidates:
            cid = old["id"]
            turns = []
            for raw in selected[cid]["turns"]:
                replay = await actual.replay_turn(raw, by_id[cid], db)
                verdict = independent_check(by_id[cid], replay, db)
                turns.append({"turn": raw["turn"], "raw_sha256": replay.get("raw_sha256"),
                              "current_runtime_status": replay.get("status"), "adapter_gaps": replay.get("adapter_gaps", {}),
                              "fixture_calls": replay.get("fixture_calls", []), **verdict})
            inspected.append({"id": cid, "question": by_id[cid]["question"], "pattern_id": by_id[cid]["pattern_id"],
                              "original_status": old.get("status"), "original_gold_status": old.get("gold_status"),
                              "scope": "current-code synthetic fixture replay + independent SQL; no production I/O",
                              "full_semantic_pass": bool(turns) and all(t["full_semantic_pass"] for t in turns), "turns": turns})
    finally:
        db.close()
    return {"source": str(path), "source_sha256": sha256(source_bytes).hexdigest(),
            "source_code_sha256": old_report.get("code_sha256", {}),
            "source_use": "Candidate IDs only; every selected raw is re-executed with the current code_sha256 recorded in this artifact, not source outputs",
            "candidate_count": len(candidates), "component_pass_ids": [r["id"] for r in candidates if r.get("gold_status") == "COMPONENT_PASS"],
            "records": inspected}


def run(paths, merged_path, current_input_path, output_path,
        actual_path=Path("/tmp/qa500-actual-execution.json"),
        manual_path=Path("/tmp/qa500-manual-runtime-audit.json")):
    version_before = source_hashes()
    selected, histories, snapshots = overlay(paths)
    gold_cases, _, _ = audit.load_gold()
    ids = [c["id"] for c in gold_cases]
    missing, unknown = sorted(set(ids) - set(selected)), sorted(set(selected) - set(ids))
    if missing or unknown:
        raise ValueError(f"Expected all 500 corpus IDs, missing={missing}, unknown={unknown}")
    originals = [selected[cid] for cid in ids]
    current = [replay_record(row) for row in originals]
    manual = asyncio.run(inspect_runtime_successes(actual_path, selected, gold_cases))
    manual_by_id = {r["id"]: r for r in manual["records"]}
    if source_hashes() != version_before:
        raise RuntimeError("Schema/planner/auditor source changed during replay; rerun on stable sources")
    write_jsonl(merged_path, originals)
    write_jsonl(current_input_path, current)
    report = audit.build_report(current_input_path)
    original_screen_counts = {k: report["summary"][k] for k in ("definite_semantic_mismatch", "review_needed_only")}
    for case_result, old, new in zip(report["cases"], originals, current):
        cid = case_result["id"]
        case_result["selected_source"] = histories[cid][-1]
        case_result["overlay_history"] = histories[cid]
        case_result["replay_turns"] = [t["current_replay"] for t in new["turns"]]
        inspected = manual_by_id.get(cid)
        if inspected:
            case_result["independent_runtime_review"] = inspected
            for turn in inspected["turns"]:
                for defect in turn["defects"]:
                    case_result["findings"].append({"dimension": "requested_output" if defect["code"] == "OUTPUT_PROJECTION_CONTRACT_GAP" else "semantic_result",
                        "code": defect["code"], "status": "SEMANTIC_MISMATCH", "failure_class": "SEMANTIC_CONTRADICTION",
                        "turn": turn["turn"], "expected": defect.get("expected", defect.get("expected_fields", "Gold output contract")),
                        "observed": defect, "evidence_paths": [f"manual_runtime_review[{cid}].turn[{turn['turn']}].independent_sql"]})
            if any(t["defects"] for t in inspected["turns"]):
                case_result["status"] = "SEMANTIC_MISMATCH"
            case_result["full_pass"] = inspected["full_semantic_pass"] and case_result["status"] != "SEMANTIC_MISMATCH"
            if case_result["full_pass"]:
                case_result["screen_status"] = case_result["status"]
                case_result["status"] = "BACKEND_SEMANTIC_PASS"
                case_result["pass_scope"] = "Selected actual raw, current backend, synthetic fixture and independent SQL; not production/SSE or all possible datasets"
                case_result["screen_findings_before_runtime_review"] = deepcopy(case_result["findings"])
                for finding in case_result["findings"]:
                    if finding["status"] == "REVIEW_NEEDED":
                        finding["status"] = "RESOLVED_FOR_BACKEND_FIXTURE"
                        finding["resolution"] = "See independent_runtime_review: actual final rows, numerical oracle, ties, units and provenance; no universal boundary-data claim"
                for dimension, status in case_result["dimensions"].items():
                    if status != "NOT_APPLICABLE":
                        case_result["dimensions"][dimension] = "VERIFIED_BACKEND_FIXTURE"
        # Whole-lowering failure with a valid logical DAG was not counted by the
        # earlier semantic screener. Surface it separately; it is NOT semantic PASS
        # nor an invented semantic mismatch/capability gap.
        for t in new["turns"]:
            if t["current_replay"]["outcome"] == "CURRENT_LOWERING_FAILURE":
                case_result["findings"].append({
                    "dimension": "lowering", "code": "CURRENT_LOWERING_FAILURE",
                    "status": "PIPELINE_FAILURE", "failure_class": "LOWERING_FAILURE", "turn": t["turn"],
                    "expected": "current lowerer accepts regenerated logical program",
                    "observed": t["error"], "evidence_paths": [f"turn[{t['turn']}].current_replay.error"]})
        case_result["current_pipeline_failure"] = any(
            t["current_replay"]["outcome"] != "CURRENT_PLAN_AND_LOWERING_AVAILABLE" for t in new["turns"])
        case_result["reviewer_requirements"] = [
            {"code": f["code"], "dimension": f["dimension"], "expected": f["expected"],
             "observed": f["observed"], "evidence_paths": f["evidence_paths"]}
            for f in case_result["findings"] if f["status"] == "REVIEW_NEEDED"]
        case_result["definite_semantic_mismatch_count"] = sum(f["status"] == "SEMANTIC_MISMATCH" for f in case_result["findings"])
        case_result["remaining_evaluation_scope"] = ({
            "classification": "EVALUATION_ORACLE_GAP", "reason": "No independent numerical/runtime oracle was executed for this ID in the final wrapper",
            "required_gold_contract": case_result["gold"]["invariant"],
            "required_operations": case_result["gold"]["operation_graph"]} if not inspected else {
            "classification": "INDEPENDENT_RUNTIME_REVIEW_COMPLETED", "requirements": [g for t in inspected["turns"] for g in t["evaluator_requirements"]]})
    traces = [(r["id"], t) for r in current for t in r["turns"]]
    failures = [(cid, t) for cid, t in traces if t["current_replay"]["outcome"] != "CURRENT_PLAN_AND_LOWERING_AVAILABLE"]
    failure_ids = sorted({cid for cid, _ in failures})
    summary = report["summary"]
    summary.update({
        "before_independent_sql_screen_counts": original_screen_counts,
        "definite_semantic_mismatch": sum(r["status"] == "SEMANTIC_MISMATCH" for r in report["cases"]),
        "review_needed_only": sum(r["status"] == "REVIEW_NEEDED" for r in report["cases"]),
        "full_pass": sum(r["full_pass"] for r in report["cases"]),
        "manual_runtime_review_cases": len(manual["records"]),
        "manual_runtime_defect_cases": sum(any(t["defects"] for t in r["turns"]) for r in manual["records"]),
        "manual_runtime_evaluator_gap_only_cases": sum(not any(t["defects"] for t in r["turns"]) and not r["full_semantic_pass"] for r in manual["records"]),
        "selected_record_source_counts": dict(Counter(histories[cid][-1]["source"] for cid in ids)),
        "current_replay_turn_counts": dict(Counter(t["current_replay"]["outcome"] for _, t in traces)),
        "semantic_changed_turns": sum(t["current_replay"].get("semantic_changed", False) for _, t in traces),
        "logical_changed_turns": sum(t["current_replay"].get("logical_changed", False) for _, t in traces),
        "cases_with_pipeline_failure": len(failure_ids), "triage_pipeline_failure_ids": failure_ids,
        "pipeline_failure_cases_without_semantic_mismatch": sum(r["current_pipeline_failure"] and
            r["status"] != "SEMANTIC_MISMATCH" for r in report["cases"]),
        "review_only_no_pipeline_failure_ids": [r["id"] for r in report["cases"] if
            r["status"] == "REVIEW_NEEDED" and not r["current_pipeline_failure"]],
        "failure_classes_case_counts_overlapping": {k: len(v) for k, v in summary["definite_case_ids_by_failure_class"].items()},
        "finding_counts": dict(Counter(f["code"] for r in report["cases"] for f in r["findings"])),
        "lowering_gap_not_inferred_from_review": True,
    })
    # Refresh indexes after independent checks; do not leave stale screen-only
    # classifications in the frozen evidence bundle.
    summary["definite_finding_counts"] = dict(Counter(f["code"] for r in report["cases"] for f in r["findings"] if f["status"] == "SEMANTIC_MISMATCH"))
    for category in summary["definite_case_ids_by_failure_class"]:
        summary["definite_case_ids_by_failure_class"][category] = [r["id"] for r in report["cases"] if any(f["status"] == "SEMANTIC_MISMATCH" and f.get("failure_class") == category for f in r["findings"])]
    summary["failure_classes_case_counts_overlapping"] = {k: len(v) for k, v in summary["definite_case_ids_by_failure_class"].items()}
    summary["pattern_counts"] = {pid: dict(Counter(r["status"] for r in report["cases"] if r["pattern_id"] == pid)) for pid in summary["pattern_counts"]}
    summary["triage_review_only_observed_ids"] = [r["id"] for r in report["cases"] if r["status"] == "REVIEW_NEEDED" and r["parsed_turns"]]
    for r in report["cases"]:
        for dimension in r["dimensions"]:
            if any(f["dimension"] == dimension and f["status"] == "SEMANTIC_MISMATCH" for f in r["findings"]):
                r["dimensions"][dimension] = "SEMANTIC_MISMATCH"
    report["final_audit"] = {
        "input_precedence": [str(p) for p in paths], "input_snapshots": snapshots,
        "selection_policy": "LAST_COMPLETE_RECORD_PER_ID; actual_execution.current_plan RAW_SELECTION; NO_RECORD_FALLBACK",
        "code_sha256": version_before,
        "merged_raw": {"path": str(merged_path), "sha256": sha256(merged_path.read_bytes()).hexdigest()},
        "current_model_input": {"path": str(current_input_path), "sha256": sha256(current_input_path.read_bytes()).hexdigest()},
        "pipeline_failures": [{"id": cid, "turn": t["turn"], "outcome": t["current_replay"]["outcome"],
                               "error": t["error"]} for cid, t in failures],
        "review_policy": "Structural availability alone is NOT PASS. BACKEND_SEMANTIC_PASS requires current runtime plus independent SQL on the stated fixture; production/SSE and untested datasets are excluded.",
        "manual_audit_policy": "All selected runtime-success candidates are recomputed with current code; old outputs and code hashes are not reused as proof.",
        "runtime_review_artifact": str(manual_path),
        "attempt_policy_change": "Aligned with actual_execution.current_plan; initial strict-last snapshot had schema=2/planner=23. UNSUPPORTED is now classified before planner, matching actual execution.",
    }
    report["scope"].update(production_imports=True, production_modified=False, new_gemma_calls=0,
                           current_schema_planner_replay=True, backend_execution_assessed=True,
                           backend_execution_assessed_cases=len(manual["records"]), production_e2e=False)
    # Exclude known pipeline failures from the concrete unknown-semantics queue.
    summary["triage_review_only_complete_ids"] = summary["review_only_no_pipeline_failure_ids"]
    if source_hashes() != version_before:
        raise RuntimeError("Sources changed during audit; report not published, rerun required")
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manual["code_sha256"] = version_before
    manual["counts"] = {"reviewed": len(manual["records"]), "full_semantic_pass": sum(r["full_semantic_pass"] for r in manual["records"]),
                        "concrete_defect": summary["manual_runtime_defect_cases"], "evaluation_oracle_gap_only": summary["manual_runtime_evaluator_gap_only_cases"]}
    manual_path.write_text(json.dumps(manual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for artifact in (merged_path, current_input_path, output_path, manual_path):
        artifact.with_suffix(artifact.suffix + ".gz").write_bytes(gzip.compress(artifact.read_bytes(), mtime=0))
    return report


class FinalAuditTests(unittest.TestCase):
    def valid_turn(self):
        return {"turn": 1, "question": "fixture", "semantic_plan": {"stale": True},
                "logical_program": {"nodes": [{"op": "WrongStaleOperation"}]},
                "record": {"attempts": [{"raw_content": json.dumps({
                    "schema_version": "semantic-requirement-v2", "request_class": "DATA_QUERY",
                    "requirements": [{"requirement_id": "r", "metric": "price", "entity": {"value": "니켈"},
                                      "time_range": {"kind": "year", "value": 2025}, "aggregation": "mean"}],
                    "requested_outputs": [{"name": "average", "fields": ["value"]}],
                })}]}}

    def test_latest_failure_record_wins_whole_case(self):
        records = {s: ({"X": (1, {"id": "X", "status": s, "turns": []})}, {})
                   for s in ("before", "after", "after2", "recovered")}
        with patch.object(audit, "read_snapshot", side_effect=lambda p: records[str(p)]):
            chosen, history, _ = overlay(list(records))
        self.assertEqual(chosen["X"]["status"], "recovered")
        self.assertEqual(len(history["X"]), 4)
        self.assertEqual(chosen["X"]["turns"], [])

    def test_stale_dag_is_replaced_by_current_aggregate(self):
        original = self.valid_turn()
        untouched = deepcopy(original)
        replay = replay_turn(original)
        self.assertEqual(original, untouched)
        self.assertIn("Aggregate", [n["op"] for n in replay["logical_program"]["nodes"]])
        self.assertNotIn("WrongStaleOperation", json.dumps(replay))
        self.assertTrue(replay["current_replay"]["logical_changed"])
        self.assertFalse(replay["backend_executed"])

    def test_attempt_selection_matches_actual_execution(self):
        for saved in (True, False):
            turn = self.valid_turn()
            if not saved:
                turn.pop("semantic_plan")
            turn["record"]["attempts"].append({"raw_content": "broken"})
            result = replay_turn(turn)
            if saved:
                self.assertEqual(result["current_replay"]["outcome"], "SCHEMA_REPLAY_FAILURE")
                self.assertNotIn("semantic_plan", result)
                self.assertNotIn("logical_program", result)
            else:
                self.assertTrue(result["current_replay"]["recovered_without_saved_plan"])
                self.assertEqual(result["current_replay"]["raw_attempt_index"], 0)
                self.assertIn("logical_program", result)

    def test_saved_plan_cannot_replace_missing_raw(self):
        turn = self.valid_turn()
        turn.pop("record")
        self.assertEqual(replay_turn(turn)["current_replay"]["outcome"], "SCHEMA_REPLAY_FAILURE")

    def test_planner_failure_keeps_semantic_but_never_old_dag(self):
        with patch(__name__ + ".logical_program_from_requirements", side_effect=ValueError("bad reference")):
            result = replay_turn(self.valid_turn())
        self.assertIn("semantic_plan", result)
        self.assertNotIn("logical_program", result)
        self.assertEqual(result["current_replay"]["outcome"], "CURRENT_PLANNER_FAILURE")

    def test_lowerer_failure_preserves_current_dag(self):
        with patch.object(LegacyActionLowerer, "lower", side_effect=ValueError("unsupported operation")):
            result = replay_turn(self.valid_turn())
        self.assertIn("logical_program", result)
        self.assertEqual(result["current_replay"]["outcome"], "CURRENT_LOWERING_FAILURE")
        self.assertNotIn("lowered", result)

    def test_independent_oracle_detects_extra_fields_but_can_accept_complete_projection(self):
        cases, _, _ = audit.load_gold()
        db = actual.backend.fixture()
        try:
            rows = [dict(r) for r in db.execute("SELECT date,high_price FROM observations WHERE domain='price' AND mineral='니켈' AND year=2025 AND high_price=(SELECT MAX(high_price) FROM observations WHERE domain='price' AND mineral='니켈' AND year=2025)")]
            turn = {"status": "RUNTIME_SUCCESS_NOT_SEMANTIC_PASS", "logical_program": {"nodes": []},
                    "roots": {"selected": {"status": "success", "value": rows, "unit": "USD/t", "evidence_count": 1,
                                           "sufficient": True, "source": ["fixture"], "provenance": ["test"]}}}
            self.assertTrue(independent_check(cases[0], turn, db)["full_semantic_pass"])
            rows[0]["value"] = 123.0
            result = independent_check(cases[0], turn, db)
            self.assertFalse(result["full_semantic_pass"])
            self.assertEqual(result["defects"][0]["code"], "OUTPUT_PROJECTION_CONTRACT_GAP")
            rows[0].pop("value")
            rows[0]["high_price"] = -1
            self.assertEqual(independent_check(cases[0], turn, db)["defects"][0]["code"], "EXTREMUM_NUMERIC_OR_DATE_MISMATCH")
        finally:
            db.close()

    def test_country_count_null_wrong_boolean_and_unverified_duplicate_flag_never_pass(self):
        cases, _, _ = audit.load_gold()
        db = actual.backend.fixture()
        try:
            for case in cases[92:96]:
                b = case["semantic_requirement"]["parameter_bindings"]
                row = dict(db.execute("SELECT SUM(value) value,COUNT(DISTINCT country) country_count,MIN(unit) unit FROM observations WHERE domain='production' AND mineral=? AND year=?", (b["m"], b["y"])).fetchone())
                count = row["country_count"]
                for mutant in (None, count + 1, True, count):
                    with self.subTest(case=case["id"], count=mutant):
                        output = {"value": row["value"], "country_count": mutant, "is_duplicate_excluded": None if mutant is None else True}
                        turn = {"status": "RUNTIME_SUCCESS_NOT_SEMANTIC_PASS", "logical_program": {"nodes": []},
                                "roots": {"final": {"value": [output], "unit": row["unit"], "evidence_count": 1,
                                                     "sufficient": True, "source": ["fixture"], "provenance": ["test"]}}}
                        result = independent_check(case, turn, db)
                        self.assertFalse(result["full_semantic_pass"])
                        codes = {d["code"] for d in result["defects"]}
                        self.assertEqual("REQUESTED_COUNTRY_COUNT_MISMATCH" in codes, mutant != count or isinstance(mutant, bool))
                        if mutant is None:
                            self.assertIn("DUPLICATE_EXCLUSION_DISCLOSURE_MISSING", codes)
                        self.assertTrue(any("total-row duplicate exclusion" in g for g in result["evaluator_requirements"]))
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", default=DEFAULT_INPUTS)
    parser.add_argument("--merged-output", type=Path, default=Path("/tmp/qa500-latest.jsonl"))
    parser.add_argument("--current-input", type=Path, default=Path("/tmp/qa500-current-model-input.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("/tmp/qa500-semantic-current.json"))
    parser.add_argument("--actual-execution", type=Path, default=Path("/tmp/qa500-actual-execution.json"))
    parser.add_argument("--manual-output", type=Path, default=Path("/tmp/qa500-manual-runtime-audit.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FinalAuditTests))
        return 0 if result.wasSuccessful() else 1
    outputs = [args.merged_output.resolve(), args.current_input.resolve(), args.output.resolve(), args.manual_output.resolve()]
    protected = {p.resolve() for p in [*args.inputs, args.actual_execution, *SOURCE_FILES,
                 Path(audit.__file__).with_name("qa_build_order2_4_500.json"),
                 Path(audit.__file__).with_name("qa_order2_4_patterns.tsv")]}
    if len(set(outputs)) != 4 or any(p in protected for p in outputs):
        parser.error("Output paths must be distinct and cannot overwrite any input/source/Gold")
    report = run(args.inputs, args.merged_output, args.current_input, args.output, args.actual_execution, args.manual_output)
    s = report["summary"]
    print(json.dumps({k: s[k] for k in ("total_ids", "definite_semantic_mismatch", "review_needed_only",
        "full_pass", "missing_log_ids", "cases_with_pipeline_failure", "current_replay_turn_counts",
        "selected_record_source_counts", "semantic_changed_turns", "logical_changed_turns")}, ensure_ascii=False))
    print("review_only_no_pipeline_failure:", len(s["review_only_no_pipeline_failure_ids"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
