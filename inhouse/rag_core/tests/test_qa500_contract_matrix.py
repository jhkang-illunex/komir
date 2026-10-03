"""Gold contracts are test oracles, never repairs of captured model plans."""
from inhouse.rag_core.tests.registered_step_helpers import execute_registered
import asyncio
from copy import deepcopy

import pytest

from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram
from inhouse.rag_core.ragkit.semantic_v2 import (
    SemanticRequirementPlanV2, logical_program_from_requirements, LegacyActionLowerer, TimeRange,
)
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus
from inhouse.rag_core.tests import qa500_backend as backend
from inhouse.rag_core.tests.qa500_actual_execution import run_program, relation_arguments


def requirement_plan(kind="join", **relation):
    return SemanticRequirementPlanV2.model_validate({
        "requirements": [
            {"requirement_id": ident, "metric": "price", "entity": {"value": mineral},
             "time_range": {"kind": "calendar_year", "value": 2025},
             "dimension": "month", "aggregation": "mean"}
            for ident, mineral in (("left", "니켈"), ("right", "구리"))],
        "relationships": [{"kind": kind, "inputs": ["left", "right"], **relation}],
    })


@pytest.fixture(scope="module")
def db():
    conn = backend.fixture()
    yield conn
    conn.close()


@pytest.mark.parametrize("kind,fields", [("join", ["value"]), ("compare", ["value"]), ("compare", [])])
def test_complete_requirement_through_lowering_and_runtime_matches_sql(db, kind, fields):
    plan = requirement_plan(kind, join_key="month", fields=fields)
    before = plan.model_dump()
    logical = logical_program_from_requirements(plan)
    trace, program, results = asyncio.run(run_program(logical, db))
    result = results[program.roots[0]]
    assert result.status == ResultStatus.SUCCESS
    assert result.evidence and result.provenance
    assert [c["action_id"] for c in trace["lowered"]] == ["price.series", "price.series"]
    expected = backend.query(db, """
        SELECT month, AVG(CASE WHEN mineral='니켈' THEN value END) AS l,
                      AVG(CASE WHEN mineral='구리' THEN value END) AS r
        FROM observations WHERE domain='price' AND year=2025
        AND mineral IN ('니켈','구리') GROUP BY month ORDER BY month
    """)
    left, right = ("left.value", "right.value") if kind == "join" else ("left_value", "right_value")
    assert [(r["month"], r[left], r[right]) for r in result.value] == [
        (r["month"], r["l"], r["r"]) for r in expected]
    assert plan.model_dump() == before


@pytest.mark.parametrize("kind,kwargs,error", [
    ("join", {}, "requires explicit join keys"),
    ("compare", {"join_key": "month"}, "requires comparison field"),
    ("join", {"inputs": ["left"], "join_key": "month"}, "requires exactly two"),
    ("compare", {"inputs": ["left"], "fields": ["value"]}, "requires exactly two"),
])
def test_missing_contract_fails_without_adapter_invention(db, kind, kwargs, error):
    plan = requirement_plan(kind)
    if error == "requires comparison field":
        # Multiple raw measures remain ambiguous. Single-measure aggregates
        # now have compiler-owned binding (covered by the SQL test above).
        for req in plan.requirements:
            req.aggregation = None
    relation = plan.relationships[0].model_copy(update=kwargs)
    plan.relationships[0] = relation
    before = plan.model_dump()
    trace, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    assert error in str(trace["adapter_gaps"])
    assert results[f"relation_{kind}_0"].status != ResultStatus.SUCCESS
    assert any(results[root].status != ResultStatus.SUCCESS for root in program.roots)
    assert plan.model_dump() == before


@pytest.mark.parametrize("arguments", [
    {"fields": ["value"], "field": "high_price"},
    {"fields": ["high_price", "low_price"], "right_field": "value"},
])
def test_conflicting_compare_fields_are_not_silently_repaired(arguments):
    before = deepcopy(arguments)
    with pytest.raises(ValueError, match="conflicting_explicit_compare_fields"):
        relation_arguments(Operator.COMPARE, arguments)
    assert arguments == before


@pytest.mark.parametrize("fields", [["value", "missing_count"], ["missing_count", "value"]])
def test_projection_validates_every_requested_field(fields):
    source = RequirementNode("rows", Operator.ENTITY, args={"values": [{"value": 1}]})
    output = RequirementNode("out", Operator.PROJECT, (InputRef("rows"),), args={"fields": fields})
    with pytest.raises(ValueError, match="missing_count"):
        SemanticProgram((source, output), ("out",))


