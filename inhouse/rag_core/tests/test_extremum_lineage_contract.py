"""Oracle equivalence must follow algebra and numeric/date checks, not labels."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements
from inhouse.rag_core.tests.qa500_actual_execution import run_program
from inhouse.rag_core.tests.qa500_linkage_eval import validate
from inhouse.rag_core.tests import qa500_backend as backend


def extrema_plan(group="date", high="max", low="min"):
    return {"requirements": [
        {"requirement_id": ident, "metric": "price", "entity": {"value": "아연"},
         "time_range": {"kind": "calendar_year", "value": 2024}, "dimension": group,
         "aggregation": agg, "output_field": ident,
         "selection": {"mode": selection, "field": ident}}
        for ident, agg, selection in [("opaque_peak", high, "argmax"), ("opaque_trough", low, "argmin")]],
        "relationships": [{"kind": "compare", "relationship_id": "spread", "operation": "difference",
            "inputs": ["opaque_peak", "opaque_trough"], "fields": ["opaque_peak", "opaque_trough"]}],
        "requested_outputs": [
            {"name": "high", "source_node": "opaque_peak", "fields": ["date", "opaque_peak"]},
            {"name": "low", "source_node": "opaque_trough", "fields": ["date", "opaque_trough"]},
            {"name": "spread", "source_node": "spread", "fields": ["difference"]}]}


def evaluate(raw, *, add_unequal_observation=True):
    typed = SemanticRequirementPlanV2.model_validate(raw)
    logical = logical_program_from_requirements(typed)
    db = backend.fixture()
    try:
        # Two unequal observations on the same date disprove max(mean) and
        # other reductions as replacements for original-row extrema.
        if add_unequal_observation:
            db.execute("INSERT INTO observations(domain,mineral,year,date,month,value,high_price,low_price,unit) VALUES('price','아연',2024,'2024-02-05','02',1,1,1,'USD/t')")
        _, program, results = asyncio.run(run_program(logical, db))
        trace = SimpleNamespace(failure_class=None, semantic_plan=typed.model_dump(mode="json"))
        case = dict(family="extrema", mineral="아연", year=2024, month=None, measure="value")
        return validate(case, trace, program, results, db)
    finally:
        db.close()


def test_date_preserving_extremum_reduction_is_equivalent_to_original_rows():
    assert evaluate(extrema_plan()) == ("PASS", [])


@pytest.mark.parametrize("high,low", [("mean", "mean"), ("sum", "sum"), ("min", "max")])
def test_other_reductions_do_not_inherit_original_row_extremum_role(high, low):
    assert evaluate(extrema_plan(high=high, low=low))[0] != "PASS"


def test_missing_date_projection_stays_failure():
    raw = extrema_plan()
    raw["requested_outputs"] = raw["requested_outputs"][-1:]
    assert evaluate(raw)[0] == "OUTPUT_CONTRACT_FAIL"


def test_non_date_group_does_not_magically_recover_date():
    raw = extrema_plan(group="month")
    with pytest.raises(ValueError, match="date"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))


@pytest.mark.parametrize("high,low", [("mean", "mean"), ("min", "max")])
def test_value_alias_and_numeric_coincidence_cannot_hide_wrong_reduction(high, low):
    raw = extrema_plan(high=high, low=low)
    for req in raw["requirements"]:
        req["output_field"] = "value"
        req["selection"]["field"] = "value"
    raw["relationships"][0]["fields"] = ["value", "value"]
    for out in raw["requested_outputs"][:2]:
        out["fields"] = ["date", "value"]
    # One value per date makes even the wrong reduction numerically identical.
    # A display/output name must not reset semantic lineage to a raw measure.
    assert evaluate(raw, add_unequal_observation=False)[0] != "PASS"
