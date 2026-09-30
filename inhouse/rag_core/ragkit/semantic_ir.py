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
    FOR_EACH = "for_each"
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


_METRIC_FIELDS: dict[str, set[str]] = {
    "price": {"price", "cmerc_prc", "value"},
    "price_change": {"price_change", "price_change_rate", "pct_change", "change_pct"},
    "price_change_rate": {"price_change", "price_change_rate", "pct_change", "change_pct"},
    "price_volatility": {"price_volatility", "price_change", "pct_change", "change_pct"},
    # Trade rows carry the dimensional metadata needed by downstream share,
    # period and unit projections.  Declaring it here keeps the AST contract
    # aligned with the existing RDB/tool result rather than allowing a later
    # project/filter node to discover the dependency at runtime.
    "import_value": {"import_value", "import_amount", "import_amount_change", "value", "country", "period", "unit"},
    "import_amount": {"import_value", "import_amount", "import_amount_change", "value", "country", "period", "unit"},
    "import_change": {"import_change", "import_value_change", "import_amount_change", "change_pct", "country", "period", "unit"},
    "import_value_change": {"import_change", "import_value_change", "import_amount_change", "change_pct", "country", "period", "unit"},
    "import_share": {"import_share", "share_percentage", "import_amount", "import_value", "country", "period", "unit"},
    "country_share": {"country_share", "share_percentage", "import_amount", "import_value", "country", "period", "unit"},
    "country_rank": {"country", "country_share", "share_percentage", "import_amount", "import_value", "period", "unit"},
    "production": {"production", "production_volume", "value", "country", "period", "unit"},
    "production_volume": {"production", "production_volume", "value", "country", "period", "unit"},
    "reserves": {"reserves", "reserves_volume", "value", "country", "period", "unit"},
    "reserves_volume": {"reserves", "reserves_volume", "value", "country", "period", "unit"},
}

