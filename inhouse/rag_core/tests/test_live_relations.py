from inhouse.rag_core.tests.registered_step_helpers import execute_registered
from dataclasses import replace
from types import SimpleNamespace

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory, live_run_events
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


def source(rows, name, unit="USD/t", **kwargs):
    return TypedResult.success(ValueType.FACT_SET, rows, unit=unit, source=(name,),
        evidence=(Evidence("structured", name, "fixture", "deterministic rows"),),
        provenance=(f"fixture:{name}",), **kwargs)


def run(operator, left, right, **args):
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    return execute_registered(factory, RequirementNode("relation", operator, args=args), {"input_0": left, "input_1": right})


def test_join_matches_keys_not_row_position_and_preserves_both_sources():
    left = source([{"country": "A", "value": 10}, {"country": "B", "value": 20}], "left")
    right = source([{"country": "B", "value": 3}, {"country": "A", "value": 4}], "right", unit="t")
    result = run(Operator.JOIN, left, right, join_key="country")
    assert result.status == ResultStatus.SUCCESS
    assert [(r["country"], r["left.value"], r["right.value"]) for r in result.value] == [("A", 10, 4), ("B", 20, 3)]
    assert result.source == ("left", "right")
    assert result.evidence == left.evidence + right.evidence
    assert result.provenance == left.provenance + right.provenance
    assert result.unit is None
    assert result.value[0]["left_unit"] == "USD/t"
    assert result.value[0]["right_unit"] == "t"


@pytest.mark.parametrize("how,keys", [("inner", ["B"]), ("left", ["A", "B"]), ("full", ["A", "B", "C"])])
def test_join_modes(how, keys):
    result = run(Operator.JOIN, source([{"key": "A"}, {"key": "B"}], "l"),
                 source([{"key": "B"}, {"key": "C"}], "r"), join_key="key", how=how)
    assert result.status == ResultStatus.SUCCESS
    assert [row["key"] for row in result.value] == keys


@pytest.mark.parametrize("operation,expected", [("difference", 15), ("ratio", 4), ("percent_change", 300)])
def test_scalar_comparison(operation, expected):
    result = run(Operator.COMPARE, source([{"value": 20}], "l"), source([{"value": 5}], "r"),
                 field="value", operation=operation)
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0][operation] == expected
    assert result.value[0]["left_value"] == 20
    assert result.value[0]["right_value"] == 5


def test_compare_temporal_alignment_and_missing_counterpart():
    left = source([{"date": "2024-01", "price": 10}, {"date": "2024-02", "price": 20}], "l")
    right = source([{"date": "2024-02", "price": 5}], "r")
    result = run(Operator.COMPARE, left, right, join_key="date", field="price", operation="difference")
    assert result.status == ResultStatus.PARTIAL
    assert result.value[0]["status"] == "DATA_UNAVAILABLE"
    assert result.value[0]["difference"] is None
    assert result.value[1]["difference"] == 15
    events = live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=result)))
    assert sum(e.type == "done" for e in events) == 1
    assert any(e.type == "table" and len(e.data["rows"]) == 2 for e in events)


def test_temporal_continuation_concatenates_observed_then_forecast():
    observed = source(
        [{"date": "2026-08-01", "value": 100}, {"date": "2026-09-01", "value": 110}],
        "observed", unit="USD/t", entity=("니켈",), metric="price",
    )
    forecast = source(
        [{"forecast_date": "2026-09-01", "predicted_price": 111},
         {"forecast_date": "2026-10-01", "predicted_price": 112}],
        "forecast", unit="USD/t", entity=("니켈",), metric="price_forecast",
    )
    result = run(Operator.COMPARE, observed, forecast,
                 operation="temporal_continuation", left_field="value",
                 right_field="predicted_price")
    assert result.status == ResultStatus.SUCCESS
    assert [(row["date"], row["value"], row["observation_type"]) for row in result.value] == [
        ("2026-08-01", 100, "observed"),
        ("2026-09-01", 110, "observed"),
        ("2026-10-01", 112, "forecast"),
    ]
    assert result.result_type == ValueType.TIME_SERIES
    assert result.source == ("observed", "forecast")


