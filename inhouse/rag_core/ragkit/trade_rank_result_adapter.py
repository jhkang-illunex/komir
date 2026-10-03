"""Country-rank source rows → the existing declared trade-measure contract.

Only table membership and the unique physical total column are adapted here.
The caller keeps the common TypedResult envelope and injects existing field
resolution helpers; this module neither calculates shares nor owns aliases.
"""

from __future__ import annotations

from typing import Any, Callable


def select_country_rank_rows(
    rows: list[dict[str, Any]], *, resolve_field: Callable[..., str | None],
) -> list[dict[str, Any]]:
    """Prefer country/share rows; retain all rows if none qualify, as before."""
    ranked = [
        row for row in rows
        if resolve_field([row], "country", strict=True)
        and resolve_field([row], "share_percentage", strict=True)
    ]
    return ranked or rows


def canonicalize_trade_rank_rows(
    rows: list[dict[str, Any]], metric: str | None, *,
    base_column_name: Callable[[Any], str],
) -> list[dict[str, Any]]:
    """Expose the declared trade-rank measure at the capability boundary.

    The structured trade adapter may label its aggregate column as
    ``total(<display label>)``. That physical label is not a stable input for
    compare/projection nodes. Only a typed ``trade.country_rank`` call may map
    a unique total column to its declared measure.
    """
    canonical = str(metric or "").casefold()
    if canonical not in {"import_amount", "export_amount", "import_weight", "export_weight"}:
        return rows
    normalized: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        if canonical not in copied:
            total_keys = [key for key in copied if base_column_name(key) in {"total", "총계"}]
            if len(total_keys) == 1:
                copied[canonical] = copied[total_keys[0]]
        normalized.append(copied)
    return normalized