_FIELD_ALIASES: dict[str, set[str]] = {
    "mineral": {"mineral", "광종", "광물", "원소", "entity"},
    "entity": {"mineral", "광종", "광물", "원소", "entity"},
}


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

        issues = self.completeness_issues()
        if issues:
            raise ValueError(f"ast_incomplete: {issues[0]}")

    def completeness_issues(self) -> tuple[str, ...]:
        """Return deterministic downstream field/dependency contract violations.

        This is intentionally conservative: it validates fields explicitly
        requested by downstream operators only when the upstream contract is
        known. It never invents a field or a physical tool capability.
        """
        node_map = {node.node_id: node for node in self.nodes}
        provided: dict[str, set[str] | None] = {}

        def aliases(field: str) -> set[str]:
            return _FIELD_ALIASES.get(field.casefold(), {field}) | {field}

        def metric_fields(metric: Any) -> set[str]:
            return set(_METRIC_FIELDS.get(str(metric).casefold(), {str(metric)})) if metric else set()

        def fields_from_value(value: Any) -> set[str]:
            if isinstance(value, Mapping):
                return {str(key) for key in value}
            if isinstance(value, (list, tuple)):
                result: set[str] = set()
                for item in value:
                    result.update(fields_from_value(item))
                return result
            return set()

        def upstream_fields(ref: InputRef) -> set[str] | None:
            source = provided.get(ref.node_id)
            if source is None:
                return None
            if ref.selector == "field" and ref.selector_value:
                return {str(ref.selector_value)}
            return set(source)

        def requested_fields(node: RequirementNode) -> set[str]:
            args = node.args
            if node.operator == Operator.FILTER.value:
                predicate = args.get("predicate")
                if isinstance(predicate, Mapping):
                    field = predicate.get("field")
                else:
                    field = args.get("field") or args.get("metric_field")
                return set(aliases(str(field))) if field else metric_fields(args.get("metric"))
            if node.operator in {Operator.SORT.value, Operator.RANK.value, Operator.ARG_MAX.value, Operator.ARG_MIN.value}:
                field = args.get("field") or args.get("metric_field") or args.get("metric")
                return set(aliases(str(field))) | metric_fields(field) if field else set()
            if node.operator == Operator.PROJECT.value:
                return {str(field) for field in (args.get("fields") or [])}
            if node.operator == Operator.CALCULATE.value:
                calculation = str(args.get("calculation", ""))
                return {"start", "end"} if calculation in {"change_pct", "percent_change"} else set()
            return set()

        issues: list[str] = []
        ordered: list[RequirementNode] = []
        visited: set[str] = set()

        def order(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            node = node_map[node_id]
            for ref in node.inputs:
                order(ref.node_id)
            ordered.append(node)

        for node in self.nodes:
            order(node.node_id)

        for node in ordered:
            args = node.args
            if node.operator == Operator.TOP_K.value:
                limit = args.get("k", args.get("top_n", args.get("limit")))
                if limit is not None:
                    try:
                        if int(limit) <= 0:
                            raise ValueError
                    except (TypeError, ValueError):
                        issues.append(f"{node.node_id} has invalid top_k limit {limit!r}")
                if not node.inputs:
                    issues.append(f"{node.node_id} requires an upstream result")
            # Calculate may be a valid leaf handled by an existing primitive
            # (for example a deterministic KPI handler).  Missing upstream
            # data is therefore checked when a calculation declares inputs,
            # while the field/dependency checks below remain strict for
            # downstream operators consuming an upstream result.
            if node.operator in {Operator.FILTER.value, Operator.SORT.value, Operator.PROJECT.value, Operator.ARG_MAX.value, Operator.ARG_MIN.value} and not node.inputs:
                issues.append(f"{node.node_id} requires an upstream result")
            if node.operator in {Operator.COMPARE.value, Operator.JOIN.value} and len(node.inputs) < 2:
                issues.append(f"{node.node_id} requires at least two upstream results")
            if node.operator == Operator.FILTER.value and not isinstance(args.get("predicate"), Mapping) and not (args.get("field") or args.get("metric") or args.get("metric_field")):
                issues.append(f"{node.node_id} requires a filter field or metric")
            if node.operator == Operator.ENTITY.value:
                fields = fields_from_value(args.get("values") or args.get("minerals") or args.get("mineral"))
                provided[node.node_id] = fields | ({"entity", "mineral", "광종"} if fields else set())
            elif node.operator == Operator.RETRIEVE.value:
                # Every retrieval carries an entity dimension even when the
                # model did not spell it out in args.
                provided[node.node_id] = {"entity", "mineral", "광종"} | metric_fields(args.get("metric"))
            elif node.operator == Operator.RETRIEVE_DOCUMENT.value:
                provided[node.node_id] = {"document", "evidence", "entity", "mineral", "광종"}
            elif node.inputs:
                input_sets = [upstream_fields(ref) for ref in node.inputs]
                if any(item is None for item in input_sets):
                    provided[node.node_id] = None
                else:
                    merged = set().union(*(item or set() for item in input_sets))
                    if node.operator == Operator.PROJECT.value:
                        provided[node.node_id] = requested_fields(node)
                    elif node.operator == Operator.CALCULATE.value:
                        provided[node.node_id] = merged | ({"change_pct"} if args.get("calculation") in {"change_pct", "percent_change"} else set())
                    else:
                        provided[node.node_id] = merged
            else:
                provided[node.node_id] = None

            required = requested_fields(node)
            if not required or not node.inputs:
                continue
            available = set().union(*(upstream_fields(ref) or set() for ref in node.inputs))
            if not any(available.intersection(aliases(field)) for field in required for _ in (0,)):
                issues.append(f"{node.node_id} requires field(s) {sorted(required)} not produced by upstream")

            for ref in node.inputs:
                if ref.selector != "field" or ref.selector_value is None:
                    continue
                source_fields = provided.get(ref.node_id)
                if source_fields is not None and not source_fields.intersection(aliases(str(ref.selector_value))):
                    issues.append(f"{node.node_id} selects field {ref.selector_value!r} absent from {ref.node_id}")
        return tuple(dict.fromkeys(issues))
