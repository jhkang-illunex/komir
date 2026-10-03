"""Capability and output contracts for the typed semantic parser.

This module deliberately contains no natural-language matching.  It is a
small structural registry used after Gemma has produced a ``SemanticPlan``.
"""
from __future__ import annotations

from typing import Any, Final, Mapping

from .capability_specs.inventory import INVENTORY_SERIES_SEMANTIC_OUTPUTS
from .capability_specs.price import PRICE_ALLOWED_OUTPUT_FIELDS, PRICE_CRITERION_MODES, PRICE_IDENTITY_FIELDS
from .output_coverage import diagnose_output_coverage


# Outputs are semantic capabilities, not presentation formats.  A renderer may
# still choose text/table/chart for a produced output later.
CAPABILITY_OUTPUTS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("concept", "retrieve"): frozenset({"usage", "concept"}),
    ("document", "retrieve"): frozenset({"document_evidence", "resource_news"}),
    ("price", "current"): frozenset({"latest_price"}),
    ("price", "price_series"): frozenset({"price_series"}),
    ("trade", "country_rank"): frozenset({
        "country_rank", "country_share", "import_share", "share_percentage",
        "country", "period", "unit", "provenance",
    }),
    ("resource", "resource_rank"): frozenset({"resource_rank", "production", "reserves", "value", "country", "period", "unit"}),
    ("inventory", "latest"): frozenset({"latest_inventory", "inventory"}),
    ("inventory", "series"): INVENTORY_SERIES_SEMANTIC_OUTPUTS,
    ("inventory", "inventory_series"): INVENTORY_SERIES_SEMANTIC_OUTPUTS,
    ("resource", "resource_yoy"): frozenset({"resource_change", "value", "period", "unit", "provenance"}),
    ("indicator", "series"): frozenset({"indicator_series", "indicator", "value", "date", "period", "unit", "provenance"}),
}


CAPABILITY_ARGUMENTS: Final[dict[str, dict[str, Any]]] = {
    "price.overview": {
        "domain": "price", "metric": "current", "canonical_metric": "price",
        "output_type": "PriceOverview", "criterion_modes": PRICE_CRITERION_MODES,
        "identity_fields": PRICE_IDENTITY_FIELDS,
        "required": frozenset({"price_group"}),
        "output_fields": PRICE_ALLOWED_OUTPUT_FIELDS,
        "group_map": {
            "strategic": ("strategic_six", "strategic_ten"),
            "strategic_six": ("strategic_six",),
            "strategic_ten": ("strategic_ten",),
            "battery_five": ("battery_five",),
        },
    },
    "price.series": {
        "domain": "price", "metric": "price_series", "canonical_metric": "price",
        "output_type": "PriceSeries", "criterion_modes": PRICE_CRITERION_MODES,
        "identity_fields": PRICE_IDENTITY_FIELDS,
        "output_fields": PRICE_ALLOWED_OUTPUT_FIELDS,
    },
    "inventory.latest": {
        "domain": "inventory", "metric": "latest",
        "output_fields": frozenset({"mineral", "inventory", "value", "date", "unit", "source", "provenance"}),
    },
    "inventory.series": {
        "domain": "inventory", "metric": "series",
        "output_fields": frozenset({"mineral", "inventory", "value", "date", "period", "unit", "source", "provenance"}),
    },
    "indicator.series": {
        "domain": "indicator", "metric": "series",
        "surface_metrics": frozenset({"indicator", "series"}),
        "canonical_metric": "indicator",
        "output_type": "IndicatorSeries",
        "output_fields": frozenset({"indicator", "value", "date", "period", "unit", "source", "provenance"}),
        "required": frozenset({"indicator"}),
    },
    "resource.rank": {
        "domain": "resource", "metric": "resource_rank",
        "surface_metrics": frozenset({"resource_rank", "production", "reserves"}),
        "canonical_metric": "resource",
        "output_type": "ResourceRanking",
        "output_fields": frozenset({
            "country", "country_code", "mineral", "production", "production_volume",
            "reserves", "reserves_volume", "value", "year", "period", "unit",
            "source", "provenance",
        }),
        "required": frozenset({"mineral", "metric"}),
    },
    "resource.yoy": {
        "domain": "resource", "metric": "resource_yoy",
        "surface_metrics": frozenset({"resource_yoy", "production_yoy", "yoy"}),
        "canonical_metric": "resource_yoy",
        "output_type": "ResourceChange",
        "output_fields": frozenset({
            "mineral", "prior_year", "prior_tonnes", "year", "tonnes",
            "change_tonnes", "change_pct", "value", "period", "unit", "source", "provenance",
        }),
        "required": frozenset({"mineral", "metric"}),
    },
    # ``trade.country_rank`` already returns country-level amount and share
    # rows.  Keep the legacy action id and executor, but make its semantic
    # output explicit so planners/validators can consume the existing
    # CountryShare result without inventing a second capability.
    "trade.country_rank": {
        "domain": "trade", "metric": "country_rank",
        "surface_metrics": frozenset({"country_rank", "country_share", "import_share"}),
        "canonical_metric": "country_share",
        "output_type": "CountryShare",
        "output_fields": frozenset({
            "country", "country_code", "import_amount", "export_amount", "value",
            "share_percentage", "import_share", "country_share", "period",
            "unit", "source", "provenance",
        }),
        "required": frozenset({"mineral", "metric"}),
    },
}


