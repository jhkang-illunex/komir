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
    # 아래 4개는 외부repo에도 없던 komir 자체 추가(2026-08-19) — §"가격·수급지도
    # 요약문 전용 모델" 참고.
    # 2026-08-27: 사용자가 실제 KOMIS 사이트맵(스샷 근거)을 확인해 "price" 1개가
    # 실제로는 서로 다른 서브메뉴 2개(광물자원가격 > 비철금속/희소금속)를 합쳐
    # 다루고 있었다는 걸 발견 — page_id를 실제 메뉴 구조에 맞춰 2개로 쪼갰다
    # (이전 "price" 단일 키는 완전히 제거, deprecated alias 없음 — 유일 소비자였던
    # streamlit_demo도 같은 날 맞춰 갱신). 이름은 rag_chat page_recommend registry
    # (services/rag_chat/app/page_recommend/resources/registry/pages/
    # price_base_metals.yaml·price_minor.yaml의 `page_id:` 필드값, 파일명과
    # 다르다 — price_minor.yaml 안엔 `price_minor_metals`가 정본이고 `price_minor`는
    # alias)와 맞춰 다른 서브시스템과 이름을 통일했다.
    "price_base_metals",
    "price_minor_metals",
    # 2026-08-28: "광물자원가격" 대메뉴의 나머지 실제 서브메뉴 2개(철광석 및
    # 에너지/기타)도 같은 이유로 추가 — 이전엔 komis_menu_map.yaml의
    # gaps_not_covered_by_report_gen에 미커버로 기록돼 있었다. 이름은
    # price_base_metals/price_minor_metals와 같은 근거(registry `page_id:`
    # 필드 — 이번엔 파일명과 동일해 alias 문제 없음, 사용자 사전 확인).
    "price_iron_energy",
    "price_other",
    "map_korea",
    "map_global",
    # 2026-08-27 신설 — PDF §1-2 "전체광종(필요시)" 대응(비철금속/희소금속
    # 그룹 전체 가격 등락 요약). 광종 1개가 아니라 그룹 전체를 다룬다.
    "price_group",
]
PriceGroup = Literal["base_metals", "minor_metals"]
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

    # 2026-08-26: "DB에서 값(데이터)을 로딩하지 않는다 — prompt/template만 DB에서
    # 읽는다"는 원칙에 따라, 계산에 쓰는 원자료를 요청 바디로 받도록 전환했다
    # (`summary.py::_analyze_*`가 DB DataSource 대신 이 필드들로 Series를
    # 조립한다 — 옛 DB 조회 경로는 주석으로 보존, WORKLOG 2026-08-26 참고).
    # `observations`는 페이지별로 다른 shape(dict 리스트)이라 여기서는 검증하지
    # 않고, 각 `_analyze_*`가 해당 페이지의 Observation 모델로 다시 검증한다.
    mineral_name: str | None = Field(default=None, min_length=1)
    observations: list[dict] | None = None
    price_unit: str | None = None
    price_criterion: str | None = None
    price_criterion_serial: int | None = None
    unavailable_page_data: list[str] | None = None
    supply_auxiliary: dict | None = None
    unit: str | None = None
    # 2026-08-26: `page_id="price_minor_metals"` 전용 — KOMIS 희소금속 페이지의
    # "비교광종" 대응(원본 응답의 `compareMnrl` 키). `compare_observations`는
    # `observations`와 같은 shape(PriceObservation dict 리스트)이다. 2026-08-27
    # price page_id 분리 후 `validate_period`가 이 4개 필드를
    # page_id != "price_minor_metals"이면 명시적으로 거부한다(이전엔 문서화만
    # 되고 강제되지 않았다 — map_korea/map_global도 같은 요청 모델을 공유해
    # 필드 자체는 존재했다).
    compare_mineral: str | None = Field(default=None, min_length=1)
    compare_mineral_name: str | None = Field(default=None, min_length=1)
    compare_price_criterion: str | None = None
    compare_observations: list[dict] | None = None
    # 2026-08-27: `page_id="map_korea"` 전용 — KOMIS 화면의 수입/수출 방향
    # 라디오(`srchIncmExp`) 대응. 이전에는 이 신호가 없어 계산 레이어가 항상
    # "수입"으로 라벨링했다(PDF 지침 점검(/unlazy)에서 발견한 버그, 실측:
    # 수출 방향으로 조회한 73건 중 "수출총액" 문구 0건). 기본값은 KOMIS 화면
    # 기본 선택과 같은 "import".
    trade_direction: Literal["import", "export"] | None = None
    # 2026-08-27: `page_id="map_mineral"` 전용 — 매장량/생산량 교차 비교(PDF
    # §4 "매장량 2위 호주는 생산량 8위" 패턴) 대응. `measure`로 지정한 주
    # 항목과 같은 shape(MineralMapObservation dict 리스트)의 반대 항목
    # 관측치를 선택적으로 함께 보낸다.
    secondary_measure_observations: list[dict] | None = None
    secondary_unit: str | None = None
    # 2026-08-27: `page_id="price_group"` 전용 — PDF §1-2 그룹 요약 대상
    # (비철금속/희소금속). `observations`는 이 페이지에서 PriceGroupMineral
    # Observation dict 리스트(광종별 전주·전월 등락률)를 담는다.
    price_group: PriceGroup | None = None

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
        if self.trade_direction is not None and self.page_id != "map_korea":
            raise ValueError("trade_direction is only accepted for page_id=map_korea")
        if self.secondary_measure_observations is not None and self.page_id != "map_mineral":
            raise ValueError("secondary_measure_observations is only accepted for page_id=map_mineral")
        if self.secondary_unit is not None and self.page_id != "map_mineral":
            raise ValueError("secondary_unit is only accepted for page_id=map_mineral")
        # 2026-08-27 price page_id 분리 — 비교광종은 희소금속 전용 KOMIS 기능이라
        # price_base_metals/map_korea/map_global로는 못 보내게 새로 강제한다(이전엔
        # 문서화만 되고 pydantic이 걸러내지 않았다).
        if (
            any(
                value is not None
                for value in (
                    self.compare_mineral,
                    self.compare_mineral_name,
                    self.compare_price_criterion,
                    self.compare_observations,
                )
            )
            and self.page_id != "price_minor_metals"
        ):
            raise ValueError("compare_* fields are only accepted for page_id=price_minor_metals")

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
        elif self.page_id == "price_group":
            # 2026-08-27 신설 — 광종 1개가 아니라 그룹(비철금속/희소금속)
            # 전체를 다뤄 다른 페이지와 달리 mineral을 받지 않는다.
            if self.price_group is None:
                raise ValueError("price_group is required for price_group summaries")
            if self.mineral is not None:
                raise ValueError("price_group summaries do not accept mineral (group-level only)")
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
                    self.forecast_horizon,
                    self.start_period,
                    self.end_period,
                )
            ):
                raise ValueError("price_group summaries do not accept period filters")
        else:
            # "price_base_metals"·"price_minor_metals"·"price_iron_energy"·
            # "price_other"·"map_korea"·"map_global" — komir 자체 추가 6종
            # (§ SummaryPageId 주석 참고), 전부 광종 필수 + 일자(day) 필터만
            # 받는 동일한 모양이다.
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


