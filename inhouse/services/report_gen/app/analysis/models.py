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
    # 2026-08-28: price_base_metals/minor_metals/iron_energy/other 4종 전용 —
    # PDF §1-1 "가격 변동의 주요 요인" 대응(GeoEventObservation dict 리스트).
    # 선택 필드라 없으면 지금처럼 이 절이 빈다(하위호환).
    geo_events: list[dict] | None = None
    # 2026-08-28 추가조사(`report_gen_price_base_metals_부실요약_원인조사_260828.md`)
    # 확정 — price_base_metals/minor_metals/iron_energy/other 4종 전용. KOMIS
    # 응답의 `dataAvg.stdMap.{WEEK,MONTH,YEAR}`를 그대로 실어 보내면(선택,
    # `PriceKomisPeriodComparisons` dict) 이 계산기가 자체 롤링창 재계산 대신
    # 그 값을 우선 쓴다 — 라이브 재현으로 KOMIS 산식(직전 완결 역주/역월/역년
    # 평균)이 롤링 N일창과 다름을 확정했기 때문(하위호환: 없으면 기존대로
    # 롤링창 계산).
    komis_period_comparisons: dict | None = None
    # 2026-08-29 Phase3 라이브 재검증 확정(`report_gen_KOMIS라이브재검증_
    # Phase3_260829.md`) — page_id="map_korea"/"map_global" 전용.
    # `TradeKomisTotals` 참고. KOMIS list 응답이 최대 30행까지만 국가/루트를
    # 줘서(map_global 정적덤프 73콤보 중 72건 영향, 최악 69.4% 과소) 관측치
    # 합산이 진짜 총액보다 작을 수 있는데, 있으면 계산기가 이 값을 우선
    # 쓴다(하위호환: 없으면 기존대로 관측치 합산).
    komis_trade_totals: dict | None = None
    # 2026-08-30 신설 — 발주처(KOMIS) 납품 최적화. 호출자가 KOMIS API 응답을
    # 손으로 report_gen 자체 shape(observations 등)으로 매번 옮겨 담아야
    # 했던 부담(그 과정에서 실제로 두 차례 실수 발생 — 0.00 결측값을 그대로
    # 실어보내 최고/최저가가 깨진 사례, 비교광종 페이지 제한을 잘못 안
    # 사례)을 없앤다. 사용자 지시("하위호환 무관 싹다 교체")로 같은 날
    # price_* 4종에서 로그인 불필요한 나머지 5종까지 확장했다 — page_id별로
    # 원본 엔드포인트가 다르니 파서도 page_id별로 다르다
    # (§`summary.py::_parse_komis_*_response`):
    # - price_base_metals/minor_metals/iron_energy/other: `getMnrlPrcByMnrkndUnqCd`
    #   → observations·compare_observations·komis_period_comparisons
    # - map_korea: `getListKoreaData` → observations·komis_trade_totals
    # - map_global: `getListDataNation` → observations·komis_trade_totals
    # - map_mineral: `getListMapMnrlChartData` → observations·unit
    # - indicator_composite: `getLineChartIndx` → observations(시계열 전체,
    #   스냅샷 아님 — Phase4에서 확정)
    # - forecast_price: `getListPricePredc` → observations(realYn→is_actual)
    # 값이 있으면 각 페이지의 기존 손 매핑 필드 대신 이걸 우선 쓴다.
    # mineral(코드)·compare_mineral(코드)·measure·forecast_horizon은 KOMIS
    # 응답 본문에 없는 조회 파라미터라 여전히 호출자가 명시해야 한다.
    komis_response: dict | None = None

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
        # 2026-08-27 price page_id 분리 당시엔 비교광종이 희소금속 전용 KOMIS
        # 기능이라고 보고 price_minor_metals로만 제한했다 — 2026-08-30 사용자
        # 정정 + 라이브 재확인(Playwright로 4개 가격 서브메뉴 전부 접속):
        # `srchCompareMnrkndUnqCd`/`srchComparePrcCrtr` 비교광종 select가
        # base_metals/minor_metals/iron_energy/other 4개 페이지 전부 동일하게
        # 존재한다 — KOMIS 광물자원가격 메뉴 공통 기능이었다. map_korea/
        # map_global(수급지도)엔 이 기능이 없어 그대로 제외한다.
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
            and self.page_id
            not in ("price_base_metals", "price_minor_metals", "price_iron_energy", "price_other")
        ):
            raise ValueError(
                "compare_* fields are only accepted for price_* pages "
                "(base_metals/minor_metals/iron_energy/other)"
            )
        if self.geo_events is not None and self.page_id not in (
            "price_base_metals", "price_minor_metals", "price_iron_energy", "price_other",
        ):
            raise ValueError("geo_events is only accepted for price_* pages")
        if self.komis_period_comparisons is not None and self.page_id not in (
            "price_base_metals", "price_minor_metals", "price_iron_energy", "price_other",
        ):
            raise ValueError("komis_period_comparisons is only accepted for price_* pages")
        if self.komis_trade_totals is not None and self.page_id not in ("map_korea", "map_global"):
            raise ValueError("komis_trade_totals is only accepted for page_id=map_korea/map_global")
        if self.komis_response is not None and self.page_id not in (
            "price_base_metals", "price_minor_metals", "price_iron_energy", "price_other",
            "map_korea", "map_global", "map_mineral", "indicator_composite", "forecast_price",
        ):
            # 2026-08-30 price_* 4종에서 신설, 같은 날 main-agent 지시로
            # 로그인 불필요한 나머지 5종(map_korea/global/mineral,
            # indicator_composite, forecast_price)까지 확장 — indicator_market/
            # indicator_supply는 로그인 필요라 이번 재검증 범위 밖(세션 시작
            # 스코핑 그대로), price_group은 KOMIS 직접 대응 엔드포인트가
            # 없는 report_gen 자체 집계 페이지라 제외.
            raise ValueError("komis_response is not accepted for this page_id")

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
            # 2026-08-31 예외 — `getListPricePredc` 응답의 `crtrPrd`
            # 자체가 분기("28년 4Q")·연("2028년") 형식으로 medium/long을
            # 이미 구분해 담고 있어(§`validate_period`의 아래 "-Q" 검사가
            # 바로 그 사실에 의존한다), komis_response가 있으면
            # forecast_horizon을 안 받아도 `summary.py::
            # _analyze_price_forecast`가 파싱된 기간 형식에서 자동
            # 판별한다. komis_response도 없으면(손 매핑 경로) 형식을 알
            # 방법이 없어 그대로 필수다.
            if self.forecast_horizon is None and self.komis_response is None:
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
            #
            # 2026-08-31 예외 — map_korea/map_global은 komis_response
            # (`getListKoreaData`/`getListDataNation` 원본)가 조회 파라미터
            # `srchMnrkndUnqCd`를 그대로 되돌려줘서 mineral을 거기서 자동
            # 채울 수 있다(`summary.py::_trade_series_from_request`).
            # price_* 4종은 KOMIS 응답 본문에 광종 코드가 없어(한글명만
            # 있음) 이 예외를 안 받는다 — mineral 없이 komis_response만
            # 오면 여전히 거부한다.
            mineral_derivable_from_response = (
                self.page_id in ("map_korea", "map_global") and self.komis_response is not None
            )
            if self.mineral is None and not mineral_derivable_from_response:
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
    is_actual: bool | None = None
    # 2026-08-29 Phase4 라이브재검증 확정(`report_gen_KOMIS라이브재검증_
    # Phase4_260829.md`) — KOMIS 원본 `realYn` 대응. True=확정 실적,
    # False=예측치, None=정보 없음(하위호환, 필드 자체를 안 보내면 계산
    # 영향 없음). `getListPricePredc`가 실측·예측 분기를 한 응답에 섞어
    # 주므로 계산기가 True(확정 실적)인 관측치는 예측 요약에서 제외한다.


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


