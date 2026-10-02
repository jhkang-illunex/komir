"""Test-only contract inventory; immutable captures, no model/Gold plan repair.

Counts are QA-level incidence (overlapping), not a new chatbot success rate.
Run with --output to preserve a separate diagnostic JSON alongside the old ledger.
"""
import argparse
import asyncio
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "documents/meta/qa500_validation_20261002"


def read(path):
    content = path.read_bytes()
    return json.loads(gzip.decompress(content) if path.suffix == ".gz" else content)


def category(reason):
    # Diagnostic messages, never natural-language query classification.
    if "requires explicit join keys" in reason:
        return "JOIN_KEYS"
    if "requires comparison field" in reason:
        return "COMPARE_FIELDS"
    if "requires exactly two upstream results" in reason:
        return "INPUT_CARDINALITY"
    if "document_scope_unresolved" in reason:
        return "DOCUMENT_SCOPE"
    if "Invalid isoformat" in reason or "unsupported v2 time range" in reason:
        return "TIME_RANGE"
    if "validation error for ActionSlots" in reason:
        return "PHYSICAL_SLOT_VOCABULARY"
    if "not produced by upstream" in reason or "absent from" in reason:
        return "FIELD_LINEAGE"
    if "MISSING_REQUIRED_SINGLE_MINERAL" in reason:
        return "ENTITY_BINDING"
    return "OTHER_CONTRACT"


CONTRACTS = {
    "JOIN_KEYS": {"required": ["two inputs", "join_key or left_on/right_on", "key types", "cardinality"],
        "gold": "test_complete_requirement_through_lowering_and_runtime_matches_sql[join]",
        "negative": "test_missing_contract_fails_without_adapter_invention",
        "decision": "Never turn fields/output labels into keys implicitly."},
    "COMPARE_FIELDS": {"required": ["left/right input", "one shared or two explicit fields", "alignment", "operation", "units"],
        "gold": "test_complete_requirement_through_lowering_and_runtime_matches_sql[compare]",
        "negative": "test_conflicting_compare_fields_are_not_silently_repaired",
        "decision": "RelationshipSpec lacks arithmetic operation: report schema gap, not data gap."},
    "INPUT_CARDINALITY": {"required": ["exactly two distinct operand roles"],
        "negative": "test_missing_contract_fails_without_adapter_invention",
        "decision": "Do not reduce multi-input relations to arbitrary first two operands."},
    "DOCUMENT_SCOPE": {"required": ["document topic/collection", "time scope", "entity inclusion", "selection order"],
        "decision": "Need independent document Gold; scope omission is not document absence."},
    "TIME_RANGE": {"required": ["supported kind", "concrete dates or typed reference", "as_of", "calendar policy"],
        "decision": "No placeholder date/default year substitution."},
    "PHYSICAL_SLOT_VOCABULARY": {"required": ["semantic metric", "registered indicator", "ActionSlots accepted value"],
        "decision": "Distinguish indicator family from trade calculation such as TSI."},
    "FIELD_LINEAGE": {"required": ["upstream-produced fields", "all projected fields", "root/output binding"],
        "gold": "test_projection_complete_alias_and_empty_data_contract",
        "negative": "test_projection_validates_every_requested_field",
        "decision": "Every requested field must exist; unknown schemas checked at runtime."},
    "ENTITY_BINDING": {"required": ["static entity or typed result reference", "consumer slot role"],
        "decision": "Derived entity is not a missing static mineral."},
    "OTHER_CONTRACT": {"required": ["manual contract review"], "decision": "Do not guess attribution."},
}


