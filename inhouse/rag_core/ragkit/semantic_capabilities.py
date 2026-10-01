"""Capability and output contracts for the typed semantic parser.

This module deliberately contains no natural-language matching.  It is a
small structural registry used after Gemma has produced a ``SemanticPlan``.
"""
from __future__ import annotations

from typing import Final


# Outputs are semantic capabilities, not presentation formats.  A renderer may
# still choose text/table/chart for a produced output later.
CAPABILITY_OUTPUTS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("concept", "retrieve"): frozenset({"usage", "concept"}),
    ("document", "retrieve"): frozenset({"document_evidence", "resource_news"}),
    ("price", "current"): frozenset({"latest_price"}),
    ("price", "price_series"): frozenset({"price_series"}),
    ("trade", "country_rank"): frozenset({"country_rank"}),
    ("resource", "resource_rank"): frozenset({"resource_rank", "production", "reserves", "value", "country", "period", "unit"}),
    ("inventory", "latest"): frozenset({"latest_inventory", "inventory"}),
    ("resource", "resource_yoy"): frozenset({"resource_change"}),
    ("indicator", "series"): frozenset({"indicator_series"}),
}


def produced_outputs(requirements: list[object]) -> frozenset[str]:
    """Return outputs declared by capabilities in a typed AST.

    Unknown capabilities produce no output and are rejected by the normal
    semantic resolver; this function never guesses from the user utterance.
    """

    outputs: set[str] = set()
    for requirement in requirements:
        key = (getattr(requirement, "domain", ""), getattr(requirement, "metric", ""))
        outputs.update(CAPABILITY_OUTPUTS.get(key, ()))
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
    missing = sorted(normalized_requested - produced_outputs(requirements))
    return "requested_output_not_produced:" + ",".join(missing) if missing else None


__all__ = ["CAPABILITY_OUTPUTS", "produced_outputs", "validate_requested_outputs"]