class GeoEventObservation(StrictModel):
    """`page_id="price_base_metals"/"price_minor_metals"/"price_iron_energy"/
    "price_other"` 전용(2026-08-28 신설, PDF §1-1 "가격 변동의 주요 요인" 대응) —
    지정학 위기지수 파이프라인의 `geo_event`(postgres `mineral_risk.geo_event`)에서
    가격 조회기간과 겹치는 행을 호출자가 그대로 실어 보낸다(report_gen은 DB를
    안 읽으므로 이 서버가 직접 조회하지 않는다).

    `direction`은 `geo_event` 실제 데이터 확인 결과 7개 값의 깨끗한 통제 어휘라
    (`komir_summary.py::_DIRECTION_LABELS` 참고) 안전하게 라벨링할 수 있지만,
    `event_type`은 같은 확인에서 268종+ 자유서술(영어/한국어 혼재, 대소문자·
    구두점 불일치)로 나와 이번 필드에는 포함하지 않았다(2026-08-28 데이터 품질
    확인, `report_gen_구조개선_작업기록_260828_보강.md` 참고)."""

    obs_date: Day
    country: str = Field(min_length=1)
    direction: Literal[
        "supply_down", "supply_up", "price_down", "price_up", "demand_down", "demand_up", "neutral",
    ]
    severity: float
    evidence_quote: str | None = None


