# -*- coding: utf-8 -*-
"""Small numerical helpers shared by analysis summary calculations.

외부 저장소 `komis_report_generator/analysis/indicators.py`를 **무수정 이식**
(2026-08-11). 순수 함수뿐이라 komir 규약과 충돌하는 지점이 없다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def percent_change(current: float | None, previous: float | None) -> float | None:
    """Return the fractional change, or ``None`` when it cannot be calculated."""

    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def direction(value: float, *, tolerance: float = 1e-12) -> int:
    """Classify a value as positive, negative, or flat within a tolerance."""

    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def pearson_correlation(
    first_values: Sequence[float],
    second_values: Sequence[float],
) -> float | None:
    """Calculate Pearson correlation when at least three varying pairs exist."""

    if len(first_values) != len(second_values):
        raise ValueError("correlation inputs must have equal lengths")
    if len(first_values) < 3:
        return None
    first_mean = sum(first_values) / len(first_values)
    second_mean = sum(second_values) / len(second_values)
    numerator = sum(
        (first - first_mean) * (second - second_mean)
        for first, second in zip(first_values, second_values, strict=True)
    )
    first_sum = sum((value - first_mean) ** 2 for value in first_values)
    second_sum = sum((value - second_mean) ** 2 for value in second_values)
    denominator = math.sqrt(first_sum * second_sum)
    return None if denominator == 0 else numerator / denominator


def month_ordinal(month: str) -> int:
    """Convert a ``YYYY-MM`` month to a monotonically increasing integer."""

    year, month_number = (int(part) for part in month.split("-", 1))
    return year * 12 + month_number - 1


def months_are_contiguous(previous: str, current: str) -> bool:
    """Return whether ``current`` immediately follows ``previous``."""

    return month_ordinal(current) - month_ordinal(previous) == 1
