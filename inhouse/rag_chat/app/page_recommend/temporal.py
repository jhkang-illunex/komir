"""Timezone-aware resolution of relative temporal filters.

이식 출처: komis-report-generator-main `search/temporal.py`(2026-08-11 스냅샷).
python3.10 호환을 위해 `datetime.UTC`(3.11+ 전용)를 `timezone.utc`로 바꾼 것 외에는
원본 로직 그대로."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Clock = Callable[[], datetime]
TemporalGranularity = Literal["day", "month", "year"]


class TemporalResolutionError(ValueError):
    """Raised when a relative date expression cannot be resolved safely."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelativeTemporalIntent(_StrictModel):
    """Validated relative-period expression produced by the workflow."""

    kind: Literal["trailing", "offset"]
    count: int = Field(ge=0, le=1000)
    unit: Literal["day", "week", "month", "year"]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def validate_timezone(timezone_name: str) -> ZoneInfo:
    """Resolve an IANA timezone name or raise a stable validation error."""

    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA timezone: {timezone_name}") from exc


def build_request_context(now: datetime, timezone_name: str) -> dict[str, str]:
    """Build UTC and local timestamps supplied to the search workflow."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    local_timezone = validate_timezone(timezone_name)
    local_now = now.astimezone(local_timezone)
    requested_at_utc = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    return {
        "requested_at_utc": requested_at_utc.replace("+00:00", "Z"),
        "current_datetime": local_now.isoformat(timespec="seconds"),
        "current_date": local_now.date().isoformat(),
        "timezone": timezone_name,
    }


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _shift_years(value: date, years: int) -> date:
    target_year = value.year + years
    day = min(value.day, calendar.monthrange(target_year, value.month)[1])
    return value.replace(year=target_year, day=day)


def _shift(value: date, count: int, unit: str) -> date:
    if unit == "day":
        return value + timedelta(days=count)
    if unit == "week":
        return value + timedelta(weeks=count)
    if unit == "month":
        return _shift_months(value, count)
    if unit == "year":
        return _shift_years(value, count)
    raise TemporalResolutionError(f"unsupported relative period unit: {unit}")


def _format(value: date, granularity: TemporalGranularity) -> str:
    if granularity == "year":
        return f"{value.year:04d}"
    if granularity == "month":
        return f"{value.year:04d}-{value.month:02d}"
    return value.isoformat()


def is_relative_temporal_intent(value: Any) -> bool:
    """Return whether a value has a supported relative-period shape."""

    return isinstance(value, dict) and value.get("kind") in {"trailing", "offset"}


def resolve_relative_temporal(
    value: Any,
    *,
    filter_type: Literal["date", "date_range"],
    current_date: date,
    granularity: TemporalGranularity,
) -> str | dict[str, str]:
    """Resolve a validated relative period against the supplied current date."""

    try:
        intent = RelativeTemporalIntent.model_validate(value)
    except ValidationError as exc:
        raise TemporalResolutionError(f"invalid relative temporal intent: {value!r}") from exc

    if intent.kind == "trailing":
        if filter_type != "date_range":
            raise TemporalResolutionError("trailing periods require a date_range filter")
        if intent.count == 0:
            raise TemporalResolutionError("trailing period count must be greater than zero")
        start = _shift(current_date, -intent.count, intent.unit)
        return {
            "start": _format(start, granularity),
            "end": _format(current_date, granularity),
        }

    if filter_type != "date":
        raise TemporalResolutionError("offset dates require a date filter")
    shifted = _shift(current_date, -intent.count, intent.unit)
    return _format(shifted, granularity)