class PriceKomisPeriodAverage(StrictModel):
    """`dataAvg.stdMap.{WEEK,MONTH,YEAR}` 1개 항목 패스스루(2026-08-28 신설,
    `report_gen_price_base_metals_부실요약_원인조사_260828.md` 참고) — KOMIS가
    서버에서 미리 계산한 기간평균과 그 대비 등락률. `change_pct`는 KOMIS
    원본 `flctnPrcnt`와 같은 스케일(예: 0.98은 +0.98%, 퍼센트 값 그대로이지
    분수가 아니다)로 호출자가 그대로 옮겨 보낸다."""

    average_price: float
    change_pct: float


class PriceKomisPeriodComparisons(StrictModel):
    """`page_id="price_base_metals"/"price_minor_metals"/"price_iron_energy"/
    "price_other"` 전용(2026-08-28 신설) — 라이브 재현으로 KOMIS의 전주/전월/
    전년평균이 이 계산기의 롤링 N일창(`komir_summary.py::_avg_before`)과 다른
    산식(직전 완결 역주/역월/역년 전체 평균)임을 확정한 뒤 도입했다. `DAY`는
    패스스루 대상에서 뺐다 — 이 계산기가 인접 관측치로 직접 계산한 day_over_day
    값이 이미 KOMIS와 일치함을 라이브 재현으로 확인했기 때문이다(재계산할
    필요 없는 값은 옮기지 않는다)."""

    week: PriceKomisPeriodAverage | None = None
    month: PriceKomisPeriodAverage | None = None
    year: PriceKomisPeriodAverage | None = None


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


class TradeKomisTotals(StrictModel):
    """`page_id="map_korea"/"map_global"` 전용(2026-08-29 신설,
    `report_gen_KOMIS라이브재검증_Phase3_260829.md` 참고) — KOMIS 응답의
    `sumIncmAmt`/`sumExpAmt`/`sumIncmWeig`/`sumExpWeig`(map_korea)·`sumAmt`/
    `sumWeig`(map_global) 패스스루. `list` 엔드포인트가 최대 30행까지만
    국가/루트를 주는데(관측상 한계, map_global은 정적 덤프 73콤보 중 72건이
    영향받음, 최악 69.4% 과소) 같은 응답에 KOMIS가 이미 계산한 진짜 총액이
    함께 온다 — 있으면 계산기가 관측치 합산 대신 이 값을 총액으로 쓴다.
    필드명은 `TradeCountryObservation`과 맞춰 direction별로 나눴다(map_global은
    사실상 `import_*`만 채워진다 — KOMIS map_global이 수입 방향만 제공)."""

    import_amount: float | None = None
    import_weight: float | None = None
    export_amount: float | None = None
    export_weight: float | None = None


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

    # 2026-08-31 안전장치 — `min_length=1`은 공백 1글자(" ")도 통과시킨다.
    # 이 세션에서 실제 라이브 LLM 호출 중 "## 핵심 진단" 절이 헤더만 있고 본문이
    # 안 보이는 사례를 2회 관측했다(재현율 낮음 — 이후 12회 재시도로도 재현
    # 실패, 원인 확정은 못 함). `_validate_llm_summary`는 섹션별 문장 "개수"만
    # 검사해 공백 문자열 sentence가 있어도 통과시킬 수 있다는 구조적 허점을
    # 발견해 막는다 — 확정된 근본원인은 아니지만 이 경로를 막아도 유효한
    # 출력을 해칠 일은 없다(공백만 있는 분석문은 어차피 무의미하다).
    @field_validator("text")
    @classmethod
    def strip_and_require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank/whitespace-only")
        return stripped


class SummaryNarrative(StrictModel):
    """3개 섹션으로 묶인 근거 연결 분석문."""

    core_diagnosis: list[SummarySentence] = Field(min_length=1, max_length=2)
    # major_changes의 max_length=5를 바꾸면 `komir_summary.py::calculate_price_
    # summary`의 `_MAJOR_CHANGES_HARD_CAP`(규칙기반 폴백 경로가 근거 1개=문장
    # 1개로 그대로 매핑해 이 상한을 직접 참조·복제한다, 2026-08-28)도 같이
    # 바꿔야 한다 — 한쪽만 바뀌면 관측치가 조밀한 요청에서 `ValidationError`로
    # 죽는다(실측 재현됨).
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
