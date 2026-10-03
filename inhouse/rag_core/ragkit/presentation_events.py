"""Ordered composition of existing result presenters, independent of live runtime.

No question/intent interpretation, source calls or execution decisions. The
ExecutionPresentation envelope and ChatEvent wire contract are unchanged.
"""
from __future__ import annotations

from datetime import date
from functools import partial
from typing import Callable, Mapping

from .canonical_presenters import partial_summary, value_events
from .chatbot_events import ChatEvent
from .presentation_compatibility import failure_outcomes, is_snapshot_list, latest_price, normalize_value, snapshot_children
from .presentation_event_assembly import child_event, completed, delta, unavailable
from .semantic_ir import ValueType
from .pipe_runtime import ResultStatus, TypedResult


def _failure(result: TypedResult, failure_events: list[ChatEvent]) -> list[ChatEvent]:
    return failure_events + unavailable(
        result.failure_reason or "source_unavailable",
        result.failure_reason or "확인 가능한 근거가 없어 답변할 수 없습니다.")


def _composite(result: TypedResult, present: Callable) -> list[ChatEvent]:
    sources = list(dict.fromkeys(source for child in result.value.values()
                   if isinstance(child, TypedResult) for source in child.source))
    events: list[ChatEvent] = []
    completed_count = 0
    for output_id, child in result.value.items():
        if not isinstance(child, TypedResult):
            continue
        events.append(delta(f"\n{output_id}\n"))
        for event in present(child):
            if event.type == "done":
                completed_count += not event.data.get("abstained", True)
            else:
                events.append(child_event(event, output_id, child, sources))
    if result.status == ResultStatus.PARTIAL or completed_count < len(result.value):
        events.append(delta("\n일부 요청 결과만 확인되었습니다."))
    events.append(completed(sources, abstained=not bool(completed_count)))
    return events


def _value(result: TypedResult, present: Callable) -> list[ChatEvent]:
    result = normalize_value(result)
    if not result.value:
        return present(TypedResult.abstain("presentation_unavailable"))
    events = value_events(result)
    if result.status == ResultStatus.PARTIAL and events:
        events.insert(0, partial_summary(result))
    if not events:
        return present(TypedResult.abstain("unsupported_presentation_type"))
    events.append(completed(result.source))
    return events


def result_events(result: TypedResult, *, row_date: Callable,
                  today: Callable[[], date]) -> list[ChatEvent]:
    # Must run before status/shape selection, including existing exception order.
    failure_events = failure_outcomes(result)
    present = partial(result_events, row_date=row_date, today=today)
    # Ordered presenters preserve legacy shape precedence; extending a family
    # does not require a new branch in live_multihop or a renderer hierarchy.
    routes = (
        (lambda r: r.status in {ResultStatus.ABSTAINED, ResultStatus.EMPTY, ResultStatus.FAILED, ResultStatus.DEPENDENCY_FAILED},
         partial(_failure, failure_events=failure_events)),
        (is_snapshot_list, lambda r: present(snapshot_children(r))),
        (lambda r: r.result_type == ValueType.COMPOSITE and isinstance(r.value, Mapping),
         partial(_composite, present=present)),
        (lambda r: r.result_type == ValueType.COMPOSITE and isinstance(r.value, list),
         partial(latest_price, row_date=row_date, today=today, failure_events=failure_events)),
        (lambda r: True, partial(_value, present=present)),
    )
    presenter = next(handler for accepts, handler in routes if accepts(result))
    return presenter(result)
