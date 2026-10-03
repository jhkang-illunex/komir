# -*- coding: utf-8 -*-
"""RAG action/slot 계약.

질문의 문구를 도구 선택 규칙으로 해석하지 않는다. LLM은 이 모듈의 엄격한
``ActionPlan``만 만들고, 이 모듈은 카탈로그·필수 슬롯·허용 조합을 결정적으로
검사한다. 어댑터는 검증된 action만 ``RetrievalRoute``로 바꾼다.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


ActionId = Literal[
    "price.series", "price.compare", "price.verify_claim", "price.overview", "price.volatility_rank",
    "inventory.latest", "inventory.series",
    "trade.country_rank", "trade.price_cross_rank", "trade.monthly", "trade.concentration", "trade.hs_summary", "trade.indicator",
    "resource.rank", "resource.price_cross_rank", "resource.yoy", "mine.rank", "mine.profile", "indicator.series", "document.retrieve", "document.lookup", "document.facts.retrieve", "menu.navigate", "dataset.navigate",
    "diagnosis.rank", "diagnosis.series", "forecast.demand", "forecast.price", "forecast.quantity",
    "geopolitics.index", "geopolitics.articles", "stockpile.status", "stockpile.methodology", "scenario.assess", "synthesis.brief",
    "off_topic",
]

# KOMIS 종합지수 계열 코드와 사용자 표시명. 각 요청은 한 계열만 조회한다.
COMPOSITE_INDEX_VARIANTS: dict[str, tuple[str, str]] = {
    "composite": ("HI001", "광물종합지수"),
    "major_metals": ("HI002", "메이저금속지수"),
    "minor_metals": ("HI003", "희소금속지수"),
}


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["trailing_months", "calendar_year", "range", "latest", "future_horizon"]
    trailing_months: int | None = Field(default=None, ge=1, le=240)
    calendar_year: int | None = Field(default=None, ge=1900, le=2200)
    start: str | None = None
    end: str | None = None
    future_horizon: int | None = Field(default=None, ge=1, le=120)
    frequency: Literal["daily", "weekly", "monthly", "yearly"] | None = None
    explicit: bool = False


class ForecastCapabilityInput(BaseModel):
    """Typed input accepted by the existing ``forecast.price`` executor."""
    model_config = ConfigDict(extra="forbid")
    mineral: str = Field(min_length=1)
    metric: Literal["price_forecast"] = "price_forecast"
    period: Period
    operation: Literal["next_month_value", "direction", "timeline", "compare_current"] = "timeline"

    @model_validator(mode="after")
    def validate_forecast_period(self):
        if self.period.kind != "future_horizon":
            raise ValueError("forecast period must be future_horizon")
        if not self.period.future_horizon:
            raise ValueError("forecast future_horizon is required")
        if self.operation == "next_month_value" and self.period.future_horizon != 1:
            raise ValueError("next_month_value requires future_horizon=1")
        return self


class IndicatorSeriesInput(BaseModel):
    """Typed input/output selector for the existing ``indicator.series`` action."""
    model_config = ConfigDict(extra="forbid")
    indicator: Literal["supply_stability", "market_outlook", "composite_index"]
    period: Period | None = None
    variant: Literal["composite", "major_metals", "minor_metals"] | None = None
    operation: Literal["latest_delta", "period_change", "period_extrema"] | None = None

    @model_validator(mode="after")
    def validate_indicator_contract(self):
        if self.indicator == "composite_index":
            if self.variant is None and self.operation is not None:
                raise ValueError("composite indicator variant is required for an operation")
            if self.operation == "latest_delta" and (self.period is None or self.period.kind != "latest"):
                raise ValueError("latest_delta requires latest period")
            if self.operation == "period_change" and (
                self.period is None or self.period.kind not in {"trailing_months", "range"}
            ):
                raise ValueError("period_change requires trailing_months or range period")
            if self.operation == "period_extrema" and (
                self.period is None or self.period.kind != "calendar_year"
            ):
                raise ValueError("period_extrema requires calendar_year period")
        return self


class IndicatorSeriesRow(BaseModel):
    """Canonical row exposed by ``indicator.series`` to downstream projection."""
    model_config = ConfigDict(extra="allow")
    indicator: str = Field(min_length=1)
    value: float
    date: str
    unit: str | None = None


class ActionSlots(BaseModel):
    """카탈로그 action이 공통으로 쓰는 정규화 슬롯; 미정값은 null이다."""
    model_config = ConfigDict(extra="forbid")
    mineral: str | None = None
    minerals: list[str] | None = None
    hs_code: str | None = None
    metric: Literal["production", "reserves", "import_amount", "import_weight", "export_amount", "export_weight"] | None = None
    flow: Literal["import", "export"] | None = None
    trade_metric: Literal["tsi", "rca", "tii", "trade_growth", "country_dependency"] | None = None
    reporter_country: str | None = None
    partner_country: str | None = None
    period: Period | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    reference_year: int | None = Field(default=None, ge=1900, le=2200)
    indicator: Literal["supply_stability", "market_outlook", "composite_index"] | None = None
    # 종합지수의 HI001(종합)·HI002(메이저)·HI003(희소금속)을 한 시계열로 섞지 않는다.
    indicator_variant: Literal["composite", "major_metals", "minor_metals"] | None = None
    indicator_operation: Literal["latest_delta", "period_change", "period_extrema"] | None = None
    forecast_operation: Literal["next_month_value", "direction", "timeline", "compare_current"] | None = None
    topic: str | None = None
    target_page: str | None = None
    claimed_change_pct: float | None = None
    comparator: Literal["greater_than", "less_than", "equals"] | None = None
    price_basis: str | None = None
    # DB-backed price criterion serial.  This is a typed source identifier,
    # not an intent selector; lowering passes it to the existing raw lookup.
    price_criterion_serial: int | None = Field(default=None, ge=1)
    # Price criterion cardinality: default representative, one explicit
    # criterion, or every valid mapped criterion for one mineral.
    criterion_mode: Literal["REPRESENTATIVE", "EXPLICIT", "ALL"] = "REPRESENTATIVE"
    currency: str | None = None
    weight_unit: str | None = None
    # 단일 가격 시계열에서 renderer가 수행할 결정적 집계 의미다. 값이 없으면
    # 기존 최신값·시계열 요약 계약을 그대로 사용한다.
    price_operation: Literal[
        "period_average_delta", "monthly_streak", "yearly_average",
        "year_over_year", "period_extrema", "significant_daily_rise",
    ] | None = None
    # price.series 전년 동월 비교의 월별 집계 기준. 미지정 시 월평균을 쓴다.
    price_yoy_basis: Literal["monthly_average", "monthly_latest"] | None = None
    # Semantic selection operators are optional refinements over an existing
    # Action.  They do not introduce a new physical action id.
    selection_mode: Literal["extremum", "rank", "ordinal"] | None = None
    selection_direction: Literal["min", "max"] | None = None
    selection_position: int | None = Field(default=None, ge=1, le=100)
    selection_limit: int | None = Field(default=None, ge=1, le=100)
    significant_change_pct: float | None = Field(default=None, gt=0, le=100)
    windows: list[int] | None = None
    comparison_operation: Literal["mean_threshold"] | None = None
    comparison_comparator: Literal["greater_than", "less_than"] | None = None
    bound_date: str | None = None
    strategic_price_groups: list[Literal["strategic_six", "strategic_ten", "battery_five"]] | None = None
    country_scope: str | None = None
    # resource.rank의 결과에 적용하는 범용 typed operation. 물리 Action은
    # 그대로 유지하고, 국가 필터·집계·projection 의미만 보존한다.
    resource_operation: Literal[
        "level", "first", "latest", "average", "sum", "count", "min", "max", "country_value"
    ] | None = None
    resource_country: str | None = None
    resource_population: Literal["all"] | None = None

    @model_validator(mode="after")
    def validate_resource_population(self):
        if self.resource_population == "all" and self.top_n is not None:
            raise ValueError("resource_population_conflict: all and explicit top_n")
        return self

    trade_scope: Literal["korea", "global"] | None = None
    # 특정국 의존도는 같은 광종·방향·기간의 전체 상대국 합계만 분모로 쓴다.
    # 한국 전체 품목·세계 전체 무역 같은 다른 모집단은 별도 원천 검증 없이는
    # 이 슬롯으로 열지 않는다.
    denominator_scope: Literal["reporter_product_trade"] | None = None
    mine_metric: Literal["production", "reserves"] | None = None
    mine_order: Literal["level", "increase", "yoy_increase", "yoy_decrease"] | None = None
    mine_name: str | None = None
    dataset: Literal["supply_stability", "market_outlook"] | None = None
    requested_outputs: set[Literal["text", "table", "chart", "menu", "raw_data"]] = {"text"}

IntentId = Literal["price_series", "price_compare", "price_claim", "trade_rank", "trade_price_cross_rank", "trade_monthly", "trade_hs", "trade_concentration", "trade_indicator", "resource_rank", "resource_price_cross_rank", "resource_yoy", "mine_rank", "mine_profile", "inventory_latest", "inventory_series", "indicator", "document", "document_facts", "okf_lookup", "concept", "stockpile_methodology", "menu", "dataset", "diagnosis", "forecast_demand", "forecast_price", "forecast_quantity", "geopolitics_index", "geopolitics_articles", "off_topic"]
INTENT_TO_ACTION = {"price_series":"price.series", "price_compare":"price.compare", "price_claim":"price.verify_claim", "trade_rank":"trade.country_rank", "trade_price_cross_rank":"trade.price_cross_rank", "trade_monthly":"trade.monthly", "trade_hs":"trade.hs_summary", "trade_concentration":"trade.concentration", "trade_indicator":"trade.indicator", "resource_rank":"resource.rank", "resource_price_cross_rank":"resource.price_cross_rank", "resource_yoy":"resource.yoy", "mine_rank":"mine.rank", "mine_profile":"mine.profile", "inventory_latest":"inventory.latest", "inventory_series":"inventory.series", "indicator":"indicator.series", "document":"document.retrieve", "document_facts":"document.facts.retrieve", "okf_lookup":"document.lookup", "concept":"document.retrieve", "stockpile_methodology":"stockpile.methodology", "menu":"menu.navigate", "dataset":"dataset.navigate", "diagnosis":"diagnosis.rank", "forecast_demand":"forecast.demand", "forecast_price":"forecast.price", "forecast_quantity":"forecast.quantity", "geopolitics_index":"geopolitics.index", "geopolitics_articles":"geopolitics.articles", "off_topic":"off_topic"}

class IntentCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str = Field(min_length=1)
    intent: IntentId
    slots: ActionSlots
    # ``metadata``는 같은 데이터 요구의 표기·기준일·단위 요구다. ``content``는
    # 독립적으로 출처를 찾아야 하는 정보요구라 mapper가 삭제할 수 없다.
    # 이전 저장 계획과의 호환을 위해 role이 빠진 concept만 metadata로 해석한다.
    # document는 독립 내용으로 보수적으로 content를 기본값으로 둔다.
    role: Literal["data", "metadata", "content"] | None = None

    @model_validator(mode="after")
    def resolve_legacy_role(self) -> "IntentCall":
        if self.role is None:
            self.role = "metadata" if self.intent == "concept" else "content"
        return self

class IntentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirements: list[IntentCall] = Field(min_length=1)


class InputBinding(BaseModel):
    """선행 typed 결과를 후속 Action 슬롯에 materialize하는 계약."""
    model_config = ConfigDict(extra="forbid")
    source_requirement_id: str = Field(min_length=1, max_length=80)
    source_field: Literal["country", "country_code", "share_pct", "date", "mineral"]
    selector: Literal["argmax", "argmin"]
    target_slot: Literal["reporter_country", "partner_country", "bound_date", "mineral"]


class ActionCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str = Field(min_length=1, max_length=80)
    action_id: ActionId
    slots: ActionSlots
    # mapper가 보존하는 closed intent/role. 레거시 직접 ActionPlan은 None으로
    # 두어 기존 API 입력을 깨지 않는다.
    intent: IntentId | None = None
    role: Literal["data", "metadata", "content"] | None = None
    depends_on: list[str] = []
    input_bindings: list[InputBinding] = []
    requested_outputs: set[Literal["text", "table", "chart", "menu", "raw_data"]] = {"text"}


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str | None = None
    history_refs: list[str] = []
    complete: bool = True
    predecessor_source_unavailable: bool = False
    actions: list[ActionCall] = Field(min_length=1)
    # Internal semantic snapshot for the AAST coverage boundary.  It is not
    # serialized into the public ActionPlan contract and never selects an
    # action; it preserves the already parsed WHAT for deterministic audit.
    _semantic_requirements: list[dict[str, Any]] | None = PrivateAttr(default=None)
    _semantic_resolution_error: str | None = PrivateAttr(default=None)


class PlanAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    failure_reason: str | None = None
    plan: ActionPlan | None = None


AVAILABLE = frozenset({
    "price.series", "price.compare", "price.verify_claim", "price.overview", "price.volatility_rank", "trade.country_rank", "trade.price_cross_rank", "trade.monthly",
    "inventory.latest", "inventory.series",
    "trade.concentration", "trade.hs_summary", "trade.indicator", "resource.rank", "resource.price_cross_rank", "resource.yoy", "mine.rank", "mine.profile", "indicator.series", "document.retrieve", "document.lookup", "document.facts.retrieve", "stockpile.methodology", "menu.navigate", "dataset.navigate",
    "forecast.price",
})
# 독립 근거를 요구하는 수치·문서 action은 requirement_id별로 실행하고
# 최종 생성 단계에서 묶을 수 있다. 메뉴 이동은 별도 page-recommend 경로가
# 소유하므로 데이터 action과 섞지 않는다.
COMPOSABLE_MULTI_ACTIONS = frozenset({
    "price.series", "price.compare", "price.verify_claim", "price.overview", "price.volatility_rank",
    "inventory.latest", "inventory.series",
    "trade.country_rank", "trade.monthly", "trade.concentration", "trade.hs_summary", "trade.indicator",
    "resource.rank", "resource.yoy", "mine.rank", "mine.profile", "indicator.series",
    "document.retrieve", "document.lookup", "stockpile.methodology",
})
OFF_TOPIC = "off_topic"
MINERAL_ALIASES = {"nickel": "니켈", "cobalt": "코발트", "copper": "구리", "lithium": "리튬", "rare earth": "희토류"}
# Deterministic price shortcuts must only claim a token that is a complete
# known mineral name.  Otherwise suffixes such as ``최신`` or a written date
# can be swallowed into the mineral slot (e.g. ``리튬최신`` or
# ``2027년7월리튬``), preventing the semantic parser from seeing the query.
_LEGACY_PRICE_MINERALS = frozenset({
    "리튬", "니켈", "코발트", "구리", "동", "망간", "흑연", "텅스텐", "희토류", "네오디뮴",
    "아연", "몰리브덴", "알루미늄", "철광석", "유연탄", "우라늄", "금", "은", "백금", "주석", "연",
})
UNAVAILABLE = frozenset({
    "diagnosis.rank", "diagnosis.series", "forecast.demand", "forecast.quantity",
    "geopolitics.index", "geopolitics.articles", "stockpile.status",
})
# ``금일``은 화면의 현재 일자를 뜻하는 듯 보이지만, 가격 원천의 적재 지연을
# 고려하면 사용자 의도는 보통 "가장 최근에 보유한 관측값"이다. 날짜 하나로
# 좁히지 않고 latest action으로 처리한다.
CURRENT_PERIOD_ENDS = frozenset({"latest", "current", "now", "현재", "오늘", "금일", "금일자"})
REQUIRED: dict[str, tuple[str, ...]] = {
    "price.series": ("mineral",), "price.compare": ("minerals",), "price.verify_claim": ("mineral", "claimed_change_pct"), "price.volatility_rank": (),
    "inventory.latest": ("mineral",), "inventory.series": ("mineral", "period"),
    "price.overview": ("strategic_price_groups",),
    "trade.country_rank": ("mineral", "metric"), "trade.price_cross_rank": ("partner_country", "metric"), "trade.monthly": (), "trade.concentration": ("mineral",), "trade.indicator": ("trade_metric",),
    "trade.hs_summary": ("hs_code",), "resource.rank": ("mineral", "metric"), "resource.price_cross_rank": ("metric",), "resource.yoy": ("mineral",),
    "mine.rank": ("mine_metric", "mine_order"), "mine.profile": ("mine_name",),
    "indicator.series": ("indicator",), "document.retrieve": ("topic",), "document.lookup": ("topic",), "document.facts.retrieve": ("topic",), "stockpile.methodology": (),
    "forecast.price": ("mineral",),
    "menu.navigate": ("target_page",), "dataset.navigate": ("dataset",),
}
# 검증 완료된 수치 조합만 연다. 문서+수치/미연결 조합은 전체 기권이다.
ALLOWED_MULTI = frozenset({
    frozenset({"resource.rank"}), frozenset({"resource.yoy"}), frozenset({"mine.rank"}), frozenset({"price.compare"}), frozenset({"price.verify_claim"}),
    frozenset({"resource.rank", "trade.country_rank"}), frozenset({"trade.monthly"}),
    frozenset({"trade.concentration"}), frozenset({"inventory.series"}),
    frozenset({"trade.country_rank"}),
    frozenset({"resource.rank", "trade.concentration"}),
    # 복수의 독립 source-first 문서 요구는 각각의 requirement ID와 출처를
    # 보존한 채 실행한다. 같은 개념의 중복 여부를 질문 문자열로 추정하지 않는다.
    frozenset({"document.retrieve"}),
    frozenset({"document.facts.retrieve"}),
    # 복합 출력 계약의 현재 연결된 데이터 조합. 각 Action은 독립 근거를
    # 유지하며 최종 형식은 answer_contracts.py/AnswerComposer가 안내한다.
    frozenset({"price.series", "indicator.series"}),
    frozenset({"price.series", "trade.country_rank"}),
    frozenset({"price.series", "resource.yoy"}),
    frozenset({"price.series", "resource.rank"}),
    frozenset({"price.series", "document.retrieve"}),
    frozenset({"price.series", "forecast.price"}),
    frozenset({"document.retrieve", "trade.concentration", "forecast.price"}),
    # A numeric price-claim verification and a source-first cause lookup are
    # separate, independently executable requirements for questions such as
    # "2025년에 정확히 300% 올랐는데 원인이 뭐야".
    frozenset({"price.verify_claim", "document.retrieve"}),
    frozenset({"forecast.price", "document.retrieve"}),
    frozenset({"trade.country_rank", "forecast.price"}),
    frozenset({"price.series", "forecast.price", "resource.rank", "trade.country_rank"}),
    frozenset({"price.series", "resource.rank", "trade.concentration", "document.retrieve"}),
    frozenset({"price.volatility_rank", "document.retrieve"}),
    frozenset({"document.retrieve", "trade.country_rank"}),
    frozenset({"document.retrieve", "resource.rank"}),
    # 수출통제 기사에서 실제 언급된 광종을 읽은 뒤, 한국의 특정국 수입의존도를
    # 별도 Action으로 계산하는 폐쇄형 후속 경로다.
    frozenset({"document.retrieve", "trade.indicator"}),
})


ACTION_PLAN_PROMPT = """질문을 action 카탈로그의 ActionPlan JSON으로만 변환한다.
action_id는 price.series, price.compare, price.verify_claim, price.overview, trade.country_rank, trade.price_cross_rank, trade.monthly,
trade.concentration, trade.hs_summary, trade.indicator, resource.rank, resource.price_cross_rank, resource.yoy, mine.rank, mine.profile, indicator.series, document.retrieve, document.lookup, document.facts.retrieve,
menu.navigate, dataset.navigate, diagnosis.rank, diagnosis.series, forecast.demand, forecast.price,
forecast.quantity, geopolitics.index, geopolitics.articles, stockpile.status, stockpile.methodology, scenario.assess,
synthesis.brief 중 하나다. 원문과 확인된 대화에 있는 값만 slots에 넣고 추측하지 않는다.
범위 밖 일반 주제에는 actions=[] 대신 action_id=off_topic 한 개를 사용한다.
질문의 핵심 의도는 요청 어미와 관계없이 판단한다. "해", "해줘", "해줘요", "해주세요",
"보여줘", "표시해 줘" 같은 말끝·공손 표현·띄어쓰기 차이는 같은 intent/Action이다.
이번주 자원뉴스 요약은 document.retrieve이며 광물명 미포함을 이유로 off_topic으로 분류하지 않는다.
실제 주간 날짜 경계는 시스템 코드가 확정한다.
수급위기 진단/예측/지정학 지수·기사에는 해당 unavailable action을 사용한다.
생산국과 수입국의 집중도·비중 비교는 resource.rank와 trade.country_rank의 검증된 조합이며,
'취약점'이라는 단어만으로 diagnosis action을 선택하지 않는다. 명시 HS 코드의 품목 요약과
수입 현황은 trade.hs_summary 하나로 표현한다. metric이 생략된 country rank는 공개 기본 표시
기준을 슬롯에 명시한다. 기간이 없는 한국 수입·수출 상위국 질의는 최근 12개월을
기본 기간으로 사용한다. "국가별 비중/점유율"을 포함한 "수입 상위국" 질의도
trade.country_rank이며 특정국 의존도나 TSI·HHI 요청과 구분한다. 메뉴 action은
등록된 page_id/alias 또는 dataset ID(supply_stability, market_outlook)만 사용한다. 범위 밖 일반
주제에는 menu action을 만들지 말고 complete=false로 둔다.
수입액·수입중량·수출액·수출중량의 월별 추이는 trade.monthly이며 price action이 아니다.
무역특화지수(TSI), 현시비교우위(RCA), 무역결합도(TII), 수출입증감률, 특정국 의존도는
trade.indicator다. trade_metric은 tsi/rca/tii/trade_growth/country_dependency 중 하나이며,
기준국은 reporter_country, 상대국은 partner_country에 넣는다. 특정국 의존도는
denominator_scope=reporter_product_trade로 같은 기준국·광종·수출입 방향·조회 기간의 전체 상대국 합계를
분모로 사용한다. 기간이 없으면 한국 기준 최근 12개월을 기본으로 쓴다.
개별 광산의 생산량·매장량 순위, 국가 안의 광산 1위, 기간 내 생산량 증가 순위는
mine.rank다. 국가별 자원 순위 resource.rank와 구분한다. mine_metric은
production/reserves, mine_order는 level/increase/yoy_increase/yoy_decrease다.
세계 총계 광종 생산량의 전년 대비·증감률은 resource.yoy다. mineral은 필수, metric=production,
country_scope=world로 두며, 사용자가 연도를 직접 말하면 period.calendar_year에 넣고 아니면 최신
시스템 데이터 연도와 직전 연도를 쓴다. 국가별·광산별 순위의 YoY는 mine.rank다. 전년 대비(YoY) 증감은 연속된 두 관측 연도만 비교하는 yoy_increase/yoy_decrease로
표현한다. 증가·감소 방향과 지표(생산량·매장량)를 질문대로 보존한다.
산출량은 생산량(production)의 동의어다. 국가 필터는 country_scope,
상위 개수는 top_n, 최근 N년은 period.trailing_months=12*N으로 둔다.
비축 실측을 요청하면서 자료 부재 시 입력값·계산식 설명을 명시적으로 허용한 요구는
stockpile.methodology다. 이 action은 실재고를 조회하거나 추정하지 않고 계산 정의만 제공한다.
문서명·원문·특정 절의 직접 확인은 document.lookup이며 topic에 찾을 문서·절·사실을 보존한다.
한 광산의 위치·소유자·개별 사실은 mine.profile이며 mine_name에 질문의 광산명을 넣는다.
가격예측 수치 자체를 요청하는 "다음 달 구리 가격 전망"과 "니켈 가격 앞으로 오를까 내릴까"는
각각 intent=forecast_price, action_id=forecast.price로 정규화한다. 예측 월·기간은
slots.period.kind=future_horizon과 future_horizon(다음 달=1)으로 보존하고, 광종은
slots.mineral에 넣는다. 가격예측은 KO_MNRL_PRC_PREDC 정규화 adapter를 통해 조회하며,
원천에 해당 광종·기간 행이 없을 때만 source_unavailable로 종료한다. price.series/price.compare로
대체하지 않는다.
광물종합지수의 현재값·전일 변동(예: "오늘 광물종합지수 얼마야?")과 최근 N개월
추세(예: "최근 3개월 광물종합지수 추세")는 intent=indicator, action_id=indicator.series,
slots.indicator=composite_index로 정규화한다. 기간이 없으면 최신값, "최근 N개월"은
trailing_months=N으로 보존하며 price action으로 대체하지 않는다.
한국·세계 수입/수출 상위국과 점유율은 trade_rank/country_rank, CR3·CR5·집중도는
trade_concentration, 생산량·매장량 국가순위는 resource_rank/resource.rank로 보존한다.
특정 국가의 한국 수입 비중이 높은 광종 중 가격이 상승한 광종을 찾는 교차 질문은
trade.price_cross_rank 하나로 표현한다. partner_country는 필수, metric은
import_amount(기본) 또는 import_weight, period는 가격과 수입에 공통 적용할 기간이다.
생산 1위국 비중이 높은 광종들의 가격 변동은 resource.price_cross_rank 하나로 표현한다.
metric=production, 생산 기준연도가 명시되면 reference_year에, 가격 기간은 period에 둔다.
월간동향·일일자원뉴스·주간자원뉴스·수출통제 뉴스의 제목·요약·최신 게시물 검색은
document 또는 document.retrieve로 분류하고 가격·무역 수치 action으로 바꾸지 않는다.
보고서 검색에서 "2025년", "최근 3개월", "지난달", "2025년 5월"처럼 기간이 지정되면
document.retrieve의 period에 보존한다. 기간 안에 발행일이 확인되는 보고서를 검색하고,
제목뿐 아니라 실제 문서 본문 발췌도 결과로 포함한다.
여러 기간 창의 가격 변화를 비교하면 price.compare 하나에 slots.windows=[3,6,12]처럼 모든
개월 창을 넣고 period에는 임의의 단일 창을 넣지 않는다.
선택한 여러 광물의 가격 YoY를 평균과 비교하는 질문은 price.compare 하나로 표현한다.
광물 목록은 slots.minerals에, 평균 기준 비교는 slots.comparison_operation=mean_threshold,
방향은 slots.comparison_comparator=greater_than 또는 less_than에 보존한다.
광종을 여러 개 언급한 인과·시나리오·영향 설명은 가격·가격변화·가격비교를 명시하지 않는 한
price.compare로 만들지 말고, 해당 설명의 출처를 찾는 document 또는 concept으로 둔다.
기간은 Period(kind, explicit, 필요한 값)으로 정규화한다. 가격 질의의 "오늘"·"현재"·"지금"·"금일"·"금일자"는
특정 일자 필터가 아니라 최신 보유 관측값을 뜻하므로 period=latest(또는 period 생략)로 두고,
시스템의 오늘 날짜를 range end로 넣지 않는다. 사용자가 일별·주별·월별·연도별 집계를
명시하면 period.frequency에 daily/weekly/monthly/yearly로 기록한다. 단순히 "이번 달" 또는
"월간동향"이라고 한 것은 집계주기 요청이 아니다. 가격의 전년 동월 대비 변화율은
intent=price_series, slots.price_operation=year_over_year,
slots.price_yoy_basis=monthly_average로 두고 period.trailing_months=13을 사용한다.
"월 최신 관측값"·"월말 기준"을 명시하면 price_yoy_basis=monthly_latest로 둔다.
후속 Action이 선행 결과에서 국가를 받아야 하면 depends_on과 input_bindings를 사용한다. 예를 들어
수입 집중도에서 비중이 가장 높은 국가를 골라 그 국가의 수출을 조회하는 경우 선행
trade.concentration을 실행하고, 후속 trade.country_rank의 metric=export_amount,
trade_scope=korea 또는 global을 질문 의미대로 보존한다. 선행 결과의 country를
selector=argmax, source_field=country로 선택하고, 수출국을 조회하는 후속 Action이면
target_slot=reporter_country, 특정 상대국을 조회하는 후속 Action이면
target_slot=partner_country로 명시한다. 국가 슬롯을 임의 기본값으로 채우지 않는다.
JSON 외 텍스트를 출력하지 않는다."""

INTENT_PLAN_PROMPT = """질문의 독립 정보요구를 빠짐없이 requirements IntentCall 목록으로 분해한 closed intent JSON을 출력한다.
intent는 price_series, price_compare, price_claim, trade_rank, trade_price_cross_rank, trade_monthly, trade_hs,
trade_concentration, trade_indicator, resource_rank, resource_price_cross_rank, resource_yoy, mine_rank, mine_profile, inventory_latest, inventory_series, indicator, document, document_facts, okf_lookup, concept, stockpile_methodology, menu, dataset, diagnosis, forecast_demand,
forecast_price, forecast_quantity, geopolitics_index, geopolitics_articles, off_topic 중 하나다.
핵심광물 공급망·HHI·수입의존도·가격변동성의 정의와 개념은 concept이며 document.retrieve로
직접 출처를 찾는다. off_topic은 날씨·음식처럼 광물·공급망과 무관한 주제에만 사용한다.
의도는 핵심 내용으로 판단한다. "해", "해줘", "해줘요", "해주세요", "보여줘",
"표시해 줘" 같은 요청 어미·공손 표현·띄어쓰기 차이는 intent를 바꾸지 않는다.
같은 정보요구는 말끝이 달라도 같은 intent와 Action으로 계획한다. "이번주 자원뉴스 요약"은
document content 검색이며 off_topic이 아니다. 이번 주의 실제 일자 경계는 시스템 코드가
확정하므로 topic에 이번 주 조건을 보존하고 날짜를 임의 계산하지 않는다.
기간이 지정된 보고서 검색은 document intent로 분류하고, 연도·최근 N개월·지난달·연월을
slots.period에 보존한다. 보고서 제목만 찾지 말고 발행일이 확인된 문서 본문 내용도 요구한다.
문서명·원문·특정 절을 찾아 사실을 확인하는 요청은 okf_lookup이고, 한 광산의 위치·소유자·개별
사실은 mine_profile이다. 둘 다 topic 또는 mine_name의 식별자를 생략하지 않는다.
비축 실측이 없을 때 필요한 입력값과 계산식을 요청한 경우는 stockpile_methodology다. 이는
실재고·목표재고·소비량 수치 없이 방법론 근거만 인용한다.
KOMIS의 등록 광물지도·가격·지표·원자료 화면으로 이동하려는 요청은 menu 또는 dataset이며
off_topic이 아니다. target_page/dataset은 카탈로그의 등록 ID·별칭 또는 표시명만 사용한다.
각 IntentCall에는 고유 requirement_id, intent, slots, role을 넣는다. role=data는 수치·원자료
조회, role=metadata는 바로 앞 또는 같은 주제 data 요구의 단위·가격기준·기준일·표/차트 형식
요구(독립 도구를 만들지 않음), role=content는 원인·정의·설명처럼 별도 출처가 필요한 내용이다.
``metric``은 한 Action이 조회하는 단일 지표다. 생산량과 매장량처럼 서로 다른
지표를 함께 요구하면 ``metrics`` 배열이나 쉼표 문자열을 만들지 말고, 각각 고유한
requirement_id를 가진 두 개의 role=data IntentCall로 분해한다. 예: resource_rank의
production 1개와 reserves 1개. 각 요구는 독립 원천·인용으로 끝까지 보존한다.
price_claim의 수치 검증과 가격상승 원인은 각각 data와 content로 분리한다. slots에는 질문에
명시된 값만 채운다. 개별 광산의 생산량·매장량 순위와 국가 안의 광산 1위는 mine_rank,
국가별 생산량·매장량 순위는 resource_rank이며 trade_rank는 수출입 금액·중량
국가 순위에만 쓴다. trade_rank가 세계 수출입 순위이면 trade_scope=global,
한국의 수입·수출 상대국 순위이면 trade_scope=korea로 보존한다. 세계 범위를 한국 순위로
대체하지 않는다. 아직 관측되지 않은 월과 실제 관측범위를 구분하는 요구는 forecast가 아니라
trade_monthly data의 기간·관측범위 요구다. forecast는 미래 예측값 자체를 요청한 경우에만 쓴다.
공급망 취약점의 설명은 기존 수치 data를 해석하는 metadata이고, 진단 점수·등급 자체를 요구할 때만
diagnosis를 쓴다. 명시 HS 코드의 품목명·수입 현황·광종 전체와의 범위 구분은 trade_hs 하나의
data와 metadata로 표현하며 HS가 없는 별도 광종 action이나 document를 만들지 않는다. trade_concentration은
수입·수출 국가 집중도(HHI) 자체를 요청할 때만 쓰며, 생산국 비중과 수입국 비중의 비교는 resource_rank와
trade_rank data의 조합이다. 전기차 수요 둔화처럼 여러 광종의 조건부 영향·상관·시나리오를 설명하는
요청은 가격 수치·가격변화·기간별 가격 비교를 명시하지 않는 한 concept 또는 document content 하나 이상으로
표현하며 price_compare data를 추가하지 않는다. 시계열 집계주기가 명시되면 slots.period.frequency에
daily/weekly/monthly/yearly로 기록한다. "이번 달"이나 "월간동향"은 집계주기가 아니다.
월간동향·일일자원뉴스·주간자원뉴스·수출통제 뉴스의 제목·요약·최신 게시물 검색은
document content이며, 전략광종·희소금속을 단일 광종 mineral 슬롯으로 만들지 않는다.
광물종합지수 또는 코발트 등 광종명이 앞에 붙은 광물종합지수 시계열은
intent=indicator, indicator=composite_index로 분류한다. 이를 private market_outlook나
concept 문서 질의로 바꾸지 않는다.
JSON 외 텍스트를 출력하지 않는다."""

def extract_intent_plan(message: str, llm: Any, history: list[dict[str, str]] | None = None) -> IntentPlan:
    try:
        plan = llm.invoke(task="intent_plan", instructions=INTENT_PLAN_PROMPT,
                          payload={"question": message, "history": history or []}, output_model=IntentPlan,
                          max_tokens=900).output
    except Exception:
        # 특정국 의존도는 모델이 HHI를 별도 요구로 과분해하면서 typed
        # validation 전에 실패할 수 있다. 질문에 관계 슬롯이 명시된 경우에만
        # deterministic typed 계획으로 복구하고, 다른 질문은 기존 예외 경로를
        # 유지한다.
        partner = _dependency_partner_from_message(message)
        if not partner or not any(marker in "".join(message.split()) for marker in ("의존도", "의존율")):
            raise
        fallback = trade_indicator_plan_from_question(message)
        call = fallback.actions[0]
        plan = IntentPlan(requirements=[IntentCall(
            requirement_id=call.requirement_id, intent="trade_indicator", role="data", slots=call.slots,
        )])
    return _normalize_mine_intent(plan, message)


def _normalize_mine_intent(plan: IntentPlan, message: str) -> IntentPlan:
    """광산 질문의 명시 기간과 기본 정렬을 보존한다.

    LLM이 '최근 5년'을 임의의 과거 range로 바꾸는 경우가 있어 질문에
    적힌 숫자만 사용한다. 광산 의도로 분류된 요구에만 적용한다.
    """
    recent = re.search(r"최근\s*(\d{1,2})\s*년", message)
    count = re.search(r"(?:top\s*|상위\s*)(\d{1,3})\s*(?:개|곳|위)?", message, re.IGNORECASE)
    for item in plan.requirements:
        if item.intent != "mine_rank":
            continue
        slots = item.slots
        if recent:
            slots.period = Period(kind="trailing_months", trailing_months=int(recent.group(1)) * 12,
                                  explicit=True)
        if count and 1 <= int(count.group(1)) <= 100:
            slots.top_n = int(count.group(1))
        if slots.mine_metric is None:
            if "매장량" in message:
                slots.mine_metric = "reserves"
            elif "생산량" in message or "산출량" in message:
                slots.mine_metric = "production"
        if slots.mine_order is None:
            slots.mine_order = "increase" if "증가" in message else "level"
        if any(token in message.casefold() for token in ("yoy", "전년 대비", "전년대비", "전년보다")):
            if any(token in message for token in ("감소", "축소", "줄어", "하락")):
                slots.mine_order = "yoy_decrease"
            elif any(token in message for token in ("증가", "늘어", "상승")):
                slots.mine_order = "yoy_increase"
    return plan


def repair_intent_plan(
    message: str, llm: Any, failure_reason: str, history: list[dict[str, str]] | None = None,
) -> IntentPlan:
    """검증 실패를 한 번만 되먹여 closed IntentPlan을 다시 채운다.

    자유 ActionPlan을 재생성하지 않는다. action 선택은 계속 mapper의 결정적
    책임이며, 재시도 뒤에도 불가능한 조합은 그대로 fail-closed 한다.
    """
    plan = llm.invoke(
        task="intent_plan_repair",
        instructions=INTENT_PLAN_PROMPT,
        payload={"question": message, "history": history or [],
                 "previous_failure": failure_reason,
                 "instruction": "이전 계획의 typed 검증 실패를 고치되, data·metadata·content 역할과 독립 요구를 다시 확인하십시오."},
        output_model=IntentPlan, max_tokens=900,
    ).output
    return _normalize_mine_intent(plan, message)

def action_plan_from_intent(intent_plan: IntentPlan, message: str = "") -> ActionPlan:
    _canonicalize_dependency_intent_plan(intent_plan, message)
    _normalize_trade_indicator_intents(intent_plan, message)
    actions: list[ActionCall] = []
    seen: dict[tuple[str, str], ActionCall] = {}
    # 명시 문서의 특정 광산 원문을 찾는 요구는 document.lookup 하나가
    # 위치·소유자 같은 profile 사실과 원문 인용을 함께 제공한다. 동일 광산에
    # mine_profile을 별도로 만들면 두 action의 독립 근거를 요구하는 것으로
    # 오해되어 미지원 조합이 된다. 광산명이라는 typed 식별자가 정확히 같은
    # 경우에만 profile 쪽을 흡수한다.
    lookup_mines = {
        item.slots.mine_name.casefold()
        for item in intent_plan.requirements
        if item.intent == "okf_lookup" and item.slots.mine_name
    }
    has_mine_rank = any(item.intent == "mine_rank" for item in intent_plan.requirements)
    # role=metadata는 action을 만들지 않는다. data가 하나라도 있는 턴에서는
    # planner의 출력 순서와 무관하게 그 data 응답 계약에 붙인다. data가 없는
    # 단독 concept만 source-first document로 남긴다.
    has_data = any(item.role == "data" for item in intent_plan.requirements)
    has_population_comparison = {
        item.intent for item in intent_plan.requirements if item.role == "data"
    } >= {"resource_rank", "trade_rank"}
    trade_rank_pairs = {
        (item.slots.mineral, item.slots.flow)
        for item in intent_plan.requirements
        if item.intent == "trade_rank" and item.role == "data"
    }
    explicit_concentration = any(marker in message.casefold() for marker in ("hhi", "집중도", "집중도 지수"))
    # 가격 수치를 요청하지 않은 조건부 영향 설명을 planner가 data+content로
    # 과분해할 수 있다. 기간·창·가격기준도 없는 비교는 관측 요구가 아니므로,
    # 같은 typed 계획 안의 시나리오 설명 source-first 요구에만 흡수한다.
    # 정상적인 현재 가격 비교처럼 별도 문서 설명이 없는 price_compare에는 적용하지
    # 않는다.
    has_conditional_scenario_content = any(
        candidate.intent in {"document", "concept"}
        and candidate.role == "content"
        and _is_conditional_scenario_topic(candidate.slots.topic)
        for candidate in intent_plan.requirements
    )
    deferred_metadata_outputs: set[str] = set()
    for item in intent_plan.requirements:
        # "수급 이슈 보고서"·"최근 동향 보고서"는 특정 파일명이 아니라
        # 주제별 비정형 보고서를 찾는 탐색 요청이다. 날짜·발행문서명처럼 강한
        # 식별자가 없는 이러한 표현을 document.lookup으로 두면 존재하지 않는
        # 단일 제목을 강제해 OKF·PageIndex·벡터 검색 전에 기권한다.
        topic = item.slots.topic or ""
        is_report_search = (
            "보고서" in topic
            and any(marker in topic for marker in ("이슈", "동향", "최근", "관련"))
            and not re.search(r"20\d{2}(?:\s*년|[-._/]?\d{2})", topic)
        )
        if item.intent == "okf_lookup" and is_report_search:
            item.intent = "document"
        # 일반적인 수요·시장 이슈는 문서에 기록된 관측 사실을 찾는 요구다.
        # 지정학 기사 action은 지정학적 사건 자체가 주제일 때만 유효하다. 모델이
        # ``수요 관련 이슈``를 그 action으로 잘못 분류하면 아직 미연결인 기사
        # 원천에서 사전 차단되어, 이미 적재된 조달청·USGS 문서를 전혀 검색하지
        # 못한다. topic이라는 typed 분류 결과 안에 지정학 표지가 없을 때만
        # source-first document로 정정한다.
        if (item.intent == "geopolitics_articles"
                and not any(marker in (item.slots.topic or "")
                            for marker in ("지정학", "전쟁", "분쟁", "제재", "정세"))):
            item.intent = "document"
        # source-first 문서 질의는 원 질문이 그대로 검색 가능한 topic이다.
        # 모델이 광종·기간 슬롯만 남기고 topic을 비우면 document.retrieve의
        # 필수 슬롯 검증에서 검색 전에 닫히므로, 이미 전달받은 질문을 보충한다.
        if item.intent in {"document", "concept"} and not item.slots.topic:
            item.slots.topic = message
        if (item.intent in {"document", "concept"} and item.slots.period
                and item.slots.period.kind == "trailing_months"
                and item.slots.period.trailing_months):
            item.slots.period.explicit = True
        if (item.intent == "trade_concentration" and item.role == "data"
                and (item.slots.mineral, item.slots.flow) in trade_rank_pairs
                and not item.slots.topic and not explicit_concentration):
            # 국가별 비중은 country rank 결과의 열이다. 같은 광종·flow의 순위
            # data가 이미 있으면 topic 없는 concentration은 HHI가 아니라 이
            # 비중 설명을 중복 action으로 과분해한 상태이므로 흡수한다.
            continue
        if (item.intent == "price_compare" and item.role == "data"
                and has_conditional_scenario_content
                and _is_unbounded_price_compare_slots(item.slots)):
            continue
        # 메뉴 위치 안내는 화면을 고르는 독립 요청이다. LLM이 role=metadata로
        # 표기해도 문서 검색으로 바꾸지 않고 원래 menu/dataset intent를 보존한다.
        if item.intent in {"menu", "dataset"} and item.role == "metadata":
            item.role = "data"
        if item.intent == "mine_profile" and not item.slots.mine_name and has_mine_rank:
            # 순위 결과의 "이름"은 mine.rank가 반환하는 행의 필드다. 아직
            # 특정되지 않은 광산 profile을 별도 요구로 만들면 필수 mine_name
            # 슬롯만 비어 전체 질문이 실패한다.
            continue
        if (item.intent == "mine_profile" and item.slots.mine_name
                and item.slots.mine_name.casefold() in lookup_mines):
            continue
        if (item.intent == "trade_monthly" and item.slots.mine_name
                and item.slots.mine_name.casefold() in lookup_mines):
            # 월별 교역은 광종/HS와 국가 범위를 집계하며 개별 광산의 수입액을
            # 표현할 수 없다. 같은 광산을 명시 문서에서 찾는 요구가 있으면
            # 이 잘못된 source family를 실행하지 않고 문서 본문에 그 사실이
            # 있는지 판정한다. 본문에 없으면 source_unavailable로 끝난다.
            continue
        # 문서/개념으로 분류된 경우에도 typed topic이 비축 대안 계산의 세 요소를
        # 모두 가리키면, 실측 조회와 분리된 closed methodology action으로 보정한다.
        # 원 질문 표현을 재해석하지 않고 planner가 만든 topic taxonomy만 사용한다.
        if item.intent in {"document", "concept"} and _is_stockpile_methodology_topic(item.slots.topic):
            item.intent = "stockpile_methodology"
        # 여러 광종이 이미 ``minerals`` 슬롯으로 확정된 가격 시계열은 단일
        # 광종 조회가 아니다. source family를 바꾸지 않고, 같은 가격 adapter의
        # 비교 capability로 정규화한다. 이 보정은 질문 문구가 아니라 closed
        # 슬롯의 cardinality만 사용한다.
        if item.intent == "price_series" and item.slots.minerals and len(item.slots.minerals) > 1:
            item.intent = "price_compare"
        # 가격 단위·기준의 비교 방법은 가격 관측값에 붙는 표기 규칙이다. 별도
        # 문서 근거를 요구하는 원인·정의와 달리, typed topic이 단위와 비교를
        # 함께 가리키고 가격 data가 있으면 metadata로 흡수한다.
        if (item.intent == "concept" and has_data and item.slots.topic
                and any(marker in item.slots.topic for marker in ("단위", "가격 기준", "계산 기준", "등락률"))
                and any(candidate.intent in {"price_series", "price_compare", "price_claim"}
                        for candidate in intent_plan.requirements)):
            item.role = "metadata"
        # 가격과 현재 수급위기 위험의 관계는 독립 문서 설명이 아니라 미연결
        # 진단 원천을 요구한다. 이를 document로 남겨 가격 action과 섞으면
        # unsupported_combination이 되어 원천 상태가 가려진다.
        if (item.intent in {"document", "concept"} and item.slots.topic
                and "수급위기" in item.slots.topic
                and any(marker in item.slots.topic for marker in ("위험", "진단", "등급", "관계"))):
            item.intent = "diagnosis"
        # 생산국/수입국 비중이 함께 있는 경우 ``공급망 취약점``은 그 두
        # 관측값의 해설이다. 현행 진단 DB는 미연결이므로 이를 diagnosis.rank로
        # 실행하면 수치가 충분해도 전체 턴이 기권된다. 별도 점수·등급 요구
        # 슬롯이 없는 이 typed 조합만 metadata로 흡수한다.
        if (item.intent in {"diagnosis", "document", "concept"} and has_population_comparison
                and item.slots.topic and "공급망 취약" in item.slots.topic):
            item.role = "metadata"
        if item.role == "metadata":
            if has_data:
                deferred_metadata_outputs |= item.slots.requested_outputs
                continue
            if not actions:
                # 단독 개념 요구는 metadata로 표시됐더라도 붙일 데이터 action이
                # 없다. 질문 내용을 버리지 않고 source-first 문서 요구로 보존한다.
                # (LLM의 role 오류가 수치 답변을 만들어 내는 것보다 보수적이다.)
                call = ActionCall(requirement_id=item.requirement_id,
                                  action_id="document.retrieve", slots=item.slots,
                                  requested_outputs=set(item.slots.requested_outputs))
                actions.append(call)
                continue
            actions[-1].requested_outputs |= item.slots.requested_outputs
            continue
        action_id = INTENT_TO_ACTION[item.intent]
        # 결과 형식·출처·기준일은 독립 조회가 아니라 같은 슬롯의 출력 요구다.
        key = (action_id, item.slots.model_dump_json(exclude={"requested_outputs"}))
        existing = seen.get(key)
        if existing:
            existing.requested_outputs |= item.slots.requested_outputs
            continue
        call = ActionCall(requirement_id=item.requirement_id, action_id=action_id,
                          slots=item.slots, intent=item.intent, role=item.role,
                          requested_outputs=set(item.slots.requested_outputs))
        seen[key] = call
        actions.append(call)
    if deferred_metadata_outputs and actions:
        # metadata에는 조회 requirement_id가 없으므로 data 근거 귀속을 늘리지
        # 않는다. target requirement가 없는 공통 단위·기준일·표/차트 요구는
        # 모든 data action에 적용해 복합 Q11류의 두 근거 표현이 갈라지지 않는다.
        for action in actions:
            action.requested_outputs |= deferred_metadata_outputs
    _normalize_trade_indicator_slots(actions, message)
    _normalize_trade_monthly_slots(actions, message)
    _normalize_price_claim_slots(actions, message)
    _normalize_indicator_slots(actions, message)
    actions = _collapse_price_claim_actions(actions)
    result = ActionPlan(actions=actions)
    _normalize_requested_frequency(result.actions, message)
    _normalize_trade_rank_scope(result.actions, message)
    return result


def _normalize_requested_frequency(actions: list[ActionCall], message: str) -> None:
    """질문에 명시된 시계열 집계주기를 typed Period에 보존한다."""
    markers = (
        ("daily", ("일별", "매일", "일 단위", "일간 추이")),
        ("weekly", ("주별", "매주", "주 단위", "주간 추이")),
        ("monthly", ("월별", "매월", "월 단위", "월간 추이")),
        ("yearly", ("연도별", "매년", "연간 추이", "연 단위")),
    )
    compact = "".join(message.split()).casefold()
    requested = next((frequency for frequency, terms in markers
                      if any("".join(term.split()).casefold() in compact for term in terms)), None)
    if requested is None:
        return
    time_series_actions = {
        "price.series", "price.compare", "price.verify_claim", "trade.monthly",
        "indicator.series", "resource.rank", "mine.rank",
    }
    for action in actions:
        if action.action_id not in time_series_actions:
            continue
        if action.slots.period is None:
            action.slots.period = Period(kind="latest", frequency=requested)
        elif action.slots.period.frequency is None:
            action.slots.period.frequency = requested


def _canonicalize_dependency_intent_plan(intent_plan: IntentPlan, message: str) -> None:
    """특정국 의존도 단일 질문의 모델 과분해를 typed 관계 하나로 수렴한다."""
    compact = "".join(message.split())
    partner = _dependency_partner_from_message(message)
    if not partner or not any(marker in compact for marker in ("의존도", "의존율")):
        return
    trade_items = [item for item in intent_plan.requirements
                   if item.intent in {"trade_indicator", "trade_concentration"}]
    if not trade_items:
        return
    primary = trade_items[0]
    primary.intent = "trade_indicator"
    primary.role = "data"
    primary.slots.trade_metric = "country_dependency"
    intent_plan.requirements = [primary] + [
        item for item in intent_plan.requirements if item not in trade_items
    ]


def trade_indicator_plan_from_question(message: str) -> ActionPlan:
    """저장된 무역 HITL 질문을 LLM 재분류 없이 복원하는 최소 typed 계획."""
    compact = "".join(message.split()).casefold()
    metric_markers = (
        ("country_dependency", ("의존도", "의존율", "비중")),
        ("trade_growth", ("증감률", "증가율", "감소율")),
        ("tsi", ("무역특화", "tsi")),
        ("rca", ("현시비교우위", "rca")),
        ("tii", ("무역결합도", "tii")),
    )
    metric = next((value for value, markers in metric_markers
                   if any(marker.casefold() in compact for marker in markers)), None)
    mineral_markers = (("리튬", "리튬"), ("니켈", "니켈"), ("코발트", "코발트"),
                       ("구리", "구리"), ("동", "동"), ("희토류", "희토류"),
                       ("흑연", "흑연"))
    mineral = next((value for marker, value in mineral_markers if marker in compact), None)
    call = ActionCall(
        requirement_id="trade_indicator_followup", action_id="trade.indicator",
        slots=ActionSlots(mineral=mineral, trade_metric=metric),
        intent="trade_indicator", role="data",
    )
    plan = ActionPlan(actions=[call])
    _normalize_trade_indicator_slots(plan.actions, message)
    return plan


_SIMPLE_PARTNER_COUNTRIES = {
    "중국": "중국", "미국": "미국", "일본": "일본", "호주": "호주", "캐나다": "캐나다",
    "칠레": "칠레", "페루": "페루", "브라질": "브라질", "멕시코": "멕시코", "아르헨티나": "아르헨티나",
    "볼리비아": "볼리비아", "인도": "인도", "인도네시아": "인도네시아", "필리핀": "필리핀",
    "베트남": "베트남", "말레이시아": "말레이시아", "미얀마": "미얀마", "러시아": "러시아",
    "카자흐스탄": "카자흐스탄", "콩고": "콩고", "콩고민주공화국": "콩고민주공화국",
    "남아프리카공화국": "남아프리카공화국", "마다가스카르": "마다가스카르", "모잠비크": "모잠비크",
    "짐바브웨": "짐바브웨", "독일": "독일", "프랑스": "프랑스", "핀란드": "핀란드",
    "노르웨이": "노르웨이", "스웨덴": "스웨덴", "몽골": "몽골", "터키": "터키",
    "CN": "CN", "US": "US", "JP": "JP", "AU": "AU", "CA": "CA",
}
_SIMPLE_PARTNER_PATTERN = "|".join(
    re.escape(country) for country in sorted(_SIMPLE_PARTNER_COUNTRIES, key=len, reverse=True)
)


def _simple_country_share_plan(message: str) -> ActionPlan | None:
    """FBQ22의 완결된 단일 문형만 LLM 없이 특정국 비중으로 해석한다.

    ``국가별 비중``, 순위, 다른 데이터 요구가 섞인 질문은 여기서 처리하지
    않는다. 그런 질문은 planner가 독립 requirement와 분모 의미를 보존해야 한다.
    """
    compact = re.sub(r"[\s,]", "", message)
    match = re.fullmatch(
        r"(?:(?:최근)(?P<prefix_count>\d+)(?P<prefix_unit>개월|년))?"
        r"(?P<mineral>리튬|니켈|코발트|구리|동|희토류|흑연)"
        rf"수입중(?P<partner>{_SIMPLE_PARTNER_PATTERN})(?:의)?비중(?:을)?"
        r"(?:(?:최근)(?P<suffix_count>\d+)(?P<suffix_unit>개월|년))?"
        r"(?:얼마야|알려줘|알려주세요|보여줘|보여주세요)[?.]?",
        compact, flags=re.IGNORECASE,
    )
    if not match:
        # ``2025년 한국 리튬 수입의 중국 의존도를 계산해줘``는 기간·기준국·
        # 광종·상대국·분모가 모두 명시된 단일 관계다. LLM이 ``period``를
        # 누락해 HITL로 되돌아가지 않도록, 기존 단일국 비중 shortcut과 같은
        # 폐쇄 계약으로만 처리한다.
        dependency = re.fullmatch(
            rf"(?P<year>20\d{{2}})년한국(?P<mineral>리튬|니켈|코발트|구리|동|희토류|흑연)수입의"
            rf"(?P<partner>{_SIMPLE_PARTNER_PATTERN})(?:의)?의존도(?:를)?"
            r"(?:계산해줘|알려줘|알려주세요|보여줘|보여주세요)[?.]?",
            compact, flags=re.IGNORECASE,
        )
        if not dependency:
            return None
        return ActionPlan(actions=[ActionCall(
            requirement_id="country_dependency_share", action_id="trade.indicator",
            slots=ActionSlots(
                mineral=dependency.group("mineral"), flow="import", trade_metric="country_dependency",
                reporter_country="한국",
                partner_country=_SIMPLE_PARTNER_COUNTRIES[dependency.group("partner").upper()],
                period=Period(kind="calendar_year", calendar_year=int(dependency.group("year")), explicit=True),
                denominator_scope="reporter_product_trade",
            ), intent="trade_indicator", role="data",
        )])
    count = match.group("prefix_count") or match.group("suffix_count")
    unit = match.group("prefix_unit") or match.group("suffix_unit")
    months = int(count) * (12 if unit == "년" else 1) if count else 12
    return ActionPlan(actions=[ActionCall(
        requirement_id="country_dependency_share", action_id="trade.indicator",
        slots=ActionSlots(
            mineral=match.group("mineral"), flow="import", trade_metric="country_dependency",
            reporter_country="한국", partner_country=_SIMPLE_PARTNER_COUNTRIES[match.group("partner").upper()],
            period=Period(kind="trailing_months", trailing_months=months, explicit=bool(count)),
            denominator_scope="reporter_product_trade",
        ), intent="trade_indicator", role="data",
    )])


def _normalize_trade_indicator_slots(actions: list[ActionCall], message: str) -> None:
    """질문에 명시된 무역지표 조건만 typed 슬롯으로 정규화한다.

    LLM이 연도나 수입·수출 같은 표면 조건을 누락해도 새 trade.indicator의
    HITL이 불필요하게 반복되지 않게 한다. 국가·기간을 추정하지 않는다.
    """
    year = re.search(r"(20\d{2})\s*년", message)
    relative = re.search(r"최근\s*(\d+)\s*(개월|년)", message)
    compact = "".join(message.split())
    partner = _dependency_partner_from_message(message)
    for call in actions:
        if call.action_id != "trade.indicator":
            continue
        slots = call.slots
        if slots.trade_metric is None:
            metric_markers = (
                (("country_dependency", ("의존도", "의존율", "비중")),),
                (("trade_growth", ("증감률", "증가율", "감소율")),),
                (("tsi", ("무역특화", "tsi")),),
                (("rca", ("현시비교우위", "rca")),),
                (("tii", ("무역결합도", "tii")),),
            )
            compact_lower = compact.casefold()
            for ((metric, markers),) in metric_markers:
                if any(marker.casefold() in compact_lower for marker in markers):
                    slots.trade_metric = metric
                    break
        if (relative and slots.trade_metric == "country_dependency"
                and (slots.period is None or not slots.period.explicit)):
            months = int(relative.group(1)) * (12 if relative.group(2) == "년" else 1)
            slots.period = Period(kind="trailing_months", trailing_months=months, explicit=True)
        elif year and (slots.period is None or not slots.period.explicit):
            slots.period = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
        if slots.reporter_country is None and "한국" in compact:
            slots.reporter_country = "한국"
        if slots.flow is None:
            if "수입" in compact:
                slots.flow = "import"
            elif "수출" in compact:
                slots.flow = "export"
        if slots.partner_country is None and partner:
            slots.partner_country = partner
        if slots.trade_metric == "country_dependency":
            # 분모는 공개 계약의 유일한 의미로 고정한다. 기준국·기간 생략은
            # 복합 질의에서 추정하지 않고, 완결 단일 문형만 위 shortcut이 닫는다.
            if slots.denominator_scope is None:
                slots.denominator_scope = "reporter_product_trade"


def _normalize_trade_monthly_slots(actions: list[ActionCall], message: str) -> None:
    """명시 연도의 월별 교역을 trailing 기본값으로 바꾸지 않는다."""
    years = {int(value) for value in re.findall(r"(20\d{2})\s*년", message)}
    if not years:
        return
    for call in actions:
        if call.action_id != "trade.monthly":
            continue
        period = call.slots.period
        if period is not None and (period.explicit
                                   or (period.kind == "range" and period.start and period.end)):
            continue
        if len(years) == 1:
            year = next(iter(years))
            call.slots.period = Period(
                kind="calendar_year", calendar_year=year, explicit=True,
                frequency=period.frequency if period else None,
            )
        else:
            # 다년 질문을 첫해 한 해로 축소하거나 무기한 최신 범위로 넓히지
            # 않는다. 문장에 실제로 나온 최저/최고 연도의 닫힌 달력 범위다.
            call.slots.period = Period(
                kind="range", start=f"{min(years)}0101", end=f"{max(years)}1231", explicit=True,
                frequency=period.frequency if period else None,
            )


def _normalize_price_claim_slots(actions: list[ActionCall], message: str) -> None:
    """가격 주장 질문의 수치 전제와 비교 연산자를 typed 슬롯으로 보완한다.

    LLM이 ``claimed_change_pct`` 또는 비교 연산자를 생략해도 질문에 실제로
    적힌 백분율·비교어만 사용한다. 질문에 없는 임계값을 추정하지 않는다.
    """
    claim = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", message)
    year = re.search(r"(20\d{2})\s*년", message)
    compact = "".join(message.split()).casefold()
    comparator = None
    if any(token in compact for token in ("이상", "넘게", "초과", "상승했어", "올랐어")):
        comparator = "greater_than"
    elif any(token in compact for token in ("이하", "미만", "안올랐", "못올랐")):
        comparator = "less_than"
    for call in actions:
        if call.action_id != "price.verify_claim":
            continue
        if call.slots.claimed_change_pct is None and claim:
            call.slots.claimed_change_pct = float(claim.group(1))
        if call.slots.comparator is None and comparator:
            call.slots.comparator = comparator
        if year and (call.slots.period is None or call.slots.period.kind != "calendar_year"):
            call.slots.period = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
        if call.slots.mineral is None:
            for alias, mineral in MINERAL_ALIASES.items():
                if alias in compact:
                    call.slots.mineral = mineral
                    break


def _collapse_price_claim_actions(actions: list[ActionCall]) -> list[ActionCall]:
    """동일 가격 주장에 대한 data/content 중복 requirement를 하나로 합친다."""
    claims = [call for call in actions if call.action_id == "price.verify_claim"]
    if len(claims) < 2:
        return actions
    primary = next((call for call in claims if call.role == "data"), claims[0])
    for duplicate in claims:
        if duplicate is primary:
            continue
        for field in ActionSlots.model_fields:
            if getattr(primary.slots, field) is None:
                value = getattr(duplicate.slots, field)
                if value is not None:
                    setattr(primary.slots, field, value)
        primary.requested_outputs |= duplicate.requested_outputs
    return [call for call in actions if call is primary or call.action_id != "price.verify_claim"]


def _normalize_indicator_slots(actions: list[ActionCall], message: str) -> None:
    """표시명으로 요청된 지표를 공개 action의 typed indicator로 정규화한다."""
    compact = "".join(message.split()).upper()
    labels = (
        ("supply_stability", ("수급동향지표", "수급동향")),
        ("market_outlook", ("시장동향지표", "시장전망지표")),
        ("composite_index", ("광물종합지수", "광물종합지표", "종합지수", "종합지표",
                              "HI001", "HI002", "HI003", "메이저금속지수", "메이저지수",
                              "희소금속지수", "희유금속지수")),
    )
    for call in actions:
        if call.action_id != "indicator.series" or call.slots.indicator is not None:
            continue
        for indicator, markers in labels:
            if any(marker in compact for marker in markers):
                call.slots.indicator = indicator
                break
    for call in actions:
        if call.action_id != "indicator.series" or call.slots.indicator != "composite_index":
            continue
        variant_markers = (
            ("major_metals", ("HI002", "메이저금속지수", "메이저지수")),
            ("minor_metals", ("HI003", "희소금속지수", "희유금속지수")),
            ("composite", ("HI001", "광물종합지수", "광물종합지표", "종합지수", "종합지표")),
        )
        matched = [variant for variant, markers in variant_markers
                   if any(marker in compact for marker in markers)]
        specific = [variant for variant in matched if variant in {"major_metals", "minor_metals"}]
        if len(set(specific)) == 1:
            explicit_code = "HI002" in compact or "HI003" in compact
            generic_name = any(marker in compact for marker in (
                "광물종합지수", "광물종합지표", "종합지수", "종합지표",
            ))
            if len(set(matched)) > 1 and generic_name and not explicit_code:
                # 두 계열명이 함께 쓰인 비교 질의는 한 계열로 축약하지 않는다.
                continue
            if "HI001" in compact:
                continue
            # 질문에 명시된 계열은 planner가 실수로 기본 계열을 채워도 우선한다.
            call.slots.indicator_variant = specific[0]
        elif len(set(specific)) > 1:
            continue
        elif "composite" in matched:
            call.slots.indicator_variant = "composite"
        elif call.slots.indicator_variant is None:
            call.slots.indicator_variant = "composite"


def merge_trade_indicator_followup(plan: ActionPlan, message: str) -> ActionPlan:
    """명확화 후속 턴의 명시 슬롯만 기존 typed 무역 계획에 병합한다."""
    _normalize_trade_indicator_slots(plan.actions, message)
    # 이 함수는 pending clarification에서만 호출된다. 따라서 새로 명시한
    # 기간은 기존 질문의 기간(명시값 포함)을 의도적으로 교체한다. 일반 복합
    # 질문의 requirement별 명시 기간은 위 normalizer가 보존한다.
    year = re.search(r"(20\d{2})\s*년", message)
    relative = re.search(r"최근\s*(\d+)\s*(개월|년)", message)
    for call in plan.actions:
        if call.action_id != "trade.indicator":
            continue
        if year:
            call.slots.period = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
        elif relative:
            months = int(relative.group(1)) * (12 if relative.group(2) == "년" else 1)
            call.slots.period = Period(kind="trailing_months", trailing_months=months, explicit=True)
    return plan


def _dependency_partner_from_message(message: str) -> str | None:
    """특정국 의존도 문맥에서만 질문에 명시된 상대국을 정규화한다.

    ``trade.indicator``의 partner_country는 자유 국가명 추측 슬롯이 아니다.
    수입·수출과 의존도 사이에 명시된 국가, 또는 ``국가산 수입 의존도``처럼
    관계가 완결된 표기만 읽는다. HHI·일반 국가순위에는 적용하지 않는다.
    """
    compact = "".join(message.split())
    patterns = (
        r"(?:수입|수출)(?:의|에서|중)?([가-힣]{2,}|[A-Z]{2,3})(?:산)?(?:의)?(?:의존도|의존율)",
        r"([가-힣]{2,}|[A-Z]{2,3})산(?:[가-힣]{0,12})?(?:수입|수출)(?:의)?(?:의존도|의존율)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return match.group(1)
    return None


def _normalize_trade_indicator_intents(intent_plan: IntentPlan, message: str) -> None:
    """특정국 의존도라는 typed 관계를 ``trade.indicator``로 수렴시킨다.

    집중도(HHI)와 의존도는 모두 국가 비중을 다루므로 모델이
    ``trade_concentration``으로 분류할 수 있다. 상대국 슬롯이 확정된 경우에만
    HHI action을 dependency action으로 바꿔, 질문별 예외 대신 action 계약
    자체에서 단일 실행 경로를 보장한다.
    """
    year = re.search(r"(20\d{2})\s*년", message)
    relative = re.search(r"최근\s*(\d+)\s*(개월|년)", message)
    compact = "".join(message.split())
    partner = _dependency_partner_from_message(message)
    dependency_question = bool(partner and any(marker in compact for marker in ("의존도", "의존율")))
    for item in intent_plan.requirements:
        if item.intent not in {"trade_indicator", "trade_concentration"}:
            continue
        slots = item.slots
        if dependency_question:
            # 모델이 특정국 의존도를 HHI와 별도 요구로 과분해해도 질문의
            # typed 관계를 하나의 country_dependency action으로 수렴한다.
            item.intent = "trade_indicator"
            slots.trade_metric = "country_dependency"
        if slots.reporter_country is None and "한국" in compact:
            slots.reporter_country = "한국"
        if (relative and slots.trade_metric == "country_dependency"
                and (slots.period is None or not slots.period.explicit)):
            months = int(relative.group(1)) * (12 if relative.group(2) == "년" else 1)
            slots.period = Period(kind="trailing_months", trailing_months=months, explicit=True)
        elif year and (slots.period is None or not slots.period.explicit):
            slots.period = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
        if slots.flow is None:
            if "수입" in compact:
                slots.flow = "import"
            elif "수출" in compact:
                slots.flow = "export"
        if slots.partner_country is None and partner:
            slots.partner_country = partner
        if item.intent == "trade_indicator" and slots.trade_metric == "country_dependency":
            if slots.denominator_scope is None:
                slots.denominator_scope = "reporter_product_trade"
        if item.intent == "trade_concentration" and slots.partner_country:
            item.intent = "trade_indicator"
            slots.trade_metric = "country_dependency"


def _is_stockpile_methodology_topic(topic: str | None) -> bool:
    """비축 대안 계산의 typed topic을 실제 비축 수치 요구와 구분한다."""
    normalized = (topic or "").replace(" ", "")
    has_stock = any(term in normalized for term in ("비축", "재고"))
    has_shortfall = any(term in normalized for term in ("부족", "목표"))
    has_days_or_formula = any(term in normalized for term in ("일수", "계산", "입력값", "산식"))
    return has_stock and has_shortfall and has_days_or_formula


def _is_unbounded_price_compare_slots(slots: ActionSlots) -> bool:
    """관측 조건이 전혀 없는 price.compare 슬롯만 식별한다."""
    return (slots.period is None and not slots.windows
            and slots.price_basis is None and slots.currency is None
            and slots.weight_unit is None)


def _is_conditional_scenario_topic(topic: str | None) -> bool:
    """수치 비교 없는 조건부 영향 설명의 closed topic 표지를 확인한다."""
    normalized = (topic or "").replace(" ", "")
    return (any(term in normalized for term in ("수요", "시나리오", "영향", "상관", "추론"))
            and any(term in normalized for term in (
                "둔화", "감소", "하락", "변화", "조건", "전기차", "ev",
            )))


def _load_numeric_constant(name: str) -> float:
    """운영 상수를 읽고 값 범위를 검증한다.

    상수 파일이 손상됐을 때 임의의 기본값으로 질의 의미가 바뀌지 않도록 호출자가
    기권할 수 있게 ValueError를 낸다.
    """
    try:
        import yaml
        payload = yaml.safe_load((Path(__file__).with_name("resources") / "constants.yml").read_text(encoding="utf-8"))
        value = float(payload[name])
        if 0 < value <= 100:
            return value
    except (OSError, TypeError, ValueError, KeyError, yaml.YAMLError):
        pass
    raise ValueError(f"numeric constant is invalid: {name}")


def _significant_daily_rise_threshold() -> float:
    """리소스에 기록된 기본 '크게' 기준. 없으면 질문을 열지 않는다."""
    return _load_numeric_constant("significant_daily_rise_pct")


def import_dependency_high_threshold() -> float:
    """특정 수입상대국 비중이 '높음'으로 분류되는 엄격한 하한값."""
    return _load_numeric_constant("import_dependency_high_pct")


def _history_for_action_query(message: str, history: list[dict[str, str]] | None) -> list[dict[str, str]] | None:
    """Do not let an unresolved antecedent poison an explicit new question.

    A follow-up such as ``그중에 3번째 국가`` must retain history.  Conversely,
    a new question that names its mineral and metric explicitly should be
    planned independently even when the preceding turn was an unresolved
    dependency request.  This is context selection, not intent classification;
    the legacy and semantic planners receive the same selected history.
    """
    if not history:
        return history
    compact = re.sub(r"\s+", "", message).casefold()
    if history_is_required(message):
        return history
    minerals = (
        "구리", "동", "copper", "cu", "니켈", "nickel", "코발트", "cobalt", "리튬", "lithium",
        "망간", "manganese", "흑연", "graphite", "희토류", "rareearth", "네오디뮴", "nd",
    )
    metrics = (
        "생산", "매장", "수입", "수출", "가격", "재고", "뉴스", "동향", "순위", "상위", "전망",
        "집중도", "특성", "성질", "용도", "지수",
    )
    if any(token in compact for token in minerals) and any(token in compact for token in metrics):
        return []
    return history


def history_is_required(message: str) -> bool:
    """현재 질문이 과거 결과의 명시적/미해결 참조를 요구하는지 판정한다.

    이 함수는 질문의 전체 의미를 재계획하지 않는다. 현재 질의에 명시된
    entity/metric이 충분하면 history를 상속하지 않으며, 대명사·지시어처럼
    현재 문장만으로 대상을 확정할 수 없는 표현이 있을 때만 기존 typed
    history resolver를 사용할 수 있게 하는 경계다.
    """
    compact = re.sub(r"\s+", "", message).casefold()
    return any(marker in compact for marker in (
        "그중", "그나라", "그국가", "해당국가", "이중", "앞서", "이것도", "그광종", "이광종",
        "그것", "방금결과", "방금답변", "아까", "같은기간", "이전결과", "앞에서말한",
    ))


def extract_action_plan(
    message: str,
    llm: Any,
    history: list[dict[str, str]] | None = None,
    semantic_context: Any | None = None,
) -> ActionPlan:
    """Resolve a question while preserving the legacy parser as a fallback.

    ``SEMANTIC_INTENT_MODE=off`` is byte-for-byte equivalent to the previous
    entry point.  In ``shadow`` mode the typed semantic parser runs in parallel
    for audit logging but the legacy plan is always returned.  ``enabled``
    gives validated semantic capabilities precedence only after deterministic
    legacy shortcuts miss; an unresolved semantic result falls back to the
    existing LLM IntentPlan path.
    """
    from .semantic_intent import parse_and_resolve, record_shadow_audit, semantic_mode

    selected_history = _history_for_action_query(message, history)
    mode = semantic_mode()
    # The caller owns live-vs-legacy routing. If it delegates a simple query
    # here, return a valid plan; an empty ActionPlan violates its own schema.
    if mode == "off":
        return _extract_action_plan_legacy(message, llm, selected_history, allow_llm=True)
    if mode == "shadow":
        legacy_plan = _extract_action_plan_legacy(message, llm, selected_history, allow_llm=True)
        result = parse_and_resolve(message, llm, selected_history, semantic_context=semantic_context)
        if result.semantic_plan is not None:
            legacy_plan._semantic_requirements = [item.model_dump(mode="json", exclude_none=True) for item in result.semantic_plan.requirements]
        record_shadow_audit(message, legacy_plan, result)
        # V2 is an independent observation path.  It never supplies or
        # replaces the production ActionPlan returned by this function.
        from .semantic_v2 import parse_v2_shadow, record_v2_shadow
        record_v2_shadow(parse_v2_shadow(message, llm, semantic_context=semantic_context))
        return legacy_plan

    # Enabled mode makes the typed semantic parser authoritative.  Legacy
    # shortcuts remain a bounded fallback for schema/model failure only; they
    # must not consume a composite request before Gemma can represent all
    # requested requirements.
    # 닫힌 typed dependency 계약은 Gemma가 문서 Action 하나로 축약해도
    # 보존한다. 이 계획은 기존 Action만 사용하며, 이후 실행 단계에서
    # 뉴스 광물 ArgMax binding을 해소한다.
    bounded_dependency_plan = _extract_action_plan_legacy(message, llm, selected_history, allow_llm=False)
    if (bounded_dependency_plan is not None
            and len(bounded_dependency_plan.actions) >= 3
            and any(call.input_bindings for call in bounded_dependency_plan.actions)):
        return bounded_dependency_plan
    result = parse_and_resolve(message, llm, selected_history, semantic_context=semantic_context)
    if result.action_plan is not None:
        if result.semantic_plan is not None:
            result.action_plan._semantic_requirements = [item.model_dump(mode="json", exclude_none=True) for item in result.semantic_plan.requirements]
        return result.action_plan
    legacy_plan = _extract_action_plan_legacy(message, llm, selected_history, allow_llm=True)
    # Preserve a successfully structured semantic snapshot even when its
    # lowering/validation failed.  The direct-capability boundary must be
    # able to detect a partial legacy plan and escalate it to AAST rather than
    # executing only the branch that happened to lower successfully.
    if result.semantic_plan is not None:
        legacy_plan._semantic_requirements = [
            item.model_dump(mode="json", exclude_none=True)
            for item in result.semantic_plan.requirements
        ]
    legacy_plan._semantic_resolution_error = result.reason
    return legacy_plan


def extract_legacy_action_plan(
    message: str,
    llm: Any,
    history: list[dict[str, str]] | None = None,
) -> ActionPlan:
    """Return the pre-semantic parser result for a targeted safety fallback.

    The public entry point normally applies the semantic feature flag.  Runtime
    validation can still discover a value (for example an unknown mineral) that
    the semantic layer must not force into an existing action.  Callers use this
    narrow helper to retry the unchanged legacy path without recursively
    invoking semantic parsing.
    """

    return _extract_action_plan_legacy(message, llm, history, allow_llm=True)


def _extract_action_plan_legacy(
    message: str,
    llm: Any,
    history: list[dict[str, str]] | None = None,
    *,
    allow_llm: bool = True,
) -> ActionPlan | None:
    compact = re.sub(r"\s+", "", message)
    mineral_info_match = next((name for name in (
        "리튬", "니켈", "코발트", "구리", "동", "망간", "흑연", "텅스텐", "희토류", "네오디뮴",
    ) if name in compact), None)
    if mineral_info_match and any(marker in compact for marker in (
            "용도", "어디에쓰", "어디쓰", "쓰여", "사용처", "활용처")) and not any(
                marker in compact for marker in ("수입", "생산국", "생산상위", "가격", "얼마")):
        mineral = "구리" if mineral_info_match == "동" else mineral_info_match
        return ActionPlan(actions=[ActionCall(
            requirement_id="mineral_info", action_id="document.retrieve",
            slots=ActionSlots(mineral=mineral, topic=message), intent="concept", role="content",
        )])
    significant_news = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격(?:이|은|가)?"
        r"(?:(?P<threshold>\d+(?:\.\d+)?)%이상)?"
        r"(?:크게|많이|급격히|상당히)?(?:오른|상승한|급등한)(?:날|날짜)(?:에)?"
        r"(?:관련)?뉴스(?:가)?(?:(?:뭐|무엇|무슨|어떤)?"
        r"(?:있어|있나요|있었어|있었나요|알려줘|알려주세요|보여줘|보여주세요))?[?.]?",
        compact,
    )
    if significant_news:
        threshold = (float(significant_news.group("threshold"))
                     if significant_news.group("threshold") else _significant_daily_rise_threshold())
        return ActionPlan(actions=[ActionCall(
            requirement_id="significant_price_rise", action_id="price.series",
            slots=ActionSlots(mineral=significant_news.group("mineral"),
                              period=Period(kind="trailing_months", trailing_months=1),
                              price_operation="significant_daily_rise", significant_change_pct=threshold),
            intent="price_series", role="data",
        )])
    export_rank = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?주요수출국(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact,
    )
    if export_rank:
        mineral = MINERAL_ALIASES.get(export_rank.group("mineral").casefold(), export_rank.group("mineral"))
        return ActionPlan(actions=[ActionCall(
            requirement_id="global_export_countries", action_id="trade.country_rank",
            slots=ActionSlots(mineral=mineral, metric="export_amount", trade_scope="global", top_n=5,
                              period=Period(kind="trailing_months", trailing_months=12)),
            intent="trade_rank", role="data",
        )])
    global_import_rank = re.fullmatch(
        r"(?:세계|글로벌)(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?주요?수입국(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if global_import_rank:
        mineral = MINERAL_ALIASES.get(global_import_rank.group("mineral").casefold(), global_import_rank.group("mineral"))
        return ActionPlan(actions=[ActionCall(
            requirement_id="global_import_countries", action_id="trade.country_rank",
            slots=ActionSlots(mineral=mineral, metric="import_amount", trade_scope="global", top_n=5,
                              period=Period(kind="trailing_months", trailing_months=12)),
            intent="trade_rank", role="data",
        )])
    import_concentration = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?(?:수입)?(?:집중도|편중도)(?:가|는|를)?"
        r"(?:어때요?|알려줘요?|알려주세요|보여줘요?|보여주세요|얼마야)?[?.]?", compact,
    )
    if import_concentration:
        mineral = MINERAL_ALIASES.get(import_concentration.group("mineral").casefold(), import_concentration.group("mineral"))
        return ActionPlan(actions=[ActionCall(
            requirement_id="import_concentration", action_id="trade.concentration",
            slots=ActionSlots(mineral=mineral, period=Period(kind="trailing_months", trailing_months=12)),
            intent="trade_concentration", role="data",
        )])
    price_date_news = re.search(
        r"(?P<mineral>구리|니켈|코발트|리튬|망간|흑연|텅스텐|희토류)"
        r".*?최근\s*(?P<months>\d{1,2})\s*개월.*?가격.*?가장\s*낮은\s*날짜.*?일일.*?뉴스.*?(?:제목|타이틀)",
        message.replace(" ", ""), flags=re.IGNORECASE,
    )
    if price_date_news:
        mineral = price_date_news.group("mineral")
        months = int(price_date_news.group("months"))
        return ActionPlan(actions=[
            ActionCall(
                requirement_id="price_min_date", action_id="price.series",
                slots=ActionSlots(
                    mineral=mineral, period=Period(kind="trailing_months", trailing_months=months),
                    selection_mode="extremum", selection_direction="min",
                ), intent="price_series", role="data",
            ),
            ActionCall(
                requirement_id="news_on_price_min_date", action_id="document.retrieve",
                slots=ActionSlots(mineral=mineral, topic="일일 광물자원 뉴스", period=Period(kind="trailing_months", trailing_months=months)),
                intent="document", role="content", depends_on=["price_min_date"],
                    input_bindings=[InputBinding(source_requirement_id="price_min_date", source_field="date", selector="argmin", target_slot="bound_date")],
            ),
        ])
    news_mineral_followup = re.search(
        r"일일.*?광물.*?뉴스.*?최근\s*(?P<months>\d{1,2})\s*(?:달|개월).*?"
        r"(?:가장|최다).*?언급.*?광물.*?수입.*?집중도.*?가격.*?(?:전망|예측)",
        message.replace(" ", ""), flags=re.IGNORECASE,
    )
    if news_mineral_followup:
        months = int(news_mineral_followup.group("months"))
        period = Period(kind="trailing_months", trailing_months=months)
        binding = InputBinding(
            source_requirement_id="daily_news", source_field="mineral",
            selector="argmax", target_slot="mineral",
        )
        return ActionPlan(actions=[
            ActionCall(
                requirement_id="daily_news", action_id="document.retrieve",
                slots=ActionSlots(topic="일일 광물자원 뉴스", period=period),
                intent="document", role="content",
            ),
            ActionCall(
                requirement_id="news_top_mineral_concentration", action_id="trade.concentration",
                slots=ActionSlots(period=period), intent="trade_concentration", role="data",
                depends_on=["daily_news"], input_bindings=[binding],
            ),
            ActionCall(
                requirement_id="news_top_mineral_forecast", action_id="forecast.price",
                slots=ActionSlots(period=Period(kind="future_horizon", future_horizon=1)),
                intent="forecast_price", role="data",
                depends_on=["daily_news"], input_bindings=[binding],
            ),
        ])
    # 사용자 Q&A 계약의 ``수입 상위국 + 현재가``는 두 독립 원천을 요구한다.
    # 조사("의")와 "현재" 유무가 달라도 같은 닫힌 문형으로 취급한다. LLM에
    # 맡기면 광종 slot이 두 action 사이에서 누락되어 unsupported_commodity로
    # 조기 종료될 수 있으므로 여기서 보존한다.
    import_current_price = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?수입(?:상위)?국(?:이랑|과|와|및)?(?:현재|최근)?가격(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if import_current_price:
        mineral = MINERAL_ALIASES.get(import_current_price.group("mineral").casefold(),
                                      import_current_price.group("mineral"))
        return ActionPlan(actions=[
            ActionCall(requirement_id="import_countries", action_id="trade.country_rank",
                       slots=ActionSlots(mineral=mineral, metric="import_amount", trade_scope="korea", top_n=5,
                                         period=Period(kind="trailing_months", trailing_months=12)),
                       intent="trade_rank", role="data"),
            ActionCall(requirement_id="current_price", action_id="price.series",
                       slots=ActionSlots(mineral=mineral, period=Period(kind="latest")),
                       intent="price_series", role="data"),
        ])
    # ``어디에 쓰이고 지금 가격``은 용도 문서와 최신 관측값을 함께 요청한다.
    # 단일 용도 질문과 달리 가격이 있으므로 위 단일-광물정보 shortcut에서는
    # 의도적으로 제외됐고, 이 전용 plan이 그 공백을 메운다.
    use_current_price = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:은|는|의)?(?:어디에)?(?:쓰이고|쓰여|사용되고)"
        r"(?:현재|지금|최근)?(?:가격)?(?:은|이|을|를)?"
        r"(?:얼마야|얼마인가요|알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if use_current_price:
        mineral = MINERAL_ALIASES.get(use_current_price.group("mineral").casefold(),
                                      use_current_price.group("mineral"))
        return ActionPlan(actions=[
            ActionCall(requirement_id="mineral_info", action_id="document.retrieve",
                       slots=ActionSlots(mineral=mineral, topic=f"{mineral} 용도"),
                       intent="concept", role="content"),
            ActionCall(requirement_id="current_price", action_id="price.series",
                       slots=ActionSlots(mineral=mineral, period=Period(kind="latest")),
                       intent="price_series", role="data"),
        ])
    production_import_compare = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?세계생산(?:상위)?국(?:이랑|과|와|및)?우리나라수입(?:상위)?국(?:을)?(?:비교해줘|비교해주세요|알려줘|알려주세요)?[?.]?", compact,
    )
    common_country = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)세계생산상위국중우리수입상위국에들어가는나라는?(?:알려줘|알려주세요)?[?.]?", compact,
    )
    if production_import_compare or common_country:
        mineral = (production_import_compare or common_country).group("mineral")
        return ActionPlan(actions=[
            ActionCall(requirement_id="world_production", action_id="resource.rank",
                       slots=ActionSlots(mineral=mineral, metric="production", country_scope="world", top_n=5), intent="resource_rank", role="data"),
            ActionCall(requirement_id="korea_import", action_id="trade.country_rank",
                       slots=ActionSlots(mineral=mineral, metric="import_amount", trade_scope="korea", top_n=5,
                                         period=Period(kind="trailing_months", trailing_months=12)), intent="trade_rank", role="data"),
        ])
    concentration_compare = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)생산집중도랑수입집중도(?:를)?(?:비교해줘|비교해주세요|알려줘|알려주세요)?[?.]?", compact,
    )
    if concentration_compare:
        mineral = concentration_compare.group("mineral")
        return ActionPlan(actions=[
            ActionCall(requirement_id="production_concentration", action_id="resource.rank",
                       slots=ActionSlots(mineral=mineral, metric="production", country_scope="world", top_n=1), intent="resource_rank", role="data"),
            ActionCall(requirement_id="import_concentration", action_id="trade.concentration",
                       slots=ActionSlots(mineral=mineral, period=Period(kind="trailing_months", trailing_months=12)), intent="trade_concentration", role="data"),
        ])
    if re.fullmatch(r"2차전지광물수입국구성(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact):
        minerals = ["리튬", "니켈", "코발트", "망간", "흑연"]
        return ActionPlan(actions=[ActionCall(
            requirement_id=f"battery_import_{mineral}", action_id="trade.country_rank",
            slots=ActionSlots(mineral=mineral, metric="import_amount", trade_scope="korea", top_n=1,
                              period=Period(kind="trailing_months", trailing_months=12)),
            intent="trade_rank", role="data",
        ) for mineral in minerals])
    if re.fullmatch(r"2차전지광물5종가격이랑전망(?:을)?(?:한번에)?(?:보여줘|알려줘|보여주세요|알려주세요)?[?.]?", compact):
        minerals = ["리튬", "니켈", "코발트", "망간", "흑연"]
        actions = []
        for mineral in minerals:
            actions.extend([
                ActionCall(requirement_id=f"battery_price_{mineral}", action_id="price.series",
                           slots=ActionSlots(mineral=mineral, period=Period(kind="latest")), intent="price_series", role="data"),
                ActionCall(requirement_id=f"battery_forecast_{mineral}", action_id="forecast.price",
                           slots=ActionSlots(mineral=mineral, forecast_operation="direction"), intent="forecast_price", role="data"),
            ])
        return ActionPlan(actions=actions)
    if re.fullmatch(r"코발트현황브리핑(?:해줘|해주세요)?[?.]?", compact):
        return ActionPlan(actions=[
            ActionCall(requirement_id="current_price", action_id="price.series",
                       slots=ActionSlots(mineral="코발트", period=Period(kind="latest")), intent="price_series", role="data"),
            ActionCall(requirement_id="forecast", action_id="forecast.price",
                       slots=ActionSlots(mineral="코발트", forecast_operation="direction"), intent="forecast_price", role="data"),
            ActionCall(requirement_id="production", action_id="resource.rank",
                       slots=ActionSlots(mineral="코발트", metric="production", country_scope="world", top_n=1), intent="resource_rank", role="data"),
            ActionCall(requirement_id="imports", action_id="trade.country_rank",
                       slots=ActionSlots(mineral="코발트", metric="import_amount", trade_scope="korea", top_n=1,
                                         period=Period(kind="trailing_months", trailing_months=12)), intent="trade_rank", role="data"),
        ])
    if re.fullmatch(r"흑연공급현황종합해서(?:알려줘|보여줘|해주세요)?[?.]?", compact):
        return ActionPlan(actions=[
            ActionCall(requirement_id="production", action_id="resource.rank", slots=ActionSlots(mineral="흑연", metric="production", country_scope="world", top_n=1), intent="resource_rank", role="data"),
            ActionCall(requirement_id="imports", action_id="trade.concentration", slots=ActionSlots(mineral="흑연", period=Period(kind="trailing_months", trailing_months=12)), intent="trade_concentration", role="data"),
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="흑연", period=Period(kind="trailing_months", trailing_months=1)), intent="price_series", role="data"),
            ActionCall(requirement_id="monthly", action_id="document.retrieve", slots=ActionSlots(mineral="흑연", topic="흑연 월간동향"), intent="document", role="content"),
        ])
    if mineral_info_match and any(marker in compact for marker in (
            "용도", "어디에쓰", "어디쓰", "쓰여", "사용처", "활용처",
            "어떤광물", "어떤금속", "무슨광물", "무슨금속", "기본특성", "특성이",
            "특성알려", "원소기호", "원자번호", "광석", "ore")) and not any(
                marker in compact for marker in ("수입", "생산국", "세계생산", "가격")):
        mineral = "구리" if mineral_info_match == "동" else mineral_info_match
        return ActionPlan(actions=[ActionCall(
            requirement_id="mineral_info", action_id="document.retrieve",
            slots=ActionSlots(mineral=mineral, topic=message), intent="concept", role="content",
        )])
    months_match = re.search(r"최근(\d+)(개월|년)", compact)
    months = int(months_match.group(1)) * (12 if months_match and months_match.group(2) == "년" else 1) if months_match else 12
    year_match = re.search(r"(20\d{2})년", compact)
    top_match = re.search(r"상위(\d+)(?:개|종)?", compact)
    top_n = int(top_match.group(1)) if top_match else 5
    price_period = (Period(kind="latest") if not 1 <= months <= 240 else
                    Period(kind="trailing_months", trailing_months=months)
                    if months_match or not year_match else
                    Period(kind="calendar_year", calendar_year=int(year_match.group(1))))
    if all(marker in compact for marker in ("수입", "비중", "광종", "가격")) and any(
            marker in compact for marker in ("오른", "상승", "올랐")):
        country_match = re.search(r"([가-힣]{2,15})수입비중", compact)
        if country_match:
            country = country_match.group(1)
            if country.endswith("의"):
                country = country[:-1]
            return ActionPlan(actions=[ActionCall(
                requirement_id="country_import_price_cross", action_id="trade.price_cross_rank",
                slots=ActionSlots(partner_country=country,
                                  metric="import_weight" if any(t in compact for t in ("중량", "물량", "무게")) else "import_amount",
                                  period=price_period, top_n=top_n if 1 <= top_n <= 100 else None),
                intent="trade_price_cross_rank", role="data",
            )])
    if all(marker in compact for marker in ("생산", "1위국", "비중", "광종", "가격")):
        return ActionPlan(actions=[ActionCall(
            requirement_id="producer_price_cross", action_id="resource.price_cross_rank",
            slots=ActionSlots(metric="production", period=price_period,
                              reference_year=int(year_match.group(1)) if year_match else None,
                              top_n=top_n if 1 <= top_n <= 100 else None),
            intent="resource_price_cross_rank", role="data",
        )])
    # 한국 수입 데이터의 조회 메뉴를 묻는 질문은 생산·매장량(resource.rank)과
    # 혼동되기 쉽다. 질문에 ``한국``과 ``수입``이 함께 있고 메뉴 위치를 묻는
    # 표현이면 대한민국 수급지도(menu.navigate)로 고정한다. 이 보정은 실제
    # 수치 조회가 아니라 페이지 안내에만 적용해 LLM의 광물지도 오분류를
    # 막는다.
    menu_text = re.sub(r"\s+", "", message)
    if (
        "한국" in menu_text and "수입" in menu_text
        and any(marker in menu_text for marker in ("어디", "페이지", "보려면", "메뉴", "가야"))
    ):
        mineral = next((name for name in ("리튬", "니켈", "코발트", "구리", "흑연", "망간") if name in menu_text), None)
        return ActionPlan(actions=[ActionCall(
            requirement_id="korea_import_menu",
            action_id="menu.navigate",
            slots=ActionSlots(target_page="map_korea", mineral=mineral),
            intent="menu",
            role="metadata",
        )])
    # 희토류 총괄 통계와 네오디뮴 가격의 범위 비교는 가격 단일조회로
    # 축약되면 안 되는 고정 문서 질의다. planner의 표현 변동과 무관하게
    # 공개 USGS 원문 action 하나로 고정해 Q15 결정적 응답 경로를 보장한다.
    q15_text = re.sub(r"\s+", "", message)
    if (
        "희토류" in q15_text and "네오디뮴" in q15_text
        and any(marker in q15_text for marker in ("범위", "가격", "생산통계"))
    ):
        return ActionPlan(actions=[ActionCall(
            requirement_id="q15_scope",
            action_id="document.retrieve",
            slots=ActionSlots(
                minerals=["희토류", "네오디뮴"],
                topic=message,
            ),
            intent="concept",
            role="content",
        )])
    strategic_overview = _strategic_price_overview_plan(message)
    if strategic_overview is not None:
        return strategic_overview
    price_world_production = _price_world_production_plan(message)
    if price_world_production is not None:
        return price_world_production
    production_yoy = _production_yoy_plan(message)
    if production_yoy is not None:
        return production_yoy
    mine_yoy = _mine_yoy_rank_plan(message)
    if mine_yoy is not None:
        return mine_yoy
    future_actual_price = _future_actual_price_plan(message)
    if future_actual_price is not None:
        return future_actual_price
    price_index_comparison = _price_index_comparison_plan(message)
    if price_index_comparison is not None:
        return price_index_comparison
    weekly_price_news = _weekly_price_news_plan(message)
    if weekly_price_news is not None:
        return weekly_price_news
    # 보고서의 특정 광종을 기준으로 함께 언급된 광종 목록을 추출하는
    # 문서 요구는 월간동향 Action으로 보존한다. 실제 목록은 원문 evidence의
    # 구조화 광종목록을 renderer가 읽으며, 질문에 광종을 임의로 추가하지 않는다.
    if ("희소금속월간동향" in compact and "언급" in compact
            and any(token in compact for token in ("광종", "광물"))
            and any(token in compact for token in ("리스트", "목록", "같이"))):
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_rare_metals", action_id="document.retrieve",
            slots=ActionSlots(topic=message.replace("회소금속", "희소금속")),
            intent="document", role="content",
        )])
    rare_monthly_mineral_list = re.fullmatch(
        r"(?P<period>최근|가장최근|이번달|20\d{2}년\d{1,2}월)?(?:희소|회소)금속월간동향(?:더?프라임)?(?:에나온|에서|의)?광종(?:들이)?(?:뭐뭐|목록|어떤)(?:을)?(?:인가요|있나요|알려줘|알려주세요|인지|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if rare_monthly_mineral_list:
        period_text = rare_monthly_mineral_list.group("period")
        topic = message.replace("회소금속", "희소금속")
        period = None
        if period_text == "이번달":
            today = date.today()
            period = Period(kind="range", start=today.replace(day=1).isoformat(), end=today.isoformat(), explicit=True)
        elif period_text and period_text not in {"최근", "가장최근"}:
            match = re.fullmatch(r"(20\d{2})년(\d{1,2})월", period_text)
            assert match is not None
            year, month = int(match.group(1)), int(match.group(2))
            month_start = date(year, month, 1)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            period = Period(kind="range", start=month_start.isoformat(), end=(next_month - timedelta(days=1)).isoformat(), explicit=True)
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_rare_metals", action_id="document.facts.retrieve",
            slots=ActionSlots(topic=topic, period=period),
            intent="document", role="content",
        )])
    rare_monthly_facts = re.fullmatch(
        r"(?P<period>최근|가장최근|이번달|20\d{2}년\d{1,2}월)?(?:희소|회소)금속월간동향(?:더?프라임)?"
        r"(?:의|에대한)?(?:내용|문서내용|요약본)?(?:을|를)?요약(?:해줘|해주세요|해|하라)?[?.]?",
        compact,
    )
    if rare_monthly_facts:
        period_text = rare_monthly_facts.group("period")
        topic = message.replace("회소금속", "희소금속")
        period = None
        if period_text == "이번달":
            today = date.today()
            period = Period(kind="range", start=today.replace(day=1).isoformat(), end=today.isoformat(), explicit=True)
        elif period_text and period_text not in {"최근", "가장최근"}:
            match = re.fullmatch(r"(20\d{2})년(\d{1,2})월", period_text)
            assert match is not None
            year, month = int(match.group(1)), int(match.group(2))
            month_start = date(year, month, 1)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            period = Period(kind="range", start=month_start.isoformat(), end=(next_month - timedelta(days=1)).isoformat(), explicit=True)
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_rare_metals_facts", action_id="document.facts.retrieve",
            slots=ActionSlots(topic=topic, period=period),
            intent="document", role="content",
        )])
    # 주간뉴스 표현의 종결형은 intent planner가 처리한다. 다음 세 질문은
    # 광종/구성 목록이 원천 조회 전에는 확정되지 않는다. 임의의
    # 광종·예측값을 채우지 않고, 질문이 명시한 상대 기간만 고정한 문서 Action으로
    # 시작한다. 적재된 원천이 없으면 source_unavailable로 닫히며 slot_unresolved
    # (라우팅 오류)로 오인되지 않는다.
    rare_monthly_prices = re.fullmatch(
        r"(?P<period>이번달|최근|가장최근|20\d{2}년\d{1,2}월)(?:희소|회소)금속월간동향(?:더?프라임)?에나온광종들가격(?:은)?(?:어때|어떤가요)?[?.]?",
        compact,
    )
    if rare_monthly_prices:
        period_text = rare_monthly_prices.group("period")
        topic = message.replace("회소금속", "희소금속")
        if period_text == "이번달":
            today = date.today()
            period = Period(kind="range", start=today.replace(day=1).isoformat(), end=today.isoformat(), explicit=True)
        elif period_text in {"최근", "가장최근"}:
            # 최근/가장 최근은 현재 월로 임의 제한하지 않고, adapter가 보유한
            # 최신 월호를 선택하게 한다.
            period = None
        else:
            match = re.fullmatch(r"(20\d{2})년(\d{1,2})월", period_text)
            assert match is not None
            year, month = int(match.group(1)), int(match.group(2))
            month_start = date(year, month, 1)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            period = Period(kind="range", start=month_start.isoformat(), end=(next_month - timedelta(days=1)).isoformat(), explicit=True)
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_rare_metals", action_id="document.retrieve",
            slots=ActionSlots(topic=topic, period=period),
            intent="document", role="content",
        )])
    if re.fullmatch(r"광물종합지수구성광종중상승전망인건뭐야?[?.]?", compact):
        return ActionPlan(actions=[ActionCall(
            requirement_id="composite_constituents_forecast", action_id="document.retrieve",
            slots=ActionSlots(topic="광물종합지수 구성 광종 가격 전망",
                              period=Period(kind="trailing_months", trailing_months=3, explicit=True)),
            intent="document", role="content",
        )])
    if re.fullmatch(r"수입의존도높은광종들가격전망(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact):
        # ``수입의존도 높음``은 특정국을 임의로 가정하지 않고, 각 광종의 1위
        # 수입상대국 비중이 운영 상수(엄격히 50% 초과)를 넘는지로 판정한다.
        # 가격 예측 원천은 아직 연결되지 않았으므로 현재 연결된 수입 원천으로
        # 대상만 확정하고, renderer가 전망 부재를 명확히 안내한다.
        minerals = ("구리", "니켈", "코발트", "리튬", "희토류")
        return ActionPlan(actions=[ActionCall(
            requirement_id=f"import_dependency_{mineral}", action_id="trade.country_rank",
            slots=ActionSlots(mineral=mineral, metric="import_amount", trade_scope="korea", top_n=1,
                              period=Period(kind="trailing_months", trailing_months=12, explicit=True)),
            intent="trade_rank", role="data",
        ) for mineral in minerals])
    if re.fullmatch(r"지난달광물종합지수변동이랑월간동향요약(?:을)?(?:같이)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact):
        return ActionPlan(actions=[
            ActionCall(requirement_id="monthly_composite_index", action_id="indicator.series",
                       slots=ActionSlots(indicator="composite_index", indicator_variant="composite",
                                         indicator_operation="period_change",
                                         period=Period(kind="trailing_months", trailing_months=1, explicit=True)),
                       intent="indicator", role="data"),
            ActionCall(requirement_id="monthly_trend", action_id="document.retrieve",
                       slots=ActionSlots(topic="월간동향"), intent="document", role="content"),
        ])
    common_monthly_weekly = re.fullmatch(
        r"(?P<monthly>이번달|20\d{2}년\d{1,2}월)(?:전략광종)?월간동향이랑"
        r"(?P<weekly>이번주|20\d{2}년\d{1,2}월\d{1,2}일)(?:주간)?뉴스에공통으로나온이슈(?:는)?[?.]?",
        compact,
    )
    if common_monthly_weekly is None:
        common_monthly_weekly = re.fullmatch(
            r"(?P<monthly>이번달|20\d{2}년\d{1,2}월)(?:전략광종)?월간동향(?:과|와|및)"
            r"(?P<weekly>이번주|20\d{2}년\d{1,2}월\d{1,2}일)(?:주간)?뉴스에공통으로나온이슈(?:는)?[?.]?",
            compact,
        )
    if common_monthly_weekly:
        today = date.today()
        monthly_text, weekly_text = common_monthly_weekly.group("monthly"), common_monthly_weekly.group("weekly")
        monthly_period = _written_month_period(monthly_text, today)
        weekly_period = _written_week_period(weekly_text, today)
        return ActionPlan(actions=[
            ActionCall(requirement_id="monthly_trend", action_id="document.retrieve",
                       slots=ActionSlots(topic=f"{monthly_text} 전략광종 월간동향", period=monthly_period), intent="document", role="content"),
            ActionCall(requirement_id="weekly_news", action_id="document.retrieve",
                       slots=ActionSlots(topic=f"{weekly_text} 주간동향", period=weekly_period), intent="document", role="content"),
        ])
    monthly_import_structure = re.fullmatch(
        r"(?P<period>이번달|20\d{2}년\d{1,2}월)전략광종월간동향에나온광종들우리수입구조(?:어때)?[?.]?",
        compact,
    )
    if monthly_import_structure:
        period_text = monthly_import_structure.group("period")
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_trend", action_id="document.retrieve",
            slots=ActionSlots(topic=f"{period_text} 전략광종 월간동향", period=_written_month_period(period_text, date.today())),
            intent="document", role="content",
        )])
    monthly_mineral_info = re.fullmatch(
        r"(?P<period>이번달|20\d{2}년\d{1,2}월)전략광종월간동향에서다룬광종기본정보(?:를)?(?:알려줘)?[?.]?",
        compact,
    )
    if monthly_mineral_info:
        period_text = monthly_mineral_info.group("period")
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_trend", action_id="document.retrieve",
            slots=ActionSlots(topic=f"{period_text} 전략광종 월간동향 광종 기본 정보", period=_written_month_period(period_text, date.today())),
            intent="document", role="content",
        )])
    if re.fullmatch(r"광물지수오를때같이오른광종은뭐야?[?.]?", compact):
        period = Period(kind="trailing_months", trailing_months=3, explicit=True)
        actions = [ActionCall(
            requirement_id="composite_index_trend", action_id="indicator.series",
            slots=ActionSlots(indicator="composite_index", indicator_variant="composite",
                              indicator_operation="period_change", period=period),
            intent="indicator", role="data",
        )]
        # 광물종합지수 원천은 전체/하위지수만 제공하므로, "같이 오른 광종"은
        # 시스템 대상 5광종(CU·NI·CO·LI·REE)의 같은 보유기간 가격 시계열로
        # 별도 검증한다. 지수 구성광종이라고 단정하지 않는다.
        actions.extend(ActionCall(
            requirement_id=f"index_co_rise_{mineral}", action_id="price.series",
            slots=ActionSlots(mineral=mineral, period=period), intent="price_series", role="data",
            depends_on=["composite_index_trend"],
        ) for mineral in ("구리", "니켈", "코발트", "리튬", "희토류"))
        return ActionPlan(actions=actions)
    if re.fullmatch(r"광물종합지수떨어진주에주요뉴스뭐있었어?[?.]?", compact):
        return ActionPlan(actions=[
            ActionCall(requirement_id="weekly_index", action_id="indicator.series",
                       slots=ActionSlots(indicator="composite_index", indicator_variant="composite",
                                         indicator_operation="period_change", period=Period(kind="trailing_months", trailing_months=3, explicit=True),
                                         topic="광물종합지수 하락 주간 주요 뉴스"), intent="indicator", role="data"),
        ])
    forecast_monthly = re.fullmatch(r"(?P<mineral>[가-힣A-Za-z0-9]+?)가격전망이랑월간동향시장전망내용(?:을)?(?:비교해줘|비교해주세요|알려줘|알려주세요)?[?.]?", compact)
    if forecast_monthly:
        mineral = forecast_monthly.group("mineral")
        return ActionPlan(actions=[
            ActionCall(requirement_id="forecast", action_id="forecast.price",
                       slots=ActionSlots(mineral=mineral, forecast_operation="direction"), intent="forecast_price", role="data"),
            ActionCall(requirement_id="monthly", action_id="document.retrieve",
                       slots=ActionSlots(mineral=mineral, topic=f"{mineral} 월간동향 시장 전망"), intent="document", role="content"),
        ])
    forecast_news = re.fullmatch(r"(?P<mineral>[가-힣A-Za-z0-9]+?)가격전망이랑최근관련뉴스(?:를)?(?:같이)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact)
    if forecast_news:
        mineral = forecast_news.group("mineral")
        return ActionPlan(actions=[
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral=mineral, forecast_operation="direction"), intent="forecast_price", role="data"),
            ActionCall(requirement_id="news", action_id="document.retrieve", slots=ActionSlots(mineral=mineral, topic=f"최근 {mineral} 자원뉴스", period=Period(kind="trailing_months", trailing_months=3)), intent="document", role="content"),
        ])
    import_forecast = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?주요수입국(?:이랑|과|와|및)?가격전망(?:을)?(?:같이)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if import_forecast:
        mineral = MINERAL_ALIASES.get(import_forecast.group("mineral").casefold(), import_forecast.group("mineral"))
        return ActionPlan(actions=[
            ActionCall(requirement_id="import_countries", action_id="trade.country_rank",
                       slots=ActionSlots(mineral=mineral, metric="import_amount", trade_scope="korea", top_n=5,
                                         period=Period(kind="trailing_months", trailing_months=12)), intent="trade_rank", role="data"),
            ActionCall(requirement_id="forecast", action_id="forecast.price",
                       slots=ActionSlots(mineral=mineral, forecast_operation="direction"), intent="forecast_price", role="data"),
        ])
    mineral_info_geography = _mineral_info_geography_plan(message)
    if mineral_info_geography is not None:
        return mineral_info_geography
    price_forecast_continuation = _price_forecast_continuation_plan(message)
    if price_forecast_continuation is not None:
        return price_forecast_continuation
    price_forecast_pair = _price_forecast_pair_plan(message)
    if price_forecast_pair is not None:
        return price_forecast_pair
    # 화면 이동은 가격 수치 조회와 다른 page-recommend 계약이다. 이 좁은
    # 문형을 최신가격 shortcut보다 먼저 닫아 ``리튬 가격 화면으로 가줘``가
    # 가격 데이터 조회로 축약되지 않게 한다.
    price_page = _price_page_navigation_plan(message)
    if price_page is not None:
        return price_page
    # 기존 독립 집계 계약으로 표현 가능한 추가 질의는 semantic LLM이
    # ``trade/price_series``처럼 잘못 분류해도 deterministic typed plan으로
    # 복원한다. 결과 의존·동적 worklist는 이 경로에 넣지 않는다.
    monthly_trade = _monthly_trade_plan(message)
    if monthly_trade is not None:
        return monthly_trade
    multi_latest_prices = _multi_latest_price_table_plan(message)
    if multi_latest_prices is not None:
        return multi_latest_prices
    historical_extrema = _historical_price_extrema_plan(message)
    if historical_extrema is not None:
        return historical_extrema
    supply_stability = _supply_stability_latest_plan(message)
    if supply_stability is not None:
        return supply_stability
    hs_code_lookup = _hs_code_lookup_plan(message)
    if hs_code_lookup is not None:
        return hs_code_lookup
    price_operation = _price_operation_plan(message)
    if price_operation is not None:
        return price_operation
    composite_index = _composite_index_plan(message)
    if composite_index is not None:
        return composite_index
    forecast_price = _forecast_price_plan(message)
    if forecast_price is not None:
        return forecast_price
    latest_inventory = _latest_inventory_plan(message)
    if latest_inventory is not None:
        return latest_inventory
    latest_price = _latest_price_plan(message)
    if latest_price is not None:
        return latest_price
    known_mine_profile = _known_mine_profile_plan(message)
    if known_mine_profile is not None:
        return known_mine_profile
    explicit_document_plan = _explicit_dated_document_plan(message)
    if explicit_document_plan is not None:
        return explicit_document_plan
    export_control_share = _export_control_import_share_plan(message)
    if export_control_share is not None:
        return export_control_share
    if re.fullmatch(r"이번달전략광종월간동향에나온광종들우리수입구조(?:어때)?[?.]?", compact):
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_trend", action_id="document.retrieve",
            slots=ActionSlots(topic="이번 달 전략광종 월간동향"), intent="document", role="content",
        )])
    publication_plan = _publication_document_plan(message)
    if publication_plan is not None:
        return publication_plan
    # 특정국 의존도는 HHI와의 경계가 명확한 typed 관계다. 모델이 HHI를
    # 별도 requirement로 과분해하면 validation/repair 전에 실패할 수 있으므로
    # 해당 문맥에서만 결정적 계획을 먼저 사용한다.
    simple_country_share = _simple_country_share_plan(message)
    if simple_country_share is not None:
        return simple_country_share
    explicit_trade_indicator = _explicit_annual_trade_indicator_plan(message)
    if explicit_trade_indicator is not None:
        return explicit_trade_indicator
    if not allow_llm:
        return None
    intent_plan = extract_intent_plan(message, llm, history)
    semantic_failure = _intent_plan_semantic_failure(intent_plan)
    if semantic_failure:
        intent_plan = repair_intent_plan(message, llm, semantic_failure, history)
    plan = action_plan_from_intent(intent_plan, message)
    plan = _normalize_report_search_period(message, plan)
    plan = _normalize_weekly_document_period(message, plan)
    plan = normalize_country_rank_request(message, plan)
    _normalize_trade_rank_scope(plan.actions, message)
    assessment = validate_action_plan(plan)
    if assessment.approved or assessment.failure_reason not in {"slot_unresolved", "unsupported_combination"}:
        return plan
    # 모델 출력의 role/중복 오류만 한 번 고친다. 원천 미연결은 재시도로
    # available action처럼 바꾸지 않는다.
    repaired = action_plan_from_intent(repair_intent_plan(message, llm, assessment.failure_reason, history), message)
    repaired = _normalize_report_search_period(message, repaired)
    repaired = normalize_country_rank_request(message, repaired)
    _normalize_trade_rank_scope(repaired.actions, message)
    if (validate_action_plan(repaired).failure_reason == "slot_unresolved"
            and _has_source_unavailable_predecessor(history or [], repaired)):
        repaired.predecessor_source_unavailable = True
    return repaired


def _known_mine_profile_plan(message: str) -> ActionPlan | None:
    """공개 OKF가 고정된 단일 광산 수락 질의를 LLM 변동 없이 보존한다."""
    compact = re.sub(r"\s+", "", message).casefold()
    if not (
        "bhp보고서" in compact and "escondida" in compact
        and any(marker in compact for marker in ("어느나라", "국가", "위치"))
    ):
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="mine_profile", action_id="mine.profile",
        slots=ActionSlots(mine_name="Escondida", topic="BHP 보고서"),
        intent="mine_profile", role="data",
    )])


def _explicit_annual_trade_indicator_plan(message: str) -> ActionPlan | None:
    """완결된 한국 연간 무역지표는 기간 HITL 없이 typed 상태로 보존한다."""
    compact = re.sub(r"\s+", "", message).casefold()
    year = re.search(r"(20\d{2})년", compact)
    if not year or "한국" not in compact:
        return None
    metric = next((value for value, markers in (
        ("rca", ("현시비교우위", "rca")),
        ("tsi", ("무역특화", "tsi")),
        ("trade_growth", ("수출입증감률", "무역증감률")),
    ) if any(marker in compact for marker in markers)), None)
    mineral = next((name for name in ("리튬", "니켈", "코발트", "구리", "동", "희토류", "흑연")
                    if name in compact), None)
    if metric is None or mineral is None:
        return None
    flow = "export" if "수출" in compact else ("import" if "수입" in compact else None)
    if metric == "trade_growth" and flow is None:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="annual_trade_indicator", action_id="trade.indicator",
        slots=ActionSlots(
            mineral=mineral, flow=flow, trade_metric=metric, reporter_country="한국",
            period=Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True),
        ), intent="trade_indicator", role="data",
    )])


def _strategic_price_overview_plan(message: str) -> ActionPlan | None:
    """YAML 전략광종 목록의 단일 최신 가격 현황 요청만 결정적으로 처리한다."""
    compact = re.sub(r"\s+", "", message)
    group: list[Literal["strategic_six", "strategic_ten", "battery_five"]] | None = None
    if re.fullmatch(r"6대전략광종가격현황(?:을)?(?:한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["strategic_six"]
    elif re.fullmatch(r"10대전략광종가격현황(?:을)?(?:한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["strategic_ten"]
    elif re.fullmatch(r"전략광종가격현황(?:을)?(?:한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["strategic_six", "strategic_ten"]
    elif re.fullmatch(r"2차전지광물5종가격(?:이랑)?(?:현황)?(?:을)?(?:한번에|한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["battery_five"]
    if group is None:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="strategic_price_overview", action_id="price.overview",
        slots=ActionSlots(strategic_price_groups=group), intent="price_series", role="data",
    )])


def _production_yoy_plan(message: str) -> ActionPlan | None:
    """임의 광종의 세계 생산량 전년 대비 단일 문형을 LLM 없이 고정한다."""
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(r"(?:(20\d{2})년)?(.+?)(?:의)?생산량(?:이)?전년대비(?:얼마나)?(?:늘었어|늘었나요|증가했어|증가했나요|변했어|변했나요)[?.]?", compact)
    if not match:
        return None
    year, mineral = match.groups()
    return ActionPlan(actions=[ActionCall(
        requirement_id="world_production_yoy", action_id="resource.yoy",
        slots=ActionSlots(mineral=mineral, metric="production", country_scope="world",
                          period=Period(kind="calendar_year", calendar_year=int(year), explicit=True) if year else None),
        intent="resource_yoy", role="data",
    )])


def _price_world_production_plan(message: str) -> ActionPlan | None:
    """가격과 세계 생산량 YoY를 함께 묻는 닫힌 복합 문형을 고정한다.

    ``세계 생산량 변화``는 국가별 최신 순위가 아니라 세계 총계의 연속 연도
    증감률이다. 가격은 같은 연도 평균 집계 Action으로 고정해 두 결과의 시간
    단위를 맞추고, 명시적 전년 대비 문형은 단일 ``resource.yoy`` 계획으로
    계속 처리한다.
    """
    compact = re.sub(r"\s+", "", message)
    mineral = r"(?:리튬|니켈|코발트|구리|동|망간|흑연|텅스텐|희토류|네오디뮴)"
    patterns = (
        rf"(?P<mineral>{mineral})(?:의)?가격(?:이랑|과|와|및)(?:세계)?생산량"
        r"(?:변화|추이)(?:같이|함께)?(?:보여줘|보여주세요|알려줘|알려주세요|표시해줘|표시해주세요)?[?.]?",
        rf"(?:세계)?생산량(?:변화|추이)(?:이랑|랑|과|와|및)(?P<mineral>{mineral})"
        r"(?:의)?가격(?:을|를)?(?:같이|함께)?(?:보여줘|보여주세요|알려줘|알려주세요|표시해줘|표시해주세요)?[?.]?",
    )
    match = next(
        (candidate for pattern in patterns
         if (candidate := re.fullmatch(pattern, compact, flags=re.IGNORECASE))),
        None,
    )
    if not match:
        return None
    mineral = MINERAL_ALIASES.get(match.group("mineral").casefold(), match.group("mineral"))
    return ActionPlan(actions=[
        ActionCall(
            requirement_id="mineral_price", action_id="price.series",
            slots=ActionSlots(mineral=mineral, period=Period(kind="latest"), price_operation="yearly_average",
                              requested_outputs={"text"}),
            intent="price_series", role="data", requested_outputs={"text"},
        ),
        ActionCall(
            requirement_id="world_production_yoy", action_id="resource.yoy",
            slots=ActionSlots(mineral=mineral, metric="production", country_scope="world",
                              requested_outputs={"text"}),
            intent="resource_yoy", role="data", requested_outputs={"text"},
        ),
    ])


def _mine_yoy_rank_plan(message: str) -> ActionPlan | None:
    """완결된 광산 YoY 상위 순위는 planner 오분류 없이 닫힌 Action으로 만든다."""

    compact = re.sub(r"\s+", "", message).casefold()
    match = re.fullmatch(
        r"(?P<mineral>.+?)광산(?P<metric>생산량|산출량|매장량)(?:최근)?"
        r"(?:yoy|전년대비)(?P<direction>증가|늘어남|감소|축소)"
        r"(?:상위|top)(?P<top_n>\d{1,3})(?:개|곳|위)?(?:를)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?",
        compact,
    )
    if not match:
        return None
    top_n = int(match.group("top_n"))
    if not 1 <= top_n <= 100:
        return None
    metric = "production" if match.group("metric") in {"생산량", "산출량"} else "reserves"
    direction = match.group("direction")
    order = "yoy_increase" if direction in {"증가", "늘어남"} else "yoy_decrease"
    return ActionPlan(actions=[ActionCall(
        requirement_id="mine_yoy_rank", action_id="mine.rank",
        slots=ActionSlots(mineral=match.group("mineral"), mine_metric=metric,
                          mine_order=order, top_n=top_n),
        intent="mine_rank", role="data",
    )])


def _future_actual_price_plan(message: str) -> ActionPlan | None:
    """아직 존재하지 않는 미래 실측 가격 요구를 결정적으로 닫는다."""
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(20\d{2})년(구리|니켈|코발트|리튬|희토류|Nd)(?:의)?"
        r"(?:실제|실측)월별가격(?:을)?차트로(?:보여줘|보여주세요)[?.]?"
        r"아직없는실측자료라면없다고(?:알려줘|알려주세요)[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    target_year = int(match.group(1))
    if target_year <= date.today().year:
        return None
    horizon = min(120, max(1, (target_year - date.today().year) * 12))
    return ActionPlan(actions=[ActionCall(
        requirement_id="future_actual_price",
        action_id="price.series",
        slots=ActionSlots(
            mineral=match.group(2),
            period=Period(kind="future_horizon", future_horizon=horizon,
                          frequency="monthly", explicit=True),
            requested_outputs={"text", "chart"},
        ),
        intent="price_series",
        role="data",
        requested_outputs={"text", "chart"},
    )])


def _mineral_info_geography_plan(message: str) -> ActionPlan | None:
    """검증된 광종정보와 국가 순위를 함께 묻는 닫힌 복합 문형."""
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?(?:용도|어디에쓰여|어디쓰여|사용처)(?:랑|와|과|및)?(?:(?:주요|수입)?수입(?:상위)?국|세계생산(?:상위)?국)(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if not match:
        return None
    mineral = MINERAL_ALIASES.get(match.group("mineral").casefold(), match.group("mineral"))
    is_import = "수입" in compact
    geography = ActionCall(
        requirement_id="import_countries" if is_import else "production_countries",
        action_id="trade.country_rank" if is_import else "resource.rank",
        slots=(ActionSlots(
            mineral=mineral, metric="import_amount", trade_scope="korea", top_n=5,
            period=Period(kind="trailing_months", trailing_months=12),
        ) if is_import else ActionSlots(
            mineral=mineral, metric="production", country_scope="world", top_n=5,
        )),
        intent="trade_rank" if is_import else "resource_rank", role="data",
    )
    return ActionPlan(actions=[
        ActionCall(
            requirement_id="mineral_info", action_id="document.retrieve",
            slots=ActionSlots(mineral=mineral, topic=f"{mineral} 용도"), intent="concept", role="content",
        ),
        geography,
    ])


def _price_forecast_pair_plan(message: str) -> ActionPlan | None:
    """현재 실측 가격과 다음 예측값을 함께 요구한 닫힌 문형."""
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?(?:현재|지금)?가격(?:이랑|과|와|및)?다음달(?:가격)?전망(?:을)?(?:같이)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    if not match:
        return None
    mineral = MINERAL_ALIASES.get(match.group("mineral").casefold(), match.group("mineral"))
    return ActionPlan(actions=[
        ActionCall(
            requirement_id="current_price", action_id="price.series",
            slots=ActionSlots(mineral=mineral, period=Period(kind="latest")),
            intent="price_series", role="data",
        ),
        ActionCall(
            requirement_id="next_month_forecast", action_id="forecast.price",
            slots=ActionSlots(mineral=mineral, period=Period(kind="future_horizon", future_horizon=1),
                              forecast_operation="next_month_value"),
            intent="forecast_price", role="data",
        ),
    ])


def _price_forecast_continuation_plan(message: str) -> ActionPlan | None:
    """실적-전망 연결 및 현재가-전망치 비교의 닫힌 출력 계약."""
    compact = re.sub(r"\s+", "", message)
    timeline = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?지난(?P<months>\d+)개월가격(?:이랑|과|와|및)?향후전망(?:을)?(?:이어서)?(?:보여줘|알려줘|보여주세요|알려주세요)?[?.]?",
        compact,
    )
    compare = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?(?:지금|현재)?가격(?:이)?전망치보다높은편이야?[?.]?",
        compact,
    )
    if timeline:
        months = int(timeline.group("months"))
        if not 1 <= months <= 240:
            return None
        mineral = MINERAL_ALIASES.get(timeline.group("mineral").casefold(), timeline.group("mineral"))
        return ActionPlan(actions=[
            ActionCall(requirement_id="actual_trend", action_id="price.series",
                       slots=ActionSlots(mineral=mineral, period=Period(kind="trailing_months", trailing_months=months, explicit=True),
                                         requested_outputs={"text", "table", "chart"}),
                       intent="price_series", role="data", requested_outputs={"text", "table", "chart"}),
            ActionCall(requirement_id="forecast_timeline", action_id="forecast.price",
                       slots=ActionSlots(mineral=mineral, forecast_operation="timeline", requested_outputs={"text", "table", "chart"}),
                       intent="forecast_price", role="data", requested_outputs={"text", "table", "chart"}),
        ])
    if compare:
        mineral = MINERAL_ALIASES.get(compare.group("mineral").casefold(), compare.group("mineral"))
        return ActionPlan(actions=[
            ActionCall(requirement_id="current_price", action_id="price.series",
                       slots=ActionSlots(mineral=mineral, period=Period(kind="latest")), intent="price_series", role="data"),
            ActionCall(requirement_id="forecast_compare", action_id="forecast.price",
                       slots=ActionSlots(mineral=mineral, forecast_operation="compare_current"), intent="forecast_price", role="data"),
        ])
    return None


def _weekly_price_news_plan(message: str) -> ActionPlan | None:
    """완료 주 또는 진행 중인 이번 주의 가격 변동 상위 광종과 뉴스만 결합한다."""
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?P<which>지난|이번)주가격변동큰광종이랑관련뉴스(?:를)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?",
        compact,
    )
    if not match:
        return None
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    if match.group("which") == "지난":
        end = this_monday - timedelta(days=1)
        start = end - timedelta(days=6)
    else:
        start, end = this_monday, today
    period = Period(kind="range", start=start.isoformat(), end=end.isoformat(), explicit=True)
    return ActionPlan(actions=[
        ActionCall(requirement_id="weekly_price_volatility", action_id="price.volatility_rank",
                   slots=ActionSlots(period=period, top_n=5), intent="price_compare", role="data"),
    ])


def _written_month_period(value: str, today: date) -> Period:
    """이번달 또는 YYYY년 M월을 문서 월호에 맞는 닫힌 기간으로 바꾼다."""
    if value == "이번달":
        return Period(kind="range", start=today.replace(day=1).isoformat(), end=today.isoformat(), explicit=True)
    match = re.fullmatch(r"(20\d{2})년(\d{1,2})월", value)
    if not match:
        raise ValueError(f"유효하지 않은 월 표현: {value}")
    start = date(int(match.group(1)), int(match.group(2)), 1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return Period(kind="range", start=start.isoformat(), end=end.isoformat(), explicit=True)


def _written_week_period(value: str, today: date) -> Period:
    """이번주 또는 YYYY년 M월 D일을 주간 보고서 발행일의 닫힌 기간으로 바꾼다."""
    if value == "이번주":
        return Period(kind="range", start=(today - timedelta(days=today.weekday())).isoformat(), end=today.isoformat(), explicit=True)
    match = re.fullmatch(r"(20\d{2})년(\d{1,2})월(\d{1,2})일", value)
    if not match:
        raise ValueError(f"유효하지 않은 주간 발행일 표현: {value}")
    published = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return Period(kind="range", start=published.isoformat(), end=published.isoformat(), explicit=True)


def _normalize_weekly_document_period(message: str, plan: ActionPlan) -> ActionPlan:
    """LLM이 주간 문서 질의로 분류한 뒤 '이번주'의 날짜 경계만 확정한다."""
    compact = re.sub(r"\s+", "", message)
    if "이번주" not in compact or not any(marker in compact for marker in ("자원뉴스", "주간뉴스", "주간동향")):
        return plan
    documents = [call for call in plan.actions if call.action_id == "document.retrieve"]
    if len(documents) != 1:
        return plan
    call = documents[0]
    period = _written_week_period("이번주", date.today())
    topic = call.slots.topic or message
    if "주간" not in re.sub(r"\s+", "", topic):
        topic = f"{topic} 주간동향"
    slots = call.slots.model_copy(update={"topic": topic, "period": period})
    updated = call.model_copy(update={"slots": slots})
    return plan.model_copy(update={"actions": [updated if item is call else item for item in plan.actions]})


def _normalize_report_search_period(message: str, plan: ActionPlan, *, today: date | None = None) -> ActionPlan:
    """기간이 명시된 보고서 검색은 planner 누락과 무관하게 날짜 슬롯을 보존한다."""
    compact = re.sub(r"\s+", "", message)
    if "보고서" not in compact:
        return plan
    calls = [call for call in plan.actions if call.action_id == "document.retrieve"]
    if len(calls) != 1:
        return plan
    today = today or date.today()
    period = None
    recent = re.search(r"최근(\d+)(개월|년)", compact)
    year_month = re.search(r"(20\d{2})년(\d{1,2})월", compact)
    year = re.search(r"(20\d{2})년", compact)
    if recent:
        months = int(recent.group(1)) * (12 if recent.group(2) == "년" else 1)
        if 1 <= months <= 240:
            period = Period(kind="trailing_months", trailing_months=months, explicit=True)
    elif year_month and 1 <= int(year_month.group(2)) <= 12:
        start = date(int(year_month.group(1)), int(year_month.group(2)), 1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        period = Period(kind="range", start=start.isoformat(), end=end.isoformat(), explicit=True)
    elif "지난달" in compact:
        start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        end = today.replace(day=1) - timedelta(days=1)
        period = Period(kind="range", start=start.isoformat(), end=end.isoformat(), explicit=True)
    elif year:
        period = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
    elif "작년" in compact:
        period = Period(kind="calendar_year", calendar_year=today.year - 1, explicit=True)
    elif "올해" in compact:
        period = Period(kind="calendar_year", calendar_year=today.year, explicit=True)
    if period is None:
        return plan
    call = calls[0]
    topic = call.slots.topic or message
    if "보고서" not in re.sub(r"\s+", "", topic):
        topic = f"{topic} 보고서"
    updated = call.model_copy(update={"slots": call.slots.model_copy(update={
        "topic": topic, "period": period,
    })})
    return plan.model_copy(update={"actions": [updated if item is call else item for item in plan.actions]})


def _price_index_comparison_plan(message: str) -> ActionPlan | None:
    """광종 가격과 HI001의 같은 기간 추세 비교를 두 typed action으로 보존한다.

    가격과 종합지수는 단위와 정의가 달라 값 자체를 합치지 않는다. 두 시계열의
    시작·종료 관측값으로 각각의 변동률만 계산하는 renderer 계약(OC05)에 맞춰,
    기간을 반드시 동일하게 넣는다.
    """
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?:최근(?P<months>\d+)개월)?(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격(?:추이|추세)(?:랑|와|과|및)?광물종합지수(?:의)?추세(?:를)?(?:비교해줘|비교해주세요|비교해|보여줘|알려줘)[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    months = int(match.group("months") or 12)
    if not 1 <= months <= 240:
        return None
    mineral = MINERAL_ALIASES.get(match.group("mineral").casefold(), match.group("mineral"))
    period = Period(kind="trailing_months", trailing_months=months, explicit=bool(match.group("months")))
    return ActionPlan(actions=[
        ActionCall(
            requirement_id="mineral_price_trend", action_id="price.series",
            slots=ActionSlots(mineral=mineral, period=period, requested_outputs={"text", "chart"}),
            intent="price_series", role="data", requested_outputs={"text", "chart"},
        ),
        ActionCall(
            requirement_id="composite_index_trend", action_id="indicator.series",
            slots=ActionSlots(
                indicator="composite_index", indicator_variant="composite",
                indicator_operation="period_change", period=period,
                requested_outputs={"text", "chart"},
            ),
            intent="indicator", role="data", requested_outputs={"text", "chart"},
        ),
    ])


def _price_page_navigation_plan(message: str) -> ActionPlan | None:
    """광종 가격 화면 이동 요청을 ``menu.navigate``로 보존한다."""
    compact = re.sub(r"\s+", "", message)
    minerals = "리튬|니켈|코발트|구리|동|아연|텅스텐|희토류|망간|흑연|네오디뮴"
    match = re.fullmatch(
        rf"(?P<mineral>{minerals})(?:의)?가격(?:화면|페이지)(?:으로|에)?"
        r"(?:가줘|가주세요|이동해줘|이동해주세요|보여줘|보여주세요)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    mineral = MINERAL_ALIASES.get(match.group("mineral").casefold(), match.group("mineral"))
    base_metals = {"니켈", "구리", "동", "아연"}
    target_page = "price_base_metals" if mineral in base_metals else "price_minor_metals"
    return ActionPlan(actions=[ActionCall(
        requirement_id="price_page",
        action_id="menu.navigate",
        slots=ActionSlots(target_page=target_page, mineral=mineral),
        intent="menu",
        role="metadata",
    )])


def _monthly_trade_plan(message: str) -> ActionPlan | None:
    """금액·중량의 월별 교역을 기존 ``trade.monthly`` 계약으로 복원한다.

    이 보정은 질문에 광종·방향·금액/중량·기간이 모두 드러난 완결 문형만
    처리한다. 국가 순위나 결과 기반 후속 질의에는 적용하지 않는다.
    """
    compact = re.sub(r"\s+", "", message)
    mineral = next((name for name in (
        "리튬", "니켈", "코발트", "구리", "동", "망간", "흑연", "텅스텐", "희토류", "아연",
    ) if name in compact), None)
    if mineral is None or "수입" not in compact and "수출" not in compact:
        return None
    flow = "import" if "수입" in compact else "export"
    metric_names: list[tuple[str, tuple[str, ...]]] = []
    if any(marker in compact for marker in ("수입액", "수출액", "금액")):
        metric_names.append((f"{flow}_amount", ("amount",)))
    if any(marker in compact for marker in ("수입중량", "수출중량", "중량", "물량")):
        metric_names.append((f"{flow}_weight", ("weight",)))
    if not metric_names:
        return None

    periods: list[Period] = []
    month_windows = [int(value) for value in re.findall(r"(?:최근|[·,/]?)(\d+)(?:개월|달)", compact)]
    if month_windows:
        for months in sorted(set(month_windows)):
            if 1 <= months <= 240:
                periods.append(Period(kind="trailing_months", trailing_months=months, explicit=True))
    year_range = re.search(r"(20\d{2})년(\d{1,2})[~∼〜-](\d{1,2})월", compact)
    if year_range:
        year, start_month, end_month = map(int, year_range.groups())
        if 1 <= start_month <= end_month <= 12:
            periods.append(Period(
                kind="range",
                start=f"{year:04d}-{start_month:02d}-01",
                end=f"{year:04d}-{end_month:02d}-{monthrange(year, end_month)[1]:02d}",
                frequency="monthly",
                explicit=True,
            ))
    if not periods:
        return None
    outputs: set[Literal["text", "table", "chart", "menu", "raw_data"]] = {"text"}
    if "표" in compact:
        outputs.add("table")
    if "차트" in compact or "그래프" in compact:
        outputs.add("chart")
    actions: list[ActionCall] = []
    for period in periods:
        period_key = (
            f"{period.trailing_months}m" if period.kind == "trailing_months"
            else f"{period.start[:7]}_{period.end[:7]}"
        )
        for metric, _ in metric_names:
            actions.append(ActionCall(
                requirement_id=f"trade_monthly_{metric}_{period_key}",
                action_id="trade.monthly",
                slots=ActionSlots(
                    mineral=MINERAL_ALIASES.get(mineral.casefold(), mineral),
                    metric=metric,
                    flow=flow,
                    period=period,
                    requested_outputs=set(outputs),
                ),
                intent="trade_monthly",
                role="data",
                requested_outputs=set(outputs),
            ))
    return ActionPlan(actions=actions)


def _historical_price_extrema_plan(message: str) -> ActionPlan | None:
    """과거부터 현재까지 가격 최고값·일자를 raw price 시계열로 요청한다."""
    compact = re.sub(r"\s+", "", message)
    minerals = "리튬|니켈|코발트|구리|동|망간|흑연|텅스텐|희토류|아연|네오디뮴"
    match = re.fullmatch(
        rf"(?P<mineral>{minerals})(?:의)?가격(?P<year>20\d{{2}})년(?:이후|부터)"
        r"(?:최고가|고점)(?:와|및|과)?(?:그)?(?:날짜|일자)(?:를)?"
        r"(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    start_year = int(match.group("year"))
    if start_year > date.today().year:
        return None
    mineral = MINERAL_ALIASES.get(match.group("mineral").casefold(), match.group("mineral"))
    return ActionPlan(actions=[ActionCall(
        requirement_id="price_extrema",
        action_id="price.series",
        slots=ActionSlots(
            mineral=mineral,
            period=Period(kind="range", start=f"{start_year:04d}-01-01",
                          end=date.today().isoformat(), explicit=True),
            price_operation="period_extrema",
            requested_outputs={"text", "table"},
        ),
        intent="price_series",
        role="data",
        requested_outputs={"text", "table"},
    )])


def _multi_latest_price_table_plan(message: str) -> ActionPlan | None:
    """여러 광종의 최신 가격·기준일·단위 표를 독립 price.series로 분해한다.

    광종 목록은 질문에 실제로 적힌 정식 명칭만 사용한다. 결과에 따라 광종을
    동적으로 확장하지 않는 bounded fan-out이며, 각 가격 근거는 기존
    ``price.series`` 계약과 Renderer를 그대로 재사용한다.
    """
    compact = re.sub(r"[\s,·、/]+", "", message)
    if "광종" not in compact or "최신가격" not in compact or "표" not in compact:
        return None
    # ADD38의 ``7개 광종``은 질문에서 집합 크기를 명시한 bounded 표시 집합이다.
    # 결과를 보고 광종을 동적으로 확장하지 않으며, 별도 physical action도 만들지 않는다.
    if "7개광종" in compact:
        minerals = ["리튬", "니켈", "코발트", "희토류", "구리", "텅스텐", "아연"]
    else:
        known = (
            "희토류", "네오디뮴", "리튬", "니켈", "코발트", "구리", "동", "망간",
            "흑연", "텅스텐", "아연", "몰리브덴", "알루미늄", "철광석", "유연탄",
            "우라늄", "금", "은", "백금", "주석", "연",
        )
        minerals = []
        for name in known:
            if name in compact and name not in minerals:
                minerals.append(name)
    if len(minerals) < 2:
        return None
    outputs: set[Literal["text", "table", "chart", "menu", "raw_data"]] = {"text", "table"}
    if "차트" in compact or "그래프" in compact:
        outputs.add("chart")
    return ActionPlan(actions=[ActionCall(
        requirement_id=f"latest_price_{MINERAL_ALIASES.get(mineral.casefold(), mineral)}",
        action_id="price.series",
        slots=ActionSlots(
            mineral=MINERAL_ALIASES.get(mineral.casefold(), mineral),
            period=Period(kind="latest"), requested_outputs=set(outputs),
        ),
        intent="price_series", role="data", requested_outputs=set(outputs),
    ) for mineral in minerals])


def _supply_stability_latest_plan(message: str) -> ActionPlan | None:
    """수급안정화지수 최신값·위기 여부를 indicator action으로 보존한다."""
    compact = re.sub(r"\s+", "", message)
    if "수급안정화지수" not in compact or not any(marker in compact for marker in ("최근값", "최근치", "현재값", "위기")):
        return None
    mineral = next((name for name in ("리튬", "니켈", "코발트", "구리", "동", "희토류", "흑연") if name in compact), None)
    return ActionPlan(actions=[ActionCall(
        requirement_id="supply_stability_latest",
        action_id="indicator.series",
        slots=ActionSlots(indicator="supply_stability", mineral=mineral, period=Period(kind="latest")),
        intent="indicator",
        role="data",
    )])


def _hs_code_lookup_plan(message: str) -> ActionPlan | None:
    """광종의 HS 코드 목록은 문서/원문 lookup으로 보존한다."""
    compact = re.sub(r"\s+", "", message)
    if "HS코드" not in compact or not any(marker in compact for marker in ("목록", "해당", "리스트")):
        return None
    # 명시 10자리 HS 품목·수입현황은 기존 trade.hs_summary 계약의 소유다.
    if re.search(r"(?<!\d)\d{10}(?!\d)", compact):
        return None
    mineral = next((name for name in ("리튬", "니켈", "코발트", "구리", "동", "희토류", "흑연", "텅스텐", "아연") if name in compact), None)
    if mineral is None:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="hs_code_lookup",
        action_id="document.lookup",
        slots=ActionSlots(mineral=mineral, topic=f"{mineral} HS코드 목록"),
        intent="okf_lookup",
        role="content",
    )])


def _price_operation_plan(message: str) -> ActionPlan | None:
    """정의가 닫힌 가격 집계 문형을 LLM 없이 typed slot으로 보존한다."""
    compact = re.sub(r"[\s,]", "", message)

    extrema = re.fullmatch(
        r"(?:최근)?(?P<count>\d+)(?P<unit>개월|년)(?:치)?(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격"
        r"(?:을)?(?:조회하고|기준으로|중에서|중)(?:그중)?(?:가격이|가격)?"
        r"(?P<direction>가장높|최고|가장낮|최저)(?:았던|였던|인)?(?:시점|날짜|일자)(?:은|는)?"
        r"(?:(?:와|과)?전체(?:도)?(?:함께)?(?:보여줘|보여주세요|알려줘|알려주세요)?)?"
        r"(?:언제|언제인가요?|어디야|무엇이야|알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if extrema:
        months = int(extrema.group("count")) * (12 if extrema.group("unit") == "년" else 1)
        if not 1 <= months <= 240:
            return None
        direction = "min" if extrema.group("direction") in {"가장낮", "최저"} else "max"
        requested_outputs = {"text", "table", "chart"} if "전체" in compact else {"text"}
        return ActionPlan(actions=[ActionCall(
            requirement_id="price_extrema", action_id="price.series",
            slots=ActionSlots(
                mineral=extrema.group("mineral"),
                period=Period(kind="trailing_months", trailing_months=months, explicit=True),
                price_operation="period_extrema", selection_direction=direction,
            ), intent="price_series", role="data", requested_outputs=requested_outputs,
        )])

    yoy = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격(?:이)?전년동월대비(?:변화율|변동률)(?:은|는|이|을|를)?"
        r"(?:(?P<basis>월최신관측값|월별최신관측값|월최신값|월별최신값|월말|월최신)(?:기준(?:으로)?|으로)?)?"
        r"(?:얼마야|어때|알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if yoy:
        basis = "monthly_latest" if yoy.group("basis") else "monthly_average"
        return ActionPlan(actions=[ActionCall(
            requirement_id="price_yoy", action_id="price.series",
            slots=ActionSlots(
                mineral=yoy.group("mineral"),
                # 전년 동월 비교는 최신 보유월과 직전년도 같은 월이 필요하다.
                period=Period(kind="trailing_months", trailing_months=13, explicit=True),
                price_operation="year_over_year", price_yoy_basis=basis,
            ), intent="price_series", role="data",
        )])

    period_average = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격(?:최근)?(?P<count>\d+)(?P<unit>개월|년)평균(?:이랑|과)?비교하면(?:어때|어떤가요)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if period_average:
        months = int(period_average.group("count")) * (12 if period_average.group("unit") == "년" else 1)
        if not 1 <= months <= 240:
            return None
        return ActionPlan(actions=[ActionCall(
            requirement_id="period_average_delta", action_id="price.series",
            slots=ActionSlots(
                mineral=period_average.group("mineral"),
                period=Period(kind="trailing_months", trailing_months=months, explicit=True),
                price_operation="period_average_delta",
            ), intent="price_series", role="data",
        )])

    streak = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격(?:이)?몇개월(?:째|재)(?:오르고(?:있어)?|상승(?:하고|중이야)?|내리고(?:있어)?|하락(?:하고|중이야)?|보합(?:이야|세야)?)[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if streak:
        # 전체 보유 월은 전용 DB 집계 adapter가 읽는다. raw 시계열 range로
        # 우회하지 않아 일별 원자료를 대량 전송하지 않는다.
        return ActionPlan(actions=[ActionCall(
            requirement_id="monthly_streak", action_id="price.series",
            slots=ActionSlots(
                mineral=streak.group("mineral"),
                period=Period(kind="latest"),
                price_operation="monthly_streak",
            ), intent="price_series", role="data",
        )])

    yearly = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?(?:가격)?(?:연도별|년도별)평균가격(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if yearly:
        return ActionPlan(actions=[ActionCall(
            requirement_id="yearly_average", action_id="price.series",
            slots=ActionSlots(
                mineral=yearly.group("mineral"),
                period=Period(kind="latest"),
                price_operation="yearly_average",
            ), intent="price_series", role="data",
        )])

    comparison = re.fullmatch(
        r"(?P<left>[가-힣A-Za-z0-9]+?)(?:과|와)(?P<right>[가-힣A-Za-z0-9]+?)(?:의)?가격(?:을)?같이비교(?:해줘|해주세요|해|해봐)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if comparison:
        return ActionPlan(actions=[ActionCall(
            requirement_id="two_mineral_price_comparison", action_id="price.compare",
            slots=ActionSlots(
                minerals=[comparison.group("left"), comparison.group("right")],
                requested_outputs={"text", "chart"},
            ), intent="price_compare", role="data", requested_outputs={"text", "chart"},
        )])
    # 조사 없이 "니켈 텅스텐 가격 같이 비교"처럼 두 광종을 나열한 문형은
    # 비탐욕 일반 정규식으로 나누면 임의 문자열을 광종으로 오인할 수 있다.
    # 등록 별칭 집합을 명시해 두 광종이 모두 식별될 때만 비교 Action을 만든다.
    bare_comparison = re.fullmatch(
        r"(?P<left>리튬|니켈|코발트|구리|동|망간|흑연|텅스텐|희토류|네오디뮴|아연|금)"
        r"(?P<right>리튬|니켈|코발트|구리|동|망간|흑연|텅스텐|희토류|네오디뮴|아연|금)"
        r"가격(?:을)?같이비교(?:해줘|해주세요|해|해봐)?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if bare_comparison:
        minerals = [MINERAL_ALIASES.get(bare_comparison.group(key).casefold(), bare_comparison.group(key))
                    for key in ("left", "right")]
        return ActionPlan(actions=[ActionCall(
            requirement_id="two_mineral_price_comparison", action_id="price.compare",
            slots=ActionSlots(minerals=minerals,
                              requested_outputs={"text", "chart"}),
            intent="price_compare", role="data", requested_outputs={"text", "chart"},
        )])
    return None


def _composite_index_plan(message: str) -> ActionPlan | None:
    """폐쇄형 종합지수 문형을 요청 계열의 단일 typed action으로 고정한다.

    private 접근 제어와 원천 provenance 판정은 graph/MCP 경계가 계속 소유한다.
    이 추출기는 질문의 계산 의미만 보존하며 public 경로를 열지 않는다.
    """
    compact = re.sub(r"[\s()（）\[\]{}]", "", message).upper()
    compact_upper = compact
    variant_markers = (
        ("major_metals", ("HI002", "메이저금속지수", "메이저지수")),
        ("minor_metals", ("HI003", "희소금속지수", "희유금속지수")),
    )
    explicit_subindices = [variant for variant, markers in variant_markers[:2]
                           if any(marker.upper() in compact_upper for marker in markers)]
    has_hi001 = "HI001" in compact_upper
    has_generic_composite = any(marker in compact_upper for marker in ("광물종합지수", "광물종합지표", "종합지수", "종합지표"))
    if len(explicit_subindices) > 1 or (explicit_subindices and has_hi001):
        return None
    if explicit_subindices:
        variant = explicit_subindices[0]
    elif has_hi001 or has_generic_composite:
        variant = "composite"
    else:
        return None
    subject = (r"(?:광물종합지수|광물종합지표|종합지수|종합지표|메이저금속지수|메이저지수|"
               r"희소금속지수|희유금속지수|HI001|HI002|HI003)(?:HI001|HI002|HI003)?")
    latest = re.fullmatch(
        rf"(?:오늘|현재|금일)?{subject}(?:는|가|)?(?:얼마야|얼마인가요|알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    trend = re.fullmatch(
        rf"최근(?P<months>\d+)개월{subject}(?:추세)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?",
        compact,
    )
    extrema = re.fullmatch(
        rf"{subject}(?:올해|금년)(?:고점|저점)(?:/|과|및|와)?(?:고점|저점)?(?:은|는)?[?.]?",
        compact,
    )
    year_range = re.fullmatch(
        rf"{subject}(?P<start>\d{{4}})년?(?:~|∼|〜|부터|[-–—])"
        r"(?P<end>\d{4})년?(?:까지)?(?:기간)?"
        r"(?:변화|추이|추세|비교|흐름)?(?:보여줘|보여주세요|알려줘|알려주세요)?[?.]?",
        compact,
    )
    if latest:
        operation, period, outputs = "latest_delta", Period(kind="latest"), {"text"}
    elif trend:
        months = int(trend.group("months"))
        if not 1 <= months <= 240:
            return None
        operation = "period_change"
        period = Period(kind="trailing_months", trailing_months=months, explicit=True)
        outputs = {"text", "chart"}
    elif year_range:
        start_year, end_year = int(year_range.group("start")), int(year_range.group("end"))
        if not 1900 <= start_year <= end_year <= 2200:
            return None
        operation = "period_change"
        period = Period(
            kind="range", start=f"{start_year}-01-01", end=f"{end_year}-12-31", explicit=True,
        )
        outputs = {"text", "chart"}
    elif extrema:
        operation = "period_extrema"
        period = Period(kind="calendar_year", calendar_year=date.today().year, explicit=True)
        outputs = {"text"}
    else:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id=f"composite_index_{operation}", action_id="indicator.series",
        slots=ActionSlots(
            indicator="composite_index", indicator_variant=variant,
            indicator_operation=operation, period=period, requested_outputs=outputs,
        ), intent="indicator", role="data", requested_outputs=outputs,
    )])


def _forecast_price_plan(message: str) -> ActionPlan | None:
    """KOMIS 예측가격 원천의 질문 의미를 typed slot으로 보존한다."""
    compact = re.sub(r"\s+", "", message)
    next_month = re.fullmatch(
        r"다음달(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격전망(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact,
    )
    if next_month is None:
        next_month = re.fullmatch(
            r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?다음달가격전망(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)?[?.]?", compact,
        )
    direction = re.fullmatch(
        r"(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?가격앞으로(?:오를까(?:내릴까)?|내릴까(?:오를까)?|상승할까|하락할까)[?.]?", compact,
    )
    if next_month:
        mineral, operation = next_month.group("mineral"), "next_month_value"
        period = Period(kind="future_horizon", future_horizon=1, explicit=True)
    elif direction:
        mineral, operation, period = direction.group("mineral"), "direction", None
    else:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id=f"forecast_price_{operation}", action_id="forecast.price",
        slots=ActionSlots(mineral=mineral, period=period, forecast_operation=operation),
        intent="forecast_price", role="data",
    )])


def _latest_inventory_plan(message: str) -> ActionPlan | None:
    """재고 질문을 가격 action으로 오인하지 않도록 최신 재고 action으로 고정한다."""
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?:(?:금일자?|오늘|현재|지금|최근)(?:의)?)?(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?"
        r"(?P<basis>LME)?(?:재고량|재고)(?:(?:은|는|이|을|를)?(?:얼마야|얼마인가요|알려줘|알려주세요|보여줘|보여주세요))?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    mineral = match.group("mineral")
    if any(marker in mineral for marker in ("과", "와", "및", "그리고")):
        return None
    mineral = MINERAL_ALIASES.get(mineral.casefold(), mineral)
    return ActionPlan(actions=[ActionCall(
        requirement_id="latest_inventory", action_id="inventory.latest",
        slots=ActionSlots(mineral=mineral, price_basis=match.group("basis")),
        intent="price_series", role="data",
    )])


def _latest_price_plan(message: str) -> ActionPlan | None:
    """완결된 금일 가격 질의를 최신 보유 관측값 조회로 고정한다.

    가격 원천은 당일 장 마감·적재 시차 때문에 달력상의 오늘 행이 없을 수 있다.
    이 좁은 문형은 planner가 ``금일``을 YYYY-MM-DD 범위로 바꾸는 변동을 막고,
    ``Period(kind=latest)``로 어댑터가 최신 실제 관측 한 행을 선택하게 한다.
    """
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?:(?:금일자?|오늘|현재|지금|최근)(?:의)?)?(?P<mineral>[가-힣A-Za-z0-9]+?)(?:의)?"
        r"(?:가격|시세)(?:(?:은|는|이|을|를)?(?:얼마야|얼마인가요|알려줘|알려주세요|보여줘|보여주세요))?[?.]?",
        compact,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    mineral = match.group("mineral")
    # 단일 광종 현재값 요청만 닫는다. 복수 광종은 price.compare/복합 계약이
    # 소유하므로 여기서 "니켈과리튬"을 하나의 광종으로 조회하지 않는다.
    if any(marker in mineral for marker in ("과", "와", "및", "그리고")):
        return None
    mineral = MINERAL_ALIASES.get(mineral.casefold(), mineral)
    if mineral not in _LEGACY_PRICE_MINERALS:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="latest_price",
        action_id="price.series",
        # ``latest``는 "기간 미지정"과 다르다. adapter가 최신·직전 보유
        # 관측 2건만 요청하도록 하는 typed 표현이며, 기본 시계열 상한(60건)을
        # 쓰지 않는다. 화면 표는 최신 1건만 표시하고 직전값은 등락 계산에만 쓴다.
        slots=ActionSlots(mineral=mineral, period=Period(kind="latest")),
        intent="price_series",
        role="data",
    )])


def _explicit_dated_document_plan(message: str) -> ActionPlan | None:
    """발행일이 적힌 단일 문서 확인은 LLM 분류 전에 OKF lookup으로 고정한다.

    ``2026년 6월 16일 주간 경제 비철금속 시장 동향 내용을 알려줘``처럼
    발행일·문서 종류·본문/제목 요청이 모두 있으면 주제 검색(document.retrieve)이
    아니라 한 문서의 실제 OKF 본문을 읽어야 한다. Planner가 이를 일반 document로
    축약하면 날짜 식별자가 사라져 공개 문서도 Advisor 단계에서 기권할 수 있다.
    가격·무역 등 별도 데이터 요구는 이 단축 경로로 흡수하지 않는다.
    """

    compact = re.sub(r"\s+", "", message)
    has_written_date = bool(re.search(r"20\d{2}년\d{1,2}월\d{1,2}일", compact))
    has_document_marker = any(marker in compact for marker in ("보고서", "동향", "뉴스"))
    is_single_document_request = bool(re.fullmatch(
        r".*(?:내용|제목|원문|요약)(?:을|를)?(?:알려줘|알려주세요|보여줘|보여주세요|찾아줘|찾아주세요|요약해줘|요약해주세요)[?.]?",
        compact,
    ))
    has_separate_data_request = any(marker in compact for marker in (
        "가격이랑", "가격과", "수입액", "수출액", "수입량", "수출량", "비교해",
    ))
    if not (has_written_date and has_document_marker and is_single_document_request) or has_separate_data_request:
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="document", action_id="document.lookup", intent="okf_lookup", role="content",
        slots=ActionSlots(topic=message), requested_outputs={"text"},
    )])


def _export_control_import_share_plan(message: str) -> ActionPlan | None:
    """수출통제 기사에 명시된 광종을 후속 교역 조회로 넘기는 진입 Action.

    기사별 광종은 질문만으로 확정할 수 없으므로 여기서는 기사 조회만 계획한다.
    ``retrieve_evidence``가 검증된 기사 표에서 명시 광종을 읽은 뒤에만 한국의
    중국 수입 의존도 Action을 동적으로 추가한다. 기사에 없는 광종을 질문에서
    추정해 교역 데이터를 붙이는 일을 막기 위한 2단계 계약이다.
    """
    compact = re.sub(r"\s+", "", message)
    if not ("수출통제" in compact and "중국" in compact
            and any(marker in compact for marker in ("수입비중", "수입의존", "점유율"))):
        return None
    if not any(marker in compact for marker in ("뉴스", "기사", "대상광종", "언급광종")):
        return None
    return ActionPlan(actions=[ActionCall(
        requirement_id="export_control_news", action_id="document.retrieve",
        slots=ActionSlots(topic=message), intent="document", role="content",
    )])


def _publication_document_plan(message: str) -> ActionPlan | None:
    """명확한 단일 월간동향·뉴스 검색을 문서 action으로 고정한다.

    가격·무역 등 다른 결과와 ``같이`` 보거나 ``비교``하는 복합 질문은 각
    요구를 분해해야 하므로 이 좁은 단축 경로가 소유하지 않는다.
    """
    compact = re.sub(r"\s+", "", message)
    # 포함어/제외어 휴리스틱은 복합 데이터 요구를 계속 삼킬 수 있다. 아래
    # 단일 문서 검색 문형으로 질문 전체가 완결될 때만 이 경로가 소유한다.
    single_publication_patterns = (
        r"최근자원뉴스(?:를)?(?:요약|정리|보여)(?:해줘|해주세요|해주십시오|줘|주세요|주십시오)?[?.]?",
        r"이번달(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"최근\d+(?:개월|년)(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"20\d{2}년(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"20\d{2}년\d{1,2}월(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"최근(?:희소금속|전략광종)?월간동향보고서제목(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)[?.]?",
        r"최근\d+(?:개월|년)월간동향에서[가-힣A-Za-z0-9·_-]+관련내용(?:을)?(?:찾아줘|찾아주세요|알려줘|알려주세요)[?.]?",
        r"20\d{2}년(?:전략광종|희소금속)?월간동향에서[가-힣A-Za-z0-9·_-]+관련내용(?:을)?(?:찾아줘|찾아주세요|알려줘|알려주세요)[?.]?",
        r"20\d{2}년\d{1,2}월(?:전략광종|희소금속)?월간동향에서[가-힣A-Za-z0-9·_-]+관련내용(?:을)?(?:찾아줘|찾아주세요|알려줘|알려주세요)[?.]?",
        r"오늘자원뉴스(?:가)?(?:뭐|무엇)(?:있어|있나요|야)[?.]?",
        r"최근[가-힣A-Za-z0-9·_-]+수출통제관련뉴스(?:가)?(?:있어|있나요)[?.]?",
    )
    if not any(re.fullmatch(pattern, compact) for pattern in single_publication_patterns):
        return None
    today = date.today()
    period: Period | None = None
    recent = re.search(r"최근(\d+)(개월|년)", compact)
    year_month = re.search(r"(20\d{2})년(\d{1,2})월", compact)
    calendar_year = re.search(r"(20\d{2})년", compact)
    if recent:
        months = int(recent.group(1)) * (12 if recent.group(2) == "년" else 1)
        period = Period(kind="trailing_months", trailing_months=months, explicit=True)
    elif year_month and 1 <= int(year_month.group(2)) <= 12:
        year, month = int(year_month.group(1)), int(year_month.group(2))
        month_start = date(year, month, 1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        period = Period(kind="range", start=month_start.isoformat(), end=(next_month - timedelta(days=1)).isoformat(), explicit=True)
    elif calendar_year:
        period = Period(kind="calendar_year", calendar_year=int(calendar_year.group(1)), explicit=True)
    elif "이번달" in compact:
        period = Period(kind="range", start=today.replace(day=1).isoformat(),
                        end=today.isoformat(), explicit=True)
    elif "이번주" in compact:
        period = Period(kind="range", start=(today - timedelta(days=today.weekday())).isoformat(),
                        end=today.isoformat(), explicit=True)
    elif "오늘" in compact:
        period = Period(kind="range", start=today.isoformat(), end=today.isoformat(), explicit=True)
    elif "최근" in compact and "뉴스" in compact:
        period = Period(kind="trailing_months", trailing_months=3, explicit=True)
    return ActionPlan(actions=[ActionCall(
        requirement_id="publication_search", action_id="document.retrieve",
        slots=ActionSlots(topic=message, period=period), intent="document", role="content",
    )])


def _normalize_trade_rank_scope(actions: list[ActionCall], message: str) -> None:
    """국가 순위의 한국/세계 모집단을 typed 슬롯에 보존한다."""
    rank_calls = [call for call in actions if call.action_id == "trade.country_rank"]
    # 서로 다른 모집단의 순위가 한 문장에 함께 있을 수 있다. 문장 전체의
    # 표지를 여러 requirement에 전파하지 않고 planner가 각 슬롯을 명시하게 한다.
    if len(rank_calls) != 1:
        return
    compact = re.sub(r"\s+", "", message)
    domestic = any(marker in compact for marker in ("우리나라", "한국"))
    if domestic and "세계" in compact and len(actions) > 1:
        return
    # 범위를 다시 말하지 않은 생략형 질의는 history를 보고 planner가 복원한
    # requirement-level scope를 보존한다. 신규 질의의 모델 오분류를 고치는
    # 국내 기본값은 광종·수출입·순위 요구가 모두 명시된 완결형에만 적용한다.
    inherited_scope = rank_calls[0].slots.trade_scope
    named_mineral = any(marker in compact for marker in (
        "구리", "니켈", "코발트", "리튬", "희토류", "네오디뮴", "Nd",
    ))
    complete_rank_request = (
        named_mineral
        and any(marker in compact for marker in ("수입", "수출"))
        and any(marker in compact for marker in ("상위", "순위", "비중", "점유율"))
    )
    if not domestic and "세계" not in compact and not complete_rank_request and inherited_scope is not None:
        return
    scope: Literal["korea", "global"] = "global" if "세계" in compact and not domestic else "korea"
    # 단일 국가 순위는 질문의 명시 표지가 모델 추론보다 우선한다. 특히
    # "국가별 비중"을 세계 순위로 확대 해석하면 기존 한국 수입상대국
    # 기본 계약이 깨지므로, 명시적인 "세계"가 없으면 korea로 되돌린다.
    rank_calls[0].slots.trade_scope = scope


def normalize_country_rank_request(message: str, plan: ActionPlan) -> ActionPlan:
    """Repair an unambiguous country-rank misclassification before HITL validation.

    Country import shares across top countries are a ranking request, not a
    trade-indicator/country-dependency calculation. Preserve unrelated
    multi-action plans and explicit dependency questions.
    """
    normalized = re.sub(r"\s+", "", message).casefold()
    has_rank = any(term in normalized for term in ("상위", "순위", "가장", "제일", "1위", "2위", "3위"))
    has_country = any(term in normalized for term in ("국가", "나라", "개국", "상위국"))
    has_flow = "수입" in normalized or "수출" in normalized
    if not (has_rank and has_country and has_flow):
        return plan
    if any(term in normalized for term in (
        "의존도", "의존율", "집중도", "hhi", "tsi", "rca", "tii", "증감률",
        "무역특화", "무역결합도", "비교우위",
    )):
        return plan

    # 순위와 국가별 비중은 같은 country-rank 표의 열이다. planner가 둘을
    # 별도 requirement로 과분해하면, 기본 metric 보정 뒤 동일한
    # ``trade.country_rank``가 두 번 실행될 수 있다. 이 완결된 단일 순위
    # 문형에서는 한 번의 조회로 충분하므로 기존 rank call을 우선 사용한다.
    rank_candidates = [call for call in plan.actions if call.action_id == "trade.country_rank"]
    candidates = rank_candidates or [
        call for call in plan.actions if call.action_id == "trade.indicator"
    ]
    if not candidates:
        return plan
    call = candidates[0]
    mineral = next((item.slots.mineral for item in candidates if item.slots.mineral), None)
    if not mineral:
        mineral = next((name for name in ("희토류", "코발트", "니켈", "리튬", "구리", "동")
                        if name in normalized), None)
    if not mineral:
        return plan
    if any(item.slots.mineral not in {None, mineral} for item in candidates):
        return plan
    # 이 명확한 단일 순위 질문에 planner가 share metadata를 별도
    # concentration/rank action으로 중복 생성한 경우만 합친다.
    if any(other.action_id not in {"trade.indicator", "trade.country_rank", "trade.concentration"}
           or other.slots.mineral not in {None, mineral}
           for other in plan.actions):
        return plan
    flow = "export" if "수출" in normalized and "수입" not in normalized else "import"
    is_weight = any(term in normalized for term in ("물량", "중량", "톤"))
    metric = call.slots.metric if call.slots.metric in {
        "import_amount", "import_weight", "export_amount", "export_weight",
    } else (
        "export_weight" if flow == "export" and is_weight else
        "import_weight" if flow == "import" and is_weight else
        "export_amount" if flow == "export" else "import_amount"
    )
    slots = call.slots.model_copy(update={
        "mineral": mineral, "metric": metric, "flow": flow, "trade_metric": None,
        "partner_country": None,
        "period": call.slots.period or Period(kind="trailing_months", trailing_months=12),
        "top_n": call.slots.top_n or 5,
    })
    fixed_call = call.model_copy(update={"action_id": "trade.country_rank", "slots": slots})
    return plan.model_copy(update={"actions": [fixed_call]})


def _has_source_unavailable_predecessor(history: list[dict[str, Any]], plan: ActionPlan) -> bool:
    """구조화된 직전 기권 상태만 후속 가격 슬롯에 전파한다."""
    if not any(call.action_id in {"price.series", "price.compare", "price.verify_claim"}
               for call in plan.actions):
        return False
    for turn in reversed(history):
        if turn.get("role") != "assistant":
            continue
        return (turn.get("abstain_reason") == "source_unavailable"
                and "price.compare" in set(turn.get("action_ids") or []))
    return False


def _intent_plan_semantic_failure(intent_plan: IntentPlan) -> str | None:
    """Action으로 바꾸기 전 intent/slot 호환성을 확인한다.

    이 검사는 재추출의 피드백 전용이다. 직접 ActionPlan의 unavailable 경계를
    느슨하게 만들거나 다른 source family로 치환하지 않는다.
    """
    trade_metrics = {"import_amount", "import_weight", "export_amount", "export_weight"}
    for item in intent_plan.requirements:
        if item.intent == "trade_rank" and item.slots.metric in {"production", "reserves"}:
            return "resource_rank_required"
        if (item.intent in {"forecast_demand", "forecast_price", "forecast_quantity"}
                and item.slots.metric in trade_metrics
                and not (item.slots.period and item.slots.period.kind == "future_horizon")):
            return "observed_trade_required"
        period = item.slots.period
        if period and period.kind == "range":
            try:
                _coerce_iso_range_boundary(period.start or "", end=False)
                # ``현재``는 수집 데이터의 관측 종료 상한을 뜻한다. 이 값은
                # action 검증에서 시스템 기준일로 정규화하므로, 재추출 사유가
                # 아니다.
                if (period.end or "").casefold() not in CURRENT_PERIOD_ENDS:
                    _coerce_iso_range_boundary(period.end or "", end=True)
            except ValueError:
                return "period_requires_iso_or_trailing_months"
    return None


def _coerce_iso_range_boundary(value: str, *, end: bool) -> str:
    """ISO 일자 또는 ISO 월을 range adapter가 쓰는 ISO 일자로 정규화한다."""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        parsed = datetime.strptime(value, "%Y-%m")
        day = monthrange(parsed.year, parsed.month)[1] if end else 1
        return date(parsed.year, parsed.month, day).isoformat()


def repair_action_plan(message: str, llm: Any, failure_reason: str, history: list[dict[str, str]] | None = None) -> ActionPlan:
    """검증 실패 사유만 제공해 1회 재추출한다; 질문 문구 규칙으로 보정하지 않는다."""
    return llm.invoke(task="action_plan_repair", instructions=ACTION_PLAN_PROMPT,
                      payload={"question": message, "history": history or [],
                               "previous_failure": failure_reason,
                               "instruction": "이 실패 사유를 해결하는 typed ActionPlan만 반환하십시오."},
                      output_model=ActionPlan, max_tokens=1100).output


def missing_trade_indicator_slots(call: ActionCall) -> tuple[str, ...]:
    """무역지표 action에만 적용하는 HITL 대상 슬롯을 결정한다."""
    if call.action_id != "trade.indicator":
        return ()
    slots = call.slots
    if slots.trade_metric is None:
        return ("trade_metric",)
    missing: list[str] = []
    if slots.reporter_country is None:
        missing.append("reporter_country")
    allowed_period_kinds = {"calendar_year"}
    if slots.trade_metric == "country_dependency":
        allowed_period_kinds |= {"trailing_months", "range"}
    if slots.period is None or slots.period.kind not in allowed_period_kinds:
        missing.append("period")
    if slots.trade_metric in {"tsi", "rca", "trade_growth", "country_dependency"} and not (slots.mineral or slots.hs_code):
        missing.append("mineral_or_hs_code")
    if slots.trade_metric in {"trade_growth", "country_dependency"} and slots.flow is None:
        missing.append("flow")
    if slots.trade_metric in {"tii", "country_dependency"} and slots.partner_country is None:
        missing.append("partner_country")
    return tuple(missing)


def validate_action_plan(plan: ActionPlan | None) -> PlanAssessment:
    if not isinstance(plan, ActionPlan):
        return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    if plan.predecessor_source_unavailable:
        return PlanAssessment(approved=False, failure_reason="source_unavailable")
    for call in plan.actions:
        if call.slots.selection_mode:
            # Selection is a typed refinement, not a shortcut around the
            # existing Action contract.  Only price.series has a local
            # observation set that can currently be selected deterministically.
            if (call.action_id not in {"price.series", "document.retrieve"}
                    or call.action_id == "document.retrieve"
                    and call.slots.selection_mode != "rank"):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if call.slots.selection_mode == "extremum":
                if (call.slots.selection_direction not in {"min", "max"}
                        or call.slots.period is None
                        or call.slots.period.kind not in {"range", "trailing_months"}):
                    return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            elif call.slots.selection_mode == "ordinal":
                if (call.slots.selection_position is None
                        or call.slots.period is None
                        or call.slots.period.kind != "range"):
                    return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            elif call.slots.selection_mode == "rank":
                if call.slots.selection_limit is None:
                    return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.slots.price_operation:
            expected_period = {
                "period_average_delta": "trailing_months",
                "monthly_streak": "latest",
                "yearly_average": "latest",
                "year_over_year": "trailing_months",
                "period_extrema": {"range", "trailing_months"},
                "significant_daily_rise": "trailing_months",
            }.get(call.slots.price_operation)
            if (call.action_id != "price.series" or call.slots.period is None
                    or (call.slots.period.kind not in expected_period
                        if isinstance(expected_period, set)
                        else call.slots.period.kind != expected_period)):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if (call.slots.price_operation == "year_over_year"
                    and (call.slots.period.trailing_months or 0) < 13):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if call.slots.price_operation == "year_over_year" and call.slots.price_yoy_basis is None:
                call.slots.price_yoy_basis = "monthly_average"
        if (call.action_id == "trade.indicator"
                and call.slots.trade_metric == "country_dependency"
                and call.slots.denominator_scope is None):
            # 구버전 저장 ActionPlan에는 이 optional 슬롯이 없다. 공개 계약의
            # 유일한 분모를 적용해 이전 연간 요청을 계속 실행 가능하게 한다.
            call.slots.denominator_scope = "reporter_product_trade"
        if call.slots.mineral:
            call.slots.mineral = MINERAL_ALIASES.get(call.slots.mineral.casefold(), call.slots.mineral)
        if call.slots.minerals:
            call.slots.minerals = [MINERAL_ALIASES.get(item.casefold(), item) for item in call.slots.minerals]
        if call.action_id == "resource.rank" and not call.slots.mineral and call.slots.minerals and len(call.slots.minerals) == 1:
            call.slots.mineral = call.slots.minerals[0]
        if call.action_id in {"price.compare", "price.verify_claim"} and not call.slots.minerals and call.slots.mineral:
            call.slots.minerals = [call.slots.mineral]
        if call.action_id == "price.verify_claim" and call.slots.comparator is None:
            # 수치 전제는 문구가 '정확히'를 생략해도 관측값과 같은지 확인한다.
            # 범위 주장(이상/미만)은 planner가 explicit comparator를 채운다.
            call.slots.comparator = "equals"
        if call.action_id == "trade.country_rank" and call.slots.metric is None:
            # 레지스트리의 public 기본 표시는 수입금액이다. planner가 기준을
            # 생략한 경우에만 명시적 기본을 기록한다.
            call.slots.metric = "import_amount" if call.slots.flow != "export" else "export_amount"
        if call.action_id == "trade.price_cross_rank" and call.slots.metric is None:
            call.slots.metric = "import_amount"
        if call.action_id == "resource.price_cross_rank" and call.slots.metric is None:
            call.slots.metric = "production"
        if call.action_id in {"trade.price_cross_rank", "resource.price_cross_rank"}:
            if call.slots.period is None:
                call.slots.period = Period(kind="trailing_months", trailing_months=12)
            if call.slots.top_n is None:
                call.slots.top_n = 5
        if call.action_id == "trade.country_rank" and call.slots.period is None:
            call.slots.period = Period(kind="trailing_months", trailing_months=12)
        if call.action_id == "trade.country_rank" and call.slots.top_n is None:
            call.slots.top_n = 5
        if call.action_id.startswith("price.") and call.slots.metric in {"import_amount", "import_weight", "export_amount", "export_weight"}:
            return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if missing_trade_indicator_slots(call):
            return PlanAssessment(approved=False, failure_reason="slot_required")
    # 미연결 원천을 쓰는 action은 그 action의 선택 자체로 제공 불가가 확정된다.
    # 다른 action의 후속 슬롯이나 의존성 오류가 이 원천 상태를 slot 오류로
    # 가리지 않게 먼저 분류한다.
    if any(call.action_id in UNAVAILABLE for call in plan.actions):
        return PlanAssessment(approved=False, failure_reason="source_unavailable")
    # 미래 시점의 실측 가격은 아직 관측될 수 없다. 예측 action으로 바꾸거나
    # 빈 조회를 실행해 no_data_for_period로 흐리지 않고 원천 부재로 닫는다.
    if any(call.action_id == "price.series"
           and call.slots.period
           and call.slots.period.kind == "future_horizon"
           for call in plan.actions):
        return PlanAssessment(approved=False, failure_reason="source_unavailable")
    # 동일 가격비교가 기간 창만 달리 반복되면 하나의 비교 action windows로
    # 정규화한다. 질문별 분기가 아니라 action ID·typed Period 기준 병합이다.
    price_calls = [call for call in plan.actions if call.action_id == "price.compare"]
    if len(price_calls) > 1 and all(call.slots.minerals == price_calls[0].slots.minerals for call in price_calls):
        windows = [call.slots.period.trailing_months for call in price_calls
                   if call.slots.period and call.slots.period.kind == "trailing_months"]
        if len(windows) == len(price_calls):
            first = price_calls[0]
            first.slots.windows = sorted(set(windows))
            first.slots.period = None
            plan.actions = [call for call in plan.actions if call is first or call.action_id != "price.compare"]
    ids = [call.requirement_id for call in plan.actions]
    if len(ids) != len(set(ids)):
        return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    known_ids = set(ids)
    if any(not set(call.depends_on) <= known_ids - {call.requirement_id} for call in plan.actions):
        return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    for call in plan.actions:
        for binding in call.input_bindings:
            if binding.source_requirement_id not in set(call.depends_on):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if call.action_id not in {"trade.country_rank", "trade.concentration", "forecast.price"}:
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if binding.target_slot == "reporter_country" and call.slots.trade_scope not in {"korea", "global"}:
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    edges = {call.requirement_id: set(call.depends_on) for call in plan.actions}
    visiting, visited = set(), set()
    def has_cycle(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        result = any(has_cycle(next_node) for next_node in edges[node])
        visiting.remove(node)
        visited.add(node)
        return result
    if any(has_cycle(node) for node in edges):
        return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    action_ids = {call.action_id for call in plan.actions}
    if len(plan.actions) > 1 and action_ids & {"trade.price_cross_rank", "resource.price_cross_rank"}:
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    trade_ranks = [call for call in plan.actions if call.action_id == "trade.country_rank"]
    if ((len(trade_ranks) > 1 or (len(plan.actions) > 1 and trade_ranks))
            and any(call.slots.trade_scope is None for call in trade_ranks)):
        return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    # Source family를 바꾸어 구제하지 않는다. 잘못 선택된 intent는 typed
    # validation feedback으로 한 번만 재추출하고, 계속 틀리면 닫힌다.
    for call in plan.actions:
        if call.action_id == "trade.country_rank" and call.slots.metric not in {
            "import_amount", "import_weight", "export_amount", "export_weight",
        }:
            return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    if OFF_TOPIC in action_ids:
        return PlanAssessment(approved=False, failure_reason="out_of_scope")
    if not action_ids <= AVAILABLE:
        return PlanAssessment(approved=False, failure_reason="unsupported_action")
    for call in plan.actions:
        for field in REQUIRED[call.action_id]:
            value = getattr(call.slots, field)
            if value is None and any(binding.target_slot == field for binding in call.input_bindings):
                continue
            if value is None or value == []:
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "resource.rank" and call.slots.metric not in {"production", "reserves"}:
            return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id in {"trade.price_cross_rank", "resource.price_cross_rank"}:
            if (call.slots.period is None or call.slots.period.kind not in
                    {"trailing_months", "calendar_year", "range"}):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if (call.action_id == "trade.price_cross_rank" and
                    (call.slots.metric not in {"import_amount", "import_weight"}
                     or call.slots.trade_scope == "global" or call.slots.reference_year is not None)):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if (call.action_id == "resource.price_cross_rank" and
                    (call.slots.metric != "production" or call.slots.partner_country is not None
                     or (call.slots.reference_year or 0) > date.today().year)):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "resource.yoy":
            if (call.slots.metric != "production" or call.slots.country_scope != "world"
                    or (call.slots.period and call.slots.period.kind != "calendar_year")):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "mine.rank":
            if call.slots.mine_order == "increase" and call.slots.mine_metric != "production":
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if call.slots.period and call.slots.period.kind == "future_horizon":
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "indicator.series" and call.slots.indicator == "composite_index" and call.slots.mineral:
            # 광물종합지표는 광종별 시계열이 아니다. 잘못된 슬롯이 아니라
            # 현재 연결된 원천이 제공하지 않는 데이터 범위다.
            return PlanAssessment(approved=False, failure_reason="source_unavailable")
        if (call.action_id == "indicator.series" and call.slots.indicator == "composite_index"
                and call.slots.indicator_variant is None):
            # legacy 비-operation call만 HI001 기본값으로 보완한다. 계산 operation은
            # 질문 정규화가 실제 요청 계열을 할당하지 못하면 fail closed 한다.
            if call.slots.indicator_operation is None:
                call.slots.indicator_variant = "composite"
            else:
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.slots.indicator_variant is not None and (
                call.action_id != "indicator.series" or call.slots.indicator != "composite_index"):
            return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.slots.indicator_operation is not None:
            if call.action_id != "indicator.series" or call.slots.indicator != "composite_index":
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            expected_period_kind = {
                "latest_delta": "latest",
                # 기간 변화는 상대기간과 사용자가 직접 지정한 연도 범위를 모두 받는다.
                "period_change": {"trailing_months", "range"},
                "period_extrema": "calendar_year",
            }[call.slots.indicator_operation]
            if (call.slots.indicator_variant not in COMPOSITE_INDEX_VARIANTS or call.slots.period is None
                    or (call.slots.period.kind not in expected_period_kind
                        if isinstance(expected_period_kind, set)
                        else call.slots.period.kind != expected_period_kind)):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.slots.forecast_operation is not None:
            if call.action_id != "forecast.price":
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if (call.slots.forecast_operation == "next_month_value"
                    and (call.slots.period is None or call.slots.period.kind != "future_horizon"
                         or call.slots.period.future_horizon != 1)):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "price.overview":
            groups = call.slots.strategic_price_groups or []
            if (not groups or len(groups) != len(set(groups))
                    or not set(groups) <= {"strategic_six", "strategic_ten", "battery_five"}
                    or call.slots.mineral is not None or call.slots.minerals is not None
                    or call.slots.period is not None):
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "trade.monthly" and not (call.slots.mineral or call.slots.hs_code):
            return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        p = call.slots.period
        if p:
            # ``현재``는 future horizon이 아니라 관측 종료 상한이다. planner가
            # 이를 range의 literal end로 남겨도 시스템 기준일로 한 번만
            # 정규화해 monthly adapter가 실제 관측월과 미도래월을 구분하게 한다.
            if p.kind == "range" and (p.end or "").casefold() in CURRENT_PERIOD_ENDS:
                p.end = date.today().isoformat()
            expected = {
                "trailing_months": p.trailing_months is not None and p.calendar_year is None and p.start is None and p.end is None and p.future_horizon is None,
                "calendar_year": p.calendar_year is not None and p.trailing_months is None and p.start is None and p.end is None and p.future_horizon is None,
                "range": p.start is not None and p.end is not None and p.trailing_months is None and p.calendar_year is None and p.future_horizon is None,
                "latest": p.trailing_months is None and p.calendar_year is None and p.start is None and p.end is None and p.future_horizon is None,
                "future_horizon": p.future_horizon is not None and p.trailing_months is None and p.calendar_year is None and p.start is None and p.end is None,
            }
            if not expected[p.kind]:
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if p.kind == "range":
                try:
                    p.start = _coerce_iso_range_boundary(p.start or "", end=False)
                    p.end = _coerce_iso_range_boundary(p.end or "", end=True)
                    if p.start > p.end:
                        return PlanAssessment(approved=False, failure_reason="slot_unresolved")
                except ValueError:
                    # 자연어 상대기간은 trailing_months/windows로만 표현한다.
                    return PlanAssessment(approved=False, failure_reason="slot_unresolved")
    # 시장전망 관측치와 그 변화의 원인·영향을 설명하는 문서는 서로 다른
    # 원천이지만, "데이터와 추론을 구분"하는 한 요구를 구성한다. 다른
    # indicator/document 조합까지 열지 않도록 market_outlook에만 한정한다.
    market_outlook_with_document = (
        frozenset(action_ids) == frozenset({"indicator.series", "document.retrieve"})
        and any(call.action_id == "indicator.series" and call.slots.indicator == "market_outlook"
                for call in plan.actions)
    )
    composite_index_with_monthly_document = (
        frozenset(action_ids) == frozenset({"indicator.series", "document.retrieve"})
        and any(call.action_id == "indicator.series" and call.slots.indicator == "composite_index"
                for call in plan.actions)
        and any(call.action_id == "document.retrieve" and "월간동향" in (call.slots.topic or "")
                for call in plan.actions)
    )
    composite_index_with_news = (
        frozenset(action_ids) == frozenset({"indicator.series", "document.retrieve"})
        and any(call.action_id == "indicator.series" and call.slots.indicator == "composite_index"
                for call in plan.actions)
        and any(call.action_id == "document.retrieve"
                and "자원뉴스" in (call.slots.topic or "")
                and "하락 주간" in (call.slots.topic or "")
                for call in plan.actions)
    )
    permitted_indicator_document = (
        market_outlook_with_document
        or composite_index_with_monthly_document
        or composite_index_with_news
    )
    has_unbounded_price_compare = any(
        call.action_id == "price.compare"
        and call.slots.period is None
        and not call.slots.windows
        and call.slots.price_basis is None
        and call.slots.currency is None
        for call in plan.actions
    )
    has_independent_document = any(
        call.action_id == "document.retrieve" and call.role == "content"
        for call in plan.actions
    )
    has_document_action = any(call.action_id == "document.retrieve" for call in plan.actions)
    price_claim_with_cause_document = (
        frozenset(action_ids) == frozenset({"price.verify_claim", "document.retrieve"})
        and any(call.action_id == "price.verify_claim" for call in plan.actions)
        and any(call.action_id == "document.retrieve"
                and any(marker in (call.slots.topic or "") for marker in ("원인", "이유", "상승"))
                for call in plan.actions)
    )
    if has_unbounded_price_compare and has_independent_document:
        return PlanAssessment(approved=False, failure_reason="source_unavailable")
    if (has_independent_document and any(
        call.action_id in {"price.compare", "price.verify_claim"} for call in plan.actions
    ) and not price_claim_with_cause_document):
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    # 가격 수치와 원인·영향 문서를 한 번에 묶는 과분해는 기존처럼 닫는다.
    # 월간동향·광물정보·뉴스처럼 독립 문서 조회는 이 조건에 해당하지 않는다.
    if (any(call.action_id == "price.series" for call in plan.actions)
            and has_document_action
            and any(any(marker in (call.slots.topic or "")
                        for marker in ("원인", "영향", "메커니즘", "상관", "추론"))
                    for call in plan.actions if call.action_id == "document.retrieve")):
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    # 시장전망 관측+영향 문서만 허용한다. 수급안정·종합지수와 임의 문서의
    # 조합은 기존 계약대로 닫아 문서 근거를 잘못된 지표에 귀속하지 않는다.
    if (has_document_action
            and any(call.action_id == "indicator.series" for call in plan.actions)
            and frozenset(action_ids) not in ALLOWED_MULTI
            and not permitted_indicator_document):
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    # 상위국 순위와 HHI를 한 번에 계산하는 조합은 전체 모집단 재집계가
    # 필요하므로 기존처럼 독립 concentration action으로만 허용한다.
    if (any(call.action_id == "trade.country_rank" for call in plan.actions)
            and any(call.action_id == "trade.concentration" and not call.slots.topic
                    for call in plan.actions)):
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    if (len(plan.actions) > 1
            and not action_ids <= COMPOSABLE_MULTI_ACTIONS
            and frozenset(action_ids) not in ALLOWED_MULTI
            and not permitted_indicator_document):
        # 독립 문서 설명과 함께 기간·창·기준이 전혀 없는 가격 비교가 나온
        # 경우, 비교 관측을 요구한 것이 아니라 모델이 "데이터와 추론 구분"을
        # 가격 action으로 과잉 분해한 상태다. 이 슬롯에는 조회 가능한 비교
        # 조건이 없으므로 조합 미지원으로 숨기지 않고 원천 부족으로 종결한다.
        # 기간/창이 있는 정상 가격 비교와 다른 미지원 조합은 기존 계약을 따른다.
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    return PlanAssessment(approved=True, plan=plan)
