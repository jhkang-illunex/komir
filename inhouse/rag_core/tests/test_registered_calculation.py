"""Characterize distinct legacy calculation families, not new semantics."""
import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionContext, FunctionStep, InputBinding, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode, ValueType


def factory():
    return LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])


def source(value, **changes):
    return replace(TypedResult.success(ValueType.TIME_SERIES, value, entity=("original",),
        metric="price", unit="USD/t", period={"year": 2024}, evidence=({"text": "existing"},),
        source=("source",), provenance=("known-contamination",), upstream_step_ids=("upstream",)), **changes)


def execute(inputs, **args):
    f = factory()
    with patch.object(f, "_derive", side_effect=AssertionError("legacy")):
        step = f.build(node=RequirementNode("calc", Operator.CALCULATE, args=args), dependencies=tuple(inputs), bindings={})
        return step._handler(ExecutionContext(), inputs)


@pytest.mark.parametrize("alias", ["share", "division", "percentage", "percent", "PERCENTAGE"])
def test_population_aliases_are_not_row_ratios(alias):
    result = execute({"s": source([{"value": 1}, {"value": 3}])}, calculation=alias, field="value")
    assert result.value == [{"value": 25}, {"value": 75}]
    assert (result.result_type, result.metric, result.unit) == (ValueType.COUNTRY_SHARE, "share", "%")


@pytest.mark.parametrize("alias", ["change_pct", "percent_change"])
@pytest.mark.parametrize("status", list(ResultStatus))
def test_inline_change_preserves_legacy_envelope_not_series_units(alias, status):
    original = source({"start": "-1,000", "end": "-500", "lineage": ["old"]}, status=status,
                      failure_reason="existing-failure", sufficient=False, evidence=())
    result = execute({"s": original}, calculation=alias)
    if status == ResultStatus.PARTIAL:
        assert result == TypedResult.abstain("incomplete_population")
    else:
        assert result == replace(original, value=[{**original.value, "change_pct": 50}])


@pytest.mark.parametrize("value", [0, None, True, "invalid", float("inf")])
def test_inline_invalid_base_policy(value):
    assert execute({"s": source({"start": value, "end": 10})}, calculation="change_pct") == TypedResult.abstain("invalid_calculation_operands")


def test_inline_and_series_contracts_are_intentionally_not_equivalent():
    rows = [{"date": "2024-01-01", "value": 10}, {"date": "2024-02-01", "value": 20}]
    s = source(rows, unit=None)
    assert execute({"s": s}, calculation="endpoint_change", field="value", time_field="date").failure_reason == "unit_unavailable"
    assert execute({"s": source({"start": 10, "end": 20}, unit=None)}, calculation="change_pct").unit is None
    assert execute({"s": s}, calculation="change_pct").failure_reason == "unsupported_calculation_contract"


@pytest.mark.parametrize("calculation", ["endpoint_change", "periodic_return", "base100", "threshold_first", "correlation"])
def test_series_family_delegates_authoritative_helper(calculation):
    from inhouse.rag_core.ragkit.operator_handlers import calculation as handler
    s = source([])
    expected = TypedResult.abstain("existing-helper-result")
    with patch.object(handler, "calculate_series", return_value=expected) as call:
        assert execute({"s": s}, calculation=calculation, field="value", time_field="date") is expected
    assert call.call_args.args[:2] == (s, {"calculation": calculation, "field": "value", "time_field": "date"})


def test_binary_ratio_order_partial_precedence_and_period_policy():
    left, right = source([{"value": 2}]), source([{"value": 4}], unit="different", period={"year": 2025})
    a = execute({"left": left, "right": right}, calculation="RATIO")
    b = execute({"right": right, "left": left}, calculation="RATIO")
    assert a.value == [{"ratio": .5}] and b.value == [{"ratio": 2}]
    assert a.period is None and a.unit == "ratio"
    partial = replace(right, status=ResultStatus.PARTIAL)
    assert execute({"a": left, "b": partial}, calculation="ratio").failure_reason == "incomplete_ratio_inputs"
    assert execute({"a": left, "b": partial}, calculation="share").failure_reason == "incomplete_population"


def test_single_ratio_three_inputs_first_source_and_invalid_operand_policy():
    s = source([{"a": True, "b": -2, "unit": "original"}])
    result = execute({"first": s, "second": source([]), "third": source([])}, calculation="ratio", numerator_field="a", denominator_field="b")
    assert result.value == [{"unit": "original", "ratio": -.5}]
    assert result.unit == "ratio"
    assert execute({"s": source([{"a": 1, "b": 0}])}, calculation="ratio", numerator_field="a", denominator_field="b").failure_reason == "zero_denominator"


def test_registration_preserves_identity_bindings_retry_timeout_and_cancel():
    node = RequirementNode("calc:id", Operator.CALCULATE, args={"calculation": "ratio"})
    bindings = {"numerator": InputBinding("left"), "denominator": InputBinding("right")}
    step = factory().build(node=node, dependencies=("left", "right"), bindings=bindings)
    assert type(step) is FunctionStep
    assert (step.step_id, step.operation, step.dependencies, step.bindings) == ("calc:id", "calculate", ("left", "right"), bindings)
    assert step.timeout_seconds is None and step.max_retries == 0
    context = ExecutionContext(); context.cancel()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {}))
