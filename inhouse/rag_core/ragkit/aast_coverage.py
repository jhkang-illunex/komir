"""Deterministic coverage checks for a generated AAST.

This module deliberately does not execute, repair values, or inspect raw query
text.  It compares a typed semantic requirement snapshot (projected from the
existing semantic/action contract) with the generated logical program.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .semantic_ir import Operator, SemanticProgram


REASONS = frozenset({
    "ENTITY_PRESERVATION_FAILED",
    "METRIC_PRESERVATION_FAILED",
    "PERIOD_PRESERVATION_FAILED",
    "BRANCH_COVERAGE_FAILED",
    "CAPABILITY_SELECTION_MISMATCH",
    "DEPENDENCY_BINDING_FAILED",
    "JOIN_CONTRACT_FAILED",
})


@dataclass(frozen=True)
class CoverageViolation:
    reason: str
    message: str
    requirement_id: str | None = None
    node_ids: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "message": self.message,
            "requirement_id": self.requirement_id,
            "node_ids": list(self.node_ids),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class CoverageReport:
    valid: bool
    violations: tuple[CoverageViolation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "violations": [item.to_dict() for item in self.violations]}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return {}


def _canonical(value: Any) -> str:
    return str(value or "").strip().casefold()


_ENTITY_ALIASES = {
    "nickel": "니켈", "ni": "니켈", "cobalt": "코발트", "co": "코발트",
    "copper": "구리", "cu": "구리", "lithium": "리튬", "li": "리튬",
    "graphite": "흑연", "graphite ore": "흑연", "rare earth": "희토류",
    "rare_earth": "희토류", "rare_earth_elements": "희토류",
    "rare-earth-elements": "희토류", "ree": "희토류", "tungsten": "텅스텐",
}


def _canonical_entity(value: Any) -> str:
    raw = _canonical(value)
    return _ENTITY_ALIASES.get(raw, raw)


def _canonical_metric(value: Any) -> str:
    raw = _canonical(value)
    return {
        "price_series": "price", "current": "price", "latest": "price",
        "retrieve": "document", "document": "document",
        "resource_rank": "resource", "production_volume": "production",
        "reserves_volume": "reserves", "country_rank": "country_rank",
        "country_share": "country_rank", "import_share": "country_rank",
    }.get(raw, raw)


def _values(raw: Any) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {_canonical_entity(item) for item in raw if _canonical_entity(item)}
    return {_canonical_entity(raw)} if _canonical_entity(raw) else set()


def _period_signature(raw: Any) -> tuple[tuple[str, str], ...] | None:
    """Return a deterministic, hashable semantic period signature.

    Periods arrive from different typed boundaries as scalar years, range
    strings, or structured objects.  Normalize those equivalent forms to a
    sorted tuple so coverage checks can safely use them as set members.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return (("kind", str(raw).casefold()),)
    if isinstance(raw, (int, float)):
        raw = str(int(raw)) if float(raw).is_integer() else str(raw)
    if isinstance(raw, str):
        value_text = raw.strip()
        if value_text.isdigit() and len(value_text) == 4:
            value = {"kind": "calendar_year", "calendar_year": value_text}
        elif ".." in value_text:
            start, end = (part.strip() for part in value_text.split("..", 1))
            value = {"kind": "range", "start": start, "end": end}
        else:
            value = {"kind": value_text.casefold()}
    else:
        value = _as_dict(raw)
    if not value:
        return None
    kind = str(value.get("kind") or "").strip().casefold()
    kind = {
        "year": "calendar_year",
        "calendar-year": "calendar_year",
        "months": "trailing_months",
        "trailing-months": "trailing_months",
        "date_range": "range",
        "date-range": "range",
    }.get(kind, kind)
    normalized: dict[str, str] = {}
    if kind:
        normalized["kind"] = kind
    aliases = {
        "trailing_months": ("trailing_months", "months"),
        "calendar_year": ("calendar_year", "year"),
        "start": ("start", "from"),
        "end": ("end", "to"),
        "frequency": ("frequency", "freq"),
    }
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            if value.get(candidate) is not None:
                normalized[canonical] = str(value[candidate])
                break
    return tuple(sorted(normalized.items()))


