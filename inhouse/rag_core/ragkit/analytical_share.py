"""Shares/HHI for complete non-negative numeric populations only."""
from collections import defaultdict
from dataclasses import replace
import math
from typing import Mapping

from .pipe_runtime import TypedResult, ResultStatus
from .semantic_ir import ValueType


def calculate_share(source, args, resolve):
    if any(warning.startswith("aggregate_nulls_excluded:") for warning in source.warnings):
        return TypedResult.abstain("incomplete_population")
    rows = source.value if isinstance(source.value, list) else []
    if not rows or not all(isinstance(row, dict) for row in rows):
        return TypedResult.abstain("calculation_input_incomplete")
    field = resolve(rows, args.get("field", "value"))
    if field is None:
        return TypedResult.abstain("calculation_field_unavailable")
    groups = args.get("group_by") or []
    groups = [groups] if isinstance(groups, str) else groups
    if not isinstance(groups, list) or any(not isinstance(g, str) for g in groups):
        return TypedResult.abstain("invalid_group_by")
    resolved = [resolve(rows, g) for g in groups]
    if any(g is None for g in resolved):
        return TypedResult.abstain("group_field_unavailable")
    buckets = defaultdict(list)
    for row in rows:
        if row.get("status", "SUCCESS") != "SUCCESS":
            return TypedResult.abstain("incomplete_population")
        try:
            value = float(row[field])
        except (ValueError, TypeError, KeyError):
            return TypedResult.abstain("invalid_share_operand")
        if isinstance(row[field], bool) or not math.isfinite(value) or value < 0:
            return TypedResult.abstain("invalid_share_operand")
        values = tuple(row.get(g) for g in resolved)
        if any(v is None or not isinstance(v, (str, int, float)) or isinstance(v, bool) for v in values):
            return TypedResult.abstain("invalid_group_key")
        key = tuple((type(v).__name__, v) for v in values)
        buckets[key].append((row, value))
    output = []
    hhi = args.get("calculation", "").lower() == "hhi"
    components = hhi and args.get("output") == "contributions"
    for key, population in buckets.items():
        units = {row.get("unit", source.unit) for row, _ in population}
        if len(units) > 1:
            return TypedResult.abstain("unit_mismatch")
        total = math.fsum(v for _, v in population)
        if not math.isfinite(total) or total <= 0:
            return TypedResult.abstain("zero_denominator")
        if hhi and not components:
            item = {name: typed[1] for name, typed in zip(groups, key)}
            item[field] = math.fsum((v / total * 100) ** 2 for _, v in population)
            output.append(item)
        else:
            for row, value in population:
                # Existing numeric field becomes the share, not a second
                # ambiguously-unitized measure on the same TypedResult.
                item = {k: v for k, v in row.items() if k != "unit"}
                item[field] = (value / total * 100) ** 2 if components else value / total * 100
                output.append(item)
    return replace(source, value=output, result_type=ValueType.SCALAR_METRIC if hhi and not components else ValueType.COUNTRY_SHARE,
                   unit="HHI(0-10000)" if hhi else "%", metric="hhi" if hhi else "share")


