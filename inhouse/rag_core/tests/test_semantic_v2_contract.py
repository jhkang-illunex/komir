import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_core.ragkit.semantic_v2 import (  # noqa: E402
    EntityRef,
    InputRefV2,
    LegacyActionLowerer,
    LogicalNodeV2,
    LogicalProgramV2,
    Metric,
    Primitive,
    RequestedOutput,
    SemanticRequirementPlanV2,
    SemanticRequirementV2,
    TimeRange,
    logical_program_from_requirements,
    validate_output_coverage,
    parse_v2_shadow,
    RelationshipSpec,
    DeterministicLogicalPlanner,
)


def _plan(*requirements, outputs=()):
    return SemanticRequirementPlanV2(
        requirements=list(requirements),
        requested_outputs=[RequestedOutput(name=item) for item in outputs],
    )


def test_a_usage_and_current_price_has_no_action_id_until_lowering():
    plan = _plan(
        SemanticRequirementV2(requirement_id="usage", entity=EntityRef(value="니켈"), metric=Metric.USAGE, requested_outputs=["usage"]),
        SemanticRequirementV2(requirement_id="price", entity=EntityRef(value="니켈"), metric=Metric.PRICE, time_range=TimeRange(kind="latest"), requested_outputs=["current_price"]),
        outputs=("usage", "current_price"),
    )
    logical = logical_program_from_requirements(plan)
    assert all("action_id" not in node.model_dump() for node in logical.nodes)
    calls = LegacyActionLowerer().lower(logical)
    assert {call.action_id for call in calls} == {"document.retrieve", "price.series"}
    assert validate_output_coverage(plan, {"usage": {"usage"}, "price": {"current_price"}}) == ()


def test_b_price_three_months_selects_max_then_projects_requested_fields():
    plan = _plan(SemanticRequirementV2(
        requirement_id="price",
        entity=EntityRef(value="구리"),
        metric=Metric.PRICE,
        time_range=TimeRange(kind="trailing_months", value=3),
        selection={"mode": "argmax", "field": "value"},
        requested_outputs=["date", "price"],
    ), outputs=("date", "price"))
    logical = logical_program_from_requirements(plan)
    assert [node.op for node in logical.nodes] == [Primitive.RETRIEVE, Primitive.SELECT]
    assert logical.roots == ["price_select"]
    calls = LegacyActionLowerer().lower(logical)
    assert len(calls) == 1
    assert calls[0].action_id == "price.series"
    assert calls[0].slots.period.trailing_months == 3


def test_c_price_top5_then_import_change_filter_keeps_dependency_nodes():
    logical = LogicalProgramV2(nodes=[
        LogicalNodeV2(node_id="price", op=Primitive.RETRIEVE, arguments={"metric": "price"}, output_type="TimeSeries"),
        LogicalNodeV2(node_id="change", op=Primitive.CALCULATE, inputs=[InputRefV2(node_id="price")], arguments={"metric": "price_change"}, output_type="FactSet"),
        LogicalNodeV2(node_id="top5", op=Primitive.TOP_K, inputs=[InputRefV2(node_id="change")], arguments={"k": 5}, output_type="EntitySet"),
        LogicalNodeV2(node_id="imports", op=Primitive.RETRIEVE, inputs=[InputRefV2(node_id="top5", selector="field", value="entity")], arguments={"metric": "import_value", "flow": "import"}, output_type="FactSet"),
        LogicalNodeV2(node_id="import_change", op=Primitive.CALCULATE, inputs=[InputRefV2(node_id="imports")], arguments={"metric": "import_change"}, output_type="FactSet"),
        LogicalNodeV2(node_id="filtered", op=Primitive.FILTER, inputs=[InputRefV2(node_id="import_change")], arguments={"field": "change_rate", "operator": ">", "value": 0}, output_type="FactSet", requested=True),
    ], roots=["filtered"])
    calls = LegacyActionLowerer().lower(logical)
    assert [call.action_id for call in calls] == ["price.series", "trade.indicator"]
    assert logical.roots == ["filtered"]