def inventory():
    ledger_path = ARTIFACTS / "corpus_results.json"
    trace_path = ARTIFACTS / "qa500-actual-execution-v4-final.json.gz"
    ledger = read(ledger_path)
    traces = {r["id"]: r for r in read(trace_path)["records"]}
    selected = [r for r in ledger["records"] if r["reason"] == "ACTUAL_PLAN_CONTRACT_GAP"]
    records = []
    for row in selected:
        observations = []
        for turn in traces[row["id"]]["turns"]:
            semantic = turn.get("semantic_plan") or {}
            logical = turn.get("logical_program") or {}
            nodes = {n["node_id"]: n for n in logical.get("nodes", [])}
            failures = dict(turn.get("adapter_gaps", {}))
            for node_id, result in turn.get("results", {}).items():
                if str(result.get("reason", "")).startswith("ACTUAL_PLAN_CONTRACT_GAP:"):
                    failures.setdefault(node_id, result["reason"])
            for node_id, reason in failures.items():
                if not reason.startswith("ACTUAL_PLAN_CONTRACT_GAP:"):
                    continue
                node = nodes.get(node_id, {})
                family = category(reason)
                relations = semantic.get("relationships", [])
                relation = None
                if node_id.startswith(("relation_join_", "relation_compare_", "relation_filter_")):
                    suffix = node_id.rsplit("_", 1)[-1]
                    if suffix.isdigit() and int(suffix) < len(relations):
                        relation = relations[int(suffix)]
                boundary = "REQUIRES_REVIEW"
                if family == "JOIN_KEYS" and relation is not None:
                    boundary = "MISSING_IN_REQUIREMENT" if not relation.get("join_key") else "REQUIREMENT_TO_LOGICAL_LOSS"
                elif family == "COMPARE_FIELDS" and relation is not None:
                    boundary = "MISSING_IN_REQUIREMENT" if not relation.get("fields") else "REQUIREMENT_TO_LOGICAL_LOSS"
                elif family == "INPUT_CARDINALITY" and relation is not None:
                    boundary = "REQUIREMENT_CARDINALITY" if len(relation.get("inputs", [])) != 2 else "REQUIREMENT_TO_LOGICAL_LOSS"
                observations.append({"turn": turn["turn"], "node_id": node_id, "family": family,
                    "observed_boundary": boundary, "reason": reason,
                    "semantic_relation": relation, "logical_node": node,
                    "requirement_fields": semantic.get("requirements", []),
                    "requested_outputs": semantic.get("requested_outputs", []),
                    "raw_sha256": turn.get("raw_sha256"),
                    "fixture_contract": CONTRACTS[family]})
        assert observations, row["id"]
        records.append({"id": row["id"], "pattern_id": row["pattern_id"], "question": row["question"],
            "original_status": row["status"], "diagnostic_status": "CLASSIFIED_NOT_REPAIRED",
            "families": sorted({o["family"] for o in observations}), "observations": observations})
    assert len(records) == len({r["id"] for r in records}) == 245
    return {"scope": "245 prior plan-contract failures, not production E2E; no status promotion",
        "source_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in (ledger_path, trace_path)},
        "total": len(records), "unclassified_qa": 0,
        "qa_incidence_overlapping": dict(Counter(f for r in records for f in r["families"])),
        "observed_boundary_incidence_overlapping": dict(Counter(
            f for r in records for f in {o["observed_boundary"] for o in r["observations"]})),
        "records": records}


async def replay(report):
    """Replay normalized captured requirements unchanged, not a new model run."""
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements
    from inhouse.rag_core.tests import qa500_backend as backend
    from inhouse.rag_core.tests.qa500_actual_execution import run_program
    traces = {r["id"]: r for r in read(ARTIFACTS / "qa500-actual-execution-v4-final.json.gz")["records"]}
    db = backend.fixture()
    try:
        for row in report["records"]:
            turns = []
            for saved in traces[row["id"]]["turns"]:
                original = saved.get("semantic_plan")
                if original is None:
                    turns.append({"turn": saved["turn"], "status": "NO_CAPTURED_REQUIREMENT"})
                    continue
                try:
                    requirement = SemanticRequirementPlanV2.model_validate(original)
                    logical = logical_program_from_requirements(requirement)
                    trace, program, _ = await run_program(logical, db)
                    turns.append({"turn": saved["turn"], "raw_sha256": saved.get("raw_sha256"),
                        "status": "REPLAYED_NOT_SEMANTIC_PASS", "logical_program": logical.to_dict(),
                        "roots": list(program.roots), "trace": trace})
                except (ValueError, TypeError, KeyError) as error:
                    turns.append({"turn": saved["turn"], "status": "PLAN_REJECTED", "reason": str(error)})
            row["current_replay"] = turns
    finally:
        db.close()
    report["replay_summary"] = {
        "qa_attempted": len(report["records"]),
        "turn_status": dict(Counter(t["status"] for r in report["records"] for t in r["current_replay"])),
        "new_gemma_calls": 0, "semantic_pass_promotions": 0, "production_sse_calls": 0,
    }
    report["replay_code_sha256"] = {
        relative: sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in ("inhouse/rag_core/ragkit/semantic_ir.py",
                         "inhouse/rag_core/ragkit/semantic_v2.py",
                         "inhouse/rag_core/tests/qa500_actual_execution.py")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    result = inventory()
    if args.replay:
        asyncio.run(replay(result))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, ensure_ascii=False, indent=2))