def calculate_ratio(source, args, resolve):
    """Calculate a typed numerator/denominator ratio from one result.

    This is deliberately row-local: the upstream result must already contain
    both operands.  Population shares use ``calculate_share`` instead; this
    helper is for explicit ratio contracts and never invents a denominator.
    """
    rows = source.value if isinstance(source.value, list) else [source.value]
    if not rows or not all(isinstance(row, dict) for row in rows):
        return TypedResult.abstain("calculation_input_incomplete")
    numerator_name = args.get("numerator_field", args.get("left_field"))
    denominator_name = args.get("denominator_field", args.get("right_field"))
    numerator = resolve(rows, numerator_name) if numerator_name else None
    denominator = resolve(rows, denominator_name) if denominator_name else None
    if not numerator or not denominator:
        return TypedResult.abstain("ratio_fields_required")
    output_field = args.get("output_field", "ratio")
    if not isinstance(output_field, str) or not output_field:
        return TypedResult.abstain("invalid_calculation_output")
    as_percentage = args.get("as_percentage") is True or args.get("unit") == "%"
    output = []
    for row in rows:
        if str(row.get("status", "success")).lower() != "success":
            return TypedResult.abstain("incomplete_population")
        try:
            left = float(row[numerator])
            right = float(row[denominator])
        except (KeyError, TypeError, ValueError):
            return TypedResult.abstain("invalid_ratio_operand")
        if not math.isfinite(left) or not math.isfinite(right) or right == 0:
            return TypedResult.abstain("zero_denominator" if right == 0 else "invalid_ratio_operand")
        item = {key: value for key, value in row.items() if key not in {numerator, denominator}}
        item[output_field] = (left / right * 100) if as_percentage else left / right
        output.append(item)
    unit = "%" if as_percentage else "ratio"
    return replace(source, value=output, result_type=ValueType.SCALAR_METRIC,
                   unit=unit, metric="percentage" if as_percentage else "ratio",
                   status=ResultStatus.SUCCESS)


def calculate_ratio_between(left, right, args, resolve):
    """Calculate a ratio from two independent scalar TypedResults.

    A ratio whose numerator and denominator are produced by separate
    aggregates is a binary calculation, not a row-local projection.  The
    operands still have to be explicitly typed/resolvable; this helper never
    selects an arbitrary numeric column.
    """
    if any(item.status != ResultStatus.SUCCESS or not item.sufficient
           for item in (left, right)):
        return TypedResult.abstain("incomplete_ratio_inputs")

    def one_row(item):
        if isinstance(item.value, Mapping):
            return dict(item.value)
        if isinstance(item.value, list) and len(item.value) == 1 and isinstance(item.value[0], Mapping):
            return dict(item.value[0])
        return None

    left_row, right_row = one_row(left), one_row(right)
    if left_row is None or right_row is None:
        return TypedResult.abstain("ratio_scalar_inputs_required")
    numerator_name = args.get("numerator_field", args.get("left_field"))
    denominator_name = args.get("denominator_field", args.get("right_field"))
    numerator = resolve([left_row], numerator_name) if numerator_name else resolve([left_row], "value")
    denominator = resolve([right_row], denominator_name) if denominator_name else resolve([right_row], "value")
    if not numerator or not denominator:
        return TypedResult.abstain("ratio_fields_required")
    try:
        left_value = float(left_row[numerator])
        right_value = float(right_row[denominator])
    except (KeyError, TypeError, ValueError):
        return TypedResult.abstain("invalid_ratio_operand")
    if not math.isfinite(left_value) or not math.isfinite(right_value):
        return TypedResult.abstain("invalid_ratio_operand")
    if right_value == 0:
        return TypedResult.abstain("zero_denominator")
    output_field = args.get("output_field", "ratio")
    if not isinstance(output_field, str) or not output_field:
        return TypedResult.abstain("invalid_calculation_output")
    as_percentage = args.get("as_percentage") is True or args.get("unit") == "%"
    result_value = left_value / right_value * 100 if as_percentage else left_value / right_value
    metadata = dict(
        entity=tuple(dict.fromkeys(left.entity + right.entity)),
        evidence=left.evidence + right.evidence,
        source=tuple(dict.fromkeys(left.source + right.source)),
        provenance=tuple(dict.fromkeys(left.provenance + right.provenance)),
        upstream_step_ids=left.upstream_step_ids + right.upstream_step_ids,
        period=left.period if left.period == right.period else None,
        warnings=tuple(dict.fromkeys(left.warnings + right.warnings)),
    )
    return TypedResult(
        result_type=ValueType.SCALAR_METRIC,
        value=[{output_field: result_value}],
        unit="%" if as_percentage else "ratio",
        metric="percentage" if as_percentage else "ratio",
        **metadata,
    )
