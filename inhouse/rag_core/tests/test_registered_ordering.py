"""Ordering extraction contract: existing behavior, not new sort semantics."""
import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionContext, FunctionStep, InputBinding, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType


def factory():
    return LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])


def source(rows, **kwargs):
    return TypedResult(ValueType.TIME_SERIES, rows, entity=("upstream",), metric="price", unit="USD/t",
        period={"year": 2024}, source=("source",), evidence=({"text": "evidence"},),
        provenance=("known-contamination",), warnings=("existing-warning",),
        upstream_step_ids=("upstream",), confidence=0.7, **kwargs)


def execute(operator, inputs, **args):
    f = factory()
    node = RequirementNode("ordering:node", operator, args=args)
    with patch.object(f, "_derive", side_effect=AssertionError("legacy execution")), \
         patch.object(f, "_retrieve", side_effect=AssertionError("unexpected retrieval")):
        step = f.build(node=node, dependencies=tuple(inputs) or ("declared-input",), bindings={})
        return asyncio.run(step.execute(ExecutionContext(), inputs))


@pytest.mark.parametrize("operator", [Operator.SORT, Operator.RANK])
@pytest.mark.parametrize("order,indices", [("asc", [1, 0, 2]), ("desc", [0, 1, 2])])
def test_numeric_order_keeps_null_at_end_and_original_row_envelope(operator, order, indices):
    rows = [{"value": "1,000", "date": "20240101", "entity": "A", "lineage": ["a"]},
            {"value": 2, "date": "2024-02-01", "entity": "B"}, {"value": None, "entity": "C"}]
    original = source(rows)
    result = execute(operator, {"source": original}, field="value", order=order, top_n=1)
    expected = [rows[i] for i in indices]
    assert result == replace(original, value=expected, entity=tuple(row["entity"] for row in expected))
    assert all(row is rows[i] for row, i in zip(result.value, indices))
    assert len(result.value) == 3  # dependency RANK does not truncate top_n


@pytest.mark.parametrize("field,values", [("date", ["2024-02-01", "2024-01-01"]), ("name", ["Zulu", "Alpha"])])
def test_lexical_ordering_is_not_normalized(field, values):
    rows = [{field: value} for value in values]
    assert execute(Operator.SORT, {"s": source(rows)}, field=field, order="asc").value == rows[::-1]


def test_existing_tie_breaker_and_stable_order_are_preserved():
    rows = [{"value": 2, "id": "z"}, {"value": 2, "id": "a"}, {"value": 1, "id": "b"}]
    assert execute(Operator.SORT, {"s": source(rows)}, field="value").value == rows
    assert execute(Operator.SORT, {"s": source(rows)}, field="value", tie_breaker="id").value == [rows[1], rows[0], rows[2]]
    assert execute(Operator.SORT, {"s": source(rows)}, field="value", tie_breaker="absent") == TypedResult.abstain("sort_tie_field_unavailable")


@pytest.mark.parametrize("operator", [Operator.SORT, Operator.RANK, Operator.TOP_K])
def test_partial_policy_is_not_unified(operator):
    original = source([{"value": 1}, {"value": 2}], status=ResultStatus.PARTIAL)
    result = execute(operator, {"s": original}, field="value")
    if operator == Operator.SORT:
        assert result == replace(original, value=original.value[::-1])
    else:
        assert result == TypedResult.abstain("incomplete_population")


@pytest.mark.parametrize("args,expected", [({"k": 1}, [0]), ({"k": -1}, [0, 1]),
    ({"k": 0}, [0, 1, 2]), ({"k": 0, "top_n": 1}, [0]), ({"top_n": "2"}, [0, 1])])
def test_top_k_preserves_legacy_slice_and_truthy_fallback(args, expected):
    rows = [{"value": 9}, {"value": 2}, {"value": 7}]
    assert execute(Operator.TOP_K, {"s": source(rows)}, **args).value == [rows[i] for i in expected]


def test_incompatible_sort_and_invalid_k_preserve_failures():
    assert execute(Operator.SORT, {"s": source([{"value": 2}, {"value": "bad"}])}, field="value") == TypedResult.abstain("incompatible_sort_values")
    with pytest.raises(ValueError):
        execute(Operator.TOP_K, {"s": source([])}, k="bad")


def test_missing_field_and_implicit_field_behavior_are_unchanged():
    rows = [{"value": 2}, {"value": 1}]
    assert execute(Operator.SORT, {"s": source(rows)}, field="missing").value == rows
    assert execute(Operator.SORT, {"s": source(rows)}, order="asc").value == rows[::-1]
    assert execute(Operator.SORT, {}, field="value") == TypedResult.failed("missing_input")


@pytest.mark.parametrize("operator", [Operator.SORT, Operator.RANK, Operator.TOP_K])
def test_first_input_and_secondary_partial(operator):
    first = source([{"value": 1}, {"value": 2}])
    second = source([{"value": 999}], status=ResultStatus.PARTIAL)
    result = execute(operator, {"first": first, "second": second}, field="value")
    assert result == (replace(first, value=first.value[::-1]) if operator == Operator.SORT else TypedResult.abstain("incomplete_population"))


@pytest.mark.parametrize("runtime_inputs", [{}, {"unbound": source([], status=ResultStatus.PARTIAL)}])
def test_no_dependency_rank_uses_existing_async_retrieval(runtime_inputs):
    f = factory()
    node = RequirementNode("rank:source", Operator.RANK, args={"metric": "import", "top_n": 2})
    expected = source([{"country": "source-rank", "value": 7}])
    with patch.object(f, "_retrieve", new=AsyncMock(return_value=expected)) as retrieve, \
         patch.object(f, "_derive", side_effect=AssertionError("legacy")):
        step = f.build(node=node, dependencies=(), bindings={})
        assert asyncio.run(step.execute(ExecutionContext(), runtime_inputs)) is expected
        retrieve.assert_awaited_once_with(node, runtime_inputs)


@pytest.mark.parametrize("operator", [Operator.SORT, Operator.RANK, Operator.TOP_K])
def test_lowered_identity_dependency_order_and_cancel(operator):
    node = RequirementNode("ordering:node", operator,
        (InputRef("second"), InputRef("first"), InputRef("second")), {"field": "value"})
    program = SemanticProgram((RequirementNode("first", Operator.RETRIEVE, args={"metric": "price"}),
        RequirementNode("second", Operator.RETRIEVE, args={"metric": "price"}), node), (node.node_id,))
    step = PipeLowerer(factory()).lower(program, pipe_id="ordering").steps[-1]
    assert type(step) is FunctionStep
    assert (step.step_id, step.operation, step.dependencies) == (node.node_id, operator.value, ("second", "first"))
    assert list(step.bindings.values()) == [InputBinding("second"), InputBinding("first"), InputBinding("second")]
    assert step.timeout_seconds is None and step.max_retries == 0
    context = ExecutionContext(); context.cancel()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {}))
