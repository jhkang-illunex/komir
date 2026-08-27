# -*- coding: utf-8 -*-
"""분석요약 API — 외부 저장소 `komis_report_generator/api/routers/analysis.py`
+ `api/schemas.py`(요청 스키마) 이식 5종(2026-08-13) + komir 자체 추가 4종
(2026-08-19 3종, 2026-08-27 `/prices` 분리로 4종).

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
3. **결과 저장(2026-08-19 추가 → 2026-08-26 다시 제거)**: 원본 엔드포인트는
   응답만 돌려주고 아무것도 저장하지 않는다. 2026-08-19에 `analysis/store.py`의
   `analyze_and_store()`로 `out_report`(MSR_DB) 적재를 추가했었는데, 2026-08-26
   사용자 지시("DB에 저장하지 않고 MD 형태로 바로 response에 작성")로 다시
   뗐다 — 지금은 `service.analyze()`만 호출하고 저장은 안 한다(`store.py`는
   지우지 않았고, `_common.py::run_summary`가 그 함수를 더 이상 부르지 않을
   뿐이다).

**komir 자체 추가(`/prices/base-metals`·`/prices/minor-metals`·`/domestic-trade`·
`/global-trade`, 2026-08-19 최초 3종)**:
2026-08-13까지는 "외부repo도 501 스텁이라 참고할 구현이 없다"는 이유로 이 3종을
만들지 않았었다. `KO_MNRL_PRC`(광물자원가격)·`KO_CSTM_CMMRC`(국내 수급지도)·
`KO_UN_CMMRC`(글로벌 수급지도) + 광종 매핑 테이블(`ai_prc_mnrl_map`/
`ai_hs_mnrl_map`)을 근거로 komir가 새로 짰다(계산은 `analysis/komir_summary.py`,
5종의 `additional_summary.py`와는 분리). 요청 스키마는 5종과 같은 패턴
(`AnalysisEndpointRequest` 상속)이되, 광종+일자 범위만 받는다 — 상세는 각 스키마
docstring 참고.

**2026-08-27 `/prices` 분리(비철금속/희소금속)**: 사용자가 실제 KOMIS
사이트맵을 확인한 결과 "광물자원가격" 메뉴가 실제로는 서브메뉴 2개(비철금속/
희소금속)라는 게 드러나 단일 `POST /prices`(`page_id="price"`)를
`/prices/base-metals`(`page_id="price_base_metals"`)·`/prices/minor-metals`
(`page_id="price_minor_metals"`) 2개로 쪼갰다. 옛 `/prices` 경로는 deprecated
alias 없이 제거했다(유일 소비자였던 streamlit_demo도 같은 날 맞춰 갱신, 다른
소비자 없음을 grep으로 확인). 계산 로직은 두 그룹이 동일해 그대로 공유하고
(`komir_summary.py::calculate_price_summary`), 페이지 이름·정의·정책버전만
그룹별로 나눴다(`komir_summary.py::KOMIR_PAGE_CONTEXTS`). 비교광종(`compare_*`
4개 필드)은 희소금속 KOMIS 화면에만 있는 기능이라 `models.py::
AnalysisSummaryRequest.validate_period`가 `page_id="price_minor_metals"`가
아니면 이제 명시적으로 거부한다(이전엔 "price" 단일 키라 문서화만 되고
강제되지 않았다).

**2026-08-26 DB 조회 → 요청 바디 입력으로 전환**: "이 서버는 prompt/template를
제외하고는 DB에서 값을 로딩하지 않는다"는 원칙에 따라, 전부 `public.KO_*`
직접 조회를 멈추고 각 요청의 `observations`(+ `mineral_name`/`unit`/`price_unit`
등 부속 필드)로 원자료를 받는다. 아래 5개 요청 스키마에 그 필드들을 추가했고,
DB 조회 코드(`data_sources/`)는 삭제하지 않고 `main.py::
build_analysis_summary_service()`·`analysis/summary.py`에서 호출부만 주석
처리해 남겨뒀다(복원 가능, WORKLOG 2026-08-26 참고).

**2026-08-26 응답 계약도 함께 교체**: 구조화 JSON(`AnalysisSummaryResponse`)
대신 `AnalysisReportResponse`(`status`+`report`, Markdown 텍스트)를 돌려준다 —
`status`는 성공 시 `"ok"`, 실패 시 오류 코드(`NO_DATA`·`TIMEOUT`·
`INTERNAL_ERROR`) 하나로 성공/실패를 겸한다. **HTTP 상태 코드는 전부 항상
200**이고(더 이상 422/503 HTTPException을 던지지 않는다), 요청당 20초
타임아웃도 이때 함께 걸었다 — 상세는 `routers/_common.py` 모듈 docstring
참고. 이식 5종은 원래 "발주처 프론트 계약이라 안 바꾼다"고 못박았던
요청·응답 모델이 이번 두 차례 변경(요청 바디 확장 + 응답 계약 교체)으로
실질적으로 달라졌다 — 계약 조율이 필요할 수 있음(WORKLOG 열린 항목).
"""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..analysis.models import (
    AnalysisReportResponse,
    Day,
    ForecastHorizon,
    ForecastPeriod,
    MineralMapMeasure,
    Month,
    PriceGroup,
)
from ._common import run_summary

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
    """시장동향·수급동향 지표 요약 요청.

    2026-08-26: `observations`(IndicatorObservation 리스트, dict 그대로) —
    DB 대신 요청 바디로 원자료를 받는다(§`models.py::AnalysisSummaryRequest`
    2026-08-26 주석 참고). `mineral_name`이 없으면 `mineral`(코드)을 표시명으로도
    쓴다."""

    mineral: str = Field(min_length=1)
    mineral_name: str | None = Field(default=None, min_length=1)
    start_month: Month | None = None
    end_month: Month | None = None
    observations: list[dict] | None = None
    price_unit: str | None = None
    price_criterion: str | None = None
    unavailable_page_data: list[str] | None = None
    supply_auxiliary: dict | None = None

    @model_validator(mode="after")
    def validate_period(self) -> IndicatorSummaryRequest:
        if self.start_month and self.end_month and self.start_month > self.end_month:
            raise ValueError("start_month must not be after end_month")
        return self


