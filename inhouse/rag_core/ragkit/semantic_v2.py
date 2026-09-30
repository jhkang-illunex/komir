"""Independent semantic IR v2 and legacy-action lowering boundary.

The v2 models describe user meaning only.  Physical ``ActionId`` values are
introduced exclusively by :class:`LegacyActionLowerer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .action_contract import ActionCall, ActionSlots, Period

_logger = logging.getLogger(__name__)


class Metric(str, Enum):
    USAGE = "usage"
    PRICE = "price"
    PRICE_CHANGE = "price_change"
    IMPORT_VALUE = "import_value"
    IMPORT_CHANGE = "import_change"
    PRODUCTION = "production"
    RESERVES = "reserves"
    COUNTRY_SHARE = "country_share"
    CONCENTRATION = "concentration"
    DOCUMENT_EVIDENCE = "document_evidence"


class Primitive(str, Enum):
    RETRIEVE = "Retrieve"
    CALCULATE = "Calculate"
    FILTER = "Filter"
    SORT = "Sort"
    TOP_K = "TopK"
    SELECT = "Select"
    AGGREGATE = "Aggregate"
    COMPARE = "Compare"
    JOIN = "Join"
    PROJECT = "Project"
    COMPOSITE = "Composite"


class EntityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = "mineral"
    value: str | None = None
    source_node: str | None = None
    field: str | None = None


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    value: int | None = Field(default=None, ge=1, le=240)
    start: str | None = None
    end: str | None = None

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "TimeRange":  # type: ignore[override]
        if isinstance(obj, dict) and obj.get("kind") == "relative" and obj.get("value"):
            # Structured synonym normalization only; no raw-query inspection.
            obj = {**obj, "kind": "trailing_months"}
        return super().model_validate(obj, **kwargs)

    def to_period(self) -> Period:
        if self.kind == "trailing_months":
            return Period(kind="trailing_months", trailing_months=self.value)
        if self.kind == "calendar_year":
            return Period(kind="calendar_year", calendar_year=self.value)
        if self.kind == "range":
            return Period(kind="range", start=self.start, end=self.end)
        if self.kind == "latest":
            return Period(kind="latest")
        raise ValueError(f"unsupported v2 time range: {self.kind}")


class SemanticRequirementV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str
    entity: EntityRef | None = None
    metric: Metric
    time_range: TimeRange | None = None
    flow: str | None = None
    scope: str | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=list)
    selection: dict[str, Any] | None = None


class RequestedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal[
        "usage", "current_price", "date", "value", "price", "mineral_info",
        "price_comparison", "concentration", "price_output", "usage_output",
    ]
    source_node: str | None = None
    fields: list[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def canonicalize(cls, value: Any) -> Any:
        return {
            "usage_info": "usage",
            "usage_details": "usage",
            "usage_field": "usage",
            "usage_output": "usage",
            "latest_nickel_price": "current_price",
            "price_field": "price",
        }.get(str(value), value)


class RelationshipSpec(BaseModel):
    """Semantic relation between requirements; contains no physical action."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["filter", "compare", "join"]
    inputs: list[str] = Field(min_length=1)
    join_key: str | None = None
    predicate: dict[str, Any] | None = None
    fields: list[str] = Field(default_factory=list)


class SemanticRequirementPlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "semantic-requirement-v2"
    requirements: list[SemanticRequirementV2] = Field(min_length=1)
    requested_outputs: list[RequestedOutput] = Field(default_factory=list)
    presentation: dict[str, Any] = Field(default_factory=dict)
    relationships: list[RelationshipSpec] = Field(default_factory=list)


