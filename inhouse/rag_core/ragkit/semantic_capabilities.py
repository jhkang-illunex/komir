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
    ("resource", "resource_rank"): frozenset({"resource_rank"}),
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
        # A selected price observation is a scalar value plus its selected
        # date, not merely an unprojected time series.  This is derived from
        # the typed AST selection, never from the raw utterance.
        selection = getattr(requirement, "selection", None)
        if (key == ("price", "price_series") and selection is not None
                and getattr(selection, "mode", None) == "extremum"):
            outputs.update({"latest_price", "date"})
    return frozenset(outputs)


def validate_requested_outputs(requirements: list[object], requested: set[str] | frozenset[str]) -> str | None:
    """Validate AST output coverage without inspecting raw natural language."""

    missing = sorted(set(requested) - produced_outputs(requirements))
    return "requested_output_not_produced:" + ",".join(missing) if missing else None


__all__ = ["CAPABILITY_OUTPUTS", "produced_outputs", "validate_requested_outputs"]
