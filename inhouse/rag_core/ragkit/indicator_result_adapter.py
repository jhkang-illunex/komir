"""Indicator source rows → the existing IndicatorSeriesRow contract.

This is the indicator-specific portion of the legacy result adapter.  Evidence
selection, status propagation and the TypedResult envelope remain with its
caller.  Shared field resolution and numeric conversion are injected unchanged;
this module does not own another alias table or infer units.
"""

from __future__ import annotations

from typing import Any, Callable

from .action_contract import ActionCall, IndicatorSeriesRow


def canonical_indicator_rows(
    rows: list[dict[str, Any]], action: ActionCall, *,
    resolve_field: Callable[..., str | None],
    numeric: Callable[[Any], float | None],
) -> list[dict[str, Any]]:
    """Normalize the existing indicator result to its typed row contract.

    The source may call the numeric observation ``series`` or ``indx`` while
    downstream AST projection uses the shared ``value`` field.  ``center``
    is also accepted for the source's moving-average observation.  Only these
    explicit physical aliases are admissible; arbitrary fields are never
    selected.
    Invalid rows remain visible to the boundary validator rather than being
    silently dropped.
    """
    normalized: list[dict[str, Any]] = []
    for row in rows:
        copied = dict(row)
        if "date" in copied:
            date_text = str(copied["date"]).strip()
            if len(date_text) == 8 and date_text.isdigit():
                copied["date"] = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
        else:
            for source_field in ("date", "crtr_ymd", "obs_date", "observed_date", "period"):
                # Evidence tables may expose DB comments in the display key,
                # e.g. ``crtr_ymd(기준일자)``. Resolve the physical column through
                # the shared canonical resolver instead of requiring an exact
                # dictionary key.
                source_key = resolve_field([copied], source_field, strict=True)
                raw_date = copied.get(source_key) if source_key else None
                if raw_date is None:
                    continue
                date_text = str(raw_date).strip()
                if len(date_text) == 8 and date_text.isdigit():
                    date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
                copied["date"] = date_text
                break
        if "value" not in copied:
            for source_field in ("series", "indx", "center"):
                source_key = resolve_field([copied], source_field, strict=True)
                number = numeric(copied.get(source_key)) if source_key else None
                if number is not None:
                    copied["value"] = number
                    break
        if "indicator" not in copied and action.slots.indicator:
            copied["indicator"] = action.slots.indicator
        normalized.append(copied)
    return normalized


def validate_indicator_output(rows: list[dict[str, Any]], action: ActionCall) -> str | None:
    """Return a stable public contract error for malformed indicator rows."""
    if not rows:
        return None
    for row in rows:
        try:
            IndicatorSeriesRow.model_validate(row)
        except Exception:
            return "indicator_output_contract_invalid"
    return None
