"""Characterize legacy continuation through execute_relation, without repairs."""

from copy import deepcopy
from dataclasses import replace
from functools import partial
from unittest.mock import patch

import pytest

from inhouse.rag_core.ragkit import relational_ops
from inhouse.rag_core.ragkit.live_multihop import _resolve_row_field
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, ValueType


resolve = partial(_resolve_row_field, strict=True)


def source(rows, name, **changes):
    return replace(TypedResult.success(
        ValueType.FACT_SET, rows, entity=("Ni",), metric="input_metric",
        unit="USD/t", period={"source": name}, source=("shared", name),
        evidence=({"text": name},), provenance=("shared", name),
        warnings=("shared", name), confidence=0.7,
    ), **changes)


def pair():
    return (source([{"date": "2024-01-01", "value": 10}], "observed"),
            source([{"forecast_date": "2024-02-01", "predicted_price": 20}], "forecast"))


def node(**args):
    return RequirementNode(
        "continuation", Operator.COMPARE,
        (InputRef("observed"), InputRef("forecast")),
        {"operation": "temporal_continuation", **args},
    )


def execute(left, right, **args):
    return relational_ops.execute_relation(node(**args), {"left": left, "right": right}, resolve)


@pytest.mark.parametrize("reverse", [False, True])
def test_stable_order_boundary_exclusion_duplicates_and_no_mutation(reverse):
    observed = [
        {"date": "2024-02-01", "value": 2, "tag": "b"},
        {"date": "2024-01-01", "value": 1, "tag": "a"},
        {"date": "2024-02-01", "value": 3, "tag": "c"},
    ]
    forecast = [
        {"forecast_date": "2024-04-01", "predicted_price": 6, "tag": "f"},
        {"forecast_date": "2024-03-01", "predicted_price": 4, "tag": "d"},
        {"forecast_date": "20240201", "predicted_price": 999, "tag": "excluded"},
        {"forecast_date": "2024-03-01", "predicted_price": 5, "tag": "e"},
    ]
    if reverse:
        observed.reverse()
        forecast.reverse()
    left, right = source(observed, "observed"), source(forecast, "forecast")
    before = deepcopy((left, right))
    result = execute(left, right)
    assert result.status == ResultStatus.SUCCESS and result.sufficient
    assert result.result_type == ValueType.TIME_SERIES and result.metric == "price"
    assert result.failure_reason is None and result.confidence is None
    assert [row["tag"] for row in result.value] == (
        ["a", "c", "b", "e", "d", "f"] if reverse else ["a", "b", "c", "d", "e", "f"])
    assert [row["observation_type"] for row in result.value] == ["observed"] * 3 + ["forecast"] * 3
    assert [row["value"] for row in result.value] == ([1, 3, 2, 5, 4, 6] if reverse else [1, 2, 3, 4, 5, 6])
    assert result.source == result.provenance == result.warnings == ("shared", "observed", "forecast")
    assert result.evidence == left.evidence + right.evidence
    assert result.period == {"kind": "temporal_continuation", "observed": left.period, "forecast": right.period}
    assert result.upstream_step_ids == ("observed", "forecast")
    assert (left, right) == before
    assert all(row is not original for row in result.value for original in observed + forecast)


@pytest.mark.parametrize("observed_date,forecast_date,has_future", [
    ("2024-01-01", "20240101", False),
    ("2024-01-01T00:00:00", "2024-01-01T23:59:59", False),
    ("2024-01", "2024-01-01", True),
    ("2024/01/01", "2024-02-01", True),
    ("not-a-date", "zzz", True),
    (None, "zzz", True),
    (None, "2025-01-01", False),
    (20240101, 20240102, True),
    ("", "0000", True),
])
def test_dates_keep_legacy_string_normalization(observed_date, forecast_date, has_future):
    left = source([{"date": observed_date, "value": 1}], "observed")
    right = source([{"forecast_date": forecast_date, "predicted_price": 2}], "forecast")
    result = execute(left, right)
    assert result.result_type == ValueType.TIME_SERIES
    if has_future:
        assert result.status == ResultStatus.SUCCESS
        assert [row["date"] for row in result.value] == [observed_date, forecast_date]
    else:
        assert result.status == ResultStatus.EMPTY and result.value is None
        assert result.failure_reason == "temporal_continuation_no_future_rows"


