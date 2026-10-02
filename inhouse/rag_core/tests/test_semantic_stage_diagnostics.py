"""Invalid stage inputs remain invalid; feedback describes contracts, not answers."""
import copy
import pytest

from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, requirement_contract_issues
from inhouse.rag_core.tests.test_semantic_v2_repair_diagnostics import rejected_payload
from inhouse.rag_core.tests.test_semantic_v2_linkage import monthly_plan


@pytest.mark.parametrize("metric,dimension", [("price", "date"), ("production", "country"), ("import_value", "country")])
@pytest.mark.parametrize("aggregation,mode", [("max", "argmax"), ("min", "argmin"), ("mean", "argmax")])
def test_stage_feedback_is_generic_and_does_not_repair_explicit_field(metric, dimension, aggregation, mode):
    raw = monthly_plan()
    raw["relationships"] = []
    raw["requested_outputs"] = []
    raw["requirements"] = [raw["requirements"][0]]
    req = raw["requirements"][0]
    req.update(metric=metric, dimension=dimension, aggregation=aggregation,
               output_field="opaque_measure", selection={"mode": mode, "field": "value"})
    plan = SemanticRequirementPlanV2.model_validate(raw)
    before = copy.deepcopy(plan.model_dump())
    errors = " ".join(requirement_contract_issues(plan))
    assert "stage_contract=" in errors
    assert "opaque_measure" in errors and "Aggregate" in errors and "Select" in errors
    assert "not an alias" in errors
    assert plan.model_dump() == before
    payload = rejected_payload(raw)
    assert payload["previous_requirement"]["requirements"][0]["selection"]["field"] == "value"


def test_projection_diagnostic_exposes_sources_without_redirecting():
    raw = monthly_plan()
    raw["requested_outputs"][0].update(source_node=raw["requirements"][0]["requirement_id"],
                                       fields=["observations"], aliases={})
    payload = rejected_payload(raw)
    errors = " ".join(payload["contract_errors"])
    assert "defined_sources=" in errors
    assert "observations" in errors and "mean_price" in errors
    assert payload["previous_requirement"]["requested_outputs"][0]["source_node"] == raw["requirements"][0]["requirement_id"]