def test_projection_complete_alias_and_empty_data_contract():
    source = RequirementNode("rows", Operator.ENTITY, args={"values": [{"value": 1, "count": None}]})
    output = RequirementNode("out", Operator.PROJECT, (InputRef("rows"),),
                             args={"fields": ["value", "count"], "aliases": {"value": "mean"}})
    SemanticProgram((source, output), ("out",))


@pytest.mark.parametrize("metric,extra,action,slot,expected", [
    ("document_evidence", {"document_requirement": {"topic": "monthly"}}, "document.retrieve", "topic", "monthly"),
    ("indicator", {"indicator": "composite_index"}, "indicator.series", "indicator", "composite_index"),
    ("production", {}, "resource.rank", "metric", "production"),
    ("reserves", {}, "resource.rank", "metric", "reserves"),
])
def test_complete_domain_contract_is_preserved_to_physical_slot(metric, extra, action, slot, expected):
    plan = SemanticRequirementPlanV2.model_validate({"requirements": [{
        "requirement_id": "r", "metric": metric, "entity": {"value": "구리"},
        "time_range": {"kind": "calendar_year", "value": 2024}, **extra}]})
    calls = LegacyActionLowerer().lower(logical_program_from_requirements(plan))
    assert calls[0].action_id == action
    assert getattr(calls[0].slots, slot) == expected
    assert calls[0].slots.period.calendar_year == 2024


@pytest.mark.parametrize("metric,extra,error", [
    ("document_evidence", {}, "document_scope_unresolved"),
    ("indicator", {"indicator": "not_registered"}, "indicator"),
    ("price", {"time_range": {"kind": "range", "start": "article_period_start", "end": "2025-12-31"}}, "Invalid isoformat"),
])
def test_lowering_missing_domain_contract_never_uses_unrelated_default(metric, extra, error):
    plan = SemanticRequirementPlanV2.model_validate({"requirements": [{
        "requirement_id": "r", "metric": metric, "entity": {"value": "구리"}, **extra}]})
    with pytest.raises(ValueError, match=error):
        LegacyActionLowerer().lower(logical_program_from_requirements(plan))


@pytest.mark.parametrize("value,error", [
    ({"kind": "trailing_months", "value": 0}, "greater than or equal"),
    ({"kind": "custom", "start": "2025-12-31", "end": "2025-01-01"}, "reversed time range"),
    ({"kind": "range", "start": "2025-12-31", "end": "2025-01-01"}, "reversed time range"),
])
def test_invalid_or_conflicting_period_does_not_become_latest(value, error):
    with pytest.raises(ValueError, match=error):
        TimeRange.model_validate(value).to_period()


def test_explicit_period_and_entity_survive_actual_fixture_call(db):
    plan = SemanticRequirementPlanV2.model_validate({"requirements": [{
        "requirement_id": "r", "metric": "price", "entity": {"value": "구리"},
        "time_range": {"kind": "range", "start": "2024-03-01", "end": "2024-05-31"}}]})
    trace, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    result = results[program.roots[0]]
    assert result.status == ResultStatus.SUCCESS
    assert trace["fixture_calls"][0]["slots"]["mineral"] == "구리"
    assert [r["date"] for r in result.value] == [r["date"] for r in backend.query(db,
        "SELECT date FROM observations WHERE domain='price' AND mineral='구리' AND date BETWEEN ? AND ? ORDER BY date",
        ("2024-03-01", "2024-05-31"))]


def test_missing_static_entity_is_not_filled_from_history_or_default(db):
    plan = SemanticRequirementPlanV2.model_validate({"requirements": [{
        "requirement_id": "r", "metric": "price", "time_range": {"kind": "calendar_year", "value": 2025}}]})
    trace, _, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    assert results["r"].failure_reason == "ACTUAL_PLAN_CONTRACT_GAP: MISSING_REQUIRED_SINGLE_MINERAL"
    assert not any(c["reader_executed"] for c in trace["fixture_calls"])


def test_inventory_covers_every_original_case_without_promoting_question_pass():
    from inhouse.rag_core.tests.qa500_contract_inventory import inventory
    report = inventory()
    assert report["total"] == 245
    assert report["unclassified_qa"] == 0
    assert "OTHER_CONTRACT" not in report["qa_incidence_overlapping"]
    assert all(r["diagnostic_status"] == "CLASSIFIED_NOT_REPAIRED" for r in report["records"])