@pytest.mark.parametrize("observed,forecast,args", [
    ({"crtr_ymd(기준일자)": "20240101", "cmerc_prc(통상가격)": 10},
     {"forecast_date(예측일)": "20240201", "predicted_price(예측값)": 20}, {"left_field": "price"}),
    ({"obs_date": "20240101", "value": 10},
     {"observed_date": "20240201", "cmerc_prc": 20}, {"right_field": "price"}),
    ({"year": 2023, "value": 10}, {"year": 2024, "predicted_price": 20}, {}),
])
def test_current_strict_live_aliases_and_year_fallback(observed, forecast, args):
    result = execute(source([observed], "observed"), source([forecast], "forecast"), **args)
    assert result.status == ResultStatus.SUCCESS
    assert [row["value"] for row in result.value] == [10, 20]
    assert result.value[0].items() >= observed.items()
    assert result.value[1].items() >= forecast.items()


@pytest.mark.parametrize("left_unit,right_unit,expected", [
    ("USD/t", "USD/t", "USD/t"), (None, "USD/t", "USD/t"),
    ("USD/t", None, "USD/t"), (None, None, None), ("", "USD/t", "USD/t"),
])
def test_missing_units_are_accepted(left_unit, right_unit, expected):
    left, right = pair()
    result = execute(replace(left, unit=left_unit), replace(right, unit=right_unit))
    assert result.status == ResultStatus.SUCCESS and result.unit == expected


@pytest.mark.parametrize("left_entity,right_entity,expected", [
    (("Ni",), ("Ni",), ("Ni",)),
    (("Ni", "Co", "Ni"), ("Co", "Ni"), ("Ni", "Co")),
    ((), ("Ni",), ("Ni",)), (("Ni",), (), ("Ni",)), ((), (), ()),
])
def test_entity_set_comparison_and_ordered_union(left_entity, right_entity, expected):
    left, right = pair()
    result = execute(replace(left, entity=left_entity), replace(right, entity=right_entity))
    assert result.status == ResultStatus.SUCCESS and result.entity == expected


@pytest.mark.parametrize("changes,reason", [
    ({"unit": "t"}, "temporal_continuation_unit_mismatch"),
    ({"entity": ("Co",)}, "temporal_continuation_entity_mismatch"),
    ({"unit": "t", "entity": ("Co",)}, "temporal_continuation_unit_mismatch"),
])
def test_unit_failure_precedes_entity_failure(changes, reason):
    left, right = pair()
    result = execute(left, replace(right, **changes))
    assert result.status == ResultStatus.ABSTAINED and not result.sufficient
    assert result.result_type == ValueType.TIME_SERIES and result.failure_reason == reason
    assert result.evidence == left.evidence + right.evidence


def test_input_metric_criterion_and_as_of_do_not_add_validation():
    left = source([{"date": "20240101", "value": 1, "price_criterion": "A"}], "observed", metric="inventory")
    right = source([{"forecast_date": "20240201", "predicted_price": 2, "price_criterion": "B"}], "forecast", metric="unrelated")
    result = execute(left, right, as_of="1900-01-01", price_criterion="C")
    assert result.status == ResultStatus.SUCCESS and result.metric == "price"
    assert [row["price_criterion"] for row in result.value] == ["A", "B"]


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("row_status", ["SUCCESS", "DATA_UNAVAILABLE", "DEPENDENCY_FAILED",
                                        "EXECUTION_FAILED", "NEEDS_SELECTION", "FAILED", "ABSTAINED"])
def test_partial_with_allowed_row_status_still_returns_success(side, row_status):
    left, right = pair()
    inputs = {"left": left, "right": right}
    item = inputs[side]
    inputs[side] = replace(item, status=ResultStatus.PARTIAL,
                           value=[{**item.value[0], "status": row_status, "reason": "existing"}])
    result = relational_ops.execute_relation(node(), inputs, resolve)
    assert result.status == ResultStatus.SUCCESS and result.sufficient
    assert result.failure_reason is None
    assert result.warnings == ("shared", "observed", "forecast", "incomplete_population")
    assert result.value[0 if side == "left" else 1]["status"] == row_status
    assert result.value[0 if side == "left" else 1]["reason"] == "existing"


@pytest.mark.parametrize("side", ["left", "right"])
def test_success_with_zero_rows_is_temporal_empty(side):
    left, right = pair()
    inputs = {"left": left, "right": right}
    inputs[side] = replace(inputs[side], value=[])
    result = relational_ops.execute_relation(node(), inputs, resolve)
    assert result.status == ResultStatus.EMPTY and result.result_type == ValueType.TIME_SERIES
    assert result.failure_reason == "temporal_continuation_no_rows"
    assert result.evidence == left.evidence + right.evidence


