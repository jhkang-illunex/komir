"""Behavior-preserving registration, not new aggregation semantics."""
import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import (
    ExecutionContext, FunctionStep, InputBinding, Pipe, PipeRuntime,
    ResultStatus, TypedResult,
)
from inhouse.rag_core.ragkit.semantic_ir import (
    InputRef, Operator, RequirementNode, SemanticProgram, ValueType,
)


def factory():
    return LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])


def node(**args):
    return RequirementNode("reduce:result", Operator.AGGREGATE,
                           args={"field": "value", "aggregation": "sum", **args})


def source(rows=None, **kwargs):
    return TypedResult.success(ValueType.TIME_SERIES,
        rows if rows is not None else [{"date": "2024-02-01", "value": 3}, {"date": "2024-01-01", "value": 2}],
        entity=("entity",), metric="metric", period={"year": 2024}, unit="unit",
        source=("source",), evidence=({"text": "evidence"},), provenance=("known-contamination",),
        warnings=("existing-warning",), confidence=0.5, **kwargs)


def execute(n, inputs):
    f = factory()
    with patch.object(f, "_derive", side_effect=AssertionError("legacy derive invoked")), \
         patch.object(f, "_retrieve", side_effect=AssertionError("retrieval invoked")):
        return asyncio.run(f.build(node=n, dependencies=tuple(inputs), bindings={}).execute(ExecutionContext(), inputs))


@pytest.mark.parametrize("operation,expected", [("first", 2), ("last", 3)])
def test_registered_ordered_selection_keeps_date_binding_and_metadata(operation, expected):
    n = node(aggregation=operation)
    original = source()
    result = execute(n, {"source": original})
    assert result == replace(original, result_type=ValueType.SCALAR_METRIC,
        value=[{"value": expected, "date": "2024-01-01" if operation == "first" else "2024-02-01"}])
    assert "order_by" not in n.args


def test_explicit_order_is_not_overwritten_by_canonical_date():
    result = execute(node(aggregation="last", order_by="priority"), {"source": source([
        {"date": "2024-02-01", "priority": 1, "value": 3},
        {"date": "2024-01-01", "priority": 2, "value": 2}])})
    assert result.value == [{"value": 2, "priority": 2}]


@pytest.mark.parametrize("rows,reason", [
    ([{"value": 3}], "aggregate_order_required"),
    ([{"date": "2024-01-01", "value": 3}, {"date": "2024-01-01", "value": 2}], "ambiguous_order_tie"),
    ([], "aggregate_input_incomplete"),
])
def test_registered_selection_preserves_fail_closed(rows, reason):
    assert execute(node(aggregation="last"), {"source": source(rows)}).failure_reason == reason


def test_any_partial_input_is_rejected_before_selecting_first_source():
    assert execute(node(), {"first": source(), "unused": replace(source(), status=ResultStatus.PARTIAL)}) == TypedResult.abstain("incomplete_population")


def test_missing_input_keeps_failed_result():
    assert execute(node(), {}) == TypedResult.failed("missing_input")


def test_first_input_and_null_policy_are_preserved():
    first = source([{"value": 2}, {"value": None}])
    result = execute(node(null_policy="skip"), {"first": first, "second": source([{"value": 999}])})
    assert result == replace(first, result_type=ValueType.SCALAR_METRIC, value=[{"value": 2.0}],
        status=ResultStatus.PARTIAL, warnings=first.warnings + ("aggregate_nulls_excluded:1",))


def test_lowering_preserves_ids_binding_order_and_runtime_defaults():
    f = factory()
    n = replace(node(), inputs=(InputRef("second"), InputRef("first"), InputRef("second")))
    program = SemanticProgram((RequirementNode("first", Operator.ENTITY), RequirementNode("second", Operator.ENTITY), n), (n.node_id,))
    step = PipeLowerer(f).lower(program, pipe_id="lowered").steps[-1]
    assert type(step) is FunctionStep
    assert step.step_id == n.node_id and step.operation == "aggregate"
    assert step.dependencies == ("second", "first")
    assert list(step.bindings.values()) == [InputBinding("second"), InputBinding("first"), InputBinding("second")]
    assert step.timeout_seconds is None and step.max_retries == 0


@pytest.mark.parametrize("status", [ResultStatus.FAILED, ResultStatus.ABSTAINED])
def test_runtime_keeps_dependency_failure_propagation(status):
    upstream = replace(source(), status=status, sufficient=False, failure_reason="existing_failure")
    step = factory().build(node=node(), dependencies=("source",), bindings={"input_0": InputBinding("source")})
    pipe = Pipe("failure", (FunctionStep("source", "retrieve", lambda _c, _i: upstream), step))
    result = asyncio.run(PipeRuntime().execute(pipe))
    assert result.results["source"] == upstream
    assert result.results[step.step_id].status == ResultStatus.DEPENDENCY_FAILED


def test_function_step_still_checks_cancellation_before_handler():
    context = ExecutionContext()
    context.cancel()
    step = factory().build(node=node(), dependencies=(), bindings={})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {"source": source()}))
