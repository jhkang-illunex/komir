"""Typed semantic IR for composable conversational BI requirements.

This module deliberately does not know physical action IDs or MCP tools.  It is
the small compiler-facing representation between semantic parsing and lowering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Operator(str, Enum):
    ENTITY = "entity"
    RETRIEVE = "retrieve"
    RETRIEVE_DOCUMENT = "retrieve_document"
    FILTER = "filter"
    PROJECT = "project"
    SORT = "sort"
    RANK = "rank"
    TOP_K = "top_k"
    AGGREGATE = "aggregate"
    COMPARE = "compare"
    ARG_MAX = "arg_max"
    ARG_MIN = "arg_min"
    JOIN = "join"
    CALCULATE = "calculate"
    RESOLVE_REFERENCE = "resolve_reference"
    VALIDATE_EVIDENCE = "validate_evidence"


class ValueType(str, Enum):
    UNKNOWN = "unknown"
    MINERAL_SET = "mineral_set"
    MINERAL_RANKING = "mineral_ranking"
    TIME_SERIES = "time_series"
    TRADE_SERIES = "trade_series"
    COUNTRY_SHARE = "country_share"
    SCALAR_METRIC = "scalar_metric"
    FACT_SET = "fact_set"
    DOCUMENT_EVIDENCE = "document_evidence"
    TABLE = "table"
    CHART = "chart"
    COMPOSITE = "composite"


@dataclass(frozen=True, slots=True)
class InputRef:
    """A typed edge in the semantic dependency graph."""

    node_id: str
    selector: str = "all"
    selector_value: str | int | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"node_id": self.node_id, "selector": self.selector}
        if self.selector_value is not None:
            result["selector_value"] = self.selector_value
        return result


@dataclass(frozen=True, slots=True)
class RequirementNode:
    node_id: str
    operator: Operator
    inputs: tuple[InputRef, ...] = ()
    args: Mapping[str, Any] = field(default_factory=dict)
    expected_type: ValueType = ValueType.UNKNOWN
    constraints: Mapping[str, Any] = field(default_factory=dict)
    evidence_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "operator": self.operator.value,
            "inputs": [item.to_dict() for item in self.inputs],
            "args": dict(self.args),
            "expected_type": self.expected_type.value,
            "constraints": dict(self.constraints),
            "evidence_required": self.evidence_required,
        }


@dataclass(frozen=True, slots=True)
class SemanticProgram:
    """A validated, inspectable semantic DAG before physical lowering."""

    nodes: tuple[RequirementNode, ...]
    roots: tuple[str, ...]

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SemanticProgram":
        def value_type(raw: Any) -> ValueType:
            candidate = str(raw)
            try:
                return ValueType(candidate)
            except ValueError:
                # The parser may use a model-local synonym such as "list" or
                # "float". Unknown output is intentionally not treated as a
                # stronger type; it is normalized to unknown and must still
                # pass downstream operator/evidence validation.
                return ValueType.UNKNOWN

        nodes = tuple(
            RequirementNode(
                node_id=str(item["node_id"]),
                operator=Operator(str(item["operator"])),
                inputs=tuple(
                    InputRef(
                        node_id=str(ref["node_id"]),
                        selector=str(ref.get("selector", "all")),
                        selector_value=ref.get("selector_value"),
                    )
                    for ref in item.get("inputs", [])
                ),
                args=dict(item.get("args", {})),
                expected_type=value_type(item.get("expected_type", ValueType.UNKNOWN.value)),
                constraints=dict(item.get("constraints", {})),
                evidence_required=bool(item.get("evidence_required", True)),
            )
            for item in payload.get("nodes", [])
        )
        roots = tuple(str(root) for root in payload.get("roots", []))
        # Models occasionally emit the first node as ``roots`` even when a
        # downstream node is the actual result. Keep the explicit roots when
        # they are already graph sinks; otherwise normalize within the same
        # dependency component to the terminal nodes. This is a structural
        # contract repair, not a query-specific execution branch.
        node_ids = {node.node_id for node in nodes}
        children: dict[str, list[str]] = {node.node_id: [] for node in nodes}
        for node in nodes:
            for ref in node.inputs:
                children.setdefault(ref.node_id, []).append(node.node_id)
        sinks = {node_id for node_id, downstream in children.items() if not downstream}
        if roots and any(root not in sinks for root in roots):
            reachable: set[str] = set()
            frontier = [root for root in roots if root in node_ids]
            while frontier:
                current = frontier.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                frontier.extend(children.get(current, ()))
            normalized = tuple(node_id for node_id in (node.node_id for node in nodes) if node_id in sinks and node_id in reachable)
            if normalized:
                roots = normalized
        return cls(nodes=nodes, roots=roots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "roots": list(self.roots),
        }

    def validate(self) -> None:
        node_map: dict[str, RequirementNode] = {}
        for node in self.nodes:
            if not node.node_id:
                raise ValueError("semantic node_id must not be empty")
            if node.node_id in node_map:
                raise ValueError(f"duplicate semantic node_id: {node.node_id}")
            node_map[node.node_id] = node

        for root in self.roots:
            if root not in node_map:
                raise ValueError(f"unknown semantic root: {root}")
        for node in self.nodes:
            for ref in node.inputs:
                if ref.node_id not in node_map:
                    raise ValueError(f"{node.node_id} references unknown node: {ref.node_id}")
                if ref.selector not in {"all", "index", "field", "predicate"}:
                    raise ValueError(f"unsupported binding selector: {ref.selector}")
                if ref.selector in {"index", "field", "predicate"} and ref.selector_value is None:
                    raise ValueError(f"selector value required: {node.node_id}/{ref.selector}")

        state: dict[str, int] = {}

        def visit(node_id: str) -> None:
            marker = state.get(node_id, 0)
            if marker == 1:
                raise ValueError(f"cycle in semantic program at: {node_id}")
            if marker == 2:
                return
            state[node_id] = 1
            for ref in node_map[node_id].inputs:
                visit(ref.node_id)
            state[node_id] = 2

        for node in self.nodes:
            visit(node.node_id)