@pytest.mark.parametrize("mineral,year", [("니켈", 2025), ("구리", 2024), ("리튬", 2023), ("코발트", 2022)])
def test_monthly_mean_and_observation_count_gold_contract(db, mineral, year):
    # Independent Gold: not inserted into any captured model requirement.
    plan = requirement_plan("join", join_key="month")
    for index, req in enumerate(plan.requirements):
        req.entity.value = mineral
        req.time_range.value = year
        req.aggregation = "mean" if index == 0 else "count"
    trace, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    root = results[program.roots[0]]
    expected = backend.query(db, """SELECT month,AVG(value) AS mean,COUNT(value) AS count
        FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month ORDER BY month""", (mineral, year))
    assert root.status == ResultStatus.SUCCESS
    assert [(r["month"], r["left.value"], r["right.value"]) for r in root.value] == [
        (r["month"], r["mean"], r["count"]) for r in expected]
    assert all(call["slots"]["mineral"] == mineral for call in trace["fixture_calls"])
    assert all(call["slots"]["period"]["calendar_year"] == year for call in trace["fixture_calls"])


def test_captured_missing_join_key_is_not_repaired_with_gold(db):
    from inhouse.rag_core.tests.qa500_contract_inventory import ARTIFACTS, read
    traces = read(ARTIFACTS / "qa500-actual-execution-v4-final.json.gz")
    saved = next(r for r in traces["records"] if r["id"] == "EXT500-009")["turns"][0]
    plan = SemanticRequirementPlanV2.model_validate(saved["semantic_plan"])
    assert plan.relationships[0].fields == ["month"]
    assert plan.relationships[0].join_key is None
    from inhouse.rag_core.ragkit.semantic_v2 import requirement_contract_issues
    assert any("join_key required" in issue for issue in requirement_contract_issues(plan))
    with pytest.raises(ValueError, match="requested_output_field_unresolved"):
        logical_program_from_requirements(plan)
    assert plan.relationships[0].join_key is None


@pytest.mark.parametrize("kind", ["join", "compare"])
def test_unsupported_relationship_predicate_is_not_silently_discarded(kind):
    plan = requirement_plan(kind, join_key="month", fields=["value"],
                            predicate={"abs_diff_threshold": 3})
    with pytest.raises(ValueError, match="unsupported_relationship_predicate"):
        logical_program_from_requirements(plan)


def test_arithmetic_relation_contract_is_explicit_not_a_fixture_data_gap():
    # The former gap is now a typed relation, not a fixture-provided answer.
    from inhouse.rag_core.ragkit.semantic_v2 import RelationshipSpec
    relation = RelationshipSpec(kind="compare", inputs=["max", "min"], fields=["value"], operation="difference")
    assert relation.operation == "difference"
    with pytest.raises(ValueError, match="relationship operation requires compare"):
        RelationshipSpec(kind="join", inputs=["max", "min"], operation="difference")


def test_projection_keeps_typed_result_unit_metadata(db):
    plan = SemanticRequirementPlanV2.model_validate({"requirements": [{
        "requirement_id": "r", "metric": "price", "entity": {"value": "니켈"},
        "time_range": {"kind": "calendar_year", "value": 2025}, "aggregation": "mean"}],
        "requested_outputs": [{"name": "mean", "fields": ["value", "unit"]}]})
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    result = results[program.roots[0]]
    assert result.status == ResultStatus.SUCCESS
    expected = db.execute("SELECT AVG(value) FROM observations WHERE domain='price' AND mineral='니켈' AND year=2025").fetchone()[0]
    assert result.value == [{"value": expected, "unit": "USD/t"}]


def test_projection_does_not_invent_absent_unit_metadata():
    from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
    from inhouse.rag_core.ragkit.pipe_runtime import TypedResult
    from inhouse.rag_core.ragkit.semantic_ir import ValueType
    factory = LiveOperatorFactory(message="", session_id="contract-test", profile="public", llm=None, history=[])
    node = RequirementNode("out", Operator.PROJECT, args={"fields": ["value", "unit"]})
    result = execute_registered(factory, node, {"source": TypedResult.success(ValueType.FACT_SET, [{"value": 1}])})
    assert result.status == ResultStatus.ABSTAINED
    assert result.failure_reason == "projection_field_unavailable:unit"