@pytest.mark.parametrize("rows,reason", [
    ([{"key": "A"}, {"key": "A"}], "ambiguous_join_cardinality"),
    ([{"key": None}], "null_join_key"),
    ([{"other": "A"}], "missing_join_key"),
])
def test_invalid_keys_abstain(rows, reason):
    result = run(Operator.JOIN, source(rows, "l"), source([{"key": "A"}], "r"), join_key="key")
    assert result.status == ResultStatus.ABSTAINED
    assert result.failure_reason == reason


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True])
def test_invalid_numeric_operand_not_zero(value):
    result = run(Operator.COMPARE, source([{"value": value}], "l"), source([{"value": 1}], "r"), field="value", operation="difference")
    assert result.status != ResultStatus.SUCCESS


def test_zero_denominator_and_unit_mismatch_are_not_values():
    left = source([{"value": 10}], "l")
    right = source([{"value": 0}], "r")
    result = run(Operator.COMPARE, left, right, field="value", operation="ratio")
    assert result.status != ResultStatus.SUCCESS
    assert result.value[0]["reason"] == "zero_denominator"
    mismatch = run(Operator.COMPARE, left, replace(right, unit="kg"), field="value", operation="difference")
    assert mismatch.failure_reason == "unit_mismatch"


def test_partial_and_rejected_inputs_cannot_be_laundered_by_join():
    left = source([{"country": "A"}], "l")
    for status in (ResultStatus.PARTIAL, ResultStatus.FAILED, ResultStatus.ABSTAINED):
        result = run(Operator.JOIN, replace(left, status=status), left, join_key="country")
        assert result.status != ResultStatus.SUCCESS


def test_no_implicit_row_zip_for_series_comparison():
    rows = [{"value": 1}, {"value": 2}]
    result = run(Operator.COMPARE, source(rows, "l"), source(rows, "r"), field="value", operation="difference")
    assert result.failure_reason == "comparison_alignment_required"


def partial_rows():
    return replace(source([
        {"date": "A", "value": 10, "status": "SUCCESS"},
        {"date": "B", "value": 999, "status": "DATA_UNAVAILABLE", "reason": "missing_operand"},
    ], "partial"), status=ResultStatus.PARTIAL)


@pytest.mark.parametrize("operator", [Operator.JOIN, Operator.COMPARE])
def test_partial_valid_rows_continue_but_failed_payload_is_not_reused(operator):
    result = run(operator, partial_rows(), source([
        {"date": "A", "value": 3}, {"date": "B", "value": 2}], "right"),
        join_key="date", field="value", operation="difference")
    assert result.status == ResultStatus.PARTIAL
    assert result.value[0]["status"] == "SUCCESS"
    assert result.value[1]["status"] == "DEPENDENCY_FAILED"
    assert "left.value" not in result.value[1]
    if operator == Operator.COMPARE:
        assert result.value[0]["difference"] == 7
        assert result.value[1]["difference"] is None
    assert "incomplete_population" in result.warnings


def test_partial_inner_join_and_projection_do_not_erase_population_gap():
    result = run(Operator.JOIN, partial_rows(), source([{"date": "A", "value": 3}], "right"), join_key="date")
    assert len(result.value) == 1
    assert result.status == ResultStatus.PARTIAL
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    projected = execute_registered(factory, RequirementNode("p", Operator.PROJECT, args={"fields": ["left.value"]}), {"input": result})
    assert projected.status == ResultStatus.PARTIAL
    for op in (Operator.AGGREGATE, Operator.RANK, Operator.TOP_K):
        blocked = execute_registered(factory, RequirementNode("a", op, args={"field": "left.value", "aggregation": "sum"}), {"input": projected})
        assert blocked.failure_reason == "incomplete_population"


def test_partial_without_validated_evidence_still_abstains():
    result = run(Operator.JOIN, replace(partial_rows(), sufficient=False), source([{"date": "A"}], "r"), join_key="date")
    assert result.status == ResultStatus.ABSTAINED
    assert result.evidence == ()


