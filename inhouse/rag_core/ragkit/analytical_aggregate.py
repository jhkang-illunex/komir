"""Deterministic aggregation of an already validated population, no retrieval."""
from collections import defaultdict
from dataclasses import replace
import math
import statistics
from typing import Mapping

from .pipe_runtime import TypedResult, ResultStatus
from .semantic_ir import ValueType

SUPPORTED_AGGREGATIONS = frozenset({"sum", "average", "mean", "count", "min", "max", "stddev_pop", "stddev_samp", "first", "last"})


def _derived_group_value(row: Mapping, requested: str, resolved: str | None):
    """Return a temporal grouping key without inventing a source column.

    Retrieval contracts commonly expose an observation date, while a semantic
    aggregate may request ``year`` or ``month``.  The grouping dimension is
    derived from that typed date; it is not a fallback to an arbitrary numeric
    field.
    """
    if resolved is not None:
        return row.get(resolved)
    if requested not in {"year", "month"}:
        return None
    for key, value in row.items():
        text = str(key).casefold()
        if not any(token in text for token in ("date", "ymd", "일자", "기준일", "시점")):
            continue
        raw = str(value).strip()
        try:
            if len(raw) == 8 and raw.isdigit():
                year, month = int(raw[:4]), int(raw[4:6])
            else:
                year, month = int(raw[:4]), int(raw[5:7])
        except (TypeError, ValueError, IndexError):
            continue
        return year if requested == "year" else f"{year:04d}-{month:02d}"
    return None


def aggregate(source, args, resolve):
    rows = source.value if isinstance(source.value, list) else [source.value]
    if not rows or not all(isinstance(row, Mapping) for row in rows):
        return TypedResult.abstain("aggregate_input_incomplete")
    if any(str(row.get("status", "success")).lower() != "success" for row in rows):
        return TypedResult.abstain("incomplete_population")
    field = resolve(rows, args.get("field") or args.get("metric_field"))
    operation = args.get("aggregation")
    if not field or operation not in SUPPORTED_AGGREGATIONS:
        return TypedResult.abstain("unsupported_aggregate_contract")
    groups = args.get("group_by") or []
    groups = [groups] if isinstance(groups, str) else groups
    if not isinstance(groups, list) or any(not isinstance(key, str) for key in groups):
        return TypedResult.abstain("invalid_group_by")
    resolved = [resolve(rows, key) for key in groups]
    if any(key is None and group not in {"year", "month"} for key, group in zip(resolved, groups)):
        return TypedResult.abstain("group_field_unavailable")
    units = {row.get("unit", source.unit) for row in rows}
    if len(units) > 1 or ("heterogeneous_units" in source.warnings and None in units):
        return TypedResult.abstain("unit_mismatch")
    buckets = defaultdict(list)
    for row in rows:
        key = tuple(_derived_group_value(row, requested, concrete)
                    for requested, concrete in zip(groups, resolved))
        if any(value is None or not isinstance(value, (str, int, float)) or isinstance(value, bool) for value in key):
            return TypedResult.abstain("invalid_group_key")
        # Match the join contract: int/string keys do not silently coalesce.
        buckets[tuple((type(v).__name__, v) for v in key)].append(row)
    output = []
    policy = args.get("null_policy", "reject")
    if policy not in {"reject", "skip"}:
        return TypedResult.abstain("invalid_null_policy")
    alias = args.get("output_field", field)
    if not isinstance(alias, str) or not alias or alias in groups or args.get("include_count") and alias == "observation_count":
        return TypedResult.abstain("aggregate_output_collision")
    for key, population in buckets.items():
        usable = [row for row in population if row.get(field) is not None]
        if not usable or policy == "reject" and len(usable) != len(population):
            return TypedResult.abstain("aggregate_input_incomplete")
        values = []
        for row in usable:
            if operation == "count":
                values.append(row[field])
                continue
            try:
                value = float(str(row[field]).replace(",", ""))
            except (ValueError, TypeError):
                return TypedResult.abstain("invalid_numeric_operand")
            if isinstance(row[field], bool) or not math.isfinite(value):
                return TypedResult.abstain("invalid_numeric_operand")
            values.append(value)
        if operation in {"first", "last"}:
            order_field = resolve(rows, args.get("order_by"))
            if not order_field or any(row.get(order_field) is None for row in usable):
                return TypedResult.abstain("aggregate_order_required")
            try:
                ordered = sorted(usable, key=lambda row: row[order_field])
            except TypeError:
                return TypedResult.abstain("incompatible_order_values")
            selected = ordered[0 if operation == "first" else -1]
            tied = [row for row in ordered if row[order_field] == selected[order_field]]
            if len(tied) != 1:
                return TypedResult.abstain("ambiguous_order_tie")
            value = selected[field]
        else:
            if operation == "stddev_samp" and len(values) < 2:
                return TypedResult.abstain("insufficient_sample")
            fn = {"sum": sum, "average": statistics.mean, "mean": statistics.mean,
                  "count": len, "min": min, "max": max,
                  "stddev_pop": statistics.pstdev, "stddev_samp": statistics.stdev}[operation]
            value = fn(values)
            if not math.isfinite(value):
                return TypedResult.abstain("invalid_numeric_result")
        item = {name: typed[1] for name, typed in zip(groups, key)}
        item[alias] = value
        if operation in {"first", "last"}:
            item[args["order_by"]] = selected[order_field]
        if args.get("include_count"):
            item["observation_count"] = len(usable)
        output.append(item)
    excluded = sum(row.get(field) is None for row in rows)
    warnings = source.warnings + ((f"aggregate_nulls_excluded:{excluded}",) if excluded else ())
    return replace(source, result_type=ValueType.FACT_SET if groups else ValueType.SCALAR_METRIC,
                   value=output, unit=None if operation == "count" else next(iter(units)),
                   warnings=warnings,
                   status=ResultStatus.PARTIAL if excluded and operation == "sum" else source.status)
