"""Pure Calculate helpers over complete, evidenced TypedResults.

Contract: calculate_series(source, args, resolve) -> TypedResult, where resolve
has the analytical_aggregate field-resolver signature. No retrieval or defaults
inferred from prose. Supported calculations: endpoint_change, periodic_return,
base100, threshold_first, correlation. Returns are simple percent returns with
an absolute base denominator (the existing Compare convention), not log returns.

time_field is an ISO date or YYYY-MM. group_by identifies independent series;
duplicate group/date pairs are rejected even when values agree. null_policy is
reject (default), or skip for explicitly requested valid-observation semantics.
periodic_return requires frequency=observation|month; missing calendar months
are rejected. endpoint bounds require endpoint_policy=inside: first/last actual
observation inside inclusive start/end, never an interpolated/as-of endpoint.
Correlation consumes an already full-joined population, explicit field and
other_field; pairwise NULLs require null_policy=pairwise and are counted.
Units of two correlation operands need not match, but each must be internally
consistent (other_unit_field is required). Truncation/failed evidence cannot be
made complete by filtering. No causality, annualization, claim tolerance, or
market-outlook interpretation contract is implied by these calculations.
"""
from collections import defaultdict
from dataclasses import replace
from datetime import date
import math
import statistics
from typing import Mapping

from .pipe_runtime import ResultStatus, TypedResult
from .semantic_ir import ValueType


CALCULATIONS = frozenset({"endpoint_change", "periodic_return", "base100",
                          "threshold_first", "correlation"})


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_numeric_operand")
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("invalid_numeric_operand") from None
    if not math.isfinite(result):
        raise ValueError("invalid_numeric_operand")
    return result


def _date(value):
    if not isinstance(value, str) or len(value) not in {7, 10}:
        raise ValueError("invalid_series_date")
    try:
        parsed = date.fromisoformat(value + "-01" if len(value) == 7 else value)
    except ValueError:
        raise ValueError("invalid_series_date") from None
    if parsed.isoformat()[:len(value)] != value:
        raise ValueError("invalid_series_date")
    return parsed


def _change(start, end):
    if start == 0:
        raise ValueError("zero_denominator")
    return (end - start) / abs(start) * 100