def test_all_failed_rows_never_become_successful_join():
    left = replace(partial_rows(), value=partial_rows().value[1:])
    result = run(Operator.JOIN, left, source([{"date": "B", "value": 2}], "r"), join_key="date")
    assert result.status == ResultStatus.EMPTY
    assert not result.sufficient


def test_partial_sse_reports_counts_and_preserves_failed_row():
    result = run(Operator.COMPARE, partial_rows(), source([
        {"date": "A", "value": 3}, {"date": "B", "value": 2}], "r"),
        join_key="date", field="value", operation="difference")
    events = live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=result)))
    text = "".join(e.data.get("delta", "") for e in events if e.type == "delta")
    assert "1개 처리 완료, 1개 처리 불가" in text
    assert "전체 모집단 결과는 아닙니다" in text
    assert "999" not in text
    assert sum(e.type == "done" for e in events) == 1
    assert any(e.type == "table" and len(e.data["rows"]) == 2 for e in events)


def test_partial_join_then_compare_keeps_dependency_failure():
    joined = run(Operator.JOIN, partial_rows(), source([
        {"date": "A", "value": 3}, {"date": "B", "value": 2}], "r"), join_key="date")
    compared = run(Operator.COMPARE, joined, source([
        {"date": "A", "value": 1}, {"date": "B", "value": 1}], "next"),
        join_key="date", left_field="left.value", right_field="value", operation="difference")
    assert compared.status == ResultStatus.PARTIAL
    assert compared.value[0]["difference"] == 9
    assert compared.value[1]["status"] == "DEPENDENCY_FAILED"
    assert compared.value[1]["difference"] is None


def test_side_by_side_keeps_different_units_without_arithmetic():
    result = run(Operator.COMPARE, source([{"value": 5}], "l", unit="t"),
                 source([{"value": 100}], "r", unit="USD"), fields=["value"], operation="side_by_side")
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["left_unit"] == "t"
    assert result.value[0]["right_unit"] == "USD"
    assert "difference" not in result.value[0]


def test_side_by_side_keeps_independent_rank_populations_without_row_zip():
    left = source([{"country": "A", "production": 10}, {"country": "B", "production": 8}], "production", unit="t")
    right = source([{"country": "B", "import_value": 5}, {"country": "C", "import_value": 3}], "imports", unit="USD")
    result = run(Operator.COMPARE, left, right, left_field="production", right_field="import_value",
                 operation="side_by_side")
    assert result.status == ResultStatus.SUCCESS
    assert [row["comparison_side"] for row in result.value] == ["left", "left", "right", "right"]
    assert [row["left_value"] for row in result.value] == [10, 8, None, None]
    assert [row["right_value"] for row in result.value] == [None, None, 5, 3]


def test_arithmetic_comparison_still_requires_alignment_for_multiple_rows():
    result = run(Operator.COMPARE, source([{"value": 10}, {"value": 8}], "l"),
                 source([{"value": 5}, {"value": 3}], "r"),
                 field="value", operation="difference")
    assert result.failure_reason == "comparison_alignment_required"


def test_side_by_side_allows_one_scalar_against_an_independent_population():
    result = run(Operator.COMPARE, source([{"country": "A", "value": 10}], "l"),
                 source([{"country": "B", "value": 5}, {"country": "C", "value": 3}], "r"),
                 field="value", operation="side_by_side")
    assert result.status == ResultStatus.SUCCESS
    assert len(result.value) == 3
    assert [row["comparison_side"] for row in result.value] == ["left", "right", "right"]


def test_side_by_side_infers_registered_metric_fields_only():
    result = run(Operator.COMPARE,
                 source([{"country": "A", "production_volume": 10}], "l"),
                 source([{"country": "B", "import_value": 5}, {"country": "C", "import_value": 3}], "r"),
                 operation="side_by_side")
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["left_value"] == 10
    assert result.value[1]["right_value"] == 5