V2_SEMANTIC_PROMPT = """자연어 BI 질문을 semantic-requirement-v2 JSON으로 변환한다.
사용자가 무엇을 원하는지만 표현하며 실행 방법은 표현하지 않는다.
반드시 다음만 사용한다: entities, requirements, requested_outputs, presentation,
relationships.
requirements.metric은 usage, price, price_change, import_value, import_change,
production, reserves, country_share, concentration, document_evidence 중 하나다.
requirements에는 entity, metric, time_range, flow, scope, constraints,
requested_outputs, selection을 사용할 수 있다.
requirement 사이의 filter/compare/join 관계가 명시되면 relationships에 기록한다.
relationships의 inputs는 requirements의 requirement_id만 사용한다.

절대 출력하지 말 것: ActionId, IntentCall, ActionCall, actor, tool, SQL, table,
physical route. 복합 요구는 requirement를 여러 개 생성하고 requested_outputs를
모두 보존한다. 최근/현재 가격은 metric=price와 time_range.kind=latest로 표현한다.
최고·최저 시점은 selection={"mode":"argmax"|"argmin","field":"value"}로
표현한다. 결과 전체가 아니라 선택 결과만 요구되면 requested_outputs에 date/value를
기록한다. JSON 외 설명은 출력하지 않는다."""


class V2ShadowTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    raw_output: dict[str, Any] | None = None
    semantic_plan: dict[str, Any] | None = None
    logical_program: dict[str, Any] | None = None
    lowering: list[dict[str, Any]] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=list)
    roots: list[str] = Field(default_factory=list)
    intermediate_nodes: list[str] = Field(default_factory=list)
    failure_class: str | None = None
    failure_reason: str | None = None


def parse_v2_shadow(
    question: str,
    llm: Any,
    *,
    semantic_context: Any | None = None,
) -> V2ShadowTrace:
    """Run the independent V2 parser; never raises into production routing."""
    trace = V2ShadowTrace(question=question)
    if llm is None or not hasattr(llm, "invoke"):
        return trace.model_copy(update={"failure_class": "PARSER_MISSING_OUTPUT", "failure_reason": "llm_unavailable"})
    try:
        invocation = llm.invoke(
            task="semantic_requirement_v2",
            instructions=V2_SEMANTIC_PROMPT,
            payload={"question": question, "semantic_context": (
                semantic_context.model_dump(mode="json") if hasattr(semantic_context, "model_dump") else semantic_context
            )},
            output_model=SemanticRequirementPlanV2,
            max_tokens=1200,
        )
        candidate = invocation.output
        if not isinstance(candidate, SemanticRequirementPlanV2):
            return trace.model_copy(update={"failure_class": "PARSER_MISSING_OUTPUT", "failure_reason": "schema_invalid"})
        raw = candidate.model_dump(mode="json")
        updated = trace.model_copy(update={
            "raw_output": raw,
            "semantic_plan": raw,
            "requested_outputs": [item.name for item in candidate.requested_outputs],
        })
        try:
            logical = logical_program_from_requirements(candidate)
        except ValueError as exc:
            return updated.model_copy(update={"failure_class": "LOGICAL_PLAN_INCOMPLETE", "failure_reason": str(exc)})
        try:
            calls = LegacyActionLowerer().lower(logical)
        except ValueError as exc:
            return updated.model_copy(update={
                "logical_program": logical.to_dict(),
                "roots": logical.roots,
                "intermediate_nodes": [node.node_id for node in logical.nodes if node.node_id not in logical.roots],
                "failure_class": "LOWERING_FAILURE",
                "failure_reason": str(exc),
            })
        return updated.model_copy(update={
            "logical_program": logical.to_dict(),
            "roots": logical.roots,
            "intermediate_nodes": [node.node_id for node in logical.nodes if node.node_id not in logical.roots],
            "lowering": [call.model_dump(mode="json") for call in calls],
        })
    except Exception as exc:
        return trace.model_copy(update={"failure_class": "PARSER_MISSING_OUTPUT", "failure_reason": f"{type(exc).__name__}:{exc}"})


def record_v2_shadow(trace: V2ShadowTrace) -> None:
    """Emit an inspectable shadow record without coupling runtime behavior."""
    _logger.info("semantic_v2_shadow=%s", trace.model_dump(mode="json"))


class InputRefV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    selector: str = "all"
    value: str | int | None = None


