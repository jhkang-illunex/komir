# -*- coding: utf-8 -*-
"""광물종합지수·광물지도·가격예측 3종의 결정론적(비-LLM) 요약 계산 — 외부 저장소
`komis_report_generator/analysis/additional_summary.py` **무수정 이식**(2026-08-13).

**원본에서 바뀐 것은 import 경로 1줄뿐**이다(`komis_report_generator.analysis.models`
→ `.models`). 계산 로직·문구·evidence 규약은 원본 그대로다 — 외부repo가 계속
개발 중이라(2026-08-12 커밋 `b6c17ca`가 가격예측을 추가) 포크를 만들지 않는다.

이 파일이 `summary.py`에 제공하는 것:
- `ADDITIONAL_PAGE_CONTEXTS` — YAML 정책이 없는 3종 페이지의 정의·제약·정책버전
  (등급 밴드가 없는 페이지라 `policy.py`의 PagePolicy 대신 SummaryPageContext를 쓴다)
- `calculate_composite_summary`/`calculate_mineral_map_summary`/
  `calculate_price_forecast_summary` — 근거(EvidenceClaim)·지표·패턴 산출
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from .models import (
    CompositeIndexObservation,
    CompositeIndexSeries,
    DetectedPattern,
    ForecastHorizon,
    Metric,
    MineralMapObservation,
    MineralMapSeries,
    OmittedIndicator,
    PriceForecastSeries,
    SummaryPageId,
)

SectionId = Literal["core_diagnosis", "major_changes", "current_position"]


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """One evidence-backed fact assigned to a summary section."""

    id: str
    section: SectionId
    fact: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class SummaryPageContext:
    """Page definition and constraints supplied to narrative generation."""

    page_id: SummaryPageId
    name: str
    definition: str
    analysis_constraints: list[str]
    policy_version: str


@dataclass(slots=True)
class AdditionalCalculatedSummary:
    """Deterministic evidence, metrics, patterns, omissions, and warnings."""

    claims: list[EvidenceClaim]
    key_metrics: list[Metric]
    detailed_metrics: list[Metric]
    patterns: list[DetectedPattern]
    omitted: list[OmittedIndicator]
    warnings: list[str]


ADDITIONAL_PAGE_CONTEXTS = {
    "indicator_composite": SummaryPageContext(
        page_id="indicator_composite",
        name="광물종합지수",
        definition=(
            "광물종합지수와 메이저금속·희소금속 하위지수의 현재 수준과 "
            "조회기간 변화를 함께 보여주는 일간 지수다."
        ),
        analysis_constraints=[
            "현재 페이지의 세 지수와 선택 기간만 사용한다.",
            "개별 광물이나 외부 사건을 지수 변화의 원인으로 추정하지 않는다.",
            "전주·전월·전년 비교에는 해당 기준일 이전의 가장 가까운 관측값을 사용한다.",
        ],
        policy_version="indicator-composite-summary-v1",
    ),
    "map_mineral": SummaryPageContext(
        page_id="map_mineral",
        name="광물지도",
        definition=(
            "선택한 광종의 국가별 매장량 또는 생산량과 세계 전체 규모를 "
            "연도별로 보여주는 자료다."
        ),
        analysis_constraints=[
            "사용자가 선택한 매장량 또는 생산량 한 항목만 분석한다.",
            "기타로 집계된 값을 개별 국가로 나누어 추정하지 않는다.",
            "외부 사건을 국가별 수치 변화의 원인으로 추정하지 않는다.",
        ],
        policy_version="mineral-map-summary-v1",
    ),
    "forecast_price": SummaryPageContext(
        page_id="forecast_price",
        name="가격예측",
        definition=(
            "선택한 광종의 중기 3년 분기예측 또는 장기 10년 연간예측 가격 경로다."
        ),
        analysis_constraints=[
            "예측가격을 확정가격처럼 표현하지 않는다.",
            "과거 예측본과 실제 결과가 없으면 예측 정확도나 발생확률을 추정하지 않는다.",
            "제공되지 않은 시장 사건을 가격 변화의 원인으로 추정하지 않는다.",
        ],
        policy_version="price-forecast-summary-v1",
    ),
}


def _number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _quantity(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _metric(
    metric_id: str,
    label: str,
    value: float | int | str,
    *,
    unit: str | None = None,
    basis: str | None = None,
) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        status="available",
        value=round(value, 6) if isinstance(value, float) else value,
        unit=unit,
        basis=basis,
    )


def _percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous


def _forecast_period_text(period: str) -> str:
    if "-Q" in period:
        year, quarter = period.split("-Q", maxsplit=1)
        return f"{year}년 {quarter}분기"
    return f"{period}년"


def _forecast_horizon_name(horizon: ForecastHorizon) -> str:
    return "중기" if horizon == "medium" else "장기"


def _forecast_price_text(value: float, unit: str | None) -> str:
    suffix = f" {unit}" if unit else ""
    return f"{_number(value)}{suffix}"


def _forecast_end_position_fact(
    *,
    last_price: float,
    low_price: float,
    high_price: float,
) -> str:
    if low_price == high_price:
        return "마지막 예측가격은 예측기간의 모든 가격과 같은 수준이다."

    above_low = _percent_change(last_price, low_price) or 0.0
    below_high = _percent_change(last_price, high_price) or 0.0
    if last_price == high_price:
        return (
            "마지막 예측가격은 예측기간 최고가격과 같고, 최저가격보다 "
            f"{_number(above_low * 100)}% 높아 전망 종단부가 예측 범위의 "
            "높은 쪽에 놓인다."
        )
    if last_price == low_price:
        return (
            "마지막 예측가격은 예측기간 최저가격과 같고, 최고가격보다 "
            f"{_number(abs(below_high) * 100)}% 낮아 전망 종단부가 예측 범위의 "
            "낮은 쪽에 놓인다."
        )
    return (
        f"마지막 예측가격은 최저가격보다 {_number(above_low * 100)}% 높고 "
        f"최고가격보다 {_number(abs(below_high) * 100)}% 낮은 수준이다."
    )


def calculate_price_forecast_summary(
    series: PriceForecastSeries,
) -> AdditionalCalculatedSummary:
    """Calculate evidence-backed direction, extrema, and turning points."""
    observations = sorted(series.observations, key=lambda item: item.period)
    if len(observations) < 2:
        raise ValueError("price forecast summary requires at least two periods")
    first = observations[0]
    last = observations[-1]
    low = min(observations, key=lambda item: item.price)
    high = max(observations, key=lambda item: item.price)
    overall_change = _percent_change(last.price, first.price)
    assert overall_change is not None
    direction = (
        "높아질"
        if overall_change > 0
        else "낮아질"
        if overall_change < 0
        else "같은 수준을 유지할"
    )
    horizon_name = _forecast_horizon_name(series.horizon)
    first_period = _forecast_period_text(first.period)
    last_period = _forecast_period_text(last.period)

    changes = [
        current.price - previous.price
        for previous, current in zip(observations[:-1], observations[1:], strict=True)
    ]
    nonzero_directions = [
        (index, 1 if change > 0 else -1)
        for index, change in enumerate(changes)
        if change
    ]
    turning_periods = [
        observations[index].period
        for (previous_index, previous_direction), (index, direction_value) in zip(
            nonzero_directions[:-1], nonzero_directions[1:], strict=True
        )
        if previous_direction != direction_value and index > previous_index
    ]
    if not nonzero_directions:
        path_fact = "예측기간의 모든 가격이 같아 방향 변화가 없는 경로다."
        path_code = "flat"
    elif not turning_periods:
        path_word = "높아지는" if nonzero_directions[0][1] > 0 else "낮아지는"
        path_fact = f"예측기간에는 가격이 일관되게 {path_word} 경로가 제시됐다."
        path_code = "one_direction"
    elif len(turning_periods) == 1:
        period_text = _forecast_period_text(turning_periods[0])
        first_direction = nonzero_directions[0][1]
        path_word = "낮아진 뒤 높아지는" if first_direction < 0 else "높아진 뒤 낮아지는"
        path_fact = f"예측가격은 {period_text}을 전후로 방향이 바뀌어 {path_word} 경로다."
        path_code = "single_turn"
    else:
        first_turn = _forecast_period_text(turning_periods[0])
        last_turn = _forecast_period_text(turning_periods[-1])
        path_fact = (
            f"예측가격의 방향은 {first_turn}부터 {last_turn} 사이에 "
            f"{len(turning_periods)}차례 바뀌어 등락이 반복되는 경로다."
        )
        path_code = "multiple_turns"

    claims = [
        EvidenceClaim(
            "current_state",
            "core_diagnosis",
            f"{series.mineral.name} {horizon_name} 예측가격은 {first_period} "
            f"{_forecast_price_text(first.price, series.price_unit)}에서 {last_period} "
            f"{_forecast_price_text(last.price, series.price_unit)}로 "
            f"{_number(abs(overall_change) * 100)}% {direction} 것으로 예측된다.",
            required=True,
        ),
        EvidenceClaim("forecast_path", "core_diagnosis", path_fact, required=True),
        EvidenceClaim(
            "forecast_start",
            "major_changes",
            f"첫 예측시점인 {first_period} 가격은 "
            f"{_forecast_price_text(first.price, series.price_unit)}로 제시됐다.",
        ),
        EvidenceClaim(
            "forecast_low",
            "major_changes",
            f"예측기간 최저가격은 {_forecast_period_text(low.period)}의 "
            f"{_forecast_price_text(low.price, series.price_unit)}다.",
        ),
        EvidenceClaim(
            "forecast_high",
            "major_changes",
            f"예측기간 최고가격은 {_forecast_period_text(high.period)}의 "
            f"{_forecast_price_text(high.price, series.price_unit)}다.",
        ),
        EvidenceClaim(
            "forecast_end_position",
            "current_position",
            _forecast_end_position_fact(
                last_price=last.price,
                low_price=low.price,
                high_price=high.price,
            ),
            required=True,
        ),
    ]
    key_metrics = [
        _metric(
            "forecast_start_price",
            "첫 예측가격",
            first.price,
            unit=series.price_unit,
            basis=first.period,
        ),
        _metric(
            "forecast_end_price",
            "마지막 예측가격",
            last.price,
            unit=series.price_unit,
            basis=last.period,
        ),
        _metric("forecast_overall_change", "전망기간 변화율", overall_change * 100, unit="%"),
        _metric(
            "forecast_low_price",
            "최저 예측가격",
            low.price,
            unit=series.price_unit,
            basis=low.period,
        ),
        _metric(
            "forecast_high_price",
            "최고 예측가격",
            high.price,
            unit=series.price_unit,
            basis=high.period,
        ),
    ]
    detailed_metrics = [
        *key_metrics,
        _metric("forecast_turning_points", "방향 전환 횟수", len(turning_periods), unit="회"),
        _metric("forecast_observation_count", "예측 관측치", len(observations), unit="개"),
    ]
    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics,
        detailed_metrics=detailed_metrics,
        patterns=[
            DetectedPattern(
                code=path_code,
                label=path_fact,
                evidence=turning_periods,
            )
        ],
        omitted=[],
        warnings=[],
    )


def _change_verb(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}% 올랐다"
    if change < 0:
        return f"{_number(abs(change) * 100)}% 내렸다"
    return "변동이 없었다"


def _change_with_contrast(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}% 올랐지만"
    if change < 0:
        return f"{_number(abs(change) * 100)}% 내렸지만"
    return "변동이 없었지만"


def _change_before_contrast(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}% 오른"
    if change < 0:
        return f"{_number(abs(change) * 100)}% 내린"
    return "변동이 없는"


def _relative_level(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}% 높은 수준이다"
    if change < 0:
        return f"{_number(abs(change) * 100)}% 낮은 수준이다"
    return "같은 수준이다"


def _change_with_and(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}% 증가했고"
    if change < 0:
        return f"{_number(abs(change) * 100)}% 감소했고"
    return "변동이 없었고"


def _change_with_result(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}% 증가해"
    if change < 0:
        return f"{_number(abs(change) * 100)}% 감소해"
    return "변동이 없어"


def _korean_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.year}년 {parsed.month}월 {parsed.day}일"


def _topic(name: str) -> str:
    final = name[-1]
    codepoint = ord(final)
    has_batchim = 0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 != 0
    return f"{name}{'은' if has_batchim else '는'}"


def _shift_month(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    month_days = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(value.day, month_days))


def _shift_year(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _at_or_before(
    observations: list[CompositeIndexObservation],
    target: date,
) -> CompositeIndexObservation | None:
    eligible = [item for item in observations if date.fromisoformat(item.date) <= target]
    return eligible[-1] if eligible else None


def calculate_composite_summary(
    series: CompositeIndexSeries,
) -> AdditionalCalculatedSummary:
    """Calculate deterministic evidence and metrics for a composite-index series."""

    observations = sorted(series.observations, key=lambda item: item.date)
    current = observations[-1]
    current_date = date.fromisoformat(current.date)
    week = _at_or_before(observations[:-1], current_date - timedelta(days=7))
    month = _at_or_before(observations[:-1], _shift_month(current_date, -1))
    year = _at_or_before(observations[:-1], _shift_year(current_date, -1))
    omitted: list[OmittedIndicator] = []
    warnings: list[str] = []

    claims = [
        EvidenceClaim(
            "current_state",
            "core_diagnosis",
            f"{_korean_date(current.date)} 광물종합지수는 "
            f"{_number(current.composite_index)}포인트다.",
        )
    ]
    key_metrics = [
        _metric(
            "current_composite_index",
            "현재 광물종합지수",
            current.composite_index,
            unit="포인트",
            basis=current.date,
        ),
        _metric(
            "current_major_metals_index",
            "현재 메이저금속지수",
            current.major_metals_index,
            unit="포인트",
            basis=current.date,
        ),
        _metric(
            "current_minor_metals_index",
            "현재 희소금속지수",
            current.minor_metals_index,
            unit="포인트",
            basis=current.date,
        ),
    ]
    detailed_metrics = [*key_metrics]

    week_change = (
        _percent_change(current.composite_index, week.composite_index) if week else None
    )
    month_change = (
        _percent_change(current.composite_index, month.composite_index) if month else None
    )
    year_change = (
        _percent_change(current.composite_index, year.composite_index) if year else None
    )
    if month_change is not None and year_change is not None:
        month_direction = "상승" if month_change > 0 else "하락" if month_change < 0 else "보합"
        claims.append(
            EvidenceClaim(
                "medium_long_term_contrast",
                "core_diagnosis",
                f"최근 한 달에는 {month_direction}했지만 1년 전보다 "
                f"{_relative_level(year_change)}.",
            )
        )
    else:
        warning = "조회기간에 한 달 또는 1년 비교값이 없어 중장기 비교를 제외했다."
        omitted.append(
            OmittedIndicator(
                id="medium_long_term_contrast",
                reason=warning,
            )
        )
        warnings.append(warning)

    if week_change is not None and month_change is not None:
        claims.append(
            EvidenceClaim(
                "composite_recent_changes",
                "major_changes",
                f"광물종합지수는 전주보다 {_change_with_contrast(week_change)} "
                f"한 달 전보다 {_change_verb(month_change)}.",
            )
        )
    elif month_change is not None:
        claims.append(
            EvidenceClaim(
                "composite_recent_changes",
                "major_changes",
                f"광물종합지수는 한 달 전보다 {_change_verb(month_change)}.",
            )
        )

    comparison_metrics = (
        ("weekly_composite_change", "전주 대비", week_change, week),
        ("monthly_composite_change", "전월 대비", month_change, month),
        ("yearly_composite_change", "전년 대비", year_change, year),
    )
    for metric_id, label, change, compared in comparison_metrics:
        if change is None or compared is None:
            continue
        metric = _metric(
            metric_id,
            label,
            change,
            unit="ratio",
            basis=f"{compared.date} 대비 {current.date}",
        )
        key_metrics.append(metric)
        detailed_metrics.append(metric)

    weekly_major = (
        _percent_change(current.major_metals_index, week.major_metals_index)
        if week
        else None
    )
    weekly_minor = (
        _percent_change(current.minor_metals_index, week.minor_metals_index)
        if week
        else None
    )
    if weekly_major is not None and weekly_minor is not None:
        claims.append(
            EvidenceClaim(
                "weekly_subindex_comparison",
                "major_changes",
                "최근 한 주 동안 메이저금속지수는 "
                f"{_change_before_contrast(weekly_major)} 반면 희소금속지수는 "
                f"{_change_verb(weekly_minor)}.",
            )
        )
        detailed_metrics.extend(
            [
                _metric(
                    "weekly_major_metals_change",
                    "메이저금속 전주 대비",
                    weekly_major,
                    unit="ratio",
                    basis=f"{week.date} 대비 {current.date}",
                ),
                _metric(
                    "weekly_minor_metals_change",
                    "희소금속 전주 대비",
                    weekly_minor,
                    unit="ratio",
                    basis=f"{week.date} 대비 {current.date}",
                ),
            ]
        )

    # 2026-08-27: PDF 지침 점검(/unlazy)에서 발견한 gap 수정 — PDF는 메이저·
    # 희소 두 하위지수 각각에 전주·전월·전년 3종 비교를 요구하는데, 이전에는
    # 전주·전년만 있고 전월 비교가 없었다(주간·연간 블록과 같은 패턴으로 추가).
    monthly_major = (
        _percent_change(current.major_metals_index, month.major_metals_index)
        if month
        else None
    )
    monthly_minor = (
        _percent_change(current.minor_metals_index, month.minor_metals_index)
        if month
        else None
    )
    if monthly_major is not None and monthly_minor is not None:
        claims.append(
            EvidenceClaim(
                "monthly_subindex_comparison",
                "major_changes",
                "최근 한 달 동안 메이저금속지수는 "
                f"{_change_before_contrast(monthly_major)} 반면 희소금속지수는 "
                f"{_change_verb(monthly_minor)}.",
            )
        )
        detailed_metrics.extend(
            [
                _metric(
                    "monthly_major_metals_change",
                    "메이저금속 전월 대비",
                    monthly_major,
                    unit="ratio",
                    basis=f"{month.date} 대비 {current.date}",
                ),
                _metric(
                    "monthly_minor_metals_change",
                    "희소금속 전월 대비",
                    monthly_minor,
                    unit="ratio",
                    basis=f"{month.date} 대비 {current.date}",
                ),
            ]
        )

    yearly_major = (
        _percent_change(current.major_metals_index, year.major_metals_index)
        if year
        else None
    )
    yearly_minor = (
        _percent_change(current.minor_metals_index, year.minor_metals_index)
        if year
        else None
    )
    patterns: list[DetectedPattern] = []
    if yearly_major is not None and yearly_minor is not None:
        difference = yearly_minor - yearly_major
        leader = "희소금속" if difference > 0 else "메이저금속"
        claims.append(
            EvidenceClaim(
                "yearly_subindex_comparison",
                "major_changes",
                f"1년 변화율은 메이저금속지수 {_number(yearly_major * 100)}%, "
                f"희소금속지수 {_number(yearly_minor * 100)}%로, {leader}의 "
                f"변화율이 {_number(abs(difference) * 100)}%포인트 더 높았다.",
            )
        )
        detailed_metrics.extend(
            [
                _metric(
                    "yearly_major_metals_change",
                    "메이저금속 전년 대비",
                    yearly_major,
                    unit="ratio",
                    basis=f"{year.date} 대비 {current.date}",
                ),
                _metric(
                    "yearly_minor_metals_change",
                    "희소금속 전년 대비",
                    yearly_minor,
                    unit="ratio",
                    basis=f"{year.date} 대비 {current.date}",
                ),
                _metric(
                    "yearly_subindex_gap",
                    "하위지수 1년 변화율 차이",
                    difference,
                    unit="ratio",
                    basis="희소금속 - 메이저금속",
                ),
            ]
        )
        patterns.append(
            DetectedPattern(
                code="long_term_subindex_leader",
                label=f"{leader} 장기 변화율 우위",
                evidence=[f"1년 변화율 차이 {_number(abs(difference) * 100)}%포인트"],
            )
        )

    highest = max(observations, key=lambda item: item.composite_index)
    lowest = min(observations, key=lambda item: item.composite_index)
    below_high = _percent_change(current.composite_index, highest.composite_index) or 0.0
    above_low = _percent_change(current.composite_index, lowest.composite_index) or 0.0
    claims.append(
        EvidenceClaim(
            "period_range_position",
            "current_position",
            f"현재 광물종합지수는 조회기간 최고치인 "
            f"{_number(highest.composite_index)}포인트보다 "
            f"{_number(abs(below_high) * 100)}% 낮고, 최저치인 "
            f"{_number(lowest.composite_index)}포인트보다 "
            f"{_number(abs(above_low) * 100)}% 높다.",
        )
    )
    detailed_metrics.extend(
        [
            _metric(
                "period_high_index",
                "조회기간 최고지수",
                highest.composite_index,
                unit="포인트",
                basis=highest.date,
            ),
            _metric(
                "period_low_index",
                "조회기간 최저지수",
                lowest.composite_index,
                unit="포인트",
                basis=lowest.date,
            ),
        ]
    )
    if month_change is not None and year_change is not None:
        month_word = "상승" if month_change > 0 else "하락" if month_change < 0 else "보합"
        year_word = "높다" if year_change > 0 else "낮다" if year_change < 0 else "같다"
        if month_change * year_change > 0:
            direction_fact = (
                f"최근 한 달과 1년 비교가 모두 {month_word} 방향이며, "
                f"현재 지수는 1년 전보다 {_number(abs(year_change) * 100)}% {year_word}."
            )
        else:
            direction_fact = (
                f"최근 한 달에는 {month_word}했지만 현재 지수는 1년 전보다 "
                f"{_number(abs(year_change) * 100)}% {year_word}."
            )
        if yearly_major is not None and yearly_minor is not None:
            if yearly_major * yearly_minor < 0:
                direction_fact += " 두 하위지수의 1년 변화 방향은 서로 달랐다."
            else:
                direction_fact += " 두 하위지수의 1년 변화 폭에도 차이가 있었다."
        claims.append(
            EvidenceClaim(
                "overall_pattern",
                "current_position",
                direction_fact,
            )
        )

    if not any(claim.section == "major_changes" for claim in claims):
        # 2026-08-27 skeptic 감사 Pass 3 NEW-2: 전주·전월 비교 관측이 하나도 없으면
        # (관측 1건, 하루치, 같은 날짜 2행 등) major_changes 근거가 0건이라
        # `SummaryNarrative`(min_length=1) 조립에서 ValidationError → INTERNAL_ERROR가
        # 났다. 데이터 조건이므로 ValueError → `_calculate_or_no_data`가 NO_DATA로.
        raise ValueError(
            "composite index summary requires observations spanning at least one week for a change comparison"
        )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=detailed_metrics,
        patterns=patterns,
        omitted=omitted,
        warnings=warnings,
    )


def _measure_name(series: MineralMapSeries) -> str:
    return "매장량" if series.measure == "reserves" else "생산량"


def _by_year(
    observations: list[MineralMapObservation],
) -> dict[int, list[MineralMapObservation]]:
    grouped: dict[int, list[MineralMapObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.year, []).append(observation)
    return grouped


def _world_total(observations: list[MineralMapObservation]) -> float:
    official = [item.value for item in observations if item.is_total]
    if official:
        return official[0]
    return sum(item.value for item in observations if not item.is_total)


def _country_ranking(
    observations: list[MineralMapObservation],
) -> list[MineralMapObservation]:
    return sorted(
        (
            item
            for item in observations
            if not item.is_total and not item.is_other and item.value > 0
        ),
        key=lambda item: (-item.value, item.country_name),
    )


def _point_change_phrase(change: float) -> str:
    if change > 0:
        return f"{_number(abs(change) * 100)}%포인트 높아졌다"
    if change < 0:
        return f"{_number(abs(change) * 100)}%포인트 낮아졌다"
    return "변동이 없었다"


def _country_change_fact(
    *,
    current: MineralMapObservation,
    previous: MineralMapObservation,
    current_total: float,
    start_total: float,
    current_rank: int,
    start_rank: int,
    measure_name: str,
    unit: str,
    start_year: int,
    current_year: int,
) -> str:
    absolute_change = current.value - previous.value
    rate = _percent_change(current.value, previous.value)
    if absolute_change > 0:
        change_text = f"{_quantity(absolute_change)}{unit}, {_number((rate or 0) * 100)}% 증가했다"
    elif absolute_change < 0:
        change_text = (
            f"{_quantity(abs(absolute_change))}{unit}, "
            f"{_number(abs(rate or 0) * 100)}% 감소했다"
        )
    else:
        change_text = "변동이 없었다"
    start_share = previous.value / start_total
    current_share = current.value / current_total
    share_change = current_share - start_share
    rank_text = (
        f" 순위는 {start_rank}위에서 {current_rank}위로 바뀌었다."
        if start_rank != current_rank
        else f" 순위는 {current_rank}위를 유지했다."
    )
    return (
        f"{_topic(current.country_name)} {start_year}년 {_quantity(previous.value)}{unit}에서 "
        f"{current_year}년 {_quantity(current.value)}{unit}으로 {change_text}. "
        f"{measure_name} 비중은 {_number(start_share * 100)}%에서 "
        f"{_number(current_share * 100)}%로 {_point_change_phrase(share_change)}."
        f"{rank_text}"
    )


def calculate_mineral_map_summary(
    series: MineralMapSeries,
    *,
    secondary_series: MineralMapSeries | None = None,
) -> AdditionalCalculatedSummary:
    """Calculate deterministic evidence and metrics for a mineral-map series.

    `secondary_series`(2026-08-27 신설, PDF 지침 점검(/unlazy)에서 발견한 gap
    수정) — PDF §4는 "매장량 2위 호주는 생산량 8위"처럼 매장량·생산량을
    한 답변에서 교차 비교하는데, 이 함수는 원래 `measure` 하나만 다뤄서
    그 비교를 만들 수 없었다. `secondary_series`는 같은 광종의 반대
    measure(예: `series.measure="reserves"`면 이건 production) 계열이다 —
    있으면 함수 끝부분에서만 교차 비교 근거 1건을 추가하고, 기존 로직(위
    본문)은 그대로 둔다(이 파일은 "무수정 이식" 원칙이라 신규 기능은 기존
    코드를 건드리지 않는 방식으로 덧붙인다)."""

    grouped = _by_year(series.observations)
    years = sorted(grouped)
    if len(years) < 2:
        # 2026-08-27 skeptic 감사 Pass 3 NEW-1: 연도가 1개뿐이면 아래 `years[-2]`가
        # IndexError로 죽어 INTERNAL_ERROR가 났다(정당한 요청 — start_year==end_year
        # 필터가 허용됨). 기간 변화를 계산할 수 없는 데이터 조건이므로 ValueError
        # → `summary.py::_calculate_or_no_data`가 NO_DATA로 바꾼다.
        raise ValueError("mineral map summary requires at least two distinct years")
    start_year = years[0]
    current_year = years[-1]
    start_rows = grouped[start_year]
    current_rows = grouped[current_year]
    start_total = _world_total(start_rows)
    current_total = _world_total(current_rows)
    absolute_change = current_total - start_total
    total_change = _percent_change(current_total, start_total)
    measure_name = _measure_name(series)
    period_years = current_year - start_year

    ranking = _country_ranking(current_rows)
    if len(ranking) < 3 or current_total <= 0:
        raise ValueError("mineral map summary requires a positive total and three countries")
    top1, top2, top3 = ranking[:3]
    top1_share = top1.value / current_total
    top2_share = top2.value / current_total
    top_gap = top1_share - top2_share
    cr3 = sum(item.value for item in ranking[:3]) / current_total
    cr5 = sum(item.value for item in ranking[:5]) / current_total
    outside_top5 = max(1.0 - cr5, 0.0)

    change_word = "늘어" if absolute_change > 0 else "줄어" if absolute_change < 0 else "같아"
    rate_word = (
        "증가했다"
        if (total_change or 0) > 0
        else "감소했다"
        if (total_change or 0) < 0
        else "변동이 없었다"
    )
    claims = [
        EvidenceClaim(
            "current_state",
            "core_diagnosis",
            f"{current_year}년 세계 {series.mineral.name} {measure_name}은 "
            f"{_quantity(current_total)}{series.unit}이다.",
            required=True,
        )
    ]
    if total_change is not None:
        period_fact = (
            f"{start_year}년보다 {_quantity(abs(absolute_change))}{series.unit} "
            f"{change_word} {period_years}년간 {_number(abs(total_change) * 100)}% "
            f"{rate_word}."
        )
        previous_year = years[-2]
        if previous_year != start_year:
            previous_total = _world_total(grouped[previous_year])
            latest_absolute = current_total - previous_total
            latest_change = _percent_change(current_total, previous_total)
            if latest_change is not None:
                # 2026-08-26 KOMIS 실데이터 회귀 테스트(/unlazy)에서 발견·수정:
                # 증감폭이 0일 때 "변동이 없었"에 뒤 템플릿이 "했다"를 또
                # 붙여 "변동이 없었했다"(문법 오류)가 나왔다 — 이 파일은
                # "무수정 이식"이 원칙이지만(모듈 docstring 참고), 사용자가
                # 명시적으로 실보고서 오타 수정을 요청해 예외적으로 고쳤다.
                # 세 갈래 모두 "~다"로 끝나는 완결형으로 통일해 뒤에서
                # "했다"를 다시 붙이지 않는다(바로 위 `rate_word`와 같은 패턴).
                latest_word = (
                    "증가했다"
                    if latest_absolute > 0
                    else "감소했다"
                    if latest_absolute < 0
                    else "변동이 없었다"
                )
                period_fact += (
                    f" 직전 관측연도인 {previous_year}년과 비교하면 "
                    f"{_quantity(abs(latest_absolute))}{series.unit}, "
                    f"{_number(abs(latest_change) * 100)}% {latest_word}."
                )
        claims.append(
            EvidenceClaim(
                "period_total_change",
                "core_diagnosis",
                period_fact,
                required=True,
            )
        )

    claims.extend(
        [
            EvidenceClaim(
                "current_leaders",
                "major_changes",
                # 연도를 근거문에 포함(2026-08-27 반복 루프 2회차: LLM이 PDF 템플릿대로
                # "2025년 기준 …1위"라고 쓰면 이 절 근거에 연도가 없어 숫자 검증에
                # 걸려 폴백된 사례 4건 — 연도는 core의 current_state에만 있었다).
                f"{current_year}년 기준 {_topic(top1.country_name)} {_quantity(top1.value)}{series.unit}으로 "
                f"세계 전체의 {_number(top1_share * 100)}%를 차지해 1위다. "
                f"{_topic(top2.country_name)} {_quantity(top2.value)}{series.unit}, "
                f"{_number(top2_share * 100)}%로 2위이며 두 국가의 비중 차이는 "
                f"{_number(top_gap * 100)}%포인트다.",
                required=True,
            ),
            EvidenceClaim(
                "third_country",
                "major_changes",
                f"{_topic(top3.country_name)} {_quantity(top3.value)}{series.unit}, "
                f"{_number(top3.value / current_total * 100)}%로 3위다.",
            ),
        ]
    )

    start_by_code = {item.country_code: item for item in start_rows}
    start_ranking = _country_ranking(start_rows)
    start_rank_by_code = {
        item.country_code: rank for rank, item in enumerate(start_ranking, start=1)
    }
    current_rank_by_code = {
        item.country_code: rank for rank, item in enumerate(ranking, start=1)
    }
    comparable_leaders = [
        item
        for item in ranking[:3]
        if item.country_code in start_by_code
        and start_by_code[item.country_code].value > 0
    ][:2]
    if comparable_leaders:
        country_facts = [
            _country_change_fact(
                current=item,
                previous=start_by_code[item.country_code],
                current_total=current_total,
                start_total=start_total,
                current_rank=current_rank_by_code[item.country_code],
                start_rank=start_rank_by_code[item.country_code],
                measure_name=measure_name,
                unit=series.unit,
                start_year=start_year,
                current_year=current_year,
            )
            for item in comparable_leaders
        ]
        claims.append(
            EvidenceClaim(
                "leading_country_changes",
                "current_position",
                " ".join(country_facts),
            )
        )

    omitted: list[OmittedIndicator] = []
    warnings: list[str] = []
    missing_leaders = [
        item.country_name
        for item in ranking[:3]
        if item.country_code not in start_by_code
    ]
    if missing_leaders:
        names = ", ".join(missing_leaders)
        warning = (
            f"{current_year}년 상위 3개국 중 {names}의 {start_year}년 비교값이 없어 "
            "해당 국가의 기간 변화율과 순위 변화는 계산하지 않았다."
        )
        warnings.append(warning)
        omitted.append(
            OmittedIndicator(id="missing_leader_history", reason=warning)
        )

    if len(start_ranking) >= 3 and start_total > 0:
        start_cr3 = sum(item.value for item in start_ranking[:3]) / start_total
        start_cr5 = sum(item.value for item in start_ranking[:5]) / start_total
        cr3_change = cr3 - start_cr3
        cr5_change = cr5 - start_cr5
        claims.append(
            EvidenceClaim(
                "concentration_change",
                "current_position",
                f"상위 3개국 비중은 {start_year}년 {_number(start_cr3 * 100)}%에서 "
                f"{current_year}년 {_number(cr3 * 100)}%로 "
                f"{_point_change_phrase(cr3_change)}. 상위 5개국 비중도 "
                f"{_number(start_cr5 * 100)}%에서 {_number(cr5 * 100)}%로 "
                f"{_point_change_phrase(cr5_change)}.",
                required=True,
            )
        )
    else:
        omitted.append(
            OmittedIndicator(
                id="concentration_change",
                reason="시작연도의 비교 가능한 국가가 3개보다 적다.",
            )
        )

    if top1_share >= 0.5:
        structure_fact = (
            f"{_topic(top1.country_name)} 세계 전체의 {_number(top1_share * 100)}%로 "
            f"절반을 넘고 상위 3개국은 {_number(cr3 * 100)}%를 차지해 "
            "상위 국가 중심의 분포다. "
        )
    elif top1_share < 0.25 and outside_top5 >= 0.35:
        structure_fact = (
            f"1위 {top1.country_name}의 비중은 {_number(top1_share * 100)}%이고 "
            f"상위 5개국 밖에도 {_number(outside_top5 * 100)}%가 분포해 "
            "특정 한 국가가 압도하는 구조는 아니다. "
        )
    else:
        structure_fact = (
            f"1위 {top1.country_name}의 비중은 {_number(top1_share * 100)}%, "
            f"상위 3개국은 {_number(cr3 * 100)}%다. "
        )
    structure_fact += (
        f"상위 5개국은 {_number(cr5 * 100)}%, 그 밖의 국가는 "
        f"{_number(outside_top5 * 100)}%를 차지한다."
    )
    claims.append(
        EvidenceClaim(
            "current_concentration_structure",
            "current_position",
            structure_fact,
            required=True,
        )
    )

    key_metrics = [
        _metric(
            "current_world_total",
            f"현재 세계 {measure_name}",
            current_total,
            unit=series.unit,
            basis=str(current_year),
        ),
        _metric(
            "period_world_total_change",
            "조회기간 세계합계 변화율",
            total_change or 0.0,
            unit="ratio",
            basis=f"{start_year} 대비 {current_year}",
        ),
        _metric("top_country", "1위 국가", top1.country_name),
        _metric(
            "top_country_share",
            "1위 국가 비중",
            top1_share,
            unit="ratio",
            basis=str(current_year),
        ),
        _metric("cr3", "상위 3개국 비중", cr3, unit="ratio", basis=str(current_year)),
        _metric("cr5", "상위 5개국 비중", cr5, unit="ratio", basis=str(current_year)),
        _metric(
            "top_two_share_gap",
            "1·2위 비중 차이",
            top_gap,
            unit="ratio",
            basis=str(current_year),
        ),
    ]
    detailed_metrics = [
        *key_metrics,
        _metric(
            "start_world_total",
            f"시작연도 세계 {measure_name}",
            start_total,
            unit=series.unit,
            basis=str(start_year),
        ),
        _metric(
            "outside_top5_share",
            "상위 5개국 외 비중",
            outside_top5,
            unit="ratio",
            basis=str(current_year),
        ),
    ]
    if len(start_ranking) >= 3 and start_total > 0:
        detailed_metrics.extend(
            [
                _metric(
                    "start_cr3",
                    "시작연도 상위 3개국 비중",
                    start_cr3,
                    unit="ratio",
                    basis=str(start_year),
                ),
                _metric(
                    "cr3_change",
                    "상위 3개국 비중 변화",
                    cr3_change,
                    unit="ratio",
                    basis=f"{start_year} 대비 {current_year}",
                ),
                _metric(
                    "cr5_change",
                    "상위 5개국 비중 변화",
                    cr5_change,
                    unit="ratio",
                    basis=f"{start_year} 대비 {current_year}",
                ),
            ]
        )
    patterns = [
        DetectedPattern(
            code="top_country_distribution",
            label="상위 국가 분포",
            evidence=[
                f"1위 {top1.country_name} {_number(top1_share * 100)}%",
                f"상위 3개국 {_number(cr3 * 100)}%",
                f"상위 5개국 {_number(cr5 * 100)}%",
            ],
        )
    ]

    if secondary_series is not None:
        secondary_measure_name = _measure_name(secondary_series)
        secondary_grouped = _by_year(secondary_series.observations)
        secondary_rows = secondary_grouped.get(current_year)
        if not secondary_rows:
            omitted.append(
                OmittedIndicator(
                    id="cross_measure_comparison",
                    reason=f"{secondary_measure_name} 계열에 {current_year}년 데이터가 없다.",
                )
            )
        else:
            secondary_total = _world_total(secondary_rows)
            secondary_ranking = _country_ranking(secondary_rows)
            secondary_rank_by_code = {
                item.country_code: (rank, item) for rank, item in enumerate(secondary_ranking, start=1)
            }
            cross_facts = []
            for rank, item in enumerate(ranking[:3], start=1):
                hit = secondary_rank_by_code.get(item.country_code)
                if hit is None or secondary_total <= 0:
                    continue
                secondary_rank, secondary_item = hit
                secondary_share = secondary_item.value / secondary_total
                primary_share = item.value / current_total
                if secondary_rank >= rank + 3:
                    cross_facts.append(
                        f"{measure_name} {rank}위인 {_topic(item.country_name)} "
                        f"{secondary_measure_name} 기준 {secondary_rank}위"
                        f"({_quantity(secondary_item.value)}{secondary_series.unit}, "
                        f"{_number(secondary_share * 100)}%)에 그치고 있어, "
                        f"{measure_name} 대비 {secondary_measure_name} 비율이 낮은 국가로 분류된다."
                    )
                elif secondary_rank <= rank - 2:
                    cross_facts.append(
                        f"{measure_name} {rank}위({_number(primary_share * 100)}%)인 "
                        f"{_topic(item.country_name)} {secondary_measure_name}은 "
                        f"{secondary_rank}위({_number(secondary_share * 100)}%)로, "
                        f"{measure_name} 대비 {secondary_measure_name} 집중도가 높은 국가다."
                    )
            if cross_facts:
                # major_changes에 붙인다 — current_position은 이미 최대 3개
                # (leading_country_changes·concentration_change·
                # current_concentration_structure)까지 찰 수 있어
                # `SummaryNarrative.current_position`의 max_length=3을 넘긴다
                # (2026-08-27 스모크 테스트에서 실측 확인).
                claims.append(
                    EvidenceClaim(
                        "cross_measure_comparison",
                        "major_changes",
                        " ".join(cross_facts),
                    )
                )
            else:
                omitted.append(
                    OmittedIndicator(
                        id="cross_measure_comparison",
                        reason=(
                            f"{measure_name} 상위 3개국의 {secondary_measure_name} 순위가 "
                            "뚜렷하게 다르지 않다."
                        ),
                    )
                )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics,
        detailed_metrics=detailed_metrics,
        patterns=patterns,
        omitted=omitted,
        warnings=warnings,
    )