def test_side_by_side_re_resolves_invalid_cross_metric_field_per_input():
    result = run(
        Operator.COMPARE,
        source([{"country": "A", "production_volume": 10}], "production"),
        source([{"country": "B", "import_value": 5}], "imports"),
        operation="side_by_side", left_field="import_value", right_field="import_value",
    )
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["left_value"] == 10
    assert result.value[0]["right_value"] == 5


def test_binary_ratio_uses_two_typed_scalar_inputs():
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    result = execute_registered(factory,
        RequirementNode("ratio", Operator.CALCULATE, args={"calculation": "ratio", "as_percentage": True}),
        {
            "numerator": source([{"value": 20}], "numerator"),
            "denominator": source([{"value": 100}], "denominator"),
        },
    )
    assert result.status == ResultStatus.SUCCESS
    assert result.metric == "percentage"
    assert result.value == [{"ratio": 20.0}]
    assert result.unit == "%"


def test_side_by_side_does_not_use_country_dimension_as_measure():
    result = run(Operator.COMPARE,
                 source([{"country": "A", "production_volume": 10}], "l"),
                 source([{"country": "B", "import_value": 5}], "r"),
                 operation="side_by_side", left_field="country", right_field="country")
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["left_value"] == 10
    assert result.value[0]["right_value"] == 5


def test_composite_keys_and_distinct_field_names():
    result = run(Operator.JOIN, source([{"country": "A", "year": 2024, "value": 5}], "l"),
        source([{"partner": "A", "period": 2024, "value": 3}], "r"),
        left_on=["country", "year"], right_on=["partner", "period"])
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["right.value"] == 3
    assert result.value[0]["year"] == 2024


def test_row_unit_disagreement_blocks_numeric_comparison():
    result = run(Operator.COMPARE, source([{"value": 5, "unit": "kg"}], "l"),
        source([{"value": 3}], "r"), field="value", operation="difference")
    assert result.failure_reason == "unit_mismatch"


def test_rejected_empty_evidence_is_not_reintroduced_by_outer_join():
    left = source([{"country": "A"}], "l")
    right = replace(source([], "rejected"), status=ResultStatus.EMPTY, sufficient=False,
                    failure_reason="retrieval unavailable: validation_failed")
    result = run(Operator.JOIN, left, right, join_key="country", how="left")
    assert result.status == ResultStatus.EMPTY
    assert not result.evidence


def test_output_metadata_cannot_overwrite_a_join_key():
    result = run(Operator.JOIN, source([{"left_unit": "A"}], "l"),
                 source([{"left_unit": "A"}], "r"), join_key="left_unit")
    assert result.failure_reason == "join_output_field_collision"


def test_join_does_not_guess_country_key_from_country_share_field():
    result = run(Operator.JOIN, source([{"country_share": 50}], "l"),
                 source([{"country_share": 50}], "r"), join_key="country")
    assert result.failure_reason == "missing_join_key"


def test_join_prefers_canonical_country_over_secondary_country_alias():
    result = run(
        Operator.JOIN,
        source([{"country": "A", "country_name_en": "Aland", "value": 1}], "l"),
        source([{"country": "A", "country_name_en": "Aland", "value": 2}], "r"),
        join_key="country",
    )
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["country"] == "A"


def test_registered_price_and_date_aliases_match_real_tool_columns():
    left = source([{"crtr_ymd(기준일자)": "20260930", "cmerc_prc(통상가격)": "10.5"}], "l")
    right = source([{"crtr_ymd(기준일자)": "20260930", "cmerc_prc(통상가격)": "2.5"}], "r")
    result = run(Operator.COMPARE, left, right, join_key="date", field="price", operation="difference")
    assert result.status == ResultStatus.SUCCESS
    assert result.value[0]["difference"] == 8


def test_annual_resource_year_is_a_valid_date_projection_alias():
    from inhouse.rag_core.ragkit.live_multihop import _resolve_row_field
    assert _resolve_row_field([{"country": "A", "year": 2025, "value": 10}], "date", strict=True) == "year"


