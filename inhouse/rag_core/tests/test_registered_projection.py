"""Legacy PROJECT characterization through the production StepFactory boundary."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import (
    ExecutionContext, FunctionStep, InputBinding, PipeRuntime, ResultStatus, TypedResult,
)
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


def factory():
    return LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])


def source(value, **changes):
    return replace(TypedResult.success(
        ValueType.FACT_SET, value, entity=("original",), unit="t", metric="fixture",
        evidence=(Evidence("structured", "fixture", "fixture", "evidence"),),
        source=("fixture",), provenance=("lineage",), warnings=("existing",),
        period={"year": 2024}, confidence=0.7, upstream_step_ids=("prior",),
    ), **changes)


def project(item=None, *, inputs=None, **args):
    inputs = ({"source": item} if item is not None else {}) if inputs is None else inputs
    request = RequirementNode("project:id", Operator.PROJECT,
                              tuple(InputRef(key) for key in inputs), args)
    step = factory().build(node=request, dependencies=tuple(inputs), bindings={})
    return asyncio.run(step.execute(ExecutionContext(), inputs))


@pytest.mark.parametrize("args,reason", [
    ({"fields": ["value"], "aliases": ["bad"]}, "invalid_projection_alias"),
    ({"fields": ["value"], "aliases": {"absent": "unit"}}, "invalid_projection_alias"),
    ({"fields": ["value"], "aliases": {"value": ""}}, "invalid_projection_alias"),
    ({"fields": ["value"], "aliases": {"value": 0}}, "invalid_projection_alias"),
    ({"fields": ["value", "unit"], "aliases": {"value": "unit"}}, "projection_reserved_unit_alias"),
    ({"fields": ["value"], "aliases": {"value": "단위"}}, "projection_reserved_unit_alias"),
    ({"fields": ["value", "missing"], "aliases": {"value": "same", "missing": "same"}}, "projection_output_collision"),
    ({"fields": ["value", "value"]}, "projection_output_collision"),
])
def test_alias_validation_reserved_unit_and_collision_precede_missing_input(args, reason):
    assert project(**args) == TypedResult.abstain(reason)


@pytest.mark.parametrize("aliases", [None, {}, [], "", False])
def test_falsy_aliases_keep_legacy_default(aliases):
    item = source([{"value": 1}])
    assert project(item, field="value", aliases=aliases) == item


def test_actual_unit_can_be_renamed_to_unit_alias():
    item = source([{"unit": "kg", "value": 1}])
    result = project(item, fields=["unit", "value"], aliases={"unit": "단위", "value": "amount"})
    assert result == replace(item, value=[{"단위": "kg", "amount": 1}])


@pytest.mark.parametrize("field", ["minerals", "mineral_list"])
@pytest.mark.parametrize("status", [ResultStatus.SUCCESS, ResultStatus.PARTIAL, ResultStatus.FAILED])
@pytest.mark.parametrize("use_evidence", [False, True])
def test_document_minerals_take_rows_before_evidence_and_preserve_envelope(field, status, use_evidence):
    evidence = (Evidence("structured", "doc", "fixture", "| mineral_list |\n| --- |\n| 구리,리튬 |"),)
    rows = [] if use_evidence else [{"minerals": "니켈, 코발트, 니켈"}]
    item = source(rows, result_type=ValueType.DOCUMENT_EVIDENCE, status=status,
                  evidence=evidence, failure_reason="old", sufficient=False)
    expected = ["구리", "리튬"] if use_evidence else ["니켈", "코발트"]
    result = project(item, fields=[field], aliases={field: "renamed"})
    assert result == replace(item, value=expected, entity=tuple(expected), result_type=ValueType.MINERAL_SET)


@pytest.mark.parametrize("rows", [[], [{"title": "니켈 report without entity column"}]])
def test_document_empty_extraction_precedes_empty_list_and_discards_old_metadata(rows):
    item = source(rows, result_type=ValueType.DOCUMENT_EVIDENCE)
    assert project(item, fields=["minerals"]) == TypedResult.empty(
        ValueType.MINERAL_SET, "document_mineral_list_unavailable")


@pytest.mark.parametrize("status", list(ResultStatus))
@pytest.mark.parametrize("result_type", [ValueType.FACT_SET, ValueType.COMPOSITE])
def test_empty_list_preserves_status_and_type_before_field_checks(status, result_type):
    item = source([], status=status, result_type=result_type, sufficient=False, failure_reason="old")
    assert project(item, fields=["missing"]) == replace(item, value=[], entity=())


@pytest.mark.parametrize("units,extra_warning", [
    (["t", "kg"], True), (["t", None], True), (["t", "t"], False),
])
def test_heterogeneous_units_warning_survives_projection(units, extra_warning):
    item = source([{"value": index, "unit": unit} for index, unit in enumerate(units)])
    result = project(item, fields=["value"])
    assert result.warnings == (("existing", "heterogeneous_units") if extra_warning else ("existing",))
    assert result.value == [{"value": 0}, {"value": 1}]
    assert result.unit == "t"
    if extra_warning:
        again = project(replace(item, warnings=("existing", "heterogeneous_units")), fields=["value"])
        assert again.warnings == ("existing", "heterogeneous_units")


@pytest.mark.parametrize("mode", ["REPRESENTATIVE", "EXPLICIT", "ALL"])
def test_legacy_price_without_identity_drops_unavailable_identity_requests(mode):
    item = source([{"price": 10, "date": "2024-01-01"}], metric="price")
    result = project(item, fields=["price", "date", "price_measure", "price_measure_label",
                                  "price_criterion", "price_criterion_serial"], criterion_mode=mode)
    assert result == item and list(result.value[0]) == ["price", "date"]


@pytest.mark.parametrize("metric", ["price", "other"])
def test_literal_price_measure_uses_legacy_identity_append_order(metric):
    row = {"price": 10, "price_measure": "cash", "price_measure_label": "Cash",
           "price_criterion": "LME", "price_criterion_serial": 7}
    item = source([row], metric=metric)
    result = project(item, fields=["price"])
    assert result.value == [row]
    assert list(result.value[0]) == ["price", "price_measure", "price_measure_label",
                                    "price_criterion", "price_criterion_serial"]


def test_annotated_measure_without_literal_key_uses_registry_order():
    row = {"price": 10, "price_measure(label)": "cash", "price_measure_label": "Cash",
           "price_criterion": "LME", "price_criterion_serial": 7}
    result = project(source([row], metric="price"), fields=["price"])
    assert list(result.value[0]) == ["price", "price_measure", "price_criterion",
                                    "price_measure_label", "price_criterion_serial"]
    assert result.value[0]["price_measure"] == "cash"


def test_all_annotated_identity_columns_keep_strict_alias_ambiguity():
    row = {"price": 10, "price_measure(label)": "cash", "price_measure_label(label)": "Cash",
           "price_criterion(label)": "LME", "price_criterion_serial(label)": 7}
    result = project(source([row], metric="price"), fields=["price"])
    assert result.value == [{"price": 10, "price_measure": "cash", "price_criterion_serial": 7}]
    assert list(result.value[0]) == ["price", "price_measure", "price_criterion_serial"]


def test_price_criterion_can_supply_label_but_never_synthesizes_serial():
    item = source([{"price": 10, "price_criterion": "LME"}], metric="price")
    result = project(item, fields=["price", "price_criterion_serial"])
    assert result.value == [{"price": 10, "price_criterion": "LME", "price_measure_label": "LME"}]
    assert list(result.value[0]) == ["price", "price_criterion", "price_measure_label"]


@pytest.mark.parametrize("metric,row,field,expected", [
    ("inventory", {"value": 3}, "inventory", 3),
    ("inventory", {"재고량": 3}, "value", 3),
    ("inventory", {"inventory": 3}, "value", 3),
    ("price", {"cmerc_prc(통상가격)": 3}, "value", 3),
    ("production", {"production_volume": 3}, "value", 3),
    ("reserves", {"reserves_volume": 3}, "value", 3),
    ("indicator", {"value": None}, "value", None),
])
def test_value_aliases_are_limited_to_source_metric(metric, row, field, expected):
    assert project(source([row], metric=metric), fields=[field]).value == [{field: expected}]


@pytest.mark.parametrize("metric,row,field", [
    ("other", {"value": 3}, "inventory"), ("indicator", {"series": 3}, "value"),
    ("other", {"arbitrary_number": 3}, "value"),
])
def test_no_arbitrary_numeric_or_cross_metric_fallback(metric, row, field):
    assert project(source([row], metric=metric), fields=[field]) == TypedResult.abstain(
        f"projection_field_unavailable:{field}")


def test_unambiguous_metadata_fallback_and_row_null_precedence():
    item = source([{"value": 1}])
    result = project(item, fields=["value", "unit", "source", "entity", "mineral"])
    assert result.value == [{"value": 1, "unit": "t", "source": "fixture", "entity": "original", "mineral": "original"}]
    row = {"unit": None, "source": None, "entity": None}
    result = project(source([row]), fields=list(row))
    assert result.value == [row] and result.entity == ("original",)


@pytest.mark.parametrize("changes,field", [
    ({"unit": None}, "unit"), ({"source": ()}, "source"),
    ({"source": ("a", "b")}, "source"), ({"entity": ()}, "mineral"),
    ({"entity": ("a", "b")}, "entity"),
])
def test_missing_or_ambiguous_metadata_is_not_broadcast(changes, field):
    assert project(source([{"value": 1}], **changes), fields=[field]) == TypedResult.abstain(
        f"projection_field_unavailable:{field}")


@pytest.mark.parametrize("status", list(ResultStatus))
def test_only_success_rejects_rows_missing_a_resolved_column(status):
    item = source([{"value": 1}, {"other": 2}], status=status, failure_reason="old")
    result = project(item, fields=["value"])
    if status == ResultStatus.SUCCESS:
        assert result == TypedResult.abstain("projection_input_incomplete")
    else:
        assert result == replace(item, value=[{"value": 1}, {"value": None}])


@pytest.mark.parametrize("args,expected", [
    ({}, TypedResult.failed("missing_input")),
    ({"fields": ["value"]}, TypedResult.abstain("projection_field_unavailable:value")),
])
def test_missing_input_preserves_failure_precedence(args, expected):
    assert project(**args) == expected


@pytest.mark.parametrize("distinct,expected_count", [(True, 2), (False, 3), (1, 3)])
def test_partial_envelope_and_distinct_preserve_failed_rows(distinct, expected_count):
    good = {"value": 1, "status": "SUCCESS", "reason": None, "output": "price", "unit": "t"}
    bad = {"status": "FAILED", "reason": "missing", "output": "price", "unit": "t"}
    item = source([good, bad, dict(good)], status=ResultStatus.PARTIAL, result_type=ValueType.COMPOSITE)
    before = deepcopy(item)
    result = project(item, fields=["value"], distinct=distinct)
    assert result.status == ResultStatus.PARTIAL and result.result_type == ValueType.FACT_SET
    assert len(result.value) == expected_count
    assert result.value[:2] == [good, {"value": None, **bad}]
    assert result.evidence == item.evidence and result.provenance == item.provenance
    assert result.upstream_step_ids == item.upstream_step_ids and item == before


def test_partial_original_status_overwrites_projection_alias_target():
    item = source([{"value": 7, "status": "FAILED"}], status=ResultStatus.PARTIAL)
    assert project(item, fields=["value"], aliases={"value": "status"}).value == [{"status": "FAILED"}]


@pytest.mark.parametrize("distinct,expected", [(True, [1, 2]), (False, [1, 1, 2]), (1, [1, 1, 2])])
def test_success_distinct_requires_literal_true_and_preserves_order(distinct, expected):
    item = source([{"value": 1}, {"value": 1}, {"value": 2}])
    before = deepcopy(item)
    result = project(item, fields=["value"], distinct=distinct)
    assert result == replace(item, value=[{"value": value} for value in expected])
    assert item == before


def test_mineral_set_projection_and_entity_recomputation_do_not_restore_old_population():
    item = source(["니켈", "코발트"], result_type=ValueType.MINERAL_SET, entity=("stale",))
    result = project(item, fields=["entity"], distinct=True)
    assert result.value == [{"entity": "니켈"}, {"entity": "코발트"}]
    assert result.entity == ("니켈", "코발트") and result.result_type == ValueType.MINERAL_SET
    dropped = project(source([{"value": 1}], result_type=ValueType.MINERAL_SET), fields=["value"])
    assert dropped.entity == ()


def test_registered_projection_bypasses_legacy_derive():
    f = factory()
    item = source([{"value": 1}])
    request = RequirementNode("project", Operator.PROJECT, args={"fields": ["value"]})
    with patch.object(f, "_derive", side_effect=AssertionError("legacy derive called")) as legacy:
        step = f.build(node=request, dependencies=("source",), bindings={})
        result = asyncio.run(step.execute(ExecutionContext(), {"source": item}))
    legacy.assert_not_called()
    assert result == item


def test_function_step_identity_defaults_and_preexecution_cancel():
    request = RequirementNode("project:opaque", Operator.PROJECT, args={"fields": ["value"]})
    bindings = {"input_0": InputBinding("right", "index", 0), "input_1": InputBinding("left")}
    step = factory().build(node=request, dependencies=("right", "left"), bindings=bindings)
    assert type(step) is FunctionStep
    assert (step.step_id, step.operation, step.dependencies, step.bindings) == (
        request.node_id, "project", ("right", "left"), bindings)
    assert step.timeout_seconds is None and step.max_retries == 0
    step._handler = Mock(side_effect=AssertionError("cancelled handler called"))
    context = ExecutionContext()
    context.cancel()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(step.execute(context, {}))
    step._handler.assert_not_called()


@pytest.mark.parametrize("reverse", [False, True])
def test_runtime_inputref_order_not_completion_order_selects_source(reverse):
    order = ("right", "left") if reverse else ("left", "right")
    f = factory()
    program = SemanticProgram((
        RequirementNode("left", Operator.RETRIEVE, args={"metric": "price"}),
        RequirementNode("right", Operator.RETRIEVE, args={"metric": "price"}),
        RequirementNode("project", Operator.PROJECT, tuple(InputRef(name) for name in order), {"fields": ["value"]}),
    ), ("project",))

    async def run():
        released = asyncio.Event()
        completed = []

        def build(*, node, dependencies, bindings):
            if node.operator == Operator.PROJECT:
                return f.build(node=node, dependencies=dependencies, bindings=bindings)

            async def retrieve(_context, _inputs):
                if node.node_id == order[0]:
                    await released.wait()
                else:
                    released.set()
                completed.append(node.node_id)
                return source([{"value": node.node_id}], upstream_step_ids=())
            return FunctionStep(node.node_id, node.operator.value, retrieve)

        result = await PipeRuntime().execute(PipeLowerer(build).lower(program, pipe_id="projection-order"))
        return result, completed

    result, completed = asyncio.run(run())
    assert completed == list(reversed(order))
    assert result.results["project"].value == [{"value": order[0]}]
    assert result.results["project"].upstream_step_ids == ("left", "right")
    assert [event.event_type for event in result.events if event.step_id == "project"] == ["step_started", "step_completed"]


@pytest.mark.parametrize("status", list(ResultStatus))
def test_runtime_status_barrier_and_project_events(status):
    item = source([] if status == ResultStatus.EMPTY else [{"value": 1}], status=status, upstream_step_ids=())
    request = RequirementNode("project", Operator.PROJECT, (InputRef("source"),), {"fields": ["value"]})
    program = SemanticProgram((RequirementNode("source", Operator.RETRIEVE, args={"metric": "price"}), request), ("project",))
    step = factory().build(node=request, dependencies=("source",), bindings={"input_0": InputBinding("source")})
    step._handler = Mock(wraps=step._handler)

    def build(*, node, dependencies, bindings):
        return step if node.operator == Operator.PROJECT else FunctionStep("source", "retrieve", lambda _c, _i: item)

    result = asyncio.run(PipeRuntime().execute(PipeLowerer(build).lower(program, pipe_id="projection-status")))
    blocked = status in {ResultStatus.FAILED, ResultStatus.ABSTAINED, ResultStatus.DEPENDENCY_FAILED}
    projected = result.results["project"]
    assert projected.status == (ResultStatus.DEPENDENCY_FAILED if blocked else status)
    assert step._handler.call_count == (0 if blocked else 1)
    events = [event.event_type for event in result.events if event.step_id == "project"]
    assert events == (["step_skipped"] if blocked else ["step_started", "step_completed"])
    if blocked:
        assert projected.failure_reason == "upstream step failed: source"


@pytest.mark.parametrize("rows,reason", [
    ([{"other": 1}], "projection_field_unavailable:value"),
    ([{"value": 1}, {"other": 2}], "projection_input_incomplete"),
])
def test_runtime_projection_failure_emits_failed_event_without_fabricating_rows(rows, reason):
    request = RequirementNode("project", Operator.PROJECT, (InputRef("source"),), {"fields": ["value"]})
    program = SemanticProgram((RequirementNode("source", Operator.RETRIEVE, args={"metric": "price"}), request), ("project",))
    f = factory()

    def build(*, node, dependencies, bindings):
        if node.operator == Operator.PROJECT:
            return f.build(node=node, dependencies=dependencies, bindings=bindings)
        return FunctionStep("source", "retrieve", lambda _c, _i: source(rows))

    result = asyncio.run(PipeRuntime().execute(PipeLowerer(build).lower(program, pipe_id="projection-failure")))
    projected = result.results["project"]
    assert projected.status == ResultStatus.ABSTAINED and projected.failure_reason == reason
    assert projected.value is None and projected.evidence == ()
    assert projected.upstream_step_ids == ("source",)
    assert [event.event_type for event in result.events if event.step_id == "project"] == ["step_started", "step_failed"]
