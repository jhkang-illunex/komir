"""Composable value presenters using the existing table/chart wire helpers."""
from __future__ import annotations

from typing import Mapping

from .chatbot_events import ChatEvent, chart_spec, table_block
from .presentation_event_assembly import delta
from .presentation_compatibility import chart_units_compatible
from .pipe_runtime import TypedResult


def text(result: TypedResult) -> list[ChatEvent]:
    return [delta(result.value)]


def string_list(result: TypedResult) -> list[ChatEvent]:
    return [delta("\n".join(result.value))]


def table(result: TypedResult) -> list[ChatEvent]:
    columns = list(dict.fromkeys(key for row in result.value for key in row.keys()))
    value = {"columns": columns,
             "rows": [[str(row.get(column, "")) for column in columns] for row in result.value],
             "markdown": ""}
    value["markdown"] = "\n".join([
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *["| " + " | ".join(row) + " |" for row in value["rows"]],
    ])
    events = [delta(value["markdown"]), ChatEvent("table", table_block(
        value, block_id="multihop-table", source_index=1,
        source_label=(result.source[0] if result.source else None), unit=result.unit))]
    events.extend(chart(result, value))
    return events


def chart(result: TypedResult, table_value: dict) -> list[ChatEvent]:
    value = chart_spec(table_value, block_id="multihop-chart", data_ref="multihop-table",
                       source_index=1, source_label=(result.source[0] if result.source else None),
                       unit=result.unit) if chart_units_compatible(result) else None
    return [ChatEvent("chart", value)] if value else []


def partial_summary(result: TypedResult) -> ChatEvent:
    rows = result.value if isinstance(result.value, list) else []
    if rows and all(isinstance(row, Mapping) and "status" in row for row in rows):
        completed = sum(str(row["status"]).casefold() == "success" for row in rows)
        summary = f"표시된 {len(rows)}개 항목 중 {completed}개 처리 완료, {len(rows) - completed}개 처리 불가."
        if "incomplete_population" in result.warnings:
            summary += " 선행 결과가 불완전하여 전체 모집단 결과는 아닙니다."
    else:
        summary = "일부 결과만 확인되었습니다. 전체 모집단 결과는 아닙니다."
    return delta(summary + "\n")


# Ordered composition seam, not an intent parser. New value presenters can be
# composed here without extending the live runtime's presentation dispatcher.
VALUE_PRESENTERS = (
    (lambda r: isinstance(r.value, str), text),
    (lambda r: isinstance(r.value, list) and all(isinstance(row, str) for row in r.value), string_list),
    (lambda r: isinstance(r.value, list) and bool(r.value)
     and all(isinstance(row, Mapping) for row in r.value), table),
)


def value_events(result: TypedResult) -> list[ChatEvent]:
    return [event for accepts, presenter in VALUE_PRESENTERS if accepts(result)
            for event in presenter(result)]
