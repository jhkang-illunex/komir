# -*- coding: utf-8 -*-
"""분석요약 API — 외부 저장소 `komis_report_generator/api/routers/analysis.py`
+ `api/schemas.py`(요청 스키마) 이식 5종(2026-08-13) + komir 자체 추가 3종
(2026-08-19).

원본 경로(`/api/v1/analysis/...`)와 메서드(POST)·이식 5종의 요청 본문·응답 모델은
그대로 유지한다 — 발주처 프론트가 외부repo API 계약에 맞춰 개발 중일 수 있어
komir 쪽에서 경로를 바꿀 이유가 없다.

**원본에서 바뀐 것(이식 5종)**

1. **서비스 주입**: 원본은 `api/dependencies.ApiRuntime`(search_service까지 함께 든
   런타임 객체)를 Depends로 받는다. komir report_gen에는 search_service가 없으므로
   `app.state.analysis_summary_service`/`analysis_lock`을 직접 읽는 얇은 의존성
   하나로 줄였다(`main.py`의 lifespan이 채운다).
2. **`POST /summary`(page_id를 본문으로 받는 통합 라우트)는 만들지 않았다.**
   원본이 "엔드포인트 이관 중 유지"라고 명시한 과도기 shim이라, 신규 이식본이
   물려받을 이유가 없다(5개 전용 경로가 정본 계약).
3. **결과 저장 추가(원본엔 없음, 2026-08-19)**: 원본 엔드포인트는 응답만 돌려주고
   아무것도 저장하지 않는다. `analysis/store.py`의 `analyze_and_store()`로
   교체해 `service.analyze()` 결과를 `out_report`에 적재까지 한다
   (`kind='summary'`, 주간 리포트와 같은 테이블·같은 멱등 방식). 응답 모델
   (`AnalysisSummaryResponse`)은 그대로라 API 계약엔 영향 없다.

**komir 자체 추가 3종(`/prices`·`/domestic-trade`·`/global-trade`, 2026-08-19)**:
2026-08-13까지는 "외부repo도 501 스텁이라 참고할 구현이 없다"는 이유로 이 3종을
만들지 않았었다. `KO_MNRL_PRC`(광물자원가격)·`KO_CSTM_CMMRC`(국내 수급지도)·
`KO_UN_CMMRC`(글로벌 수급지도) + 광종 매핑 테이블(`ai_prc_mnrl_map`/
`ai_hs_mnrl_map`)을 근거로 komir가 새로 짰다(계산은 `analysis/komir_summary.py`,
5종의 `additional_summary.py`와는 분리). 요청 스키마는 5종과 같은 패턴
(`AnalysisEndpointRequest` 상속)이되, 광종+일자 범위만 받는다 — 상세는 각 스키마
docstring 참고.

에러 매핑은 8종 전부 동일하다 — `RawDataAccessError`(원천 조회 실패) → 503,
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
from ..analysis.store import analyze_and_store

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


class MineralDateRangeSummaryRequest(AnalysisEndpointRequest):
    """광물자원가격·국내/글로벌 수급지도 3종이 공통으로 쓰는 요청(광종+일자범위).

    komir 자체 추가(2026-08-19) — 외부repo에 대응하는 스키마가 없다."""

    mineral: str = Field(min_length=1)
    start_date: Day | None = None
    end_date: Day | None = None

    @model_validator(mode="after")
    def validate_period(self) -> MineralDateRangeSummaryRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
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
            return analyze_and_store(service, summary_request)
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


# ── komir 자체 추가 3종(2026-08-19, 이식 아님) ───────────────────────


@router.post("/prices", response_model=AnalysisSummaryResponse)
def summarize_price(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """광물자원가격 분석요약(KO_MNRL_PRC)."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="price", **payload.model_dump()),
        request,
    )


@router.post("/domestic-trade", response_model=AnalysisSummaryResponse)
def summarize_domestic_trade(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """국내 수급지도 분석요약(KO_CSTM_CMMRC, 관세청)."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="map_korea", **payload.model_dump()),
        request,
    )


@router.post("/global-trade", response_model=AnalysisSummaryResponse)
def summarize_global_trade(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisSummaryResponse:
    """글로벌 수급지도 분석요약(KO_UN_CMMRC, UN Comtrade)."""

    return _run_summary(
        AnalysisSummaryRequest(page_id="map_global", **payload.model_dump()),
        request,
    )