class PriceGroupMineralObservation(StrictModel):
    """`page_id="price_group"` 전용(2026-08-27 신설) — 그룹 내 광종 1개의
    전주·전월 등락률(%, signed). 원시 일별 가격 계열이 아니라 이미 계산된
    등락률을 받는다 — 그룹 요약은 광종별 raw 계열을 전부 다시 계산하기보다
    "이미 계산된 개별 광종 등락률을 모아 그룹 통계를 내는" PDF §1-2 문구
    구조에 맞다."""

    mineral_name: str = Field(min_length=1)
    week_change_pct: float
    month_change_pct: float | None = None


class PriceSeries(StrictModel):
    """출처 메타를 포함한 광물자원가격(KO_MNRL_PRC) 계열."""

    # 2026-08-27: 값 자체는 어디서도 읽지 않는 메타 필드다(계산기 `calculate_price_
    # summary`는 참조하지 않는다) — 그래도 실제 호출부(`_analyze_price`)가
    # `request.page_id`를 명시적으로 넘긴다. 기본값은 임의(비철금속) — dead code인
    # `data_sources/extra.py`의 미사용 호출부만 이 기본값에 의존한다.
    page_id: Literal["price_base_metals", "price_minor_metals", "price_iron_energy", "price_other"] = "price_base_metals"
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
    """특정 일자·상대국의 수입(있으면 수출) 중량·금액.

    `origin_country_*`(2026-08-27 신설, map_global 전용)는 UN Comtrade
    양자무역 "루트"(원산지→도착지)를 표현한다 — `country_code`/`country_name`을
    도착국(수입국, KOMIS `incmNtnNm`)으로 쓰고, `origin_country_*`를 원산국
    (수출국, KOMIS `expNtnNm`)으로 쓴다. map_korea는 상대국 1개 축만 있어
    이 필드들을 쓰지 않는다(PDF 지침 점검(/unlazy)에서 발견한 gap 수정 —
    이전에는 도착국 정보를 버리고 원산국별로만 집계해 PDF가 요구하는
    "미국→독일" 식 루트 랭킹과 대한민국 자체 순위를 만들 수 없었다)."""

    date: Day
    country_code: str
    country_name: str
    import_weight: float | None = None
    import_amount: float | None = None
    export_weight: float | None = None
    export_amount: float | None = None
    origin_country_code: str | None = None
    origin_country_name: str | None = None


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
    # 상한 3→5(2026-08-27 반복 루프 4회차): price 페이지는 PDF 1-1 템플릿대로 전일·전주·
    # 전월·전년(·연속) 비교를 한 문장에 담아야 하는데 3개 상한 때문에 4번째 사실의
    # id를 못 달아 "근거에 없는 숫자"로 폴백됐다. 페이지별 실제 허용치는
    # `prompts.py`의 output_contract(max_evidence_ids_per_sentence)가 정한다.
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


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


