"""Existing Extremum semantics through the registered FunctionStep boundary."""
import asyncio
from dataclasses import replace
from unittest.mock import patch

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
    n = RequirementNode("selected:row", operator, args=args)
    with patch.object(f, "_derive", side_effect=AssertionError("legacy execution")), \
         patch.object(f, "_retrieve", side_effect=AssertionError("unexpected retrieval")):
        return asyncio.run(f.build(node=n, dependencies=tuple(inputs), bindings={}).execute(ExecutionContext(), inputs))


@pytest.mark.parametrize("operator,index", [(Operator.ARG_MAX, 0), (Operator.ARG_MIN, 1)])
def test_registered_extremum_retains_original_row_date_and_full_envelope(operator, index):
    rows = [{"date": "20240201", "value": 3, "entity": "A", "lineage": ["original-a"]},
            {"date": "2024-01-01", "value": 2, "entity": "B", "lineage": ["original-b"]}]
    original = source(rows)
    result = execute(operator, {"source": original}, field="value")
    assert result == replace(original, value=[rows[index]], entity=(rows[index]["entity"],))
    assert result.value[0] is rows[index]


@pytest.mark.parametrize("operator", [Operator.ARG_MAX, Operator.ARG_MIN])
@pytest.mark.parametrize("policy", ["all", "first", "error", "invalid"])
def test_registered_ties_preserve_existing_policy(operator, policy):
    rows = [{"date": "first", "value": 2}, {"date": "second", "value": 2}]
    result = execute(operator, {"source": source(rows)}, field="value", ties=policy)
    if policy in {"all", "first"}:
        assert result.value == (rows if policy == "all" else rows[:1])
    else:
        assert result == TypedResult.abstain("ambiguous_extremum_tie" if policy == "error" else "unsupported_tie_policy")


def test_numeric_and_iso_date_selection_are_not_normalized():
    rows = [{"date": "2024-02-01"}, {"date": "2024-01-01"}]
    assert execute(Operator.ARG_MIN, {"s": source(rows)}, field="date").value == rows[1:]
    numeric = [{"value": "1,000%"}, {"value": 20}]
    assert execute(Operator.ARG_MAX, {"s": source(numeric)}, field="value").value == numeric[:1]


def test_invalid_values_keep_abstention():
    result = execute(Operator.ARG_MAX, {"s": source([{"value": "bad"}, {"value": 2}])}, field="value")
    assert result == TypedResult.abstain("incompatible_extremum_values")


def test_absent_candidate_preserves_existing_empty_lineage_not_new_metadata():
    original = source([{"other": 2}])
    result = execute(Operator.ARG_MAX, {"s": original}, field="value")
    assert result == TypedResult.empty(ValueType.TIME_SERIES, "arg field unavailable: value",
        evidence=original.evidence, source=original.source, provenance=original.provenance,
        upstream_step_ids=original.upstream_step_ids)


def test_no_field_and_empty_rows_keep_legacy_behavior_even_with_invalid_ties():
    for rows in ([], [{"value": 2}, {"value": 3}]):
        original = source(rows)
        assert execute(Operator.ARG_MAX, {"s": original}, ties="invalid") == original
    assert execute(Operator.ARG_MIN, {}, field="value") == TypedResult.failed("missing_input")


def test_any_partial_input_is_blocked_and_first_input_selection_is_unchanged():
    first = source([{"value": 1}, {"value": 2}])
    second = source([{"value": 999}])
    assert execute(Operator.ARG_MAX, {"first": first, "second": second}, field="value").value == [{"value": 2}]
    assert execute(Operator.ARG_MIN, {"first": first, "second": replace(second, status=ResultStatus.PARTIAL)}, field="value") == TypedResult.abstain("incomplete_population")


def test_registration_preserves_lowered_identity_bindings_and_cancellation():
    n = RequirementNode("extremum:node", Operator.ARG_MIN,
        (InputRef("second"), InputRef("first"), InputRef("second")), {"field": "value"})
    program = SemanticProgram((RequirementNode("first", Operator.RETRIEVE, args={"metric": "price"}),
        RequirementNode("second", Operator.RETRIEVE, args={"metric": "price"}), n), (n.node_id,))
    step = PipeLowerer(factory()).lower(program, pipe_id="lowered").steps[-1]
    assert type(step) is FunctionStep
    assert (step.step_id, step.operation, step.dependencies) == (n.node_id, "arg_min", ("second", "first"))
    assert list(step.bindings.values()) == [InputBinding("second"), InputBinding("first"), InputBinding("second")]
    assert step.timeout_seconds is None and step.max_retries == 0
    context = ExecutionContext(); context.cancel()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {}))
