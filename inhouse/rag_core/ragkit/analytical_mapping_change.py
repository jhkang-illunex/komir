"""Legacy mapping change contract, distinct from analytical series operations.

No date, unit or evidence validation is introduced here. The caller retains
the existing result envelope through its derived-row finalizer.
"""

from typing import Any, Callable, Mapping

from .pipe_runtime import TypedResult


def calculate_mapping_change(
    value: Mapping[str, Any],
    numeric: Callable[[Any], float | None],
    finalize: Callable[[list[Any]], TypedResult],
) -> TypedResult:
    start, end = numeric(value.get("start")), numeric(value.get("end"))
    if start is not None and start != 0 and end is not None:
        return finalize([{**value, "change_pct": (end - start) / abs(start) * 100}])
    return TypedResult.abstain("invalid_calculation_operands")