@pytest.mark.parametrize("changes,args", [
    ({"value": [{"value": 1}]}, {}),
    ({"value": [{"date": "20240101", "unrelated": 1}]}, {}),
    ({"value": [{"price_date": "20240101", "obs_date": "20240101", "value": 1}]}, {}),
    ({}, {"left_field": "absent"}), ({}, {"right_field": "absent"}),
])
def test_missing_or_ambiguous_fields_keep_temporal_failure(changes, args):
    left, right = pair()
    result = execute(replace(left, **changes), right, **args)
    assert result.status == ResultStatus.ABSTAINED
    assert result.result_type == ValueType.TIME_SERIES
    assert result.failure_reason == "temporal_continuation_field_required"


@pytest.mark.parametrize("changes,status,reason", [
    ({"status": ResultStatus.FAILED}, ResultStatus.FAILED, "dependency_failed"),
    ({"status": ResultStatus.EMPTY}, ResultStatus.EMPTY, "dependency_unavailable"),
    ({"evidence": ()}, ResultStatus.ABSTAINED, "evidence_insufficient"),
    ({"sufficient": False}, ResultStatus.ABSTAINED, "evidence_insufficient"),
    ({"value": [1]}, ResultStatus.ABSTAINED, "relation_requires_structured_rows"),
    ({"status": ResultStatus.PARTIAL}, ResultStatus.ABSTAINED, "partial_row_status_required"),
    ({"status": ResultStatus.PARTIAL, "value": [{"status": "success"}]}, ResultStatus.ABSTAINED, "partial_row_status_required"),
])
def test_outer_guards_do_not_delegate(changes, status, reason):
    left, right = pair()
    with patch.object(relational_ops, "compose_temporal_continuation", side_effect=AssertionError("guard bypass")) as helper:
        result = execute(replace(left, **changes), right)
    helper.assert_not_called()
    assert result.status == status and result.failure_reason == reason
    assert result.result_type == (ValueType.FACT_SET if reason in {
        "dependency_unavailable", "relation_requires_structured_rows", "partial_row_status_required",
    } else ValueType.UNKNOWN)


@pytest.mark.parametrize("operator,operation", [
    (Operator.COMPARE, "side_by_side"), (Operator.COMPARE, "difference"),
    (Operator.COMPARE, "ratio"), (Operator.COMPARE, "percent_change"),
    (Operator.JOIN, "temporal_continuation"),
])
def test_non_temporal_paths_do_not_delegate(operator, operation):
    left, right = pair()
    right = replace(right, value=[{"date": "2024-01-01", "value": 2}])
    request = replace(node(operation=operation, join_key="date", field="value"), operator=operator)
    with patch.object(relational_ops, "compose_temporal_continuation", side_effect=AssertionError("wrong route")) as helper:
        result = relational_ops.execute_relation(request, {"left": left, "right": right}, resolve)
    helper.assert_not_called()
    assert result.status == ResultStatus.SUCCESS and result.result_type == ValueType.FACT_SET


def test_delegate_receives_same_operands_args_resolver_and_returns_same_result():
    left, right = pair()
    request = node()
    expected = TypedResult.abstain("sentinel")
    with patch.object(relational_ops, "compose_temporal_continuation", return_value=expected) as helper:
        actual = relational_ops.execute_relation(request, {"left": left, "right": right}, resolve)
    helper.assert_called_once()
    l_arg, r_arg, lrows, rrows, args, metadata, resolver = helper.call_args.args
    assert l_arg is left and r_arg is right and args is request.args and resolver is resolve
    assert lrows == left.value and rrows == right.value
    assert lrows is not left.value and lrows[0] is not left.value[0]
    assert rrows is not right.value and rrows[0] is not right.value[0]
    assert metadata == {
        "entity": ("Ni",), "evidence": left.evidence + right.evidence,
        "source": ("shared", "observed", "forecast"),
        "provenance": ("shared", "observed", "forecast"),
        "upstream_step_ids": ("observed", "forecast"),
        "warnings": ("shared", "observed", "forecast"), "period": None,
    }
    assert actual is expected


@pytest.mark.parametrize("error_type", [ValueError, TypeError])
def test_delegate_exception_boundary_is_unchanged(error_type):
    left, right = pair()
    with patch.object(relational_ops, "compose_temporal_continuation", side_effect=error_type("sentinel")):
        if error_type is TypeError:
            with pytest.raises(TypeError, match="sentinel"):
                execute(left, right)
        else:
            result = execute(left, right)
            assert result.status == ResultStatus.ABSTAINED and result.result_type == ValueType.FACT_SET
            assert result.failure_reason == "sentinel" and result.evidence == left.evidence + right.evidence
            assert result.warnings == ("shared", "observed", "forecast")
