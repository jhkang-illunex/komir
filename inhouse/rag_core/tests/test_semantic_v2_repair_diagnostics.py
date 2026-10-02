"""Compiler diagnostics contain actual symbols, never query-specific repairs."""
from types import SimpleNamespace
import pytest
import socket
from unittest.mock import Mock, patch
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, parse_v2_shadow
from inhouse.rag_core.tests.test_semantic_v2_linkage import monthly_plan


def rejected_payload(raw):
    calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output=SemanticRequirementPlanV2.model_validate(raw))
    trace = parse_v2_shadow("opaque user input", SimpleNamespace(invoke=invoke))
    assert len(calls) == 2
    assert trace.failure_class == "LOGICAL_PLAN_INCOMPLETE"
    return calls[1]["payload"]


def test_unknown_source_diagnostic_exposes_only_defined_symbols_and_fields():
    raw = monthly_plan()
    raw["requested_outputs"][0]["source_node"] = "invented_join"
    payload = rejected_payload(raw)
    errors = " ".join(payload["contract_errors"])
    assert "defined_sources=" in errors
    assert "summary" in errors and "left.mean_price" in errors and "right.observations" in errors
    assert payload["previous_requirement"]["requested_outputs"][0]["source_node"] == "invented_join"
    assert payload["question"] == "opaque user input"
    assert "gold" not in str(payload).lower()


def test_missing_compare_fields_diagnostic_preserves_input_roles():
    raw = monthly_plan()
    # A raw price series has multiple measures, unlike a single-measure aggregate.
    for req in raw["requirements"]:
        req.pop("aggregation")
        req.pop("output_field")
    raw["relationships"][0].update(kind="compare", operation="side_by_side", fields=[])
    errors = " ".join(rejected_payload(raw)["contract_errors"])
    assert "operand_fields=" in errors
    assert "high_price" in errors and "low_price" in errors
    assert "left" in errors and "right" in errors


def test_diagnostic_is_invariant_to_requirement_symbol_renaming():
    raw = monthly_plan()
    raw["requirements"][0]["requirement_id"] = "opaque_alpha"
    raw["requirements"][1]["requirement_id"] = "opaque_beta"
    raw["relationships"][0]["inputs"] = ["opaque_alpha", "opaque_beta"]
    raw["relationships"][0]["relationship_id"] = "opaque_gamma"
    raw["requested_outputs"][0]["source_node"] = "missing"
    errors = " ".join(rejected_payload(raw)["contract_errors"])
    assert "defined_sources=" in errors and "opaque_gamma" in errors
    assert "opaque_alpha" in errors and "opaque_beta" in errors


def test_stability_accounting_does_not_select_best_run_or_hide_pending():
    from inhouse.rag_core.tests.qa500_stability_eval import summarize
    rows = [{"case": {"id": ident}, "repeat": repeat, "status": status}
            for ident, repeat, status in [("a", 1, "PASS"), ("a", 2, "LOGICAL_PLAN_INCOMPLETE"),
                ("b", 1, "PASS"), ("b", 2, "PASS"), ("c", 1, "PASS")]]
    report = summarize(rows, ["a", "b", "c"], 2)
    assert report["question_counts"] == {"VARIABLE": 1, "STABLE_PASS": 1, "PENDING": 1}
    with pytest.raises(ValueError):
        summarize(rows + [rows[0]], ["a", "b", "c"], 2)


def socket_guard_active():
    return isinstance(socket.socket.connect, Mock)


def test_spawned_worker_does_not_inherit_process_global_fixture_guard():
    with patch("socket.socket.connect", side_effect=AssertionError("NETWORK_FORBIDDEN")):
        assert socket_guard_active()
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
            assert not pool.submit(socket_guard_active).result(timeout=20)


def test_guard_failure_is_not_parser_failure_or_unsafe_acceptance():
    from inhouse.rag_core.tests.qa500_linkage_eval import evaluate_trace
    from inhouse.rag_core.ragkit.semantic_v2 import V2ShadowTrace
    trace = V2ShadowTrace(question="opaque", failure_class="PARSER_MISSING_OUTPUT", failure_reason="AssertionError:NETWORK_FORBIDDEN")
    for family in ("unsupported", "monthly"):
        assert evaluate_trace({"family": family}, trace)["status"] == "HARNESS_FAILURE"


def test_existing_runtime_average_alias_is_semantically_mean_not_sum():
    from inhouse.rag_core.tests.qa500_linkage_eval import evaluate_trace
    from inhouse.rag_core.ragkit.semantic_v2 import V2ShadowTrace, logical_program_from_requirements
    raw = monthly_plan()
    case = {"family": "monthly", "mineral": "구리", "year": 2024, "month": None, "measure": "value"}
    for aggregate, expected in [("average", "PASS"), ("sum", "SEMANTIC_MISMATCH")]:
        raw["requirements"][0]["aggregation"] = aggregate
        plan = SemanticRequirementPlanV2.model_validate(raw)
        trace = V2ShadowTrace(question="opaque", semantic_plan=plan.model_dump(mode="json"),
            logical_program=logical_program_from_requirements(plan).to_dict())
        assert evaluate_trace(case, trace)["status"] == expected


@pytest.mark.parametrize("aggregation", ["none", "", "invented_reduction"])
def test_unsupported_aggregate_is_rejected_before_lowering(aggregation):
    from inhouse.rag_core.ragkit.semantic_v2 import logical_program_from_requirements, requirement_contract_issues
    raw = monthly_plan();raw["requirements"][0]["aggregation"] = aggregation
    plan = SemanticRequirementPlanV2.model_validate(raw)
    assert any("unsupported_aggregation" in error for error in requirement_contract_issues(plan))
    with pytest.raises(ValueError, match="unsupported_aggregation"):
        logical_program_from_requirements(plan)
    assert plan.requirements[0].aggregation == aggregation


def test_validator_and_runtime_share_aggregate_vocabulary():
    from inhouse.rag_core.ragkit.analytical_aggregate import SUPPORTED_AGGREGATIONS
    from inhouse.rag_core.ragkit.semantic_v2 import requirement_contract_issues
    for aggregation in SUPPORTED_AGGREGATIONS:
        raw = monthly_plan();raw["requirements"][0]["aggregation"] = aggregation
        assert not requirement_contract_issues(SemanticRequirementPlanV2.model_validate(raw))