class CompositeIndexSummaryRequest(AnalysisEndpointRequest):
    """광물종합지수 요약 요청.

    2026-08-26: `observations`(CompositeIndexObservation 리스트) — DB 대신
    요청 바디로 원자료를 받는다."""

    start_date: Day | None = None
    end_date: Day | None = None
    observations: list[dict] | None = None

    @model_validator(mode="after")
    def validate_period(self) -> CompositeIndexSummaryRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class MineralMapSummaryRequest(AnalysisEndpointRequest):
    """광물지도(매장량/생산량) 요약 요청.

    2026-08-26: `observations`(MineralMapObservation 리스트) — DB 대신 요청
    바디로 원자료를 받는다. `unit`(예: "천톤")도 요청에서 받는다(DB의
    `MineralMapSeries.unit`을 대체)."""

    mineral: str = Field(min_length=1)
    mineral_name: str | None = Field(default=None, min_length=1)
    measure: MineralMapMeasure
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    observations: list[dict] | None = None
    unit: str | None = None
    # 2026-08-27 신설 — 매장량/생산량 교차 비교(PDF §4). `measure`의 반대
    # measure 관측치를 같은 shape(dict 리스트)으로 선택적으로 함께 보낸다.
    secondary_measure_observations: list[dict] | None = None
    secondary_unit: str | None = None

    @model_validator(mode="after")
    def validate_period(self) -> MineralMapSummaryRequest:
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must not be after end_year")
        return self


class PriceForecastSummaryRequest(AnalysisEndpointRequest):
    """중기(분기)·장기(연간) 가격예측 요약 요청.

    2026-08-26: `observations`(PriceForecastObservation 리스트) — DB 대신
    요청 바디로 원자료를 받는다."""

    mineral: str = Field(min_length=1)
    mineral_name: str | None = Field(default=None, min_length=1)
    forecast_horizon: ForecastHorizon
    start_period: ForecastPeriod | None = None
    end_period: ForecastPeriod | None = None
    observations: list[dict] | None = None
    price_unit: str | None = None

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
    """광물자원가격(비철금속/희소금속)·국내/글로벌 수급지도 4종이 공통으로 쓰는
    요청(광종+일자범위).

    komir 자체 추가(2026-08-19) — 외부repo에 대응하는 스키마가 없다.
    2026-08-26: `observations`(PriceObservation 또는 TradeCountryObservation
    리스트, page_id에 따라 다르다) — DB 대신 요청 바디로 원자료를 받는다.
    `page_id="price_base_metals"`/`"price_minor_metals"` 전용: `price_criterion`
    (자유 텍스트, 예: "LME CASH"·"Lithium Carbonate") — 두 그룹은 같은 광종이어도
    조회조건(가격기준/품목·스펙)이 다를 수 있어, 어떤 조건으로 조회한 값인지
    문자열로 실어 보내면 보고서 상단에 그대로 표시된다(report_render.py).

    2026-08-26: `page_id="price_minor_metals"`(희소금속, 2026-08-27 이전엔
    `"price"`) 전용으로 `compare_*` 4종 필드도 추가 — KOMIS 원본 API는 비교광종
    지정 시 응답이 `data.defaultMnrl`(기본 계열)·`data.compareMnrl`(비교 계열)
    두 키로 온다(사용자 확인). 이 서버는 `observations`=defaultMnrl 상당,
    `compare_observations`=compareMnrl 상당으로 그대로 받는다 — 둘 다 있으면
    보고서에 두 광종의 조회기간 변화율 비교 문장이 추가된다(`komir_summary.py::
    calculate_price_summary`). `page_id="price_base_metals"`로 이 필드들을
    보내면 `models.py::AnalysisSummaryRequest.validate_period`가 거부한다
    (2026-08-27부터 강제, 이전엔 문서화만 됨)."""

    mineral: str = Field(min_length=1)
    mineral_name: str | None = Field(default=None, min_length=1)
    start_date: Day | None = None
    end_date: Day | None = None
    observations: list[dict] | None = None
    price_unit: str | None = None
    price_criterion: str | None = None
    price_criterion_serial: int | None = None
    # `page_id="price_minor_metals"`(희소금속) 전용 — KOMIS "비교광종" 기능 대응,
    # 클래스 docstring 참고.
    compare_mineral: str | None = Field(default=None, min_length=1)
    compare_mineral_name: str | None = Field(default=None, min_length=1)
    compare_price_criterion: str | None = None
    compare_observations: list[dict] | None = None
    # 2026-08-27 신설 — `page_id="map_korea"`(국내 수급지도) 전용, KOMIS 화면의
    # 수입/수출 방향 라디오 대응. PDF 지침 점검(/unlazy)에서 발견한 버그
    # 수정 — 이 신호가 없어 계산 레이어가 항상 "수입"으로 라벨링했었다.
    trade_direction: Literal["import", "export"] | None = None

    @model_validator(mode="after")
    def validate_period(self) -> MineralDateRangeSummaryRequest:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class PriceGroupSummaryRequest(AnalysisEndpointRequest):
    """비철금속/희소금속 그룹 전체 가격 요약 요청 — 2026-08-27 신설(PDF §1-2
    "전체광종(필요시)" 대응, PDF 지침 점검(/unlazy)에서 발견한 gap).

    광종 1개가 아니라 그룹 전체를 다루므로 `mineral`이 없다. `observations`는
    `PriceGroupMineralObservation`(광종명 + 전주·전월 등락률) 리스트다."""

    price_group: PriceGroup
    observations: list[dict] | None = None