ReportStatus = Literal["ok", "NO_DATA", "TIMEOUT", "INTERNAL_ERROR"]


class AnalysisReportResponse(StrictModel):
    """분석요약 8종의 API 응답 계약 — 2026-08-26 신설.

    사용자 지시: "보고서는 DB에 저장하지 않고 MD 형태로 풍부한 표현력을 가진
    텍스트로 바로 response에 작성", "response에 status(정상/오류코드)", "요청당
    20초 초과 금지". `AnalysisSummaryResponse`(구조화 JSON)는 내부 계산
    결과로는 그대로 두고, 라우터 경계(`routers/_common.py::run_summary`)에서
    이 얇은 겉껍질로 감싼다 — 계산·검증·프롬프트 레이어는 무수정.

    `status`는 한 필드가 성공/실패를 겸한다: 성공 시 `"ok"`, 실패 시 오류
    코드 문자열. 오류 코드 3종: `NO_DATA`(요청에 observations가 없거나
    분석 불가능한 형태 — 이전 `DataSourceError`/422에 대응),
    `TIMEOUT`(20초 초과), `INTERNAL_ERROR`(그 밖의 예외 — 서버 로그에 상세
    기록, 클라이언트에는 코드만). HTTP 상태 코드는 8종 전부 항상 200이고,
    성공/실패 구분은 이 `status` 필드로만 한다(라우터에서 HTTPException을
    던지지 않는다)."""

    status: ReportStatus
    report: str | None = None
