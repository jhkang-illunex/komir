"""Existing observed/forecast composition after the Relation input guards."""

from typing import Any, Callable, Mapping

from .pipe_runtime import TypedResult
from .semantic_ir import ValueType


def compose_temporal_continuation(
    left: TypedResult,
    right: TypedResult,
    lrows: list[dict[str, Any]],
    rrows: list[dict[str, Any]],
    args: Mapping[str, Any],
    metadata: Mapping[str, Any],
    resolve_field: Callable[..., str | None],
) -> TypedResult:
    # Historical observed rows and future forecast rows are concatenated
    # on the time axis. They are not paired by equal dates and therefore
    # must not use the generic side-by-side alignment path.
    if not lrows or not rrows:
        return TypedResult.empty(ValueType.TIME_SERIES, "temporal_continuation_no_rows", **metadata)
    left_date = resolve_field(lrows, "date") or resolve_field(lrows, "crtr_ymd")
    right_date = resolve_field(rrows, "forecast_date") or resolve_field(rrows, "date")
    left_value = resolve_field(lrows, args.get("left_field") or "value")
    right_value = resolve_field(rrows, args.get("right_field") or "predicted_price")
    if not left_date or not right_date or not left_value or not right_value:
        return TypedResult.abstain("temporal_continuation_field_required", ValueType.TIME_SERIES, **metadata)
    if left.unit and right.unit and left.unit != right.unit:
        return TypedResult.abstain("temporal_continuation_unit_mismatch", ValueType.TIME_SERIES, **metadata)
    if left.entity and right.entity and set(left.entity) != set(right.entity):
        return TypedResult.abstain("temporal_continuation_entity_mismatch", ValueType.TIME_SERIES, **metadata)

    def normalized_date(value: Any) -> str:
        return str(value).replace("-", "")[:8]

    observed = sorted(lrows, key=lambda row: normalized_date(row.get(left_date)))
    observed_end = normalized_date(observed[-1].get(left_date))
    output = []
    for row in observed:
        item = dict(row)
        item.update({"date": row.get(left_date), "value": row.get(left_value),
                     "observation_type": "observed"})
        output.append(item)
    for row in sorted(rrows, key=lambda item: normalized_date(item.get(right_date))):
        # The forecast source may include the as-of/base month. Keep the
        # observed value at that boundary and append only future months.
        if normalized_date(row.get(right_date)) <= observed_end:
            continue
        item = dict(row)
        item.update({"date": row.get(right_date), "value": row.get(right_value),
                     "observation_type": "forecast"})
        output.append(item)
    if not output or not any(item.get("observation_type") == "forecast" for item in output):
        return TypedResult.empty(ValueType.TIME_SERIES, "temporal_continuation_no_future_rows", **metadata)
    unit = left.unit or right.unit
    return TypedResult.success(
        ValueType.TIME_SERIES, output, entity=metadata["entity"], metric="price",
        period={"kind": "temporal_continuation", "observed": left.period, "forecast": right.period},
        unit=unit, source=metadata["source"], evidence=metadata["evidence"],
        provenance=metadata["provenance"], upstream_step_ids=metadata["upstream_step_ids"],
        warnings=metadata["warnings"],
    )
