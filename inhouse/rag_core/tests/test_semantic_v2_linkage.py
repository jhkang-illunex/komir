"""Contract-first tests; Gold is never fed to the semantic model."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from inhouse.rag_core.ragkit.semantic_v2 import (
    SemanticRequirementPlanV2, logical_program_from_requirements, parse_v2_shadow,
    LegacyActionLowerer, requirement_contract_issues,
)
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus
from inhouse.rag_core.tests.qa500_actual_execution import run_program
from inhouse.rag_core.tests import qa500_backend as backend


def monthly_plan(mineral="구리", year=2024):
    return {"requirements": [
        {"requirement_id": name, "metric": "price", "entity": {"value": mineral},
         "time_range": {"kind": "calendar_year", "value": year}, "dimension": "month",
         "aggregation": operation, "output_field": name}
        for name, operation in (("mean_price", "mean"), ("observations", "count"))],
        "relationships": [{"relationship_id": "summary", "kind": "join",
            "inputs": ["mean_price", "observations"], "join_key": "month"}],
        "requested_outputs": [{"name": "monthly", "source_node": "summary",
            "fields": ["month", "left.mean_price", "right.observations"],
            "aliases": {"left.mean_price": "average", "right.observations": "count"}}]}


@pytest.fixture(scope="module")
def db():
    conn = backend.fixture()
    yield conn
    conn.close()


@pytest.mark.parametrize("mineral,year", [("구리", 2024), ("아연", 2022), ("흑연", 2021)])
def test_grouped_outputs_have_explicit_lineage_and_match_sql(db, mineral, year):
    plan = SemanticRequirementPlanV2.model_validate(monthly_plan(mineral, year))
    trace, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    actual = results[program.roots[0]]
    assert actual.status == ResultStatus.SUCCESS
    expected = backend.query(db, "SELECT month,AVG(value) average,COUNT(value) count FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month ORDER BY month", (mineral, year))
    assert actual.value == expected
    assert actual.evidence and actual.provenance
    assert all(call["slots"]["mineral"] == mineral for call in trace["fixture_calls"])


@pytest.mark.parametrize("operation", ["difference", "ratio", "percent_change"])
def test_binary_arithmetic_is_not_lowered_as_unary_calculation(db, operation):
    plan = {"requirements": [
        {"requirement_id": ident, "metric": "price", "entity": {"value": "아연"},
         "time_range": {"kind": "calendar_year", "value": 2024}, "aggregation": aggregate}
        for ident, aggregate in (("a", "max"), ("b", "min"))],
        "relationships": [{"relationship_id": "comparison", "kind": "compare", "inputs": ["a", "b"],
            "fields": ["value"], "operation": operation}],
        "requested_outputs": [{"name": "calculated", "source_node": "comparison", "fields": [operation]}]}
    logical = logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(plan))
    assert not any(n.op.value == "Calculate" for n in logical.nodes)
    _, program, results = asyncio.run(run_program(logical, db))
    actual = results[program.roots[0]]
    high, low = db.execute("SELECT MAX(value),MIN(value) FROM observations WHERE domain='price' AND mineral='아연' AND year=2024").fetchone()
    expected = {"difference": high-low, "ratio": high/low, "percent_change": (high-low)/abs(low)*100}[operation]
    assert actual.status == ResultStatus.SUCCESS
    assert actual.value == [{operation: expected}]


def test_unknown_output_source_is_not_silently_ignored():
    plan = monthly_plan()
    plan["requested_outputs"][0]["source_node"] = "missing"
    with pytest.raises(ValueError, match="requested_output_source"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(plan))


def test_contract_reparse_is_bounded_and_never_inserts_gold_fields():
    incomplete = monthly_plan()
    incomplete["relationships"][0].pop("join_key")
    calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output=SemanticRequirementPlanV2.model_validate(incomplete))
    trace = parse_v2_shadow("어떤 월별 비교 요청", SimpleNamespace(invoke=invoke))
    assert len(calls) == 2
    assert trace.failure_class == "LOGICAL_PLAN_INCOMPLETE"
    assert "join_key" in trace.failure_reason
    assert "contract_errors" in calls[1]["payload"]
    assert "gold" not in str(calls).lower()
    assert trace.semantic_plan["relationships"][0]["join_key"] is None


def test_reparse_can_accept_model_supplied_contract_without_changing_question():
    incomplete = monthly_plan()
    incomplete["relationships"][0].pop("join_key")
    plans = iter([incomplete, monthly_plan()]); calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output=SemanticRequirementPlanV2.model_validate(next(plans)))
    trace = parse_v2_shadow("두 통계 결과를 월 기준으로 연결", SimpleNamespace(invoke=invoke))
    assert trace.failure_class is None
    assert len(calls) == 2
    assert calls[0]["payload"]["question"] == calls[1]["payload"]["question"]
    assert len(trace.attempts) == 2


def test_unique_output_column_resolution_never_guesses_ambiguous_columns(db):
    plan = monthly_plan()
    plan["requested_outputs"][0].update(fields=["month", "mean_price", "observations"], aliases={})
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(plan)), db))
    assert results[program.roots[0]].status == ResultStatus.SUCCESS
    assert set(results[program.roots[0]].value[0]) == {"month", "mean_price", "observations"}
    for req in plan["requirements"]:
        req["output_field"] = "amount"
    plan["requested_outputs"][0]["fields"] = ["month", "amount"]
    with pytest.raises(ValueError, match="requested_output_field_unresolved"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(plan))


def test_missing_compare_alignment_is_reported_not_inferred():
    plan = monthly_plan()
    plan["relationships"][0].update(kind="compare", join_key=None, fields=["mean_price", "observations"])
    typed = SemanticRequirementPlanV2.model_validate(plan)
    assert any("explicit join_key alignment" in error for error in requirement_contract_issues(typed))
    assert typed.relationships[0].join_key is None


def test_explicit_output_sources_remain_distinct(db):
    plan = monthly_plan()
    plan["relationships"] = []
    plan["requested_outputs"] = [
        {"name": "mean", "source_node": "mean_price", "fields": ["month", "mean_price"]},
        {"name": "count", "source_node": "observations", "fields": ["month", "observations"]}]
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(plan)), db))
    assert len(program.roots) == 2
    assert all(results[root].status == ResultStatus.SUCCESS for root in program.roots)
    assert [{*results[root].value[0]} for root in program.roots] == [{"month", "mean_price"}, {"month", "observations"}]


@pytest.mark.parametrize("context", [None, {"previous_requirements": [{"metric": "price"}], "result_snapshots": []}])
def test_derived_entity_keeps_input_reference_but_never_emits_unbound_action(context):
    raw = {"requirements": [
        {"requirement_id": "doc", "metric": "document_evidence", "document_requirement": {"topic": "monthly"}},
        {"requirement_id": "prices", "metric": "price", "entity": {"source_node": "doc", "field": "mineral_list"}}]}
    plan = SemanticRequirementPlanV2.model_validate(raw)
    logical = logical_program_from_requirements(plan)
    ref = next(n for n in logical.nodes if n.node_id == "prices").inputs[0]
    assert (ref.node_id, ref.selector, ref.value) == ("doc", "field", "mineral_list")
    with pytest.raises(ValueError, match="derived_entity_materialization_required"):
        LegacyActionLowerer().lower(logical)
    trace = parse_v2_shadow("문서에서 추출한 대상", SimpleNamespace(invoke=lambda **_: SimpleNamespace(output=plan)), semantic_context=context)
    assert trace.failure_class == "LOWERING_FAILURE"
    assert trace.failure_reason == "derived_entity_materialization_required"
    assert not trace.lowering


def test_static_and_derived_entity_conflict_is_not_silently_resolved():
    plan = monthly_plan()
    plan["requirements"][1]["entity"]["source_node"] = "mean_price"
    with pytest.raises(ValueError, match="conflicting_static_and_derived_entity"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(plan))


@pytest.mark.parametrize("metric,domain", [("production", "production"), ("import_value", "trade")])
def test_named_aggregate_join_generalizes_beyond_price(db, metric, domain):
    raw = monthly_plan("텅스텐", 2023)
    for req in raw["requirements"]:
        req.update(metric=metric, dimension="country")
    raw["relationships"][0]["join_key"] = "country"
    raw["requested_outputs"][0].update(fields=["country", "mean_price", "observations"], aliases={})
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw)), db))
    actual = results[program.roots[0]]
    expected = backend.query(db, "SELECT country, AVG(value) mean_price, COUNT(value) observations FROM observations WHERE domain=? AND mineral='텅스텐' AND year=2023 GROUP BY country ORDER BY country", (domain,))
    assert actual.status == ResultStatus.SUCCESS
    assert sorted(actual.value, key=lambda r: r["country"]) == expected


def test_semantic_evaluator_understands_qualified_dimension_and_rejects_numeric_mutation(db):
    from dataclasses import replace
    from inhouse.rag_core.tests.qa500_linkage_eval import validate
    raw = monthly_plan("아연", 2022)
    raw["requested_outputs"][0].update(fields=["left.month", "mean_price", "observations"], aliases={"left.month": "월"})
    plan = SemanticRequirementPlanV2.model_validate(raw)
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    trace = SimpleNamespace(failure_class=None, semantic_plan=plan.model_dump(mode="json"))
    case = dict(family="monthly", mineral="아연", year=2022)
    assert validate(case, trace, program, results, db)[0] == "PASS"
    root = program.roots[0]
    damaged = deepcopy(results[root].value)
    damaged[0]["observations"] = None
    assert validate(case, trace, program, {**results, root: replace(results[root], value=damaged)}, db)[0] == "RESULT_MISMATCH"


def test_alias_collision_never_overwrites_two_outputs(db):
    raw = monthly_plan()
    raw["requested_outputs"][0]["aliases"] = {"left.mean_price": "same", "right.observations": "same"}
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw)), db))
    assert results[program.roots[0]].status == ResultStatus.ABSTAINED
    assert results[program.roots[0]].failure_reason == "projection_output_collision"


def test_qualified_comparison_operands_preserve_roles(db):
    raw = monthly_plan()
    raw["relationships"][0].update(kind="compare", fields=["left.mean_price", "right.observations"], operation="side_by_side")
    logical = logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))
    assert next(n for n in logical.nodes if n.node_id == "summary").arguments["fields"] == ["mean_price", "observations"]
    _, program, results = asyncio.run(run_program(logical, db))
    assert results[program.roots[0]].status == ResultStatus.SUCCESS
    raw["relationships"][0]["fields"] = ["right.mean_price", "left.observations"]
    with pytest.raises(ValueError, match="comparison_field_operand_conflict"):
        logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw))


def test_join_projection_materializes_unit_from_metadata(db):
    raw = monthly_plan()
    raw["requirements"][1]["aggregation"] = "mean"
    raw["requested_outputs"][0].update(fields=["month", "unit"], aliases={})
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(SemanticRequirementPlanV2.model_validate(raw)), db))
    assert results[program.roots[0]].status == ResultStatus.SUCCESS
    assert all(r["unit"] == "USD/t" for r in results[program.roots[0]].value)


def test_extrema_oracle_rejects_swapped_dates_unit_and_missing_source(db):
    from dataclasses import replace
    from inhouse.rag_core.tests.qa500_linkage_eval import validate
    raw = {"requirements": [
        {"requirement_id": ident, "metric": "price", "entity": {"value": "구리"},
         "time_range": {"kind": "calendar_year", "value": 2024}, "selection": {"mode": mode, "field": "value"}}
        for ident, mode in (("peak", "argmax"), ("bottom", "argmin"))],
        "relationships": [{"kind": "compare", "relationship_id": "diff", "inputs": ["peak", "bottom"], "fields": ["value"], "operation": "difference"}],
        "requested_outputs": [{"name": "range", "source_node": "diff", "fields": ["difference", "left.date", "right.date", "unit"], "aliases": {"unit": "단위"}}]}
    plan = SemanticRequirementPlanV2.model_validate(raw)
    _, program, results = asyncio.run(run_program(logical_program_from_requirements(plan), db))
    case = dict(family="extrema", mineral="구리", year=2024, month=None, measure="value")
    trace = SimpleNamespace(failure_class=None, semantic_plan=plan.model_dump(mode="json"))
    root = program.roots[0]; result = results[root]
    assert validate(case, trace, program, results, db)[0] == "PASS"
    swapped = deepcopy(result.value)
    swapped[0]["left.date"], swapped[0]["right.date"] = swapped[0]["right.date"], swapped[0]["left.date"]
    assert swapped != result.value
    bad_unit = [{**row, "단위": "kg"} for row in result.value]
    for mutant in (replace(result, value=swapped), replace(result, unit="kg"), replace(result, source=()), replace(result, value=bad_unit)):
        assert validate(case, trace, program, {**results, root: mutant}, db)[0] != "PASS"
