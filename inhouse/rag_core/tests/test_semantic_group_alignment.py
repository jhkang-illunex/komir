"""Comparison of explicitly grouped outputs binds their unique identity key."""
import asyncio
from copy import deepcopy

import pytest

from inhouse.rag_core.ragkit.semantic_v2 import (
    SemanticRequirementPlanV2, logical_program_from_requirements, requirement_contract_issues,
)
from inhouse.rag_core.tests.qa500_actual_execution import run_program
from inhouse.rag_core.tests.test_semantic_v2_linkage import monthly_plan
from inhouse.rag_core.tests import qa500_backend as backend


def grouped():
    raw = monthly_plan()
    raw["relationships"][0].update(kind="compare", operation="side_by_side", fields=[])
    raw["relationships"][0].pop("join_key")
    return raw


@pytest.mark.parametrize("dimension,metric,domain", [("month", "price", "price"), ("country", "production", "production"), ("country", "import_value", "trade")])
def test_shared_group_key_matches_explicit_alignment_and_sql(dimension, metric, domain):
    raw = grouped()
    for req in raw["requirements"]:
        req.update(dimension=dimension, metric=metric)
    raw["requested_outputs"][0]["fields"][0] = dimension
    typed = SemanticRequirementPlanV2.model_validate(raw)
    before = typed.model_dump()
    assert requirement_contract_issues(typed) == ()
    logical = logical_program_from_requirements(typed)
    explicit = deepcopy(raw)
    explicit["relationships"][0]["join_key"] = dimension
    assert logical == logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(explicit))
    db = backend.fixture()
    try:
        _, program, results = asyncio.run(run_program(logical, db))
        result = results[program.roots[0]]
        expected = backend.query(db, f"SELECT {dimension},AVG(value) average,COUNT(value) count FROM observations WHERE domain=? AND mineral=? AND year=? GROUP BY {dimension} ORDER BY {dimension}", (domain, "구리", 2024))
        assert result.status.value == "success"
        assert sorted(result.value, key=lambda r:r[dimension]) == expected
        assert result.evidence and result.provenance
        assert typed.model_dump() == before
    finally:
        db.close()


@pytest.mark.parametrize("change", ["different_dimension", "raw_series", "selection", "calculation", "limit", "no_operation", "different_period", "different_entity", "different_metric", "different_scope", "different_filter", "arithmetic", "empty_key", "empty_key_list"])
def test_ambiguous_alignment_is_not_inferred(change):
    raw = grouped()
    if change == "different_dimension": raw["requirements"][1]["dimension"] = "country"
    if change == "raw_series": raw["requirements"][0]["aggregation"] = None
    if change == "selection": raw["requirements"][0]["selection"] = {"mode":"argmax", "field":"mean_price"}
    if change == "calculation": raw["requirements"][0]["operation"] = "share"
    if change == "limit": raw["requirements"][0]["limit"] = 3
    if change == "no_operation": raw["relationships"][0].pop("operation")
    if change == "different_period": raw["requirements"][1]["time_range"]["value"] = 2023
    if change == "different_entity": raw["requirements"][1]["entity"]["value"] = "아연"
    if change == "different_metric": raw["requirements"][1]["metric"] = "production"
    if change == "different_scope": raw["requirements"][1]["scope"] = "separate population"
    if change == "different_filter": raw["requirements"][1]["constraints"] = [{"field":"country", "op":"eq", "value":"A"}]
    if change == "arithmetic": raw["relationships"][0]["operation"] = "difference"
    if change == "empty_key": raw["relationships"][0]["join_key"] = ""
    if change == "empty_key_list": raw["relationships"][0]["join_key"] = []
    assert any("explicit join_key" in s for s in requirement_contract_issues(SemanticRequirementPlanV2.model_validate(raw)))


def test_explicit_other_key_is_not_replaced_with_dimension():
    raw = grouped()
    raw["relationships"][0]["join_key"] = "date"
    raw["requested_outputs"] = []
    program = logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    assert next(n for n in program.nodes if n.op.value == "Compare").arguments["join_key"] == "date"