def _requirement_capability(requirement: Mapping[str, Any]) -> str | None:
    explicit = requirement.get("capability") or requirement.get("action_id")
    metric = _canonical(requirement.get("metric"))
    # Older semantic snapshots may carry the physical price.series label
    # beside the newer forecast metric.  Normalize that boundary mismatch
    # before candidate selection; do not let a stale label erase the typed
    # future-horizon requirement.
    if explicit == "price.series" and metric == "price_forecast":
        return "forecast.price"
    if explicit:
        return str(explicit)
    domain = _canonical(requirement.get("domain"))
    intent = _canonical(requirement.get("intent"))
    by_intent = {
        "trade_rank": "trade.country_rank", "trade_country_rank": "trade.country_rank",
        "trade_concentration": "trade.concentration", "inventory_latest": "inventory.latest", "inventory_series": "inventory.series",
        "indicator": "indicator.series", "resource_rank": "resource.rank",
        "price_series": "price.series", "price_compare": "price.compare",
        "document": "document.retrieve", "document_retrieve": "document.retrieve",
        "document_facts": "document.facts.retrieve", "okf_lookup": "document.lookup",
        "forecast_price": "forecast.price",
    }
    if intent in by_intent:
        return by_intent[intent]
    if domain == "document":
        return "document.retrieve"
    if domain == "inventory":
        period = requirement.get("period")
        period_kind = period.get("kind") if isinstance(period, Mapping) else None
        if metric in {"series", "inventory_series", "trend", "time_series"} or period_kind in {
            "trailing_months", "range", "calendar_year",
        }:
            return "inventory.series"
        return "inventory.latest"
    if domain == "indicator":
        return "indicator.series"
    # Forecast is a semantic capability of its own even when the upstream
    # parser retains the broad price domain.  Keep it out of price.series so
    # its future-horizon period reaches the typed capability boundary.
    if metric == "price_forecast":
        return "forecast.price"
    if domain == "forecast" and metric == "price_forecast":
        return "forecast.price"
    if domain == "resource" and metric in {"resource_yoy", "production_yoy", "reserves_yoy"}:
        return "resource.yoy"
    if domain == "resource" or metric in {"production", "production_volume", "reserves", "reserves_volume"}:
        return "resource.rank"
    if domain == "trade":
        return "trade.concentration" if metric in {"concentration", "hhi"} else "trade.country_rank"
    if domain == "price" or metric in {"price", "price_series", "current", "latest"}:
        return "price.compare" if metric in {"price_compare", "compare"} else "price.series"
    return None