def test_verified_unit_codes_are_normalized_without_price_basis_comparison():
    from inhouse.rag_core.ragkit.live_multihop import _typed_unit
    assert _typed_unit("가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002") == "USD/톤"
    assert _typed_unit("가격기준=spot; 통화코드=USD; 중량단위코드=TON") == "USD/톤"
    assert _typed_unit("통화코드=UNKNOWN; 중량단위코드=TON") is None


def test_compare_result_flows_through_lowering_runtime_and_projection():
    import asyncio
    from inhouse.rag_core.ragkit.lowering import PipeLowerer
    from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, PipeRuntime
    from inhouse.rag_core.ragkit.semantic_ir import InputRef, SemanticProgram
    left = source([{"country": "A", "value": 10}], "l")
    right = source([{"country": "A", "value": 3}], "r")
    program = SemanticProgram((
        RequirementNode("l", Operator.RETRIEVE, args={"metric": "import_value"}),
        RequirementNode("r", Operator.RETRIEVE, args={"metric": "import_value"}),
        RequirementNode("compare", Operator.COMPARE, inputs=(InputRef("l"), InputRef("r")),
            args={"join_key": "country", "field": "value", "operation": "difference"}),
        RequirementNode("project", Operator.PROJECT, inputs=(InputRef("compare"),), args={"fields": ["country", "difference"]}),
    ), ("project",))
    program.validate()
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    def build(node, dependencies, bindings):
        if node.node_id in {"l", "r"}:
            return FunctionStep(node.node_id, node.operator.value, lambda c, i: left if node.node_id == "l" else right)
        return factory.build(node=node, dependencies=dependencies, bindings=bindings)
    result = asyncio.run(PipeRuntime().execute(PipeLowerer(build).lower(program, pipe_id="relation-fixture")))
    assert result.results["project"].value == [{"country": "A", "difference": 7}]
    assert result.results["project"].evidence == left.evidence + right.evidence


def test_actual_gemma_identifier_only_comparison_requires_replanning():
    from inhouse.rag_core.ragkit.semantic_ir import SemanticProgram
    # Reduced actual audit27 structured output: no retrieval exists.
    payload = {"nodes": [
        {"node_id": "node_nickel", "operator": "entity", "args": {"mineral": "nickel"}, "expected_type": "time_series"},
        {"node_id": "node_copper", "operator": "entity", "args": {"mineral": "copper"}, "expected_type": "time_series"},
        {"node_id": "node_compare_diff", "operator": "compare", "inputs": [{"node_id": "node_nickel"}, {"node_id": "node_copper"}],
         "args": {"operation": "difference", "join_key": "date"}},
    ], "roots": ["node_compare_diff"]}
    with pytest.raises(ValueError, match="requires comparison field"):
        SemanticProgram.from_dict(payload)
    payload["nodes"][-1]["args"]["field"] = "price"
    with pytest.raises(ValueError, match="requires retrieved rows"):
        SemanticProgram.from_dict(payload)


def test_compare_keeps_input_order_even_when_right_finishes_first():
    import asyncio
    from inhouse.rag_core.ragkit.lowering import PipeLowerer
    from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, PipeRuntime
    from inhouse.rag_core.ragkit.semantic_ir import InputRef, SemanticProgram
    program = SemanticProgram((RequirementNode("l", Operator.RETRIEVE), RequirementNode("r", Operator.RETRIEVE),
        RequirementNode("diff", Operator.COMPARE, inputs=(InputRef("l"), InputRef("r")),
                        args={"field": "value", "operation": "difference"})), ("diff",))
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    def build(node, dependencies, bindings):
        if node.node_id in {"l", "r"}:
            async def retrieve(c, i):
                if node.node_id == "l":
                    await asyncio.sleep(0.01)
                return source([{"value": 10 if node.node_id == "l" else 3}], node.node_id)
            return FunctionStep(node.node_id, node.operator.value, retrieve)
        return factory.build(node=node, dependencies=dependencies, bindings=bindings)
    result = asyncio.run(PipeRuntime().execute(PipeLowerer(build).lower(program, pipe_id="ordered")))
    assert result.results["diff"].value[0]["difference"] == 7
