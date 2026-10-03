"""Registered FILTER preserves legacy semantics, including empty/partial policy."""
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
        failure_reason="existing-reason", upstream_step_ids=("upstream",), confidence=0.7, **kwargs)


def execute(inputs, **args):
    f = factory()
    node = RequirementNode("filter:node", Operator.FILTER, args=args)
    with patch.object(f, "_derive", side_effect=AssertionError("legacy execution")), \
         patch.object(f, "_retrieve", side_effect=AssertionError("unexpected retrieval")):
        return asyncio.run(f.build(node=node, dependencies=tuple(inputs), bindings={}).execute(ExecutionContext(), inputs))


@pytest.mark.parametrize("status", list(ResultStatus))
def test_preserve_envelope_status_and_original_row_identity(status):
    rows = [{"date": "20240201", "value": "2", "entity": "B", "lineage": ["b"]},
            {"date": "2024-01-01", "value": 1, "entity": "A"}]
    original = source(rows, status=status)
    result = execute({"s": original}, predicate={"field": "value", "operator": "gte", "value": 2})
    assert result == replace(original, value=rows[:1], entity=("B",))
    assert result.value[0] is rows[0]


@pytest.mark.parametrize("operator,values", [("equals", [2]), ("not_equals", [1, 3]),
    ("greater_than", [3]), ("less_than", [1]), ("gte", [2, 3]), ("lte", [1, 2])])
def test_existing_predicate_operators(operator, values):
    rows = [{"value": i} for i in (1, 2, 3)]
    assert execute({"s": source(rows)}, field="value", operator=operator, value="2").value == [{"value": v} for v in values]


@pytest.mark.parametrize("predicate", ["increase", "decrease", "greater_than"])
def test_compact_predicate_keeps_existing_metric_alias_priority(predicate):
    rows = [{"price_change": 1, "pct_change": -10}, {"price_change": -1, "pct_change": 10}]
    result = execute({"s": source(rows)}, metric="price_change", predicate=predicate, value=0)
    assert result.value == [rows[1 if predicate == "decrease" else 0]]


def test_explicit_field_is_not_reinterpreted_as_metric_alias():
    original = source([{"pct_change": 3}])
    assert execute({"s": original}, field="price_change", operator="greater_than", value=0).value == []
    assert execute({"s": original}, metric="price_change", operator="greater_than", value=0).value == original.value


def test_none_equality_unsupported_operator_and_mixed_type_policy():
    original = source([{"value": None}, {"value": 2}])
    assert execute({"s": original}, field="value", value=None).value == [{"value": None}]
    assert execute({"s": original}, field="value", operator="not_equals", value=1).value == [{"value": 2}]
    with pytest.raises(ValueError, match="unsupported filter operator"):
        execute({"s": source([{"value": 2}])}, field="value", operator="unknown", value=1)
    with pytest.raises(TypeError):
        execute({"s": source([{"value": "text"}])}, field="value", operator="greater_than", value=1)


def test_explicit_empty_result_preserves_success_and_metadata():
    original = source([{"value": 1}])
    assert execute({"s": original}, field="value", value=999) == replace(original, value=[])


def test_unavailable_metric_empty_retains_only_legacy_empty_envelope():
    original = source([{"other": 1}])
    assert execute({"s": original}, metric="unavailable") == TypedResult.empty(
        original.result_type, "filter field unavailable: unavailable", evidence=original.evidence,
        source=original.source, provenance=original.provenance, upstream_step_ids=original.upstream_step_ids)


@pytest.mark.parametrize("period,indices", [({"trailing_months": 1}, [1, 2]),
    ({"start": "2024-02-29", "end": "2024-02-29"}, [1]),
    ({"start": "invalid"}, [0, 1, 2]), ({"start": "2025-01-01"}, [])])
def test_fieldless_period_filter_preserves_original_entity_binding(period, indices):
    rows = [{"date": "2024-01-31", "value": 1}, {"date": "2024-02-29", "value": 2}, {"date": "2024-03-31", "value": 3}]
    original = source(rows, status=ResultStatus.PARTIAL)
    assert execute({"s": original}, period=period) == replace(original, value=[rows[i] for i in indices])


def test_period_not_applied_when_explicit_field_is_present():
    original = source([{"date": "2024-01-01", "value": 1}])
    assert execute({"s": original}, field="value", value=1, period={"start": "2025-01-01"}) == original


def test_country_alias_uses_original_rows_and_fail_closed_ambiguity():
    rows = [{"country": "칠레", "country_code": "CL", "country_name_en": "Chile", "value": 2},
            {"country": "페루", "country_code": "PE", "value": 1}]
    result = execute({"s": source(rows)}, field="country", value=" cHiLe ")
    assert result.value == rows[:1] and result.value[0] is rows[0]
    ambiguous = rows + [{"country_code": "XX", "country_name_en": "Chile"}]
    assert execute({"s": source(ambiguous)}, field="country", value="Chile") == TypedResult.abstain("country_alias_ambiguous")


def test_set_empty_and_first_input_selection_are_preserved():
    original = TypedResult.success(ValueType.MINERAL_SET, ["A", "B"], entity=("A", "B"))
    result = execute({"first": original, "second": source([], status=ResultStatus.PARTIAL)}, field="mineral", value="B")
    assert result == replace(original, value=["B"], entity=("B",))
    assert execute({"s": original}, field="mineral", value="absent") == replace(original, value=[], entity=())
    assert execute({}) == TypedResult.failed("missing_input")


def test_registration_keeps_identity_dependency_bindings_and_cancel():
    node = RequirementNode("filter:node", Operator.FILTER, (InputRef("source"),), {"field": "value", "value": 1})
    program = SemanticProgram((RequirementNode("source", Operator.RETRIEVE, args={"metric": "price"}), node), (node.node_id,))
    step = PipeLowerer(factory()).lower(program, pipe_id="filtered").steps[-1]
    assert type(step) is FunctionStep
    assert (step.step_id, step.operation, step.dependencies) == (node.node_id, "filter", ("source",))
    assert list(step.bindings.values()) == [InputBinding("source")]
    assert step.timeout_seconds is None and step.max_retries == 0
    context = ExecutionContext(); context.cancel()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {}))