def test_d_compare_is_lowered_to_existing_price_compare():
    logical = LogicalProgramV2(nodes=[
        LogicalNodeV2(node_id="compare", op=Primitive.COMPARE, arguments={"entities": ["구리", "니켈"]}, output_type="Comparison", requested=True),
    ], roots=["compare"])
    calls = LegacyActionLowerer().lower(logical)
    assert len(calls) == 1
    assert calls[0].action_id == "price.compare"
    assert calls[0].slots.minerals == ["구리", "니켈"]


def test_e_concentration_and_price_are_two_logical_branches():
    logical = LogicalProgramV2(nodes=[
        LogicalNodeV2(node_id="concentration", op=Primitive.RETRIEVE, arguments={"metric": "concentration", "flow": "import"}, output_type="FactSet"),
        LogicalNodeV2(node_id="price", op=Primitive.RETRIEVE, arguments={"metric": "price"}, output_type="TimeSeries"),
        LogicalNodeV2(node_id="root", op=Primitive.COMPOSITE, inputs=[InputRefV2(node_id="concentration"), InputRefV2(node_id="price")], arguments={"requested_outputs": ["concentration", "price"]}, output_type="CompositeResult", requested=True),
    ], roots=["root"])
    calls = LegacyActionLowerer().lower(logical)
    assert [call.action_id for call in calls] == ["trade.concentration", "price.series"]
    assert logical.roots == ["root"]


def test_v2_shadow_adapter_accepts_gemma_structured_plan_and_never_changes_production():
    class Invocation:
        output = _plan(
            SemanticRequirementV2(requirement_id="usage", entity=EntityRef(value="니켈"), metric=Metric.USAGE, requested_outputs=["usage"]),
            SemanticRequirementV2(requirement_id="price", entity=EntityRef(value="니켈"), metric=Metric.PRICE, time_range=TimeRange(kind="latest"), requested_outputs=["current_price"]),
            outputs=("usage", "current_price"),
        )

    class FakeGemma:
        def __init__(self):
            self.calls = []

        def invoke(self, **kwargs):
            self.calls.append(kwargs)
            return Invocation()

    llm = FakeGemma()
    trace = parse_v2_shadow("니켈은 어디에 쓰이고 지금은 얼마야?", llm)
    assert trace.failure_class is None
    assert trace.requested_outputs == ["usage", "current_price"]
    assert {item["action_id"] for item in trace.lowering} == {"document.retrieve", "price.series"}
    assert all("action_id" not in node for node in trace.logical_program["nodes"])
    assert llm.calls[0]["task"] == "semantic_requirement_v2"


def test_deterministic_planner_expands_change_metric_into_retrieve_and_calculate():
    plan = _plan(
        SemanticRequirementV2(requirement_id="r", entity=EntityRef(value="리튬"), metric=Metric.PRICE_CHANGE, limit=5),
        outputs=("mineral_info",),
    )
    logical = DeterministicLogicalPlanner().plan(plan)
    assert [node.op for node in logical.nodes] == [Primitive.RETRIEVE, Primitive.CALCULATE, Primitive.SORT, Primitive.TOP_K]
    assert logical.roots == ["r_topk"]


def test_relationship_spec_builds_filter_and_compare_without_physical_action_names():
    plan = SemanticRequirementPlanV2(
        requirements=[
            SemanticRequirementV2(requirement_id="imports", entity=EntityRef(value="리튬"), metric=Metric.IMPORT_CHANGE),
            SemanticRequirementV2(requirement_id="price", entity=EntityRef(value="리튬"), metric=Metric.PRICE),
        ],
        requested_outputs=[RequestedOutput(name="price_comparison")],
        relationships=[RelationshipSpec(
            kind="compare", inputs=["imports", "price"], join_key="entity",
            fields=["import_change", "price"],
        )],
    )
    logical = DeterministicLogicalPlanner().plan(plan)
    relation = next(node for node in logical.nodes if node.node_id == "relation_compare_0")
    assert relation.op == Primitive.COMPARE
    assert all("action_id" not in node.model_dump() for node in logical.nodes)