def required_capabilities(requirements: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Project typed requirements to their required physical capabilities.

    This is a coverage view only.  It never parses the query or invents a
    missing action, so callers can use it as a deterministic execution gate.
    """

    return tuple(
        capability
        for requirement in requirements
        if (capability := _requirement_capability(requirement))
    )


def _node_capability(node: Any) -> str:
    if node.operator == Operator.RETRIEVE_DOCUMENT:
        return "document.retrieve"
    args = node.args
    domain = _canonical(args.get("domain"))
    metric = _canonical(args.get("metric"))
    if (domain == "resource" and metric in {"resource_yoy", "production_yoy", "reserves_yoy"}) or (
        domain == "resource" and _canonical(args.get("calculation") or args.get("operation")) in {
        "yoy", "year_over_year", "annual_change"
    }):
        return "resource.yoy"
    if domain == "document":
        return "document.retrieve"
    if domain == "inventory":
        period = args.get("period")
        period_kind = period.get("kind") if isinstance(period, Mapping) else None
        if metric in {"series", "inventory_series", "trend", "time_series"} or period_kind in {
            "trailing_months", "range", "calendar_year",
        }:
            return "inventory.series"
        return "inventory.latest"
    if domain == "indicator":
        return "indicator.series"
    if metric == "price_forecast":
        return "forecast.price"
    if domain == "resource" or metric in {"production", "production_volume", "reserves", "reserves_volume"}:
        return "resource.rank"
    if metric in {"concentration", "hhi"}:
        return "trade.concentration"
    if domain == "trade" or metric in {
        "country_rank", "country_share", "import_share", "import_value", "import_amount",
        "export_share", "export_value", "export_amount", "export_weight",
    }:
        return "trade.country_rank"
    if domain == "price" or metric in {"price", "price_series", "price_change", "price_change_rate"}:
        return "price.compare" if node.operator == Operator.COMPARE else "price.series"
    return ""


def _node_metric(node: Any) -> str:
    """Infer only the declared semantic metric, never a physical DB column."""
    if node.operator == Operator.RETRIEVE_DOCUMENT:
        return "document"
    args = node.args
    metric = args.get("metric")
    domain = _canonical(args.get("domain"))
    # ``latest`` is an operation within the inventory domain, not the generic
    # latest-price alias. Keep the domain-qualified canonical metric so
    # coverage compares InventoryObservation with inventory output.
    if domain == "inventory" and _canonical(metric) in {
        "latest", "inventory", "inventory_series", "series",
    }:
        return "inventory"
    if metric:
        return _canonical_metric(metric)
    return {
        "price": "price", "document": "document", "indicator": "indicator",
        "inventory": "inventory", "production": "production", "reserves": "reserves",
        "resource": "resource", "trade": "country_rank", "import": "country_rank",
    }.get(domain, "")


def _derived_metric_spec(metric: str) -> tuple[str, frozenset[str]] | None:
    """Return the base metric and required temporal operation for a derived metric.

    Semantic requirements intentionally keep derived metrics orthogonal to their
    base metric.  This lets ``production_yoy`` and ``price_yoy`` share one
    contract without adding every compound phrase to the vocabulary.
    """
    normalized = _canonical(metric)
    for suffix, operations in (
        ("_yoy", frozenset({"yoy", "year_over_year", "annual_change"})),
        ("_change_rate", frozenset({"change_rate", "percent_change", "change_pct"})),
        ("_change", frozenset({"change", "percent_change", "change_pct"})),
    ):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return normalized[:-len(suffix)], operations
    return None


def _has_downstream_calculation(program: SemanticProgram, node_id: str, operations: frozenset[str]) -> bool:
    """Whether a candidate retrieval has the required calculation descendant."""
    by_id = {node.node_id: node for node in program.nodes}
    children: dict[str, list[Any]] = {}
    for node in program.nodes:
        for ref in node.inputs:
            children.setdefault(ref.node_id, []).append(node)
    seen: set[str] = set()
    stack = list(children.get(node_id, ()))
    while stack:
        node = stack.pop()
        if node.node_id in seen:
            continue
        seen.add(node.node_id)
        if node.operator == Operator.CALCULATE:
            operation = _canonical(node.args.get("calculation") or node.args.get("operation"))
            if operation in operations:
                return True
        stack.extend(children.get(node.node_id, ()))
    return False


def _derived_metric_satisfied(
    required_metric: str, candidates: list[Any], program: SemanticProgram,
) -> bool:
    """Check derived metric equivalence without treating the base as the result."""
    spec = _derived_metric_spec(required_metric)
    if spec is None:
        return False
    base_metric, operations = spec
    base_aliases = {base_metric}
    if base_metric == "resource":
        base_aliases |= {"resource", "production", "reserves"}
    if base_metric == "price_series":
        base_aliases.add("price")
    for node in candidates:
        node_metric = _node_metric(node)
        if node_metric in base_aliases and _has_downstream_calculation(program, node.node_id, operations):
            return True
        # An existing typed atomic capability may expose the derived result
        # directly.  It is equivalent only when its capability is the derived
        # resource capability, not merely because its base metric matches.
        if required_metric == "resource_yoy" and _node_capability(node) == "resource.yoy":
            return True
    return False


def _node_entities(node: Any) -> set[str]:
    args = node.args
    return _values(args.get("mineral")) | _values(args.get("minerals")) | _values(args.get("entity"))


def _planned_nodes(program: SemanticProgram, capability: str | None = None) -> list[Any]:
    nodes = [node for node in program.nodes if node.operator in {Operator.RETRIEVE, Operator.RETRIEVE_DOCUMENT, Operator.FOR_EACH}]
    if capability:
        nodes = [node for node in nodes if _node_capability(node) == capability]
    return nodes


def _nodes_for_requirement(program: SemanticProgram, capability: str | None) -> list[Any]:
    nodes = _planned_nodes(program, capability)
    if not nodes and capability == "resource.yoy":
        # The logical representation may use a resource production retrieve
        # followed by Calculate(yoy); the physical boundary may instead use
        # the existing resource.yoy capability directly.  Both are the same
        # typed semantic branch, so inspect resource retrieval candidates.
        nodes = _planned_nodes(program, "resource.rank")
    if nodes or capability not in {"price.compare"}:
        return nodes
    # A compare capability is a composite boundary in the physical graph: its
    # inputs remain price.series calls, while the compare node is the selected
    # logical capability.  Treat those inputs as candidates for dimension and
    # period checks without requiring the parser to expose a physical action.
    if any(node.operator == Operator.COMPARE for node in program.nodes):
        return [node for node in program.nodes if node.operator == Operator.RETRIEVE]
    return nodes


def _output_contract_compatible(required_capability: str, node: Any) -> bool:
    """Check the selected retrieve node's semantic output contract.

    ``trade`` is a broad domain, but its physical series metrics and country
    ranking output are different typed results.  In particular, an
    ``import_value`` retrieve is lowered to ``trade.monthly`` unless the node
    explicitly declares the country-rank operation.  Do not accept that
    time-series output as a RankedCountrySet merely because both belong to the
    trade domain.
    """
    if required_capability != "trade.country_rank":
        return True
    if node.operator != Operator.RETRIEVE:
        return True
    args = node.args
    if _canonical(args.get("domain")) != "trade":
        return True
    operation = _canonical(args.get("operation"))
    if operation in {"country_rank", "rank"}:
        return True
    metric = _canonical(args.get("metric"))
    return metric not in {"import_value", "export_value", "import_weight", "export_weight"}


def _is_saved_result_requirement(requirement: Mapping[str, Any]) -> bool:
    """Whether the requirement refines a previously saved typed result.

    Such a branch intentionally has no new retrieve capability.  Its
    executable input is a materialized history entity followed by a project
    or calculation node, so capability coverage must not demand a second
    physical call.
    """
    relation = _canonical(requirement.get("relation"))
    return relation in {"reference", "refine_previous", "previous_result", "history"} or bool(
        requirement.get("context_ref")
    )


def _root_ancestors(program: SemanticProgram) -> set[str]:
    by_id = {node.node_id: node for node in program.nodes}
    result: set[str] = set()
    stack = list(program.roots)
    while stack:
        node_id = stack.pop()
        if node_id in result or node_id not in by_id:
            continue
        result.add(node_id)
        stack.extend(ref.node_id for ref in by_id[node_id].inputs)
    return result


def _check_graph_contract(program: SemanticProgram) -> list[CoverageViolation]:
    violations: list[CoverageViolation] = []
    by_id = {node.node_id: node for node in program.nodes}
    reachable = _root_ancestors(program)
    for node in program.nodes:
        if node.node_id not in reachable:
            violations.append(CoverageViolation("BRANCH_COVERAGE_FAILED", f"unreachable node: {node.node_id}", node_ids=(node.node_id,)))
        for ref in node.inputs:
            if ref.node_id not in by_id:
                violations.append(CoverageViolation("DEPENDENCY_BINDING_FAILED", f"unknown input: {ref.node_id}", node_ids=(node.node_id,)))
    for node in program.nodes:
        if node.operator in {Operator.COMPARE, Operator.JOIN}:
            if len(node.inputs) != 2:
                violations.append(CoverageViolation("JOIN_CONTRACT_FAILED", f"{node.operator.value} requires two inputs", node_ids=(node.node_id,)))
            key = node.args.get("join_key") or node.args.get("left_on") or node.args.get("field") or node.args.get("left_field")
            if not key:
                violations.append(CoverageViolation("JOIN_CONTRACT_FAILED", f"{node.operator.value} has no alignment key/field", node_ids=(node.node_id,)))
            # Model-local ``expected_type=unknown`` is common in older AAST
            # outputs.  Do not reject it by itself; the key/field contract is
            # checked against the declared upstream metric below/runtime.
    return violations


def _canonical_plan_scopes(plan: Mapping[str, Any] | None) -> set[str]:
    """Read canonical physical scope bindings already accepted by lowering.

    Older AAST payloads do not repeat the physical ``trade_scope`` on every
    retrieve node.  When the typed ActionPlan already carries that binding,
    it is an equivalent representation of the semantic scope and must be
    considered by coverage validation.
    """
    if not isinstance(plan, Mapping):
        return set()
    scopes: set[str] = set()
    for action in plan.get("actions", ()) or ():
        slots = action.get("slots", {}) if isinstance(action, Mapping) else {}
        raw = slots.get("trade_scope") or slots.get("scope") or slots.get("country_scope")
        if raw is None:
            continue
        value = _canonical(raw)
        scopes.add({"korea": "kr", "kor": "kr", "한국": "kr", "대한민국": "kr"}.get(value, value))
    return scopes


def _canonical_plan_periods(plan: Mapping[str, Any] | None) -> set[tuple[tuple[str, str], ...]]:
    """Return period signatures from the already-lowered typed plan.

    The semantic/action bridge may carry a period on the typed capability call
    while an older AAST retrieve node leaves it implicit.  Coverage validation
    must compare the canonical typed binding as well as the logical spelling;
    execution still remains responsible for applying the binding.
    """
    if not isinstance(plan, Mapping):
        return set()
    periods: set[tuple[tuple[str, str], ...]] = set()
    for action in plan.get("actions", ()) or ():
        slots = action.get("slots", {}) if isinstance(action, Mapping) else {}
        signature = _period_signature(slots.get("period"))
        if signature:
            periods.add(signature)
    return periods


def validate_aast(
    requirements: Iterable[Any] | None,
    program: SemanticProgram,
    canonical_plan: Mapping[str, Any] | None = None,
) -> CoverageReport:
    """Compare typed requirements with an AAST without reading the query text."""
    normalized = [_as_dict(item) for item in (requirements or [])]
    violations = _check_graph_contract(program)
    canonical_scopes = _canonical_plan_scopes(canonical_plan)
    canonical_periods = _canonical_plan_periods(canonical_plan)
    if not normalized:
        return CoverageReport(not violations, tuple(violations))
    for index, requirement in enumerate(normalized):
        requirement_id = str(requirement.get("requirement_id") or requirement.get("id") or f"requirement_{index}")
        capability = _requirement_capability(requirement)
        candidates = _nodes_for_requirement(program, capability)
        if capability and not candidates:
            if _is_saved_result_requirement(requirement):
                # The graph contract below still verifies that the materialized
                # typed input is connected to a reachable downstream node.
                continue
            # A document branch can be a retrieve_document primitive.
            if not (capability == "price.compare" and any(node.operator == Operator.COMPARE for node in program.nodes)):
                violations.append(CoverageViolation("CAPABILITY_SELECTION_MISMATCH", f"required={capability}, planned=[]", requirement_id, details={"required_capability": capability}))
            continue
        incompatible = [node for node in candidates
                        if not _output_contract_compatible(capability or "", node)]
        if incompatible:
            violations.append(CoverageViolation(
                "CAPABILITY_SELECTION_MISMATCH",
                f"required_output=RankedCountrySet, planned_output=TradeTimeSeries, nodes={[node.node_id for node in incompatible]}",
                requirement_id,
                details={
                    "required_capability": capability,
                    "required_output": "RankedCountrySet",
                    "planned_output": "TradeTimeSeries",
                    "nodes": [node.node_id for node in incompatible],
                },
            ))
        required_entities = _values(requirement.get("mineral")) | _values(requirement.get("minerals")) | _values(requirement.get("entities"))
        if required_entities:
            planned_entities = set().union(*(_node_entities(node) for node in program.nodes)) if program.nodes else set()
            if not required_entities.issubset(planned_entities):
                violations.append(CoverageViolation("ENTITY_PRESERVATION_FAILED", f"required={sorted(required_entities)}, planned={sorted(planned_entities)}", requirement_id, details={"required": sorted(required_entities), "planned": sorted(planned_entities)}))
        # ``latest`` is an output cardinality, not a price metric.  Inventory
        # requirements historically used metric=latest while carrying the
        # inventory domain; resolve that typed capability boundary here rather
        # than letting the generic price alias produce a false rejection.
        if _canonical(requirement.get("domain")) == "inventory" and _canonical(requirement.get("metric")) in {
            "latest", "inventory", "inventory_series", "series",
        }:
            required_metric = "inventory"
        else:
            required_metric = _canonical_metric(requirement.get("metric"))
        if required_metric and candidates:
            planned_metrics = {_node_metric(node) for node in candidates}
            aliases = {required_metric}
            # indicator.series exposes the canonical metric name
            # ``indicator`` at the capability boundary while the semantic
            # requirement vocabulary uses ``series``.  They describe the
            # same typed capability, not two different requests.
            if _canonical(requirement.get("domain")) == "indicator" and required_metric == "series":
                aliases.add("indicator")
            if required_metric == "resource":
                aliases |= {"resource", "production", "reserves"}
            if required_metric in {"country_rank", "country_share", "import_share"}:
                # A ranked country set is an output semantic, not an import-only
                # metric.  The same typed result can be built from either flow;
                # the operation/capability check above still rejects a plain
                # trade time series.
                aliases |= {
                    "country_rank", "country_share", "import_share",
                    "import_value", "import_amount", "import_weight",
                    "export_share", "export_value", "export_amount",
                    "export_weight",
                }
            derived_ok = _derived_metric_satisfied(required_metric, candidates, program)
            if not planned_metrics.intersection(aliases) and not derived_ok:
                violations.append(CoverageViolation("METRIC_PRESERVATION_FAILED", f"required={required_metric}, planned={sorted(planned_metrics)}", requirement_id))
        required_country = requirement.get("reporter_country") or requirement.get("partner_country") or requirement.get("country")
        required_scope = requirement.get("scope")
        if (required_country or required_scope) and candidates:
            planned_countries = set()
            planned_scopes = set()
            children: dict[str, list[Any]] = {}
            for child in program.nodes:
                for ref in child.inputs:
                    children.setdefault(ref.node_id, []).append(child)
            for node in candidates:
                planned_countries |= _values(node.args.get("reporter_country")) | _values(node.args.get("partner_country")) | _values(node.args.get("country"))
                scope = node.args.get("scope", node.constraints.get("scope"))
                if scope is not None:
                    raw_scope = _canonical(scope)
                    planned_scopes.add({"korea": "kr", "kor": "kr", "한국": "kr", "대한민국": "kr"}.get(raw_scope, raw_scope))
                # Resource ranking is world-scoped by contract when no
                # narrower scope is supplied.  Omission is equivalent to
                # semantic WORLD, not a lost country binding.
                if _node_capability(node) == "resource.rank" and scope is None:
                    planned_scopes.add("world")
                if _node_capability(node) == "trade.country_rank" and scope is None:
                    # A country filter is an equivalent downstream binding for
                    # trade scope; do not require the model to duplicate it on
                    # the retrieve node.
                    stack = list(children.get(node.node_id, ()))
                    seen: set[str] = set()
                    found_filter = False
                    while stack:
                        child = stack.pop()
                        if child.node_id in seen:
                            continue
                        seen.add(child.node_id)
                        if child.operator == Operator.FILTER:
                            predicate = child.args.get("predicate")
                            if isinstance(predicate, Mapping) and _canonical(predicate.get("field")) in {"country", "country_code", "reporter_country"}:
                                value = predicate.get("value")
                                if value is not None:
                                    planned_scopes.add(_canonical(value))
                                    found_filter = True
                        stack.extend(children.get(child.node_id, ()))
                    if not found_filter:
                        # The trade country-rank capability defaults to the
                        # global population when no narrower scope is bound.
                        planned_scopes.add("global")
            if required_country and not _values(required_country).intersection(planned_countries):
                violations.append(CoverageViolation("ENTITY_PRESERVATION_FAILED", f"required_country={required_country}, planned={sorted(planned_countries)}", requirement_id))
            required_scope_key = {"korea": "kr", "kor": "kr", "한국": "kr", "대한민국": "kr"}.get(
                _canonical(required_scope), _canonical(required_scope)
            )
            if (required_scope and required_scope_key not in planned_scopes
                    and required_scope_key not in canonical_scopes):
                violations.append(CoverageViolation("ENTITY_PRESERVATION_FAILED", f"required_scope={required_scope}, planned={sorted(planned_scopes)}", requirement_id))
        required_period = _period_signature(requirement.get("period"))
        if required_period and candidates:
            planned_periods = {_period_signature(node.args.get("period")) for node in candidates}
            # A requirement may intentionally share a capability with another
            # branch that has no period (for example current value + forecast).
            # Do not select an arbitrary set member: validate membership in the
            # candidate signatures so equivalent structured periods survive
            # multi-branch planning deterministically.
            if (required_period not in planned_periods
                    and required_period not in canonical_periods):
                violations.append(CoverageViolation("PERIOD_PRESERVATION_FAILED", f"required={required_period}, planned={sorted(map(str, planned_periods))}", requirement_id))
    required_caps = [_requirement_capability(item) for item in normalized]
    required_caps = [item for item in required_caps if item]
    planned_caps = [_node_capability(node) for node in program.nodes if node.operator in {Operator.RETRIEVE, Operator.RETRIEVE_DOCUMENT, Operator.FOR_EACH}]
    saved_result_branches = sum(
        1 for item in normalized
        if _requirement_capability(item) and _is_saved_result_requirement(item)
        and any(node.operator == Operator.ENTITY and node.node_id in _root_ancestors(program) for node in program.nodes)
    )
    if len(required_caps) > len(planned_caps) + saved_result_branches:
        violations.append(CoverageViolation("BRANCH_COVERAGE_FAILED", f"required_branches={len(required_caps)}, planned_branches={len(planned_caps)}", details={"required": required_caps, "planned": planned_caps}))
    return CoverageReport(not violations, tuple(violations))


__all__ = [
    "CoverageReport",
    "CoverageViolation",
    "REASONS",
    "required_capabilities",
    "validate_aast",
]
