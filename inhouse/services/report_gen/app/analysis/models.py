# -*- coding: utf-8 -*-
"""분석 계열(series)·관측(observation)·요약문 타입 — 외부 저장소
`komis_report_generator/analysis/models.py` 이식본(2026-08-11 1차, 2026-08-13 완성).

**2026-08-13**: 1차 때 "요약문 엔진을 안 가져왔으니 그 전용 모델도 뺀다"고 적어둔
주석은 이제 무효다 — 같은 날 `summary.py`·`additional_summary.py`·`policy.py`·
`prompts.py`를 실제로 이식하면서 그 모델들(`GradeResult`/`Metric`/
`DetectedPattern`/`OmittedIndicator`/`DataQuality`/`SourceInfo`/`Summary*`/
`AnalysisSummaryRequest`/`AnalysisSummaryResponse`/`PAGE_PROFILES`)과 가격예측
계열(`Forecast*`/`PriceForecast*`)·수급 보조패널(`Supply*`)을 전부 채워 넣었다.

**여전히 안 가져온 것**: `AnalysisRequest`/`AnalysisResponse`/`NarrativeOutput`/
`ProfileId`. 이건 프로파일 기반(profile_id) 분석 경로 전용인데, 외부repo에서도
`experiments/analysis_summary_evaluation/`(평가용 CLI)만 쓰고 5개 운영
엔드포인트는 쓰지 않는다(2026-08-13 grep 실측) — 소비자 없는 타입을 들여오면
죽은 코드가 된다(CLAUDE.md §4 최소 변경).
"""
from __future__ import annotations

from typing import Literal
from uuid import uuid4

try:  # pydantic v2
    from typing import Annotated
