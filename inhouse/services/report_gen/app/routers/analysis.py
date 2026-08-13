# -*- coding: utf-8 -*-
"""분석요약 5종 API — 외부 저장소 `komis_report_generator/api/routers/analysis.py`
+ `api/schemas.py`(요청 스키마) 이식본(2026-08-13).

원본 경로(`/api/v1/analysis/...`)와 메서드(POST)·요청 본문·응답 모델을 그대로
유지한다 — 발주처 프론트가 외부repo API 계약에 맞춰 개발 중일 수 있어 komir 쪽에서
경로를 바꿀 이유가 없다.

**원본에서 바뀐 것**

1. **서비스 주입**: 원본은 `api/dependencies.ApiRuntime`(search_service까지 함께 든
   런타임 객체)를 Depends로 받는다. komir report_gen에는 search_service가 없으므로
   `app.state.analysis_summary_service`/`analysis_lock`을 직접 읽는 얇은 의존성
   하나로 줄였다(`main.py`의 lifespan이 채운다).
2. **미구현 3종(`/prices`·`/domestic-trade`·`/global-trade`)은 만들지 않았다.**
   외부repo도 501 NOT_IMPLEMENTED 예약 라우트로만 두고 있어(광물자원가격·대한민국
   수급지도·글로벌 수급지도) 이식해도 동작이 없다 — 이번 이식 범위 밖.
3. **`POST /summary`(page_id를 본문으로 받는 통합 라우트)도 만들지 않았다.**
   원본이 "엔드포인트 이관 중 유지"라고 명시한 과도기 shim이라, 신규 이식본이
   물려받을 이유가 없다(5개 전용 경로가 정본 계약).

에러 매핑은 원본 그대로다 — `RawDataAccessError`(원천 조회 실패) → 503,
`DataSourceError`(요청 조건에 맞는 데이터 없음/모순) → 422 + 한국어 사유.
텅스텐(MNRL0018) 외 광종은 `public.KO_*`에 데이터가 없어 대부분 422로 떨어지는데,
이게 500이 아니라 "우아한 데이터 없음" 응답이다.
"""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..analysis.data_sources import DataSourceError
from ..analysis.models import (
    AnalysisSummaryRequest,
    AnalysisSummaryResponse,
    Day,
    ForecastHorizon,
    ForecastPeriod,
    MineralMapMeasure,
    Month,
)
from ..analysis.scaffold import RawDataAccessError

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


# ── 요청 스키마(원본 `api/schemas.py`) ────────────────────────────────


class ApiModel(BaseModel):
    """추가 필드를 거부하고 문자열 공백을 다듬는 API 기반 모델."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnalysisEndpointRequest(ApiModel):
    """페이지별 분석요약 요청이 공통으로 갖는 필드."""

    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    analysis_scope: Literal["page_only"] = "page_only"


class IndicatorSummaryRequest(AnalysisEndpointRequest):
    """시장동향·수급동향 지표 요약 요청."""

    mineral: str = Field(min_length=1)
    start_month: Month | None = None
    end_month: Month | None = None

    @model_validator(mode="after")
    def validate_period(self) -> IndicatorSummaryRequest:
        if self.start_month and self.end_month and self.start_month > self.end_month:
            raise ValueError("start_month must not be after end_month")
        return self


class CompositeIndexSummaryRequest(AnalysisEndpointRequest):
    """광물종합지수 요약 요청."""

    start_date: Day | None = None
    end_date: Day | None = None

    @model_validator(mode="after")
    def validate_period(self) -> CompositeIndexSummaryRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class MineralMapSummaryRequest(AnalysisEndpointRequest):
    """광물지도(매장량/생산량) 요약 요청."""

    mineral: str = Field(min_length=1)
    measure: MineralMapMeasure
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)

    @model_validator(mode="after")
    def validate_period(self) -> MineralMapSummaryRequest:
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must not be after end_year")
        return self


class PriceForecastSummaryRequest(AnalysisEndpointRequest):
    """중기(분기)·장기(연간) 가격예측 요약 요청."""

    mineral: str = Field(min_length=1)
    forecast_horizon: ForecastHorizon
    start_period: ForecastPeriod | None = None
    end_period: ForecastPeriod | None = None

    @model_validator(mode="after")
    def validate_period(self) -> PriceForecastSummaryRequest:
        if self.start_period and self.end_period and self.start_period > self.end_period:
            raise ValueError("start_period must not be after end_period")
        periods = [value for value in (self.start_period, self.end_period) if value]
        if self.forecast_horizon == "medium" and any("-Q" not in value for value in periods):
            raise ValueError("medium forecasts require YYYY-Q1..Q4 periods")
        if self.forecast_horizon == "long" and any("-Q" in value for value in periods):
            raise ValueError("long forecasts require YYYY periods")
        return self


# ── 공용 실행부 ───────────────────────────────────────────────────────


def _run_summary(
    summary_request: AnalysisSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """검증된 요약 요청 1건을 공용 서비스로 태운다."""

    service = getattr(request.app.state, "analysis_summary_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analysis database is not configured.",
        )
    try:
        # 동기 엔드포인트는 스레드풀에서 돌아 동시 진입이 가능하다 — 원본
        # ApiRuntime.analysis_lock과 같은 이유로 직렬화한다.
        with request.app.state.analysis_lock:
            return service.analyze(summary_request)
    except RawDataAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except DataSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post("/market-indicator", response_model=AnalysisSummaryResponse)
def summarize_market_indicator(
    payload: IndicatorSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """시장동향지표 분석요약."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="indicator_market", **payload.model_dump()),
        request,
    )


@router.post("/supply-indicator", response_model=AnalysisSummaryResponse)
def summarize_supply_indicator(
    payload: IndicatorSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """수급동향지표 분석요약."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="indicator_supply", **payload.model_dump()),
        request,
    )


@router.post("/composite-index", response_model=AnalysisSummaryResponse)
def summarize_composite_index(
    payload: CompositeIndexSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """광물종합지수 분석요약."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="indicator_composite", **payload.model_dump()),
        request,
    )


@router.post("/mineral-map", response_model=AnalysisSummaryResponse)
def summarize_mineral_map(
    payload: MineralMapSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """광물지도(매장량 또는 생산량) 분석요약."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="map_mineral", **payload.model_dump()),
        request,
    )


@router.post("/price-forecast", response_model=AnalysisSummaryResponse)
def summarize_price_forecast(
    payload: PriceForecastSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """중기 분기 또는 장기 연간 가격예측 분석요약."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="forecast_price", **payload.model_dump()),
        request,
    )
