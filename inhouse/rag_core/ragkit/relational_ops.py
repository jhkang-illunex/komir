"""Deterministic binary Join/Compare over validated typed results.

Inputs are ordered by InputRef, never by completion order. Duplicate or null
keys are rejected rather than manufacturing a Cartesian product. Numeric
comparisons use left minus/divided by right; percent change uses right as base.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping

from .pipe_runtime import ResultStatus, TypedResult
from .semantic_ir import Operator, RequirementNode, ValueType
from .temporal_composition import compose_temporal_continuation


def execute_relation(node: RequirementNode, inputs: Mapping[str, TypedResult],
                     resolve_field: Callable[..., str | None]) -> TypedResult:
    if len(inputs) != 2:
        return TypedResult.abstain("relation_requires_two_inputs")
    left, right = inputs.values()
    inherited_partial = any(item.status == ResultStatus.PARTIAL for item in (left, right))
    if any(item.status not in {ResultStatus.SUCCESS, ResultStatus.EMPTY, ResultStatus.PARTIAL} for item in (left, right)):
        return TypedResult.failed("dependency_failed")
    # Legacy adapters also use EMPTY for rejected retrieval. Its evidence is
    # not approved and must never be reintroduced by an outer join.
    if any(item.status == ResultStatus.EMPTY for item in (left, right)):
        return TypedResult.empty(ValueType.FACT_SET, "dependency_unavailable")
    if any(not item.sufficient or not item.evidence for item in (left, right)):
        return TypedResult.abstain("evidence_insufficient")

    metadata = dict(
        entity=tuple(dict.fromkeys(left.entity + right.entity)),
        evidence=left.evidence + right.evidence,
        source=tuple(dict.fromkeys(left.source + right.source)),
        provenance=tuple(dict.fromkeys(left.provenance + right.provenance)),
        upstream_step_ids=tuple(ref.node_id for ref in node.inputs) or tuple(inputs),
        warnings=tuple(dict.fromkeys(left.warnings + right.warnings + (("incomplete_population",) if inherited_partial else ()))),
        period=left.period if left.period == right.period else None,
    )

    def rows(item):
        if item.status == ResultStatus.EMPTY:
            return []
        if isinstance(item.value, Mapping):
            return [dict(item.value)]
        if isinstance(item.value, list) and all(isinstance(row, Mapping) for row in item.value):
            return [dict(row) for row in item.value]
        raise ValueError("relation_requires_structured_rows")

    def key_fields(value):
        fields = [value] if isinstance(value, str) else value
        if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or not f for f in fields):
            raise ValueError("invalid_join_keys")
        if len(set(fields)) != len(fields):
            raise ValueError("invalid_join_keys")
        return fields

    def indexed(data, fields):
        resolved = [resolve_field(data, f) for f in fields]
        if data and any(f is None for f in resolved):
            raise ValueError("missing_join_key")
        index = {}
        for row in data:
            if any(field not in row for field in resolved):
                raise ValueError("missing_join_key")
            values = tuple(row[f] for f in resolved)
            if any(v is None for v in values):
                raise ValueError("null_join_key")
            if any(isinstance(v, (list, dict, bool)) or not isinstance(v, (str, int, float))
                   or isinstance(v, float) and not math.isfinite(v) for v in values):
                raise ValueError("invalid_join_key")
            # Do not silently equate country code 1, string '1', and bool True.
            key = tuple((type(v).__name__, v) for v in values)
            if key in index:
                raise ValueError("ambiguous_join_cardinality")
            index[key] = row
        return index

    try:
        lrows, rrows = rows(left), rows(right)
        # Only an explicit per-row outcome can make a partial population safe
        # for row-local operations. Opaque partial payloads remain blocked.
        allowed = {"SUCCESS", "DATA_UNAVAILABLE", "DEPENDENCY_FAILED", "EXECUTION_FAILED",
                   "NEEDS_SELECTION", "FAILED", "ABSTAINED"}
        for item, data in ((left, lrows), (right, rrows)):
            if item.status == ResultStatus.PARTIAL and any(
                not isinstance(row.get("status"), str) or row["status"] not in allowed for row in data
            ):
                raise ValueError("partial_row_status_required")
        args = node.args
        compare = node.operator == Operator.COMPARE
        operation = args.get("operation", "side_by_side")
        if compare and operation not in {"side_by_side", "difference", "ratio", "percent_change", "temporal_continuation"}:
            raise ValueError("unsupported_comparison_operation")

        if compare and operation == "temporal_continuation":
            return compose_temporal_continuation(left, right, lrows, rrows, args, metadata, resolve_field)
        common_key = args.get("join_key", args.get("on"))
        lkey = args.get("left_on", common_key)
        rkey = args.get("right_on", common_key)
        broadcast = args.get("broadcast")
        if broadcast is not None:
            if not compare or broadcast not in {"left", "right"} or lkey is not None or rkey is not None:
                raise ValueError("invalid_scalar_broadcast")
            scalar, scalar_rows = (left, lrows) if broadcast == "left" else (right, rrows)
            if scalar.result_type != ValueType.SCALAR_METRIC or len(scalar_rows) != 1:
                raise ValueError("broadcast_requires_typed_scalar")
            if scalar.status != ResultStatus.SUCCESS or any(w.startswith("aggregate_nulls_excluded:") for w in scalar.warnings):
                raise ValueError("incomplete_scalar_population")
            lkeys = []
            count = len(rrows) if broadcast == "left" else len(lrows)
            li = {(i,): lrows[0] if broadcast == "left" else lrows[i] for i in range(count)}
            ri = {(i,): rrows[0] if broadcast == "right" else rrows[i] for i in range(count)}
        elif lkey is None and rkey is None:
            if compare and operation == "side_by_side" and (len(lrows) > 1 or len(rrows) > 1):
                # Independent populations can be presented side by side, but
                # must not be paired by row position.  Arithmetic comparisons
                # still require an explicit key (or scalar broadcast).
                lkeys = rkeys = []
                li = {("left", index): row for index, row in enumerate(lrows)}
                ri = {("right", index): row for index, row in enumerate(rrows)}
                keys = list(li) + list(ri)
            elif not compare:
                raise ValueError("join_key_required")
            elif len(lrows) > 1 or len(rrows) > 1:
                raise ValueError("comparison_alignment_required")
            else:
                lkeys = []
                li = {(): lrows[0]} if lrows else {}
                ri = {(): rrows[0]} if rrows else {}
        else:
            lkeys, rkeys = key_fields(lkey), key_fields(rkey)
            reserved = {"left_unit", "right_unit", "left_period", "right_period", "left_entity", "right_entity",
                        "left_source", "right_source", "left_value", "right_value", "status", "reason",
                        "difference", "ratio", "percent_change", "match_status"}
            if any(field in reserved or field.startswith(("left.", "right.")) for field in lkeys):
                raise ValueError("join_output_field_collision")
            if len(lkeys) != len(rkeys):
                raise ValueError("join_key_arity_mismatch")
            li, ri = indexed(lrows, lkeys), indexed(rrows, rkeys)
        how = args.get("how", "full" if compare else "inner")
        if how not in {"inner", "left", "full"}:
            raise ValueError("unsupported_join_mode")
        keys = [k for k in li if how != "inner" or k in ri]
        if how == "full":
            keys += [k for k in ri if k not in li]
        lf = rf = None
        if compare:
            fields = args.get("fields") or []
            if not isinstance(fields, list) or len(fields) > 2:
                raise ValueError("invalid_comparison_fields")
            left_field = args.get("left_field", args.get("field", fields[0] if fields else None))
            right_field = args.get("right_field", args.get("field", fields[-1] if fields else None))
            preferred = ("value", "production_volume", "reserves_volume",
                         "import_value", "import_amount", "price", "inventory")
            def infer(data):
                for candidate in preferred:
                    resolved = resolve_field(data, candidate)
                    if resolved:
                        return candidate
                return None
            if operation == "side_by_side" and (left_field is None or right_field is None):
                # A presentation-only comparison may omit field names when
                # each typed input exposes one canonical measure.  Infer only
                # registered metric aliases, never an arbitrary numeric year
                # or metadata column.  Arithmetic comparisons stay strict.
                left_field = left_field or infer(lrows)
                right_field = right_field or infer(rrows)
            if operation == "side_by_side":
                # Country/entity fields are join dimensions, not measures.
                # If a model supplies one as the display field, keep the
                # dimension in the source rows and compare the typed measure.
                dimensions = {"country", "country_code", "country_name", "entity", "mineral", "year", "date"}
                if str(left_field).casefold() in dimensions:
                    left_field = infer(lrows)
                if str(right_field).casefold() in dimensions:
                    right_field = infer(rrows)
            if not isinstance(left_field, str) or not isinstance(right_field, str):
                raise ValueError("comparison_field_required")
            lf, rf = resolve_field(lrows, left_field), resolve_field(rrows, right_field)
            if operation == "side_by_side":
                # Models sometimes copy one metric field to both sides of a
                # presentation-only comparison.  Do not let that lexical
                # mismatch discard otherwise valid typed measures; resolve
                # each side against its own result contract.  Arithmetic
                # comparisons remain strict because changing an operand
                # there would change the calculation semantics.
                if lrows and lf is None:
                    left_field = infer(lrows)
                    lf = resolve_field(lrows, left_field) if left_field else None
                if rrows and rf is None:
                    right_field = infer(rrows)
                    rf = resolve_field(rrows, right_field) if right_field else None
            if not left_field or not right_field or lrows and not lf or rrows and not rf:
                raise ValueError("comparison_field_required")
            if operation != "side_by_side":
                if not left.unit or not right.unit:
                    raise ValueError("unit_unavailable")
                if left.unit != right.unit:
                    raise ValueError("unit_mismatch")
                if any(row.get("unit", item.unit) != item.unit for item, data in ((left, lrows), (right, rrows)) for row in data):
                    raise ValueError("unit_mismatch")

        output = []
        incomplete = 0
        successful = 0
        for key in keys:
            lrow, rrow = li.get(key), ri.get(key)
            invalid_left = lrow is not None and lrow.get("status", "SUCCESS") != "SUCCESS"
            invalid_right = rrow is not None and rrow.get("status", "SUCCESS") != "SUCCESS"
            dependency_failed = invalid_left or invalid_right
            row = {field: value[1] for field, value in zip(lkeys, key)}
            independent_side = key[0] if len(key) == 2 and key[0] in {"left", "right"} else None
            for side, data, invalid in (("left", lrow, invalid_left), ("right", rrow, invalid_right)):
                # A failed row may contain a stale numeric payload. Preserve
                # its status/reason but never expose that payload as evidence.
                row.update({f"{side}.{field}": value for field, value in (data or {}).items()
                            if not invalid or field in {"status", "reason"}})
            row.update(left_unit=left.unit, right_unit=right.unit,
                       left_period=left.period, right_period=right.period,
                       left_entity=list(left.entity), right_entity=list(right.entity),
                       left_source=list(left.source), right_source=list(right.source))
            if not compare:
                row["match_status"] = "matched" if lrow is not None and rrow is not None else "left_only" if lrow is not None else "right_only"
                row.update(status="DEPENDENCY_FAILED" if dependency_failed else "SUCCESS",
                           reason="upstream_row_failed" if dependency_failed else None)
                incomplete += int(dependency_failed)
                successful += int(not dependency_failed)
            else:
                lv = lrow.get(lf) if lrow is not None and not invalid_left else None
                rv = rrow.get(rf) if rrow is not None and not invalid_right else None
                if independent_side == "left":
                    rv = None
                elif independent_side == "right":
                    lv = None
                row.update(left_value=lv, right_value=rv, comparison_side=independent_side,
                           status="SUCCESS", reason=None)
                if dependency_failed:
                    row.update(status="DEPENDENCY_FAILED", reason="upstream_row_failed")
                elif independent_side is not None:
                    pass
                elif lrow is None or rrow is None:
                    row.update(status="DATA_UNAVAILABLE", reason="unmatched_key")
                elif lv is None or rv is None:
                    row.update(status="DATA_UNAVAILABLE", reason="missing_operand")
                if operation != "side_by_side":
                    row[operation] = None
                    if row["status"] == "SUCCESS":
                        try:
                            if isinstance(lv, bool) or isinstance(rv, bool):
                                raise ValueError
                            a, b = float(str(lv).replace(",", "")), float(str(rv).replace(",", ""))
                            if not math.isfinite(a) or not math.isfinite(b):
                                raise ValueError
                            if operation != "difference" and b == 0:
                                row.update(status="DATA_UNAVAILABLE", reason="zero_denominator")
                            else:
                                value = a - b if operation == "difference" else a / b if operation == "ratio" else (a - b) / abs(b) * 100
                                if not math.isfinite(value):
                                    raise ValueError
                                row[operation] = value
                        except (ValueError, TypeError, OverflowError):
                            row.update(status="DATA_UNAVAILABLE", reason="invalid_numeric_operand")
                if row["status"] != "SUCCESS":
                    incomplete += 1
                else:
                    successful += 1
            output.append(row)
        if not output:
            return TypedResult.empty(ValueType.FACT_SET, "no_matching_rows", **metadata)
        unit = (left.unit if operation in {"difference", "side_by_side"} and left.unit == right.unit else
                "%" if compare and operation == "percent_change" else "ratio" if compare and operation == "ratio" else None)
        status = (ResultStatus.EMPTY if not successful else
                  ResultStatus.PARTIAL if incomplete or inherited_partial else ResultStatus.SUCCESS)
        return TypedResult(ValueType.FACT_SET, output, status=status, unit=unit, sufficient=status != ResultStatus.EMPTY,
            metric=operation if compare else None, failure_reason="no_comparable_rows" if status == ResultStatus.EMPTY else None, **metadata)
    except ValueError as exc:
        return TypedResult.abstain(str(exc), ValueType.FACT_SET, **metadata)
