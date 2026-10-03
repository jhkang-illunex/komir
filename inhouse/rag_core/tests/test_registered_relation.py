"""Registered Relation routing preserves the existing algorithm boundary."""
import asyncio
from dataclasses import replace
from unittest.mock import patch

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.operator_handlers import relation
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionContext, FunctionStep, InputBinding, PipeRuntime, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType


def factory():
    return LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])


def source(value=2, **changes):
    return replace(TypedResult.success(ValueType.FACT_SET, [{"value": value}], unit="t",
        entity=("original",), metric="metric", evidence=({"text": "evidence"},),
        source=("source",), provenance=("known-contamination",), warnings=("existing",)), **changes)


@pytest.mark.parametrize("operator", [Operator.JOIN, Operator.COMPARE])
@pytest.mark.parametrize("status", list(ResultStatus))
def test_delegation_preserves_input_object_order_node_and_helper_failure(operator, status):
    f = factory()
    node = RequirementNode("relation:id", operator, (InputRef("right"), InputRef("left")))
    inputs = {"input_0": source(status=status), "input_1": source(4)}
    expected = TypedResult.abstain("helper-owned-failure", provenance=("existing",))
    with patch.object(f, "_derive", side_effect=AssertionError("legacy routing")), \
         patch.object(relation, "execute_relation", return_value=expected) as helper:
        step = f.build(node=node, dependencies=("right", "left"), bindings={})
        assert asyncio.run(step.execute(ExecutionContext(), inputs)) is expected
    assert helper.call_args.args[0] is node and helper.call_args.args[1] is inputs
    assert list(helper.call_args.args[1]) == ["input_0", "input_1"]
    resolve = helper.call_args.args[2]
    assert resolve([{"unrelated": 2}], "missing") is None


@pytest.mark.parametrize("operator", [Operator.JOIN, Operator.COMPARE])
def test_function_step_identity_defaults_and_cancellation(operator):
    node = RequirementNode("relation:id", operator)
    bindings = {"input_0": InputBinding("right", "index", 0), "input_1": InputBinding("left")}
    step = factory().build(node=node, dependencies=("right", "left"), bindings=bindings)
    assert type(step) is FunctionStep
    assert (step.step_id, step.operation, step.dependencies, step.bindings) == (node.node_id, operator.value, ("right", "left"), bindings)
    assert step.timeout_seconds is None and step.max_retries == 0
    context = ExecutionContext(); context.cancel()
    with patch.object(relation, "execute_relation", side_effect=AssertionError("cancelled helper")), pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {}))


@pytest.mark.parametrize("status", [ResultStatus.FAILED, ResultStatus.ABSTAINED, ResultStatus.DEPENDENCY_FAILED])
def test_runtime_dependency_barrier_does_not_invoke_relation(status):
    f = factory()
    node = RequirementNode("relation", Operator.COMPARE, (InputRef("left"), InputRef("right")), {"operation": "difference", "field": "value"})
    program = SemanticProgram((RequirementNode("left", Operator.RETRIEVE, args={"metric": "price"}),
        RequirementNode("right", Operator.RETRIEVE, args={"metric": "price"}), node), (node.node_id,))

    def build(*, node, dependencies, bindings):
        if node.operator == Operator.RETRIEVE:
            return FunctionStep(node.node_id, node.operator.value, lambda _c, _i: source(status=status if node.node_id == "left" else ResultStatus.SUCCESS))
        return f.build(node=node, dependencies=dependencies, bindings=bindings)

    with patch.object(relation, "execute_relation", side_effect=AssertionError("dependency barrier")):
        result = asyncio.run(PipeRuntime().execute(PipeLowerer(build).lower(program, pipe_id="barrier")))
    assert result.results["relation"].status == ResultStatus.DEPENDENCY_FAILED
    assert result.results["relation"].failure_reason == "upstream step failed: left, right"


@pytest.mark.parametrize("reverse", [False, True])
def test_partial_rows_reach_helper_instead_of_legacy_unreachable_guard(reverse):
    left = replace(source(5), status=ResultStatus.PARTIAL, value=[{"value": 5, "status": "SUCCESS"}])
    right = source(2)
    inputs = {"left": left, "right": right}
    if reverse:
        inputs = dict(reversed(list(inputs.items())))
    step = factory().build(node=RequirementNode("r", Operator.COMPARE, args={"operation": "difference", "field": "value"}), dependencies=tuple(inputs), bindings={})
    result = asyncio.run(step.execute(ExecutionContext(), inputs))
    assert result.status == ResultStatus.PARTIAL
    assert result.value[0]["difference"] == (-3 if reverse else 3)
    assert result.failure_reason is None
    assert result.provenance == ("known-contamination",)
