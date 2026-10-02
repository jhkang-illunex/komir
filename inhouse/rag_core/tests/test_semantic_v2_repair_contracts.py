"""Captured model failures plus domain-independent negative controls."""
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from inhouse.rag_core.ragkit.semantic_v2 import (
    SemanticRequirementPlanV2, logical_program_from_requirements,
    parse_v2_shadow, requirement_contract_issues, LegacyActionLowerer, V2ShadowTrace,
)
from inhouse.rag_core.tests.test_semantic_v2_linkage import monthly_plan


ARCHIVE = Path(__file__).resolve().parents[3] / "documents/meta/qa500_linkage_20261002"


def captured(name, ident):
    with gzip.open(ARCHIVE / f"qa500-linkage-{name}.jsonl.gz", "rt") as stream:
        return next(json.loads(line)["trace"]["semantic_plan"] for line in stream
                    if json.loads(line)["case"]["id"] == ident)


def test_captured_group_identity_loss_rejected_before_execution():
    plan = SemanticRequirementPlanV2.model_validate(captured("after4", "H1"))
    with pytest.raises(ValueError, match="group_identity_missing"):
        logical_program_from_requirements(plan)


def test_captured_double_reduction_requires_scope_not_silent_deduplication():
    plan = SemanticRequirementPlanV2.model_validate(captured("fresh-holdout", "Z5"))
    assert any("reduction_scope_ambiguous" in e for e in requirement_contract_issues(plan))
    assert plan.requirements[0].operation == "average"
    with pytest.raises(ValueError, match="reduction_scope_ambiguous"):
        logical_program_from_requirements(plan)


def test_captured_unbound_unused_requirement_repair_explains_relation_role():
    plan = SemanticRequirementPlanV2.model_validate(captured("after4", "H4"))
    assert any("unbound_unreferenced_requirement" in e for e in requirement_contract_issues(plan))


@pytest.mark.parametrize("metric,dimension", [("price", "month"), ("production", "country"), ("import_value", "country")])
def test_group_identity_contract_generalizes_and_preserves_aliases(metric, dimension):
    raw = monthly_plan()
    for req in raw["requirements"]:
        req.update(metric=metric, dimension=dimension)
    raw["relationships"][0]["join_key"] = dimension
    output = raw["requested_outputs"][0]
    output.update(fields=[dimension, "left.mean_price", "right.observations"], aliases={dimension: "group"})
    program = logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    assert program.nodes[-1].arguments["aliases"][dimension] == "group"
    output["fields"].remove(dimension); output["aliases"] = {}
    with pytest.raises(ValueError, match="group_identity_missing"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))


def test_scalar_selection_can_explicitly_project_only_value():
    raw = monthly_plan()
    raw["relationships"] = []
    raw["requirements"] = raw["requirements"][:1]
    raw["requirements"][0]["selection"] = {"mode": "argmax", "field": "mean_price"}
    raw["requested_outputs"] = [{"name": "peak", "source_node": "mean_price", "fields": ["mean_price"]}]
    logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    trace = parse_v2_shadow("generic input", SimpleNamespace(invoke=lambda **_: SimpleNamespace(output=SemanticRequirementPlanV2.model_validate(raw))))
    assert trace.failure_class is None


def test_aggregate_then_share_is_not_misclassified_as_duplicate_reduction():
    raw = monthly_plan()
    raw["requirements"] = [{"requirement_id": "shares", "metric": "import_value",
        "aggregation": "sum", "dimension": "country", "operation": "share"}]
    raw["relationships"] = []; raw["requested_outputs"] = []
    plan = SemanticRequirementPlanV2.model_validate(raw)
    assert not requirement_contract_issues(plan)
    program = logical_program_from_requirements(plan)
    assert [n.op.value for n in program.nodes] == ["Retrieve", "Aggregate", "Calculate"]


def test_renamed_aggregate_is_not_fed_to_implicit_value_calculation():
    raw = monthly_plan()
    raw["requirements"][0]["operation"] = "share"
    with pytest.raises(ValueError, match="calculation_input_missing"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))


def test_group_projection_reparse_uses_contract_only_and_is_bounded():
    raw = monthly_plan(); raw["requested_outputs"][0]["fields"].remove("month")
    calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output=SemanticRequirementPlanV2.model_validate(raw))
    trace = parse_v2_shadow("arbitrary input", SimpleNamespace(invoke=invoke))
    assert len(calls) == 2
    assert trace.failure_class == "LOGICAL_PLAN_INCOMPLETE"
    assert "group_identity_missing" in trace.failure_reason
    assert "gold" not in str(calls).lower()


@pytest.mark.parametrize("operation", ["share", "SHARE", " Share "])
def test_share_preserves_group_identity_but_scalar_hhi_does_not_require_it(operation):
    raw = {"requirements": [{"requirement_id": "r", "metric": "import_value", "aggregation": "sum",
        "dimension": "country", "operation": operation}],
        "requested_outputs": [{"name": "shares", "source_node": "r", "fields": ["value", "unit"]}]}
    with pytest.raises(ValueError, match="group_identity_missing"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    raw["requirements"][0]["operation"] = "hhi"
    logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))


def test_indicator_has_no_implicit_physical_series_default():
    raw = {"requirements": [{"requirement_id": "i", "metric": "indicator"}]}
    plan = SemanticRequirementPlanV2.model_validate(raw)
    assert any("indicator selector required" in e for e in requirement_contract_issues(plan))
    with pytest.raises(ValueError, match="indicator_selector_required"):
        LegacyActionLowerer().lower(logical_program_from_requirements(plan))
    raw["requirements"][0]["indicator"] = "composite_index"
    assert LegacyActionLowerer().lower(logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw)))[0].slots.indicator == "composite_index"


def test_evaluator_uses_existing_canonical_entity_contract_not_spelling():
    from inhouse.rag_core.tests.qa500_linkage_eval import evaluate_trace
    raw = monthly_plan("nickel", 2021)
    plan = SemanticRequirementPlanV2.model_validate(raw)
    trace = V2ShadowTrace(question="test", semantic_plan=plan.model_dump(mode="json"),
        logical_program=logical_program_from_requirements(plan).to_dict())
    case = dict(id="alias-test", family="monthly", mineral="니켈", year=2021, month=None, measure="value")
    assert evaluate_trace(case, trace)["status"] == "PASS"
    case["mineral"] = "코발트"
    assert evaluate_trace(case, trace)["status"] == "SEMANTIC_MISMATCH"