class LogicalNodeV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    op: Primitive
    inputs: list[InputRefV2] = Field(default_factory=list)
    arguments: dict[str, Any] = Field(default_factory=dict)
    output_type: str
    requested: bool = False


class LogicalProgramV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "logical-primitive-v2"
    nodes: list[LogicalNodeV2] = Field(min_length=1)
    roots: list[str] = Field(min_length=1)

    def validate_structure(self) -> None:
        ids = {node.node_id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("duplicate logical node id")
        if not set(self.roots) <= ids:
            raise ValueError("logical root references unknown node")
        for node in self.nodes:
            for ref in node.inputs:
                if ref.node_id not in ids:
                    raise ValueError(f"{node.node_id} references unknown node {ref.node_id}")
                if ref.selector not in {"all", "field", "index"}:
                    raise ValueError(f"unsupported semantic selector: {ref.selector}")
            if node.op == Primitive.CALCULATE and not node.inputs:
                raise ValueError(f"calculate node has no upstream input: {node.node_id}")
        state: dict[str, int] = {}
        by_id = {node.node_id: node for node in self.nodes}

        def visit(node_id: str) -> None:
            mark = state.get(node_id, 0)
            if mark == 1:
                raise ValueError(f"cycle in logical AST: {node_id}")
            if mark == 2:
                return
            state[node_id] = 1
            for ref in by_id[node_id].inputs:
                visit(ref.node_id)
            state[node_id] = 2

        for node in self.nodes:
            visit(node.node_id)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DeterministicLogicalPlanner:
    """Build a logical DAG from typed requirements, never from raw language."""

    _BASE_METRIC: dict[Metric, Metric] = {
        Metric.PRICE_CHANGE: Metric.PRICE,
        Metric.IMPORT_CHANGE: Metric.IMPORT_VALUE,
    }

    def plan(self, plan: SemanticRequirementPlanV2) -> LogicalProgramV2:
        plan_nodes: list[LogicalNodeV2] = []
        roots: list[str] = []
        requirement_roots: dict[str, str] = {}
        for req in plan.requirements:
            entity = req.entity.model_dump(mode="json") if req.entity else None
            base_metric = self._BASE_METRIC.get(req.metric)
            if base_metric is not None:
                retrieve_id = f"{req.requirement_id}_retrieve"
                plan_nodes.append(LogicalNodeV2(
                    node_id=retrieve_id,
                    op=Primitive.RETRIEVE,
                    arguments=self._arguments(req, base_metric, entity),
                    output_type="TimeSeries" if base_metric == Metric.PRICE else "FactSet",
                ))
                node_id = req.requirement_id
                plan_nodes.append(LogicalNodeV2(
                    node_id=node_id,
                    op=Primitive.CALCULATE,
                    inputs=[InputRefV2(node_id=retrieve_id)],
                    arguments={"metric": req.metric.value},
                    output_type="FactSet",
                ))
            else:
                node_id = req.requirement_id
                plan_nodes.append(LogicalNodeV2(
                    node_id=node_id,
                    op=Primitive.RETRIEVE,
                    arguments=self._arguments(req, req.metric, entity),
                    output_type="DocumentEvidence" if req.metric in {Metric.USAGE, Metric.DOCUMENT_EVIDENCE} else "FactSet",
                ))

            if req.selection:
                node_id = self._add_selection(plan_nodes, node_id, req)
            if req.limit and not req.selection:
                sort_id = f"{node_id}_sort"
                plan_nodes.append(LogicalNodeV2(
                    node_id=sort_id,
                    op=Primitive.SORT,
                    inputs=[InputRefV2(node_id=node_id)],
                    arguments={"field": req.metric.value, "order": "desc"},
                    output_type="FactSet",
                ))
                node_id = f"{node_id}_topk"
                plan_nodes.append(LogicalNodeV2(
                    node_id=node_id,
                    op=Primitive.TOP_K,
                    inputs=[InputRefV2(node_id=sort_id)],
                    arguments={"k": req.limit},
                    output_type="EntitySet",
                ))
            requirement_roots[req.requirement_id] = node_id
            roots.append(node_id)

        relation_roots: list[str] = []
        for relation in plan.relationships:
            inputs = [requirement_roots[item] for item in relation.inputs if item in requirement_roots]
            if len(inputs) != len(relation.inputs):
                raise ValueError(f"relationship references unknown requirement: {relation.inputs}")
            if relation.kind == "filter":
                node_id = f"relation_filter_{len(relation_roots)}"
                node = LogicalNodeV2(node_id=node_id, op=Primitive.FILTER,
                    inputs=[InputRefV2(node_id=item) for item in inputs],
                    arguments={"predicate": relation.predicate or {}}, output_type="FactSet", requested=True)
            elif relation.kind == "compare":
                node_id = f"relation_compare_{len(relation_roots)}"
                node = LogicalNodeV2(node_id=node_id, op=Primitive.COMPARE,
                    inputs=[InputRefV2(node_id=item) for item in inputs],
                    arguments={"join_key": relation.join_key, "fields": relation.fields}, output_type="Comparison", requested=True)
            else:
                node_id = f"relation_join_{len(relation_roots)}"
                node = LogicalNodeV2(node_id=node_id, op=Primitive.JOIN,
                    inputs=[InputRefV2(node_id=item) for item in inputs],
                    arguments={"join_key": relation.join_key}, output_type="FactSet", requested=True)
            plan_nodes.append(node)
            relation_roots.append(node_id)
        if relation_roots:
            roots = relation_roots

        requested_names = {item.name for item in plan.requested_outputs}
        if len(roots) > 1 and (plan.presentation.get("type") == "comparison" or "price_comparison" in requested_names):
            compare_id = "comparison_root"
            plan_nodes.append(LogicalNodeV2(
                node_id=compare_id, op=Primitive.COMPARE,
                inputs=[InputRefV2(node_id=node_id) for node_id in roots],
                arguments={"fields": list(requested_names)}, output_type="Comparison", requested=True,
            ))
            roots = [compare_id]
        if len(roots) > 1:
            composite_id = "composite_root"
            plan_nodes.append(LogicalNodeV2(
                node_id=composite_id, op=Primitive.COMPOSITE,
                inputs=[InputRefV2(node_id=node_id) for node_id in roots],
                arguments={"requested_outputs": [item.name for item in plan.requested_outputs]},
                output_type="CompositeResult", requested=True,
            ))
            roots = [composite_id]
        program = LogicalProgramV2(nodes=plan_nodes, roots=roots)
        program.validate_structure()
        return program

    @staticmethod
    def _arguments(req: SemanticRequirementV2, metric: Metric, entity: dict[str, Any] | None) -> dict[str, Any]:
        args: dict[str, Any] = {"entity": entity, "metric": metric.value}
        if req.time_range:
            args["time_range"] = req.time_range.model_dump(mode="json")
        if req.flow:
            args["flow"] = req.flow
        if req.scope:
            args["scope"] = req.scope
        return args

    @staticmethod
    def _add_selection(nodes: list[LogicalNodeV2], source_id: str, req: SemanticRequirementV2) -> str:
        selection = req.selection or {}
        mode = str(selection.get("mode", ""))
        if mode in {"rank", "sort", "desc", "asc"} or req.limit:
            sort_id = f"{source_id}_sort"
            nodes.append(LogicalNodeV2(node_id=sort_id, op=Primitive.SORT,
                inputs=[InputRefV2(node_id=source_id)], arguments=dict(selection), output_type="FactSet"))
            if req.limit:
                top_id = f"{source_id}_topk"
                nodes.append(LogicalNodeV2(node_id=top_id, op=Primitive.TOP_K,
                    inputs=[InputRefV2(node_id=sort_id)], arguments={"k": req.limit}, output_type="EntitySet"))
                return top_id
            return sort_id
        select_id = f"{source_id}_select"
        nodes.append(LogicalNodeV2(node_id=select_id, op=Primitive.SELECT,
            inputs=[InputRefV2(node_id=source_id)], arguments=dict(selection),
            output_type="PriceObservation", requested=bool(req.requested_outputs)))
        return select_id


def logical_program_from_requirements(plan: SemanticRequirementPlanV2) -> LogicalProgramV2:
    """Compatibility wrapper for callers of the pre-planner API."""
    return DeterministicLogicalPlanner().plan(plan)


def validate_output_coverage(
    plan: SemanticRequirementPlanV2,
    produced: Mapping[str, set[str]],
) -> tuple[str, ...]:
    """Validate requested semantic outputs without reading the raw query."""
    required = {item.name for item in plan.requested_outputs}
    available = set().union(*(set(fields) for fields in produced.values())) if produced else set()
    return tuple(sorted(required - available))


@dataclass(frozen=True)
class Capability:
    name: str
    metrics: frozenset[Metric]
    physical_action: str
    output_type: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability("document_usage", frozenset({Metric.USAGE, Metric.DOCUMENT_EVIDENCE}), "document.retrieve", "DocumentEvidence"),
    Capability("price_series", frozenset({Metric.PRICE}), "price.series", "TimeSeries<PriceObservation>"),
    Capability("trade_value", frozenset({Metric.IMPORT_VALUE, Metric.IMPORT_CHANGE}), "trade.indicator", "FactSet"),
    Capability("trade_concentration", frozenset({Metric.CONCENTRATION}), "trade.concentration", "FactSet"),
    Capability("resource_fact", frozenset({Metric.PRODUCTION, Metric.RESERVES}), "resource.rank", "FactSet"),
)


