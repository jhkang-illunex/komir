# -*- coding: utf-8 -*-
"""광물자원가격·국내/글로벌 수급지도 3종의 결정론적(비-LLM) 요약 계산 — komir 자체
추가(2026-08-19, 이식 아님).

`additional_summary.py`(외부repo 무수정 이식본)와 나란히 쓰는 파일이다 — 그 파일은
"원본에서 바뀐 것은 import 경로 1줄뿐"이라고 명시하고 있어, 원본에 없는 이 3종의
계산 로직을 거기에 섞지 않았다. 계산 스타일(`EvidenceClaim`으로 근거를 절에
배정, `AdditionalCalculatedSummary`로 반환)은 그 파일의 `calculate_mineral_map_
summary` 등을 따른다 — 재사용 가능한 헬퍼(`EvidenceClaim`·`SummaryPageContext`·
`AdditionalCalculatedSummary`·`_number`·`_quantity`)는 새로 만들지 않고 그 파일에서
가져다 쓴다.
"""
from __future__ import annotations

from datetime import date as _date, timedelta as _timedelta

from .additional_summary import (
    AdditionalCalculatedSummary,
    EvidenceClaim,
    SummaryPageContext,
    _number,
    _quantity,
)
from .models import DetectedPattern, Metric, PriceSeries, TradeMapSeries

KOMIR_PAGE_CONTEXTS = {
    "price": SummaryPageContext(
        page_id="price",
        name="광물자원가격",
        definition="선택한 광종의 일별 실거래가·최저가·최고가 추이를 보여주는 자료다.",
        analysis_constraints=[
            "제공된 가격 계열과 선택 기간만 사용한다.",
            "외부 사건을 가격 변화의 원인으로 추정하지 않는다.",
            "가격 단위·기준이 없으면 절대 수준을 해석하지 않는다.",
        ],
        policy_version="price-summary-v1",
    ),
    "map_korea": SummaryPageContext(
        page_id="map_korea",
        name="국내 수급지도",
        definition="선택한 광종을 한국이 어느 나라로부터 수입하는지 국가별 금액·중량으로 보여주는 자료다.",
        analysis_constraints=[
            "관세청 원천에 있는 상대국·기간만 분석한다.",
            "수입 집중도(상위국 비중)를 공급망 리스크로 단정하지 않고 사실만 서술한다.",
        ],
        policy_version="map-korea-summary-v1",
    ),
    "map_global": SummaryPageContext(
        page_id="map_global",
        name="글로벌 수급지도",
        definition=(
            "선택한 광종의 전세계 양자무역 기록에서 수입(I) 방향 거래만 모아 "
            "상대국(공급국)별 규모로 보여주는 자료다."
        ),
        analysis_constraints=[
            "한국 기준이 아니라 전세계 보고국 기준 데이터다 — 이 점을 서술에서 흐리지 않는다.",
            "UN Comtrade 원천에 있는 공급국·기간만 분석한다.",
        ],
        policy_version="map-global-summary-v1",
    ),
}


def calculate_price_summary(series: PriceSeries) -> AdditionalCalculatedSummary:
    """Calculate deterministic evidence and metrics for a price series."""

    observations = sorted(series.observations, key=lambda item: item.date)
    latest = observations[-1]
    if latest.commerce_price is None:
        raise ValueError("price summary requires the latest observation to have commerce_price")

    def _avg_before(days: int) -> float | None:
        cutoff = _shift_date(latest.date, -days)
        window = [
            item.commerce_price
            for item in observations[:-1]
            if item.commerce_price is not None and item.date >= cutoff
        ]
        return sum(window) / len(window) if window else None

    claims = [
        EvidenceClaim(
            "latest_price",
            "core_diagnosis",
            f"{latest.date} 기준 {series.mineral.name} 실거래가는 {_number(latest.commerce_price)}이다.",
            required=True,
        )
    ]
    key_metrics = [_price_metric("latest_price", "최신 가격", latest.commerce_price)]

    if len(observations) >= 2 and observations[-2].commerce_price is not None:
        prior = observations[-2].commerce_price
        change = _pct(latest.commerce_price, prior)
        if change is not None:
            claims.append(
                EvidenceClaim(
                    "day_over_day",
                    "major_changes",
                    f"전일({observations[-2].date}) 대비 {_signed_pct(change)} 변동했다.",
                    required=True,
                )
            )
            key_metrics.append(_price_metric("day_over_day_change_pct", "전일대비", change * 100, unit="%"))

    for days, label, metric_id in ((7, "전주평균", "week_avg"), (30, "전월평균", "month_avg"), (365, "전년평균", "year_avg")):
        avg = _avg_before(days)
        if avg is None:
            continue
        change = _pct(latest.commerce_price, avg)
        if change is None:
            continue
        claims.append(
            EvidenceClaim(
                metric_id,
                "major_changes",
                f"{label}({_number(avg)}) 대비 {_signed_pct(change)} 수준이다.",
            )
        )
        key_metrics.append(_price_metric(f"{metric_id}_change_pct", f"{label}대비", change * 100, unit="%"))

    if not any(claim.section == "major_changes" for claim in claims):
        # `SummaryNarrative`는 3개 절 전부 최소 1개 근거를 요구한다(models.py) —
        # 비교 가능한 이전 관측이 없는 경우(관측 1건뿐 등)를 대비한 폴백.
        claims.append(
            EvidenceClaim(
                "no_comparable_period",
                "major_changes",
                "비교 가능한 이전 가격이 없어 등락률은 계산하지 않았다.",
            )
        )

    highs = [item.highest_price for item in observations if item.highest_price is not None]
    lows = [item.lowest_price for item in observations if item.lowest_price is not None]
    patterns: list[DetectedPattern] = []
    if highs and lows:
        period_high, period_low = max(highs), min(lows)
        claims.append(
            EvidenceClaim(
                "period_range",
                "current_position",
                f"조회기간 중 최고 {_number(period_high)}, 최저 {_number(period_low)}였다.",
            )
        )
        if period_high > period_low and latest.commerce_price is not None:
            position = (latest.commerce_price - period_low) / (period_high - period_low)
            if position >= 0.9:
                patterns.append(
                    DetectedPattern(
                        code="near_period_high",
                        label="조회기간 고점 근접",
                        evidence=["period_range", "latest_price"],
                    )
                )
            elif position <= 0.1:
                patterns.append(
                    DetectedPattern(
                        code="near_period_low",
                        label="조회기간 저점 근접",
                        evidence=["period_range", "latest_price"],
                    )
                )
    else:
        claims.append(
            EvidenceClaim(
                "no_price_range",
                "current_position",
                "최고가·최저가 정보가 없어 조회기간 범위는 계산하지 않았다.",
            )
        )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=key_metrics,
        patterns=patterns,
        omitted=[],
        warnings=[],
    )