def resolve_canonical_capability(
    domain: Any, metric: Any, args: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve surface semantic fields through the shared capability registry."""
    domain_key = str(domain or "").strip().casefold()
    metric_key = str(metric or "").strip().casefold()
    values = dict(args or {})
    if domain_key == "price" and metric_key == "current" and values.get("price_group"):
        group = str(values["price_group"]).strip().casefold()
        spec = CAPABILITY_ARGUMENTS["price.overview"]
        groups = spec["group_map"].get(group)
        if groups is not None:
            return {"action_id": "price.overview", "output_fields": spec["output_fields"],
                    "canonical_args": {"strategic_price_groups": list(groups)}, "spec": spec}
    for action_id, spec in CAPABILITY_ARGUMENTS.items():
        surface_metrics = set(spec.get("surface_metrics", (spec["metric"],)))
        if domain_key == spec["domain"] and metric_key in surface_metrics:
            return {"action_id": action_id, "output_fields": spec["output_fields"],
                    "canonical_args": {}, "spec": spec}
    return None


def capability_spec(action_id: str) -> Mapping[str, Any] | None:
    """Return the registry-owned contract for an executable capability."""
    return CAPABILITY_ARGUMENTS.get(str(action_id))


def capability_identity_fields(domain: Any, metric: Any | None = None) -> tuple[str, ...]:
    """Return canonical identity fields declared by the capability registry.

    The registry owns the semantic identity list; projection must not maintain a
    second price-specific alias list.  ``metric`` is optional because the live
    typed result has already canonicalized price variants to ``price``.
    """
    domain_key = str(domain or "").strip().casefold()
    metric_key = str(metric or "").strip().casefold()
    fields: list[str] = []
    for spec in CAPABILITY_ARGUMENTS.values():
        if str(spec.get("domain", "")).casefold() != domain_key:
            continue
        if metric_key and str(spec.get("canonical_metric", spec.get("metric", ""))).casefold() != metric_key:
            continue
        for field in spec.get("identity_fields", ()):
            if field not in fields:
                fields.append(field)
    return tuple(fields)


def capability_output_fields(domain: Any, metric: Any, args: Mapping[str, Any] | None = None) -> frozenset[str]:
    resolved = resolve_canonical_capability(domain, metric, args)
    if resolved is not None:
        return frozenset(resolved["output_fields"])
    # CAPABILITY_OUTPUTS is the semantic-output registry, not a physical row
    # field declaration.  Unknown/unresolved capabilities must fall back to
    # the existing metric-field contract at the IR boundary.
    return frozenset()


def produced_outputs(requirements: list[object]) -> frozenset[str]:
    """Return outputs declared by capabilities in a typed AST.

    Unknown capabilities produce no output and are rejected by the normal
    semantic resolver; this function never guesses from the user utterance.
    """

    outputs: set[str] = set()
    for requirement in requirements:
        key = (getattr(requirement, "domain", ""), getattr(requirement, "metric", ""))
        outputs.update(CAPABILITY_OUTPUTS.get(key, ()))
        if key == ("inventory", "latest"):
            # Gemma may call a bounded inventory trend ``latest`` while
            # retaining the requested period.  At the semantic boundary that
            # is the series output contract; do not force the parser into a
            # failure merely because the surface metric used the legacy label.
            period = getattr(requirement, "period", None)
            period_kind = getattr(period, "kind", None)
            if isinstance(period, dict):
                period_kind = period.get("kind")
            if period_kind in {"trailing_months", "range", "calendar_year"}:
                outputs.update(INVENTORY_SERIES_SEMANTIC_OUTPUTS)
        if key == ("resource", "resource_rank"):
            operation = getattr(requirement, "resource_operation", None)
            outputs.update({"production", "reserves", "value", "country", "period", "unit"})
            if operation:
                outputs.add(operation)
                metric_name = getattr(requirement, "operation", None) or getattr(requirement, "metric", "resource")
                outputs.add(f"{metric_name}_{operation}")
                domain_metric = "reserves" if getattr(requirement, "operation", None) == "reserves" else "production"
                outputs.update({
                    f"{operation}_{domain_metric}", f"{domain_metric}_{operation}",
                    f"{operation}_of_{domain_metric}", f"{domain_metric}_value",
                    f"{domain_metric}_country", f"{operation}_{domain_metric}_country",
                })
                if operation == "country_value":
                    outputs.update({"country", "value"})
    resource_ops = {
        getattr(r, "resource_operation", None) for r in requirements
        if (getattr(r, "domain", ""), getattr(r, "metric", "")) == ("resource", "resource_rank")
    }
    if {"average", "sum"}.issubset(resource_ops):
        outputs.update({"difference_between_average_and_total", "total_production", "average_production"})
    # A selected price observation is a scalar value plus its selected date,
    # not merely an unprojected time series. This is derived from the typed AST
    # selection, never from the raw utterance.
    for requirement in requirements:
        key = (getattr(requirement, "domain", ""), getattr(requirement, "metric", ""))
        selection = getattr(requirement, "selection", None)
        if (key == ("price", "price_series") and selection is not None
                and getattr(selection, "mode", None) == "extremum"):
            outputs.update({"latest_price", "date"})
    return frozenset(outputs)


def validate_requested_outputs(requirements: list[object], requested: set[str] | frozenset[str]) -> str | None:
    """Validate AST output coverage without inspecting raw natural language."""

    aliases = {"current_price": "latest_price"}
    normalized_requested = {aliases.get(str(item), str(item)) for item in requested}
    missing = diagnose_output_coverage(normalized_requested, produced_outputs(requirements)).missing
    return "requested_output_not_produced:" + ",".join(missing) if missing else None


__all__ = ["CAPABILITY_ARGUMENTS", "CAPABILITY_OUTPUTS", "capability_identity_fields",
           "capability_output_fields", "capability_spec", "produced_outputs",
           "resolve_canonical_capability", "validate_requested_outputs"]