# ── 공용 실행부 ───────────────────────────────────────────────────────


@router.post("/market-indicator", response_model=AnalysisReportResponse)
def summarize_market_indicator(
    payload: IndicatorSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """시장동향지표 분석요약."""

    return run_summary("indicator_market", payload, request)


@router.post("/supply-indicator", response_model=AnalysisReportResponse)
def summarize_supply_indicator(
    payload: IndicatorSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """수급동향지표 분석요약."""

    return run_summary("indicator_supply", payload, request)


@router.post("/composite-index", response_model=AnalysisReportResponse)
def summarize_composite_index(
    payload: CompositeIndexSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """광물종합지수 분석요약."""

    return run_summary("indicator_composite", payload, request)


@router.post("/mineral-map", response_model=AnalysisReportResponse)
def summarize_mineral_map(
    payload: MineralMapSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """광물지도(매장량 또는 생산량) 분석요약."""

    return run_summary("map_mineral", payload, request)


@router.post("/price-forecast", response_model=AnalysisReportResponse)
def summarize_price_forecast(
    payload: PriceForecastSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """중기 분기 또는 장기 연간 가격예측 분석요약."""

    return run_summary("forecast_price", payload, request)


# ── komir 자체 추가 4종(2026-08-19 최초 3종, 2026-08-27 /prices 분리로 4종,
# 이식 아님) ────────────────────────────────────────────────────────


@router.post("/prices/base-metals", response_model=AnalysisReportResponse)
def summarize_price_base_metals(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """비철금속 가격 분석요약(KO_MNRL_PRC) — 2026-08-27 이전엔 `/prices`
    (`page_id="price"`)로 희소금속과 합쳐 다뤘다(§모듈 docstring)."""

    return run_summary("price_base_metals", payload, request)


@router.post("/prices/minor-metals", response_model=AnalysisReportResponse)
def summarize_price_minor_metals(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """희소금속 가격 분석요약(KO_MNRL_PRC) — 2026-08-27 이전엔 `/prices`
    (`page_id="price"`)로 비철금속과 합쳐 다뤘다(§모듈 docstring). `compare_*`
    (비교광종)는 이 페이지에서만 허용된다."""

    return run_summary("price_minor_metals", payload, request)


@router.post("/domestic-trade", response_model=AnalysisReportResponse)
def summarize_domestic_trade(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """국내 수급지도 분석요약(KO_CSTM_CMMRC, 관세청)."""

    return run_summary("map_korea", payload, request)


@router.post("/global-trade", response_model=AnalysisReportResponse)
def summarize_global_trade(
    payload: MineralDateRangeSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """글로벌 수급지도 분석요약(KO_UN_CMMRC, UN Comtrade)."""

    return run_summary("map_global", payload, request)


@router.post("/price-group", response_model=AnalysisReportResponse)
def summarize_price_group(
    payload: PriceGroupSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """비철금속/희소금속 그룹 전체 가격요약(PDF §1-2, 2026-08-27 신설)."""

    return run_summary("price_group", payload, request)