def calculate_domestic_trade_summary(series: TradeMapSeries) -> AdditionalCalculatedSummary:
    return _calculate_trade_map_summary(series, direction_label="수입")


def calculate_global_trade_summary(series: TradeMapSeries) -> AdditionalCalculatedSummary:
    return _calculate_trade_map_summary(series, direction_label="공급")


def _calculate_trade_map_summary(series: TradeMapSeries, *, direction_label: str) -> AdditionalCalculatedSummary:
    """Calculate deterministic evidence and metrics for a trade-map series.

    `direction_label`은 문구만 바꾼다("수입" 국내 관세청 / "공급" 글로벌 Comtrade) —
    두 원천 다 "국가별 금액 랭킹" 계산 자체는 동일한 모양이라 하나로 묶었다.
    """

    dates = sorted({item.date for item in series.observations})
    latest_date = dates[-1]
    latest_rows = [item for item in series.observations if item.date == latest_date]
    ranking = sorted(latest_rows, key=lambda item: item.import_amount or 0.0, reverse=True)
    total = sum(item.import_amount or 0.0 for item in ranking)
    if total <= 0 or len(ranking) < 1:
        raise ValueError("trade map summary requires a positive total amount")

    claims = [
        EvidenceClaim(
            "current_state",
            "core_diagnosis",
            f"{latest_date} 기준 {series.mineral.name} {direction_label}총액은 {_quantity(total)}(단위 미상)이다.",
            required=True,
        )
    ]
    key_metrics = [_price_metric("total_amount", f"{direction_label}총액", total)]

    top_n = ranking[: min(3, len(ranking))]
    if top_n:
        top1 = top_n[0]
        top1_share = (top1.import_amount or 0.0) / total
        claims.append(
            EvidenceClaim(
                "top1_country",
                "major_changes",
                f"{top1.country_name}이 {_quantity(top1.import_amount or 0.0)}({_number(top1_share * 100)}%)로 "
                f"1위 {direction_label}국이다.",
                required=True,
            )
        )
        key_metrics.append(_price_metric("top1_share_pct", f"1위국 {direction_label}비중", top1_share * 100, unit="%"))
    if len(top_n) >= 3:
        cr3 = sum(item.import_amount or 0.0 for item in top_n) / total
        names = "·".join(item.country_name for item in top_n)
        claims.append(
            EvidenceClaim(
                "top3_concentration",
                "major_changes",
                f"상위 3개국({names})이 전체의 {_number(cr3 * 100)}%를 차지한다.",
                required=True,
            )
        )
        key_metrics.append(_price_metric("top3_share_pct", f"상위3국 {direction_label}비중", cr3 * 100, unit="%"))

    patterns: list[DetectedPattern] = []
    if top_n and (top_n[0].import_amount or 0.0) / total >= 0.5:
        patterns.append(
            DetectedPattern(
                code="single_country_concentration",
                label=f"1개국 {direction_label} 과반 집중",
                evidence=["top1_country"],
            )
        )

    if len(dates) >= 2:
        previous_date = dates[-2]
        previous_total = sum(
            item.import_amount or 0.0 for item in series.observations if item.date == previous_date
        )
        change = _pct(total, previous_total)
        if change is not None:
            claims.append(
                EvidenceClaim(
                    "period_total_change",
                    "current_position",
                    f"직전 관측일({previous_date}) 대비 {direction_label}총액이 {_signed_pct(change)} 변동했다.",
                )
            )
            key_metrics.append(
                _price_metric("period_total_change_pct", f"직전 대비 {direction_label}총액 변동", change * 100, unit="%")
            )
    else:
        claims.append(
            EvidenceClaim(
                "single_snapshot",
                "current_position",
                "조회기간에 관측일이 1건뿐이라 기간별 변화는 계산하지 않았다.",
            )
        )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=key_metrics,
        patterns=patterns,
        omitted=[],
        warnings=[],
    )


def _price_metric(metric_id: str, label: str, value: float | None, *, unit: str | None = None) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        status="available" if value is not None else "insufficient_data",
        value=round(value, 6) if isinstance(value, float) else value,
        unit=unit,
    )


def _pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def _signed_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{_number(value * 100)}%"


def _shift_date(date_text: str, days: int) -> str:
    year, month, day = (int(part) for part in date_text.split("-"))
    return (_date(year, month, day) + _timedelta(days=days)).isoformat()