def calculate_series(source, args, resolve):
    """Reject the whole calculation on invalid data, preserving its provenance."""
    if source is None:
        return TypedResult.abstain("missing_input")
    try:
        if source.status != ResultStatus.SUCCESS or source.failure_reason or any(
            marker in warning.lower() for warning in source.warnings
            for marker in ("incomplete", "truncat", "partial")
        ):
            raise ValueError("incomplete_population")
        if not source.sufficient or not source.evidence:
            raise ValueError("evidence_insufficient")
        if source.result_type not in {ValueType.TIME_SERIES, ValueType.FACT_SET, ValueType.SCALAR_METRIC}:
            raise ValueError("invalid_series_type")
        rows = source.value
        if not isinstance(rows, list) or not rows or not all(isinstance(r, Mapping) for r in rows):
            raise ValueError("series_input_incomplete")
        operation = args.get("calculation")
        if operation not in CALCULATIONS:
            raise ValueError("unsupported_calculation_contract")
        field = resolve(rows, args.get("field") or args.get("metric_field"))
        time = resolve(rows, args.get("time_field"))
        if not field or not time:
            raise ValueError("series_fields_required")
        groups = args.get("group_by", [])
        groups = [groups] if isinstance(groups, str) else groups
        if not isinstance(groups, list) or any(not isinstance(g, str) or not g for g in groups) or len(set(groups)) != len(groups):
            raise ValueError("invalid_group_by")
        keys = [resolve(rows, g) for g in groups]
        if any(k is None for k in keys) or len(set(keys)) != len(keys):
            raise ValueError("group_field_unavailable")
        alias = args.get("output_field", "value")
        reserved = {"date", "start_date", "end_date", "base_date", "start_value", "end_value",
                    "base_value", "observation_count", "matched", "threshold", "left_only_count",
                    "right_only_count", "neither_count", "unit", "source_unit"}
        if not isinstance(alias, str) or not alias or alias in reserved or alias in groups or reserved.intersection(groups):
            raise ValueError("series_output_collision")
        policy = args.get("null_policy", "reject")
        if policy not in ({"reject", "pairwise"} if operation == "correlation" else {"reject", "skip"}):
            raise ValueError("invalid_null_policy")
        frequency = args.get("frequency")
        if operation == "periodic_return" and frequency not in {"observation", "month"}:
            raise ValueError("return_frequency_required")
        bounded = "start" in args or "end" in args
        if bounded and (operation != "endpoint_change" or args.get("endpoint_policy") != "inside"):
            raise ValueError("endpoint_policy_required")
        if operation == "endpoint_change" and args.get("endpoint_policy", "inside") != "inside":
            raise ValueError("unsupported_endpoint_policy")
        lower, upper = (_date(args["start"]), _date(args["end"])) if bounded else (None, None)
        if bounded and lower > upper:
            raise ValueError("invalid_endpoint_window")
        other = resolve(rows, args.get("other_field")) if operation == "correlation" else None
        other_unit = resolve(rows, args.get("other_unit_field")) if other else None
        unit_field = resolve(rows, args["unit_field"]) if "unit_field" in args else "unit"
        if unit_field is None or operation == "correlation" and (not other or not other_unit):
            raise ValueError("correlation_fields_required")
        buckets = defaultdict(list)
        for row in rows:
            if str(row.get("status", "success")).lower() != "success":
                raise ValueError("incomplete_population")
            values = tuple(row.get(k) for k in keys)
            if any(v is None or isinstance(v, bool) or not isinstance(v, (str, int, float))
                   or isinstance(v, float) and not math.isfinite(v) for v in values):
                raise ValueError("invalid_group_key")
            day = _date(row.get(time))
            missing_pair = operation == "correlation" and policy == "pairwise" and (
                row.get("match_status") == "left_only" and field in row or
                row.get("match_status") == "right_only" and other in row)
            if (field not in row or other and other not in row) and not missing_pair:
                raise ValueError("series_field_missing")
            buckets[tuple((type(v).__name__, v) for v in values)].append((day, row))
        output = []
        skipped = False
        for key, population in buckets.items():
            population.sort(key=lambda pair: pair[0])
            if len({d for d, _ in population}) != len(population):
                raise ValueError("duplicate_series_date")
            if len({len(r[time]) for _, r in population}) != 1:
                raise ValueError("mixed_date_granularity")
            def unit_for(column, unit_column, fallback):
                units = {r.get(unit_column, fallback) for _, r in population if r.get(column) is not None}
                if not units or any(not isinstance(u, str) or not u.strip() for u in units):
                    raise ValueError("unit_unavailable")
                if len(units) != 1:
                    raise ValueError("unit_mismatch")
                return next(iter(units))
            source_unit = unit_for(field, unit_field, source.unit)
            item = {name: typed[1] for name, typed in zip(groups, key)}
            if operation == "correlation":
                unit_for(other, other_unit, None)
                pairs, left, right, neither = [], 0, 0, 0
                for _, row in population:
                    x, y = row.get(field), row.get(other)
                    x = _number(x) if x is not None else None
                    y = _number(y) if y is not None else None
                    if x is None or y is None:
                        if policy != "pairwise":
                            raise ValueError("series_input_incomplete")
                        left += x is not None
                        right += y is not None
                        neither += x is None and y is None
                    else:
                        pairs.append((x, y))
                if len(pairs) < 2:
                    raise ValueError("insufficient_sample")
                x, y = zip(*pairs)
                if len(set(x)) == 1 or len(set(y)) == 1:
                    raise ValueError("constant_series")
                output.append({**item, alias: statistics.correlation(x, y), "observation_count": len(pairs),
                               "left_only_count": left, "right_only_count": right, "neither_count": neither})
                continue
            usable = []
            for day, row in population:
                if row[field] is None:
                    if policy == "reject" or operation == "periodic_return" and frequency == "month":
                        raise ValueError("series_input_incomplete")
                    skipped = True
                    continue
                value = _number(row[field])
                if not bounded or lower <= day <= upper:
                    usable.append((day, row[time], value))
            if not usable:
                raise ValueError("series_input_incomplete")
            first, last = usable[0], usable[-1]
            if operation == "endpoint_change":
                if len(usable) < 2:
                    raise ValueError("insufficient_sample")
                output.append({**item, alias: _change(first[2], last[2]), "start_date": first[1],
                               "end_date": last[1], "start_value": first[2], "end_value": last[2],
                               "source_unit": source_unit, "observation_count": len(usable)})
            elif operation == "periodic_return":
                if len(usable) < 2:
                    raise ValueError("insufficient_sample")
                for previous, current in zip(usable, usable[1:]):
                    if frequency == "month" and (current[0].year * 12 + current[0].month -
                                                  previous[0].year * 12 - previous[0].month != 1):
                        raise ValueError("nonconsecutive_months")
                    output.append({**item, "date": current[1], "start_date": previous[1],
                                   alias: _change(previous[2], current[2])})
            elif operation == "base100":
                if first[2] == 0:
                    raise ValueError("zero_denominator")
                for _, day, value in usable:
                    output.append({**item, "date": day, "base_date": first[1],
                                   "base_value": first[2], "source_unit": source_unit,
                                   alias: value / first[2] * 100})
            elif operation == "threshold_first":
                ratio = _number(args["threshold_ratio"])
                if ratio < 0 or first[2] <= 0 or args.get("comparison") not in {"le", "ge"}:
                    raise ValueError("unsupported_threshold_contract")
                threshold = first[2] * ratio
                match = next((v for v in usable if (v[2] <= threshold if args["comparison"] == "le"
                                                   else v[2] >= threshold)), None)
                output.append({**item, "matched": match is not None, "date": match[1] if match else None,
                               alias: match[2] if match else None, "base_date": first[1],
                               "threshold": threshold, "unit": source_unit})
        if any(isinstance(v, float) and not math.isfinite(v) for row in output for v in row.values()):
            raise ValueError("invalid_numeric_result")
        unit = {"endpoint_change": "%", "periodic_return": "%", "base100": "index",
                "correlation": "1", "threshold_first": None}[operation]
        if operation == "threshold_first":
            units = {row["unit"] for row in output}
            unit = next(iter(units)) if len(units) == 1 else None
        series = operation in {"base100", "periodic_return"}
        return replace(source, value=output, unit=unit, metric=alias,
                       result_type=ValueType.TIME_SERIES if series else ValueType.FACT_SET if groups else ValueType.SCALAR_METRIC,
                       warnings=source.warnings + (("null_observations_skipped",) if skipped else ()))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "invalid_series_contract"
        return replace(source, value=None, status=ResultStatus.ABSTAINED, sufficient=False,
                       failure_reason=reason)