except ImportError:  # pragma: no cover
    from typing_extensions import Annotated  # type: ignore

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PageId = Literal["indicator_market", "indicator_supply"]
SummaryPageId = Literal[
    "indicator_market",
    "indicator_supply",
    "indicator_composite",
    "forecast_price",
    "map_mineral",
    # 아래 3개는 외부repo에도 없던 komir 자체 추가(2026-08-19) — §"가격·수급지도
    # 요약문 전용 모델" 참고.
    "price",
    "map_korea",
    "map_global",
]
Month = Annotated[str, Field(pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")]
MineralMapMeasure = Literal["reserves", "production"]
ForecastHorizon = Literal["medium", "long"]
ForecastPeriod = Annotated[str, Field(pattern=r"^\d{4}(?:-Q[1-4])?$")]

#: 광종·월 필터를 쓰는 "지표" 페이지 집합. `AnalysisSummaryRequest`의 필터 검증이
#: 이 dict의 키를 그대로 쓴다(원본은 profile_id 목록도 담았지만, 프로파일 경로를
#: 이식하지 않았으므로 값은 페이지 구분용으로만 남는다).
PAGE_PROFILES: dict[str, set[str]] = {
    "indicator_market": {
        "current_status",
        "grade_persistence",
        "score_price_relationship",
    },
    "indicator_supply": {
        "current_status",
        "grade_persistence",
        "score_price_relationship",
        "world_supply_balance",
        "domestic_procurement_concentration",
    },
}


class StrictModel(BaseModel):
    """정의되지 않은 필드를 거부하는 기반 모델."""

    model_config = ConfigDict(extra="forbid")


class AnalysisSummaryRequest(StrictModel):
    """페이지 단위 분석요약 요청(페이지별로 허용 필터가 다르다)."""

    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    page_id: SummaryPageId
    mineral: str | None = Field(default=None, min_length=1)
    start_month: Month | None = None
    end_month: Month | None = None
    start_date: Day | None = None
    end_date: Day | None = None
    start_year: int | None = Field(default=None, ge=1900, le=2100)
    end_year: int | None = Field(default=None, ge=1900, le=2100)
    measure: MineralMapMeasure | None = None
    forecast_horizon: ForecastHorizon | None = None
    start_period: ForecastPeriod | None = None
    end_period: ForecastPeriod | None = None
    analysis_scope: Literal["page_only"] = "page_only"

    @field_validator("request_id")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("mineral")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_period(self) -> AnalysisSummaryRequest:
        if self.start_month and self.end_month and self.start_month > self.end_month:
            raise ValueError("start_month must not be after end_month")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.start_year and self.end_year and self.start_year > self.end_year:
            raise ValueError("start_year must not be after end_year")
        if self.start_period and self.end_period and self.start_period > self.end_period:
            raise ValueError("start_period must not be after end_period")

        if self.page_id in PAGE_PROFILES:
            if self.mineral is None:
                raise ValueError("mineral is required for indicator summaries")
            if any(
                value is not None
                for value in (
                    self.start_date,
                    self.end_date,
                    self.start_year,
                    self.end_year,
                    self.measure,
                    self.forecast_horizon,
                    self.start_period,
                    self.end_period,
                )
            ):
                raise ValueError("indicator summaries only accept month filters")
        elif self.page_id == "indicator_composite":
            if any(
                value is not None
                for value in (
                    self.start_month,
                    self.end_month,
                    self.start_year,
                    self.end_year,
                    self.measure,
                    self.forecast_horizon,
                    self.start_period,
                    self.end_period,
                )
            ):
                raise ValueError("composite index summaries only accept date filters")
        elif self.page_id == "forecast_price":
            if self.mineral is None:
                raise ValueError("mineral is required for price forecast summaries")
            if self.forecast_horizon is None:
                raise ValueError("forecast_horizon is required for price forecasts")
            if any(
                value is not None
                for value in (
                    self.start_month,
                    self.end_month,
                    self.start_date,
                    self.end_date,
                    self.start_year,
                    self.end_year,
                    self.measure,
                )
            ):
                raise ValueError("price forecasts only accept forecast-period filters")
            periods = [value for value in (self.start_period, self.end_period) if value]
            if self.forecast_horizon == "medium" and any("-Q" not in value for value in periods):
                raise ValueError("medium forecasts require YYYY-Q1..Q4 periods")
            if self.forecast_horizon == "long" and any("-Q" in value for value in periods):
                raise ValueError("long forecasts require YYYY periods")
        elif self.page_id == "map_mineral":
            if self.mineral is None:
                raise ValueError("mineral is required for mineral map summaries")
            if self.measure is None:
                raise ValueError("measure is required for mineral map summaries")
            if any(
                value is not None
                for value in (
                    self.start_month,
                    self.end_month,
                    self.start_date,
                    self.end_date,
                    self.forecast_horizon,
                    self.start_period,
                    self.end_period,
                )
            ):
                raise ValueError("mineral map summaries only accept year filters")
        else:
            # "price"·"map_korea"·"map_global" — komir 자체 추가 3종(§ SummaryPageId
            # 주석 참고), 셋 다 광종 필수 + 일자(day) 필터만 받는 동일한 모양이다.
            if self.mineral is None:
                raise ValueError("mineral is required for price/trade map summaries")
            if any(
                value is not None
                for value in (
                    self.start_month,
                    self.end_month,
                    self.start_year,
                    self.end_year,
                    self.measure,
                    self.forecast_horizon,
                    self.start_period,
                    self.end_period,
                )
            ):
                raise ValueError("price/trade map summaries only accept date filters")
        return self


class MineralRef(StrictModel):
    """광종의 안정적인 코드와 표시명."""

    code: str
    name: str


class IndicatorObservation(StrictModel):
    """월 단위 지표 점수 1건과 (있으면) 그 시점 가격."""

    month: Month
    score: float = Field(ge=0, le=100)
    price: float | None = None
    crisis_flag: bool | None = None


class SupplyInternationalPriceObservation(StrictModel):
    """수급안정 페이지 국제가격 보조패널의 월 1건."""

    month: Month
    price: float


class SupplyDomesticImportObservation(StrictModel):
    """국내 수입중량·수입금액 보조패널의 연 1건(KOMIS 화면 표기 배율)."""

    year: int = Field(ge=1900, le=2100)
    import_weight_ton: float = Field(ge=0)
    import_amount_million_usd: float = Field(ge=0)


class SupplyWorldBalanceObservation(StrictModel):
    """세계 수요·공급·과부족 보조패널의 연 1건."""

    year: int = Field(ge=1900, le=2100)
    demand_thousand_ton: float
    supply_thousand_ton: float
    balance_thousand_ton: float


class SupplyImportDependencyObservation(StrictModel):
    """상위 3개국 수입의존도 보조패널의 국가 1행."""

    year: int = Field(ge=1900, le=2100)
    country_name: str
    amount_usd: float = Field(ge=0)
    weight_kg: float = Field(ge=0)
    share_percent: float = Field(ge=0, le=100)


class SupplyAuxiliaryData(StrictModel):
    """수급안정 페이지의 선택적 보조패널 묶음.

    ⚠ 현재 komir가 쓰는 `DatabaseIndicatorDataSource`는 이 값을 채우지 않는다
    (`public.KO_SPDM_STBT_INDX` 한 테이블만 읽으므로 보조패널 원천이 없다) —
    항상 None이라 `summary.py._supply_auxiliary_metrics`가 빈 리스트를 돌려준다.
    그럼에도 타입을 이식해 둔 이유는 `summary.py`를 원본과 동일하게 유지하기
    위해서다(외부repo가 계속 개발 중이라 포크를 만들면 재동기화가 어려워진다).
    """

    international_prices: list[SupplyInternationalPriceObservation] = Field(
        default_factory=list
    )
    domestic_imports: list[SupplyDomesticImportObservation] = Field(default_factory=list)
    world_balances: list[SupplyWorldBalanceObservation] = Field(default_factory=list)
    import_dependencies: list[SupplyImportDependencyObservation] = Field(
        default_factory=list
    )
    top_three_dependency_percent: float | None = Field(default=None, ge=0, le=100)


class IndicatorSeries(StrictModel):
    """출처 메타를 포함한 월별 지표 관측 계열."""

    page_id: PageId
    mineral: MineralRef
    requested_start_month: Month | None = None
    requested_end_month: Month | None = None
    available_start_month: Month
    available_end_month: Month
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[IndicatorObservation] = Field(min_length=1)
    supply_auxiliary: SupplyAuxiliaryData | None = None
    price_unit: str | None = None
    price_criterion: str | None = None
    unavailable_page_data: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompositeIndexObservation(StrictModel):
    """기준일 1건의 광물종합지수와 두 구성지수."""

    date: Day
    composite_index: float = Field(gt=0)
    major_metals_index: float = Field(gt=0)
    minor_metals_index: float = Field(gt=0)


class CompositeIndexSeries(StrictModel):
    """출처 메타를 포함한 광물종합지수 계열."""

    page_id: Literal["indicator_composite"] = "indicator_composite"
    available_start_date: Day
    available_end_date: Day
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[CompositeIndexObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class PriceForecastObservation(StrictModel):
    """분기(YYYY-Qn) 또는 연(YYYY) 예측가격 1건."""

    period: ForecastPeriod
    price: float = Field(gt=0)


class PriceForecastSeries(StrictModel):
    """출처 메타를 포함한 중기(분기)/장기(연간) 가격예측 계열."""

    page_id: Literal["forecast_price"] = "forecast_price"
    mineral: MineralRef
    horizon: ForecastHorizon
    available_start_period: ForecastPeriod
    available_end_period: ForecastPeriod
    price_unit: str | None = None
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[PriceForecastObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class MineralMapObservation(StrictModel):
    """특정 연도·국가의 광물지도 값(톤 환산)."""

    year: int = Field(ge=1900, le=2100)
    country_code: str
    country_name: str
    value: float = Field(ge=0)
    is_total: bool = False
    is_other: bool = False


class MineralMapSeries(StrictModel):
    """출처 메타를 포함한 광물지도(매장량/생산량) 계열."""

    page_id: Literal["map_mineral"] = "map_mineral"
    mineral: MineralRef
    measure: MineralMapMeasure
    unit: str
    available_start_year: int = Field(ge=1900, le=2100)
    available_end_year: int = Field(ge=1900, le=2100)
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[MineralMapObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


# ────────────────────────────────────────────────────────────────────
# 가격·수급지도 요약문 전용 모델 — komir 자체 추가(2026-08-19, 이식 아님).
# 외부repo는 `/prices`·`/domestic-trade`·`/global-trade` 3종을 501 스텁으로만
# 남겨뒀다(원본에 참고할 모델이 없다). `KO_MNRL_PRC`(가격)·`KO_CSTM_CMMRC`(국내
# 수급지도)·`KO_UN_CMMRC`(글로벌 수급지도) 원천 컬럼에 맞춰 새로 정의했다.
# ────────────────────────────────────────────────────────────────────


class PriceObservation(StrictModel):
    """특정 일자의 실거래가·최저가·최고가·재고(있으면)."""

    date: Day
    commerce_price: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None
    inventory: float | None = None


class PriceSeries(StrictModel):
    """출처 메타를 포함한 광물자원가격(KO_MNRL_PRC) 계열."""

    page_id: Literal["price"] = "price"
    mineral: MineralRef
    price_criterion_serial: int
    available_start_date: Day
    available_end_date: Day
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[PriceObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class TradeCountryObservation(StrictModel):
    """특정 일자·상대국의 수입(있으면 수출) 중량·금액."""

    date: Day
    country_code: str
    country_name: str
    import_weight: float | None = None
    import_amount: float | None = None
    export_weight: float | None = None
    export_amount: float | None = None


class TradeMapSeries(StrictModel):
    """출처 메타를 포함한 국내(KO_CSTM_CMMRC)/글로벌(KO_UN_CMMRC) 수급지도 계열."""

    page_id: Literal["map_korea", "map_global"]
    mineral: MineralRef
    available_start_date: Day
    available_end_date: Day
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[TradeCountryObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


# ────────────────────────────────────────────────────────────────────
# 요약문(summary.py·additional_summary.py) 전용 모델 — 2026-08-13 이식
# ────────────────────────────────────────────────────────────────────


class GradeResult(StrictModel):
    """정책 등급과 다음 상한 경계까지의 거리."""

    label: str
    score: float
    crisis_flag: bool | None = None
    upper_boundary: float | None = None
    distance_to_upper_boundary: float | None = None


class Metric(StrictModel):
    """이름·가용성·산출근거를 가진 분석 지표 1건."""

    id: str
    label: str
    status: Literal["available", "insufficient_data", "not_provided"]
    value: float | int | str | bool | None = None
    unit: str | None = None
    basis: str | None = None


class DetectedPattern(StrictModel):
    """이름 붙은 데이터 패턴과 그 근거 사실들."""

    code: str
    label: str
    evidence: list[str] = Field(default_factory=list)


class OmittedIndicator(StrictModel):
    """분석에서 제외한 지표와 그 사유."""

    id: str
    reason: str


class DataQuality(StrictModel):
    """원천 데이터의 커버리지·유효기간·누락·경고."""

    status: Literal["available", "partial", "insufficient"]
    observation_count: int = Field(ge=0)
    available_start_month: Month | None = None
    available_end_month: Month | None = None
    effective_start_month: Month | None = None
    effective_end_month: Month | None = None
    available_start_date: Day | None = None
    available_end_date: Day | None = None
    effective_start_date: Day | None = None
    effective_end_date: Day | None = None
    available_start_year: int | None = None
    available_end_year: int | None = None
    effective_start_year: int | None = None
    effective_end_year: int | None = None
    available_start_period: ForecastPeriod | None = None
    available_end_period: ForecastPeriod | None = None
    effective_start_period: ForecastPeriod | None = None
    effective_end_period: ForecastPeriod | None = None
    missing_data: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceInfo(StrictModel):
    """분석에 쓴 원천 데이터의 출처·버전 정보."""

    type: Literal["file", "database", "api", "snapshot"]
    id: str
    data_version: str
    as_of: str
    file: str | None = None
    sheets: list[str] = Field(default_factory=list)


class SummarySentence(StrictModel):
    """근거(evidence_id)에 묶인 분석문 1문장."""

    text: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class SummaryNarrative(StrictModel):
    """3개 섹션으로 묶인 근거 연결 분석문."""

    core_diagnosis: list[SummarySentence] = Field(min_length=1, max_length=2)
    major_changes: list[SummarySentence] = Field(min_length=1, max_length=5)
    current_position: list[SummarySentence] = Field(min_length=1, max_length=3)


class AnalysisSummaryResponse(StrictModel):
    """페이지 단위 분석요약 응답 전체와 그 산출 메타."""

    request_id: str
    page_id: SummaryPageId
    analysis_scope: Literal["page_only"]
    mineral: MineralRef
    applied_filters: dict[str, str | None]
    defaulted_filters: list[str]
    filter_hash: str
    source: SourceInfo
    policy_version: str
    page_definition: str
    grade: GradeResult | None
    data_quality: DataQuality
    summary: SummaryNarrative
    key_metrics: list[Metric] = Field(max_length=8)
    detailed_metrics: list[Metric]
    detected_patterns: list[DetectedPattern]
    omitted_indicators: list[OmittedIndicator]
    notices: list[str]
    llm_refined: bool = False
