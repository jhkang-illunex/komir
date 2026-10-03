"""Deferred legacy presentation behavior, not canonical domain contracts.

Snapshot interpretation, document text, price physical keys/unit codes and chart
eligibility remain unchanged. They must not be reused as source normalization.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any, Callable, Mapping

from .chatbot_events import ChatEvent, table_block, _price_unit_from_codes, _verified_display_unit
from .presentation_event_assembly import completed, delta, unavailable
from .semantic_ir import ValueType
from .pipe_runtime import ResultStatus, TypedResult


def failure_outcomes(result: TypedResult) -> list[ChatEvent]:
    failed_rows = []
    if result.result_type == ValueType.COMPOSITE and isinstance(result.value, list):
        failed_rows = [[str(item.get("mineral") or ""), str(item.get("output") or item.get("metric") or ""),
                        str(item.get("status") or "unknown"), str(item.get("reason") or "unspecified_failure")]
                       for item in result.value if isinstance(item, Mapping) and item.get("status") != "success"]
    if not failed_rows:
        return []
    return [ChatEvent("table", table_block(
        {"columns": ["광종", "요청 결과", "상태", "사유"], "rows": failed_rows, "markdown": ""},
        block_id="multihop-item-outcomes", source_index=None, source_label=None))]


def is_snapshot_list(result: TypedResult) -> bool:
    return result.result_type == ValueType.COMPOSITE and isinstance(result.value, list) and any(
        isinstance(item, Mapping) and (item.get("output") == "time_series" or item.get("metric") not in {None, "price"})
        for item in result.value)


def snapshot_children(result: TypedResult) -> TypedResult:
    children = {}
    for index, item in enumerate(result.value):
        if not isinstance(item, Mapping):
            continue
        key = f"{item.get('mineral', index)}:{item.get('output', 'result')}"
        children[key] = TypedResult(
            ValueType(item.get("result_type", "fact_set")), item.get("value"),
            status=ResultStatus(item.get("status", "failed")),
            sufficient=item.get("status") in {"success", "partial"},
            unit=item.get("unit"), period=item.get("period"),
            evidence=tuple(item.get("evidence") or ()), source=tuple(item.get("source") or ()),
            provenance=tuple(item.get("provenance") or ()), failure_reason=item.get("reason"))
    return replace(result, value=children)


def normalize_value(result: TypedResult) -> TypedResult:
    if isinstance(result.value, Mapping):
        result = replace(result, value=[result.value])
    if result.result_type == ValueType.DOCUMENT_EVIDENCE and isinstance(result.value, list):
        texts = [getattr(item, "text", "") for item in result.value]
        if texts and all(texts):
            result = replace(result, value="\n\n".join(texts))
    return result


def chart_units_compatible(result: TypedResult) -> bool:
    row_units = {row.get("unit", result.unit) for row in result.value}
    return len(row_units) <= 1 and not (
        (result.metric == "price" or "heterogeneous_units" in result.warnings) and None in row_units)


def _latest_price_rows(result: TypedResult, row_date: Callable, today: Callable[[], date]):
    lines: list[str] = []
    latest_rows: list[tuple[str, Any, Any, str | None, str | None]] = []
    for item in result.value:
        if not isinstance(item, Mapping) or str(item.get("status", "")).casefold() != "success":
            continue
        mineral = str(item.get("mineral") or "").strip()
        value = item.get("value")
        dated_rows = [row for row in value if isinstance(row, Mapping) and row_date(row) is not None and row_date(row) <= today()] if isinstance(value, list) else []
        if isinstance(value, list) and not dated_rows and any(isinstance(row, Mapping) and row_date(row) is not None for row in value):
            continue
        row = max(dated_rows, key=row_date) if dated_rows else (value[0] if isinstance(value, list) and value and isinstance(value[0], Mapping) else value)
        if not mineral or not isinstance(row, Mapping):
            continue
        date_key = next((key for key in row if "기준일" in str(key) or str(key).casefold() in {"date", "observed_date", "crtr_ymd"}), None)
        price_key = next((key for key in row if "통상가격" in str(key)), None)
        price_key = price_key or next((key for key in row if str(key).casefold() in {"price", "value", "latest_price"}), None)
        if price_key is None or row.get(price_key) in (None, "None", ""):
            continue
        observed = f" ({row[date_key]} 기준)" if date_key and row.get(date_key) not in (None, "") else ""
        raw_unit = item.get("unit") or row.get("단위")
        unit = _verified_display_unit(raw_unit)
        if not unit and isinstance(raw_unit, str):
            unit_fields = dict(part.strip().split("=", 1) for part in raw_unit.split(";") if "=" in part)
            currency, weight = unit_fields.get("통화코드"), unit_fields.get("중량단위코드")
            if currency and weight:
                unit = _price_unit_from_codes([currency.strip()], [weight.strip()])
        item_source = next(iter(item.get("source") or []), None)
        lines.append(f"{mineral}: {row[price_key]}{(' ' + str(unit)) if unit else ''}{observed}")
        latest_rows.append((mineral, row[price_key], row.get(date_key) if date_key else None, unit, item_source))
    return lines, latest_rows


def latest_price(result: TypedResult, *, row_date: Callable, today: Callable[[], date],
                 failure_events: list[ChatEvent]) -> list[ChatEvent]:
    lines, latest_rows = _latest_price_rows(result, row_date, today)
    if not lines:
        return failure_events + unavailable("presentation_unavailable", "표시할 수 있는 검증된 결과가 없습니다.")
    events = [delta("\n".join(lines))]
    for index, (mineral, price, observed_date, unit, item_source) in enumerate(latest_rows, 1):
        table = {
            "columns": ["광종", "최근 가격", "기준일"],
            "rows": [[mineral, str(price), str(observed_date or "")]],
            "markdown": f"| 광종 | 최근 가격 | 기준일 |\n| --- | --- | --- |\n| {mineral} | {price} | {observed_date or ''} |",
        }
        events.append(ChatEvent("table", table_block(
            table, block_id=f"multihop-price-{index}",
            source_index=(result.source.index(item_source) + 1 if item_source in result.source else None),
            source_label=item_source, unit=unit)))
    if result.status == ResultStatus.PARTIAL:
        events.append(delta("\n일부 항목은 조회하지 못했습니다."))
    events.extend(failure_events)
    events.append(completed(result.source))
    return events
