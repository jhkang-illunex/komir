"""Independent semantic IR v2 and legacy-action lowering boundary.

The v2 models describe user meaning only.  Physical ``ActionId`` values are
introduced exclusively by :class:`LegacyActionLowerer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .action_contract import ActionCall, ActionSlots, Period


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
    name: str
    source_node: str | None = None
    fields: list[str] = Field(default_factory=list)


class SemanticRequirementPlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "semantic-requirement-v2"
    requirements: list[SemanticRequirementV2] = Field(min_length=1)
    requested_outputs: list[RequestedOutput] = Field(default_factory=list)
    presentation: dict[str, Any] = Field(default_factory=dict)


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


def logical_program_from_requirements(plan: SemanticRequirementPlanV2) -> LogicalProgramV2:
    """Compile requirements into a small logical AST without physical names."""
    nodes: list[LogicalNodeV2] = []
    roots: list[str] = []
    for req in plan.requirements:
        entity = req.entity.model_dump(mode="json") if req.entity else None
        node_id = req.requirement_id
        if req.metric == Metric.USAGE or req.metric == Metric.DOCUMENT_EVIDENCE:
            op = Primitive.RETRIEVE
            output_type = "DocumentEvidence"
        elif req.metric == Metric.PRICE:
            op = Primitive.RETRIEVE
            output_type = "TimeSeries<PriceObservation>"
        elif req.metric in {Metric.PRICE_CHANGE, Metric.IMPORT_CHANGE}:
            op = Primitive.CALCULATE
            output_type = "FactSet"
        else:
            op = Primitive.RETRIEVE
            output_type = "FactSet"
        args = {"entity": entity, "metric": req.metric.value}
        if req.time_range:
            args["time_range"] = req.time_range.model_dump(mode="json")
        if req.flow:
            args["flow"] = req.flow
        if req.scope:
            args["scope"] = req.scope
        if req.selection:
            args["selection"] = req.selection
        nodes.append(LogicalNodeV2(
            node_id=node_id,
            op=op,
            arguments=args,
            output_type=output_type,
            requested=bool(req.requested_outputs),
        ))
        roots.append(node_id)
        if req.selection and req.metric == Metric.PRICE:
            select_id = f"{node_id}_select"
            nodes.append(LogicalNodeV2(
                node_id=select_id,
                op=Primitive.SELECT,
                inputs=[InputRefV2(node_id=node_id)],
                arguments=dict(req.selection),
                output_type="PriceObservation",
                requested=bool(req.requested_outputs),
            ))
            roots[-1] = select_id
    if len(roots) > 1:
        composite_id = "composite_root"
        nodes.append(LogicalNodeV2(
            node_id=composite_id,
            op=Primitive.COMPOSITE,
            inputs=[InputRefV2(node_id=node_id) for node_id in roots],
            arguments={"requested_outputs": [item.name for item in plan.requested_outputs]},
            output_type="CompositeResult",
            requested=True,
        ))
        roots = [composite_id]
    program = LogicalProgramV2(nodes=nodes, roots=roots)
    program.validate_structure()
    return program


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
    "CAPABILITIES", "Capability", "EntityRef", "InputRefV2", "LegacyActionLowerer",
    "LogicalNodeV2", "LogicalProgramV2", "Metric", "Primitive", "RequestedOutput",
    "SemanticRequirementPlanV2", "SemanticRequirementV2", "TimeRange",
    "logical_program_from_requirements", "validate_output_coverage",
]