class LegacyActionLowerer:
    """Lower only after logical AST validation; this is the first ActionId boundary."""

    def __init__(self, capabilities: tuple[Capability, ...] = CAPABILITIES) -> None:
        self._capabilities = capabilities

    def lower(self, program: LogicalProgramV2) -> list[ActionCall]:
        program.validate_structure()
        calls: list[ActionCall] = []
        for node in program.nodes:
            if node.op == Primitive.COMPARE:
                calls.append(ActionCall(
                    requirement_id=node.node_id,
                    action_id="price.compare",
                    slots=ActionSlots(minerals=list(node.arguments.get("entities", []))),
                ))
                continue
            # Calculate/Filter/Sort/TopK/Project are logical runtime steps;
            # only data access nodes cross the legacy Action boundary here.
            if node.op != Primitive.RETRIEVE:
                continue
            metric = str(node.arguments.get("metric", ""))
            capability = next((item for item in self._capabilities if Metric(metric) in item.metrics), None)
            if capability is None:
                raise ValueError(f"no capability for semantic metric: {metric}")
            entity = node.arguments.get("entity") or {}
            slots = ActionSlots()
            if isinstance(entity, Mapping):
                slots = slots.model_copy(update={"mineral": entity.get("value")})
            time_range = node.arguments.get("time_range")
            if isinstance(time_range, Mapping):
                slots = slots.model_copy(update={"period": TimeRange.model_validate(time_range).to_period()})
            if capability.physical_action == "document.retrieve":
                topic = f"{entity.get('value', '')} 용도".strip()
                slots = slots.model_copy(update={"topic": topic})
            if capability.physical_action == "trade.concentration":
                slots = slots.model_copy(update={"flow": node.arguments.get("flow", "import")})
            calls.append(ActionCall(
                requirement_id=node.node_id,
                action_id=capability.physical_action,
                slots=slots,
            ))
        return calls


__all__ = [
    "CAPABILITIES", "Capability", "DeterministicLogicalPlanner", "EntityRef", "InputRefV2", "LegacyActionLowerer",
    "LogicalNodeV2", "LogicalProgramV2", "Metric", "Primitive", "RequestedOutput",
    "RelationshipSpec", "SemanticRequirementPlanV2", "SemanticRequirementV2", "TimeRange", "V2_SEMANTIC_PROMPT",
    "V2ShadowTrace", "logical_program_from_requirements", "parse_v2_shadow", "record_v2_shadow",
    "validate_output_coverage",
]
