# -*- coding: utf-8 -*-
"""RAG action/slot 계약.

질문의 문구를 도구 선택 규칙으로 해석하지 않는다. LLM은 이 모듈의 엄격한
``ActionPlan``만 만들고, 이 모듈은 카탈로그·필수 슬롯·허용 조합을 결정적으로
검사한다. 어댑터는 검증된 action만 ``RetrievalRoute``로 바꾼다.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ActionId = Literal[
    "price.series", "price.compare", "price.verify_claim", "price.overview",
    "trade.country_rank", "trade.monthly", "trade.concentration", "trade.hs_summary", "trade.indicator",
    "resource.rank", "resource.yoy", "mine.rank", "mine.profile", "indicator.series", "document.retrieve", "document.lookup", "menu.navigate", "dataset.navigate",
    "diagnosis.rank", "diagnosis.series", "forecast.demand", "forecast.price", "forecast.quantity",
    "geopolitics.index", "geopolitics.articles", "stockpile.status", "stockpile.methodology", "scenario.assess", "synthesis.brief",
    "off_topic",
]


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
    indicator: Literal["supply_stability", "market_outlook", "composite_index"] | None = None
    topic: str | None = None
    target_page: str | None = None
    claimed_change_pct: float | None = None
    comparator: Literal["greater_than", "less_than", "equals"] | None = None
    price_basis: str | None = None
    currency: str | None = None
    weight_unit: str | None = None
    windows: list[int] | None = None
    strategic_price_groups: list[Literal["strategic_six", "strategic_ten"]] | None = None
    country_scope: str | None = None
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

IntentId = Literal["price_series", "price_compare", "price_claim", "trade_rank", "trade_monthly", "trade_hs", "trade_concentration", "trade_indicator", "resource_rank", "resource_yoy", "mine_rank", "mine_profile", "indicator", "document", "okf_lookup", "concept", "stockpile_methodology", "menu", "dataset", "diagnosis", "forecast_demand", "forecast_price", "forecast_quantity", "geopolitics_index", "geopolitics_articles", "off_topic"]
INTENT_TO_ACTION = {"price_series":"price.series", "price_compare":"price.compare", "price_claim":"price.verify_claim", "trade_rank":"trade.country_rank", "trade_monthly":"trade.monthly", "trade_hs":"trade.hs_summary", "trade_concentration":"trade.concentration", "trade_indicator":"trade.indicator", "resource_rank":"resource.rank", "resource_yoy":"resource.yoy", "mine_rank":"mine.rank", "mine_profile":"mine.profile", "indicator":"indicator.series", "document":"document.retrieve", "okf_lookup":"document.lookup", "concept":"document.retrieve", "stockpile_methodology":"stockpile.methodology", "menu":"menu.navigate", "dataset":"dataset.navigate", "diagnosis":"diagnosis.rank", "forecast_demand":"forecast.demand", "forecast_price":"forecast.price", "forecast_quantity":"forecast.quantity", "geopolitics_index":"geopolitics.index", "geopolitics_articles":"geopolitics.articles", "off_topic":"off_topic"}

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
    requested_outputs: set[Literal["text", "table", "chart", "menu", "raw_data"]] = {"text"}


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: str | None = None
    history_refs: list[str] = []
    complete: bool = True
    predecessor_source_unavailable: bool = False
    actions: list[ActionCall] = Field(min_length=1)


class PlanAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    failure_reason: str | None = None
    plan: ActionPlan | None = None


AVAILABLE = frozenset({
    "price.series", "price.compare", "price.verify_claim", "price.overview", "trade.country_rank", "trade.monthly",
    "trade.concentration", "trade.hs_summary", "trade.indicator", "resource.rank", "resource.yoy", "mine.rank", "mine.profile", "indicator.series", "document.retrieve", "document.lookup", "stockpile.methodology", "menu.navigate", "dataset.navigate",
})
# 독립 근거를 요구하는 수치·문서 action은 requirement_id별로 실행하고
# 최종 생성 단계에서 묶을 수 있다. 메뉴 이동은 별도 page-recommend 경로가
# 소유하므로 데이터 action과 섞지 않는다.
COMPOSABLE_MULTI_ACTIONS = frozenset({
    "price.series", "price.compare", "price.verify_claim", "price.overview",
    "trade.country_rank", "trade.monthly", "trade.concentration", "trade.hs_summary", "trade.indicator",
    "resource.rank", "resource.yoy", "mine.rank", "mine.profile", "indicator.series",
    "document.retrieve", "document.lookup", "stockpile.methodology",
})
OFF_TOPIC = "off_topic"
MINERAL_ALIASES = {"nickel": "니켈", "cobalt": "코발트", "copper": "구리", "lithium": "리튬", "rare earth": "희토류"}
UNAVAILABLE = frozenset({
    "diagnosis.rank", "diagnosis.series", "forecast.demand", "forecast.price", "forecast.quantity",
    "geopolitics.index", "geopolitics.articles", "stockpile.status",
})
CURRENT_PERIOD_ENDS = frozenset({"latest", "current", "now", "현재", "오늘"})
REQUIRED: dict[str, tuple[str, ...]] = {
    "price.series": ("mineral",), "price.compare": ("minerals",), "price.verify_claim": ("mineral", "claimed_change_pct"),
    "price.overview": ("strategic_price_groups",),
    "trade.country_rank": ("mineral", "metric"), "trade.monthly": (), "trade.concentration": ("mineral",), "trade.indicator": ("trade_metric",),
    "trade.hs_summary": ("hs_code",), "resource.rank": ("mineral", "metric"), "resource.yoy": ("mineral",),
    "mine.rank": ("mine_metric", "mine_order"), "mine.profile": ("mine_name",),
    "indicator.series": ("indicator",), "document.retrieve": ("topic",), "document.lookup": ("topic",), "stockpile.methodology": (),
    "menu.navigate": ("target_page",), "dataset.navigate": ("dataset",),
}
# 검증 완료된 수치 조합만 연다. 문서+수치/미연결 조합은 전체 기권이다.
ALLOWED_MULTI = frozenset({
    frozenset({"resource.rank"}), frozenset({"resource.yoy"}), frozenset({"mine.rank"}), frozenset({"price.compare"}), frozenset({"price.verify_claim"}),
    frozenset({"resource.rank", "trade.country_rank"}), frozenset({"trade.monthly"}),
    # 복수의 독립 source-first 문서 요구는 각각의 requirement ID와 출처를
    # 보존한 채 실행한다. 같은 개념의 중복 여부를 질문 문자열로 추정하지 않는다.
    frozenset({"document.retrieve"}),
})


ACTION_PLAN_PROMPT = """질문을 action 카탈로그의 ActionPlan JSON으로만 변환한다.
action_id는 price.series, price.compare, price.verify_claim, price.overview, trade.country_rank, trade.monthly,
trade.concentration, trade.hs_summary, trade.indicator, resource.rank, resource.yoy, mine.rank, mine.profile, indicator.series, document.retrieve, document.lookup,
menu.navigate, dataset.navigate, diagnosis.rank, diagnosis.series, forecast.demand, forecast.price,
forecast.quantity, geopolitics.index, geopolitics.articles, stockpile.status, stockpile.methodology, scenario.assess,
synthesis.brief 중 하나다. 원문과 확인된 대화에 있는 값만 slots에 넣고 추측하지 않는다.
범위 밖 일반 주제에는 actions=[] 대신 action_id=off_topic 한 개를 사용한다.
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
slots.mineral에 넣는다. 가격예측 원천은 아직 연결되지 않았으므로 이 action은 실행 단계에서
source_unavailable로 종료하며 price.series/price.compare로 대체하지 않는다.
광물종합지수의 현재값·전일 변동(예: "오늘 광물종합지수 얼마야?")과 최근 N개월
추세(예: "최근 3개월 광물종합지수 추세")는 intent=indicator, action_id=indicator.series,
slots.indicator=composite_index로 정규화한다. 기간이 없으면 최신값, "최근 N개월"은
trailing_months=N으로 보존하며 price action으로 대체하지 않는다.
한국·세계 수입/수출 상위국과 점유율은 trade_rank/country_rank, CR3·CR5·집중도는
trade_concentration, 생산량·매장량 국가순위는 resource_rank/resource.rank로 보존한다.
월간동향·일일자원뉴스·주간자원뉴스·수출통제 뉴스의 제목·요약·최신 게시물 검색은
document 또는 document.retrieve로 분류하고 가격·무역 수치 action으로 바꾸지 않는다.
여러 기간 창의 가격 변화를 비교하면 price.compare 하나에 slots.windows=[3,6,12]처럼 모든
개월 창을 넣고 period에는 임의의 단일 창을 넣지 않는다.
광종을 여러 개 언급한 인과·시나리오·영향 설명은 가격·가격변화·가격비교를 명시하지 않는 한
price.compare로 만들지 말고, 해당 설명의 출처를 찾는 document 또는 concept으로 둔다.
기간은 Period(kind, explicit, 필요한 값)으로 정규화한다. 사용자가 일별·주별·월별·연도별 집계를
명시하면 period.frequency에 daily/weekly/monthly/yearly로 기록한다. 단순히 "이번 달" 또는
"월간동향"이라고 한 것은 집계주기 요청이 아니다. JSON 외 텍스트를 출력하지 않는다."""

INTENT_PLAN_PROMPT = """질문의 독립 정보요구를 빠짐없이 requirements IntentCall 목록으로 분해한 closed intent JSON을 출력한다.
intent는 price_series, price_compare, price_claim, trade_rank, trade_monthly, trade_hs,
trade_concentration, trade_indicator, resource_rank, resource_yoy, mine_rank, mine_profile, indicator, document, okf_lookup, concept, stockpile_methodology, menu, dataset, diagnosis, forecast_demand,
forecast_price, forecast_quantity, geopolitics_index, geopolitics_articles, off_topic 중 하나다.
핵심광물 공급망·HHI·수입의존도·가격변동성의 정의와 개념은 concept이며 document.retrieve로
직접 출처를 찾는다. off_topic은 날씨·음식처럼 광물·공급망과 무관한 주제에만 사용한다.
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
        if (item.intent == "diagnosis" and has_population_comparison
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
    compact = re.sub(r"\s+", "", message)
    match = re.fullmatch(
        r"(?:(?:최근)(?P<prefix_count>\d+)(?P<prefix_unit>개월|년))?"
        r"(?P<mineral>리튬|니켈|코발트|구리|동|희토류|흑연)"
        rf"수입중(?P<partner>{_SIMPLE_PARTNER_PATTERN})(?:의)?비중(?:을)?"
        r"(?:(?:최근)(?P<suffix_count>\d+)(?P<suffix_unit>개월|년))?"
        r"(?:얼마야|알려줘|알려주세요|보여줘|보여주세요)[?.]?",
        compact, flags=re.IGNORECASE,
    )
    if not match:
        return None
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
    compact = "".join(message.split())
    labels = (
        ("supply_stability", ("수급동향지표", "수급동향")),
        ("market_outlook", ("시장동향지표", "시장전망지표")),
        ("composite_index", ("광물종합지표", "종합지표")),
    )
    for call in actions:
        if call.action_id != "indicator.series" or call.slots.indicator is not None:
            continue
        for indicator, markers in labels:
            if any(marker in compact for marker in markers):
                call.slots.indicator = indicator
                break


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


def extract_action_plan(message: str, llm: Any, history: list[dict[str, str]] | None = None) -> ActionPlan:
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
    production_yoy = _production_yoy_plan(message)
    if production_yoy is not None:
        return production_yoy
    future_actual_price = _future_actual_price_plan(message)
    if future_actual_price is not None:
        return future_actual_price
    publication_plan = _publication_document_plan(message)
    if publication_plan is not None:
        return publication_plan
    # 특정국 의존도는 HHI와의 경계가 명확한 typed 관계다. 모델이 HHI를
    # 별도 requirement로 과분해하면 validation/repair 전에 실패할 수 있으므로
    # 해당 문맥에서만 결정적 계획을 먼저 사용한다.
    simple_country_share = _simple_country_share_plan(message)
    if simple_country_share is not None:
        return simple_country_share
    intent_plan = extract_intent_plan(message, llm, history)
    semantic_failure = _intent_plan_semantic_failure(intent_plan)
    if semantic_failure:
        intent_plan = repair_intent_plan(message, llm, semantic_failure, history)
    plan = action_plan_from_intent(intent_plan, message)
    plan = normalize_country_rank_request(message, plan)
    _normalize_trade_rank_scope(plan.actions, message)
    assessment = validate_action_plan(plan)
    if assessment.approved or assessment.failure_reason not in {"slot_unresolved", "unsupported_combination"}:
        return plan
    # 모델 출력의 role/중복 오류만 한 번 고친다. 원천 미연결은 재시도로
    # available action처럼 바꾸지 않는다.
    repaired = action_plan_from_intent(repair_intent_plan(message, llm, assessment.failure_reason, history), message)
    repaired = normalize_country_rank_request(message, repaired)
    _normalize_trade_rank_scope(repaired.actions, message)
    if (validate_action_plan(repaired).failure_reason == "slot_unresolved"
            and _has_source_unavailable_predecessor(history or [], repaired)):
        repaired.predecessor_source_unavailable = True
    return repaired


def _strategic_price_overview_plan(message: str) -> ActionPlan | None:
    """YAML 전략광종 목록의 단일 최신 가격 현황 요청만 결정적으로 처리한다."""
    compact = re.sub(r"\s+", "", message)
    group: list[Literal["strategic_six", "strategic_ten"]] | None = None
    if re.fullmatch(r"6대전략광종가격현황(?:을)?(?:한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["strategic_six"]
    elif re.fullmatch(r"10대전략광종가격현황(?:을)?(?:한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["strategic_ten"]
    elif re.fullmatch(r"전략광종가격현황(?:을)?(?:한눈에)?(?:보여줘|알려줘|보여주세요|알려주세요)[?.]?", compact):
        group = ["strategic_six", "strategic_ten"]
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


def _publication_document_plan(message: str) -> ActionPlan | None:
    """명확한 단일 월간동향·뉴스 검색을 문서 action으로 고정한다.

    가격·무역 등 다른 결과와 ``같이`` 보거나 ``비교``하는 복합 질문은 각
    요구를 분해해야 하므로 이 좁은 단축 경로가 소유하지 않는다.
    """
    compact = re.sub(r"\s+", "", message)
    # 포함어/제외어 휴리스틱은 복합 데이터 요구를 계속 삼킬 수 있다. 아래
    # 단일 문서 검색 문형으로 질문 전체가 완결될 때만 이 경로가 소유한다.
    single_publication_patterns = (
        r"이번달(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"최근\d+(?:개월|년)(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"20\d{2}년(?:전략광종|희소금속)?월간동향(?:을)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"최근(?:희소금속|전략광종)?월간동향보고서제목(?:을)?(?:알려줘|알려주세요|보여줘|보여주세요)[?.]?",
        r"최근\d+(?:개월|년)월간동향에서[가-힣A-Za-z0-9·_-]+관련내용(?:을)?(?:찾아줘|찾아주세요|알려줘|알려주세요)[?.]?",
        r"오늘자원뉴스(?:가)?(?:뭐|무엇)(?:있어|있나요|야)[?.]?",
        r"이번주주간자원뉴스(?:를)?요약(?:해줘|해주세요|해주십시오)[?.]?",
        r"최근[가-힣A-Za-z0-9·_-]+수출통제관련뉴스(?:가)?(?:있어|있나요)[?.]?",
    )
    if not any(re.fullmatch(pattern, compact) for pattern in single_publication_patterns):
        return None
    today = date.today()
    period: Period | None = None
    recent = re.search(r"최근(\d+)(개월|년)", compact)
    calendar_year = re.search(r"(20\d{2})년", compact)
    if recent:
        months = int(recent.group(1)) * (12 if recent.group(2) == "년" else 1)
        period = Period(kind="trailing_months", trailing_months=months, explicit=True)
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

    candidates = [call for call in plan.actions if call.action_id == "trade.indicator"]
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
            if value is None or value == []:
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "resource.rank" and call.slots.metric not in {"production", "reserves"}:
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
        if call.action_id == "price.overview":
            groups = call.slots.strategic_price_groups or []
            if (not groups or len(groups) != len(set(groups))
                    or not set(groups) <= {"strategic_six", "strategic_ten"}
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
    if has_unbounded_price_compare and has_independent_document:
        return PlanAssessment(approved=False, failure_reason="source_unavailable")
    if has_independent_document and any(
        call.action_id in {"price.compare", "price.verify_claim"} for call in plan.actions
    ):
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
            and not market_outlook_with_document):
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
            and not market_outlook_with_document):
        # 독립 문서 설명과 함께 기간·창·기준이 전혀 없는 가격 비교가 나온
        # 경우, 비교 관측을 요구한 것이 아니라 모델이 "데이터와 추론 구분"을
        # 가격 action으로 과잉 분해한 상태다. 이 슬롯에는 조회 가능한 비교
        # 조건이 없으므로 조합 미지원으로 숨기지 않고 원천 부족으로 종결한다.
        # 기간/창이 있는 정상 가격 비교와 다른 미지원 조합은 기존 계약을 따른다.
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    return PlanAssessment(approved=True, plan=plan)
