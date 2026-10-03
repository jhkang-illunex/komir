"""Resource-rank physical total columns → the existing declared mass field.

Only the legacy column rename belongs here. The caller retains scalar binding
and the common TypedResult envelope. Collision order and failure behavior are
preserved; this adapter does not infer population, units, or new aliases.
"""

from __future__ import annotations

from typing import Any


def canonicalize_resource_rank_rows(
    rows: list[dict[str, Any]], metric: str | None,
) -> list[dict[str, Any]]:
    """Preserve the reader's existing production/reserves column binding."""
    # Bind the complete reader's normalized mass column, not a ranking
    # share or a summary value, to its explicitly declared metric.
    metric_field = {"production": "production_volume", "reserves": "reserves_volume"}.get(metric)
    if metric_field:
        normalized_rows = []
        for row in rows:
            copied = {(metric_field if key.split("(", 1)[0].casefold() in {"total", "총계"} else key): value
                      for key, value in row.items()}
            if metric_field not in copied:
                for alias in ("total", "총계"):
                    if alias in copied:
                        copied[metric_field] = copied[alias]
                        break
            normalized_rows.append(copied)
        rows = normalized_rows
    return rows
