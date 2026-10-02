"""Compiler-owned operand wiring; no query text or QA identifiers involved."""
import asyncio
from copy import deepcopy

import pytest

from inhouse.rag_core.ragkit.semantic_v2 import (
    SemanticRequirementPlanV2, requirement_contract_issues,
    logical_program_from_requirements,
)
from inhouse.rag_core.tests.qa500_actual_execution import run_program
from inhouse.rag_core.tests import qa500_backend as backend


def plan():
    return {"requirements": [
        {"requirement_id": ident, "metric": "price", "entity": {"value": "아연"},
         "time_range": {"kind": "calendar_year", "value": 2024},
         "aggregation": aggregation, "output_field": field}
        for ident, aggregation, field in (("a", "max", "peak"), ("b", "min", "trough"))],
        "relationships": [{"kind": "compare", "inputs": ["a", "b"], "operation": "difference"}],
        # Neither the generated relation node ID nor numeric operand fields
        # belong to the model when the typed source contract is unambiguous.
        "requested_outputs": [{"name": "spread", "fields": ["difference"]}]}


@pytest.mark.parametrize("operation", ["difference", "ratio", "percent_change"])
def test_omitted_operands_equal_explicit_operands_and_sql(operation):
    raw = plan()
    raw["relationships"][0]["operation"] = operation
    raw["requested_outputs"][0]["fields"] = [operation]
    typed = SemanticRequirementPlanV2.model_validate(raw)
    assert requirement_contract_issues(typed) == ()
    logical = logical_program_from_requirements(typed)
    explicit = deepcopy(raw)
    explicit["relationships"][0]["fields"] = ["peak", "trough"]
    assert logical == logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(explicit))
    db = backend.fixture()
    try:
        _, program, results = asyncio.run(run_program(logical, db))
        high, low = db.execute("SELECT MAX(value),MIN(value) FROM observations WHERE domain='price' AND mineral='아연' AND year=2024").fetchone()
        expected = {"difference": high-low, "ratio": high/low, "percent_change": (high-low)/abs(low)*100}[operation]
        root = results[program.roots[0]]
        assert root.status.value == "success"
        assert root.value == [{operation: expected}]
        assert root.evidence and root.provenance
    finally:
        db.close()


def test_unknown_source_stays_invalid_and_explicit_fields_are_not_overwritten():
    raw = plan()
    raw["requested_outputs"][0]["source_node"] = "invented"
    with pytest.raises(ValueError, match="requested_output_source_unknown"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    raw = plan()
    raw["relationships"][0]["fields"] = ["nonexistent"]
    logical = logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    compare = next(n for n in logical.nodes if n.op.value == "Compare")
    assert compare.arguments["fields"] == ["nonexistent"]


def test_multiple_measure_series_do_not_get_a_default_field():
    raw = plan()
    for req in raw["requirements"]:
        req.pop("aggregation")
        req.pop("output_field")
    typed = SemanticRequirementPlanV2.model_validate(raw)
    assert any("comparison fields required" in s for s in requirement_contract_issues(typed))


def test_operand_roles_survive_symbol_renaming_and_order_reversal():
    raw = plan()
    raw["requirements"][0]["requirement_id"] = "opaque_first"
    raw["requirements"][1]["requirement_id"] = "opaque_second"
    raw["relationships"][0]["inputs"] = ["opaque_second", "opaque_first"]
    logical = logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    compare = next(n for n in logical.nodes if n.op.value == "Compare")
    assert compare.arguments["fields"] == ["trough", "peak"]
