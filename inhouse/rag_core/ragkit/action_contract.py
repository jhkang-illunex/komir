# -*- coding: utf-8 -*-
"""RAG action/slot 계약.

질문의 문구를 도구 선택 규칙으로 해석하지 않는다. LLM은 이 모듈의 엄격한
``ActionPlan``만 만들고, 이 모듈은 카탈로그·필수 슬롯·허용 조합을 결정적으로
검사한다. 어댑터는 검증된 action만 ``RetrievalRoute``로 바꾼다.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ActionId = Literal[
    "price.series", "price.compare", "price.verify_claim",
    "trade.country_rank", "trade.monthly", "trade.concentration", "trade.hs_summary", "trade.indicator",
    "resource.rank", "mine.rank", "mine.profile", "indicator.series", "document.retrieve", "document.lookup", "menu.navigate", "dataset.navigate",
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
    country_scope: str | None = None
    mine_metric: Literal["production", "reserves"] | None = None
    mine_order: Literal["level", "increase", "yoy_increase", "yoy_decrease"] | None = None
    mine_name: str | None = None
    dataset: Literal["supply_stability", "market_outlook"] | None = None
    requested_outputs: set[Literal["text", "table", "chart", "menu", "raw_data"]] = {"text"}

IntentId = Literal["price_series", "price_compare", "price_claim", "trade_rank", "trade_monthly", "trade_hs", "trade_concentration", "trade_indicator", "resource_rank", "mine_rank", "mine_profile", "indicator", "document", "okf_lookup", "concept", "stockpile_methodology", "menu", "dataset", "diagnosis", "forecast_demand", "forecast_price", "forecast_quantity", "geopolitics_index", "geopolitics_articles", "off_topic"]
INTENT_TO_ACTION = {"price_series":"price.series", "price_compare":"price.compare", "price_claim":"price.verify_claim", "trade_rank":"trade.country_rank", "trade_monthly":"trade.monthly", "trade_hs":"trade.hs_summary", "trade_concentration":"trade.concentration", "trade_indicator":"trade.indicator", "resource_rank":"resource.rank", "mine_rank":"mine.rank", "mine_profile":"mine.profile", "indicator":"indicator.series", "document":"document.retrieve", "okf_lookup":"document.lookup", "concept":"document.retrieve", "stockpile_methodology":"stockpile.methodology", "menu":"menu.navigate", "dataset":"dataset.navigate", "diagnosis":"diagnosis.rank", "forecast_demand":"forecast.demand", "forecast_price":"forecast.price", "forecast_quantity":"forecast.quantity", "geopolitics_index":"geopolitics.index", "geopolitics_articles":"geopolitics.articles", "off_topic":"off_topic"}

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
    "price.series", "price.compare", "price.verify_claim", "trade.country_rank", "trade.monthly",
    "trade.concentration", "trade.hs_summary", "trade.indicator", "resource.rank", "mine.rank", "mine.profile", "indicator.series", "document.retrieve", "document.lookup", "stockpile.methodology", "menu.navigate", "dataset.navigate",
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
    "trade.country_rank": ("mineral", "metric"), "trade.monthly": (), "trade.concentration": ("mineral",), "trade.indicator": ("trade_metric",),
    "trade.hs_summary": ("hs_code",), "resource.rank": ("mineral", "metric"),
    "mine.rank": ("mine_metric", "mine_order"), "mine.profile": ("mine_name",),
    "indicator.series": ("indicator",), "document.retrieve": ("topic",), "document.lookup": ("topic",), "stockpile.methodology": (),
    "menu.navigate": ("target_page",), "dataset.navigate": ("dataset",),
}
# 검증 완료된 수치 조합만 연다. 문서+수치/미연결 조합은 전체 기권이다.
ALLOWED_MULTI = frozenset({
    frozenset({"resource.rank"}), frozenset({"mine.rank"}), frozenset({"price.compare"}), frozenset({"price.verify_claim"}),
    frozenset({"resource.rank", "trade.country_rank"}), frozenset({"trade.monthly"}),
    # 복수의 독립 source-first 문서 요구는 각각의 requirement ID와 출처를
    # 보존한 채 실행한다. 같은 개념의 중복 여부를 질문 문자열로 추정하지 않는다.
    frozenset({"document.retrieve"}),
})


ACTION_PLAN_PROMPT = """질문을 action 카탈로그의 ActionPlan JSON으로만 변환한다.
action_id는 price.series, price.compare, price.verify_claim, trade.country_rank, trade.monthly,
trade.concentration, trade.hs_summary, trade.indicator, resource.rank, mine.rank, mine.profile, indicator.series, document.retrieve, document.lookup,
menu.navigate, dataset.navigate, diagnosis.rank, diagnosis.series, forecast.demand, forecast.price,
forecast.quantity, geopolitics.index, geopolitics.articles, stockpile.status, stockpile.methodology, scenario.assess,
synthesis.brief 중 하나다. 원문과 확인된 대화에 있는 값만 slots에 넣고 추측하지 않는다.
범위 밖 일반 주제에는 actions=[] 대신 action_id=off_topic 한 개를 사용한다.
수급위기 진단/예측/지정학 지수·기사에는 해당 unavailable action을 사용한다.
생산국과 수입국의 집중도·비중 비교는 resource.rank와 trade.country_rank의 검증된 조합이며,
'취약점'이라는 단어만으로 diagnosis action을 선택하지 않는다. 명시 HS 코드의 품목 요약과
수입 현황은 trade.hs_summary 하나로 표현한다. metric이 생략된 country rank는 공개 기본 표시
기준을 슬롯에 명시한다. 메뉴 action은
등록된 page_id/alias 또는 dataset ID(supply_stability, market_outlook)만 사용한다. 범위 밖 일반
주제에는 menu action을 만들지 말고 complete=false로 둔다.
수입액·수입중량·수출액·수출중량의 월별 추이는 trade.monthly이며 price action이 아니다.
무역특화지수(TSI), 현시비교우위(RCA), 무역결합도(TII), 수출입증감률, 특정국 의존도는
trade.indicator다. trade_metric은 tsi/rca/tii/trade_growth/country_dependency 중 하나이며,
기준국은 reporter_country, 상대국은 partner_country에 넣는다. 질문에 없는 필수 조건은
추측하지 않고 null로 둔다.
개별 광산의 생산량·매장량 순위, 국가 안의 광산 1위, 기간 내 생산량 증가 순위는
mine.rank다. 국가별 자원 순위 resource.rank와 구분한다. mine_metric은
production/reserves, mine_order는 level/increase/yoy_increase/yoy_decrease다.
전년 대비(YoY) 증감은 연속된 두 관측 연도만 비교하는 yoy_increase/yoy_decrease로
표현한다. 증가·감소 방향과 지표(생산량·매장량)를 질문대로 보존한다.
산출량은 생산량(production)의 동의어다. 국가 필터는 country_scope,
상위 개수는 top_n, 최근 N년은 period.trailing_months=12*N으로 둔다.
비축 실측을 요청하면서 자료 부재 시 입력값·계산식 설명을 명시적으로 허용한 요구는
stockpile.methodology다. 이 action은 실재고를 조회하거나 추정하지 않고 계산 정의만 제공한다.
문서명·원문·특정 절의 직접 확인은 document.lookup이며 topic에 찾을 문서·절·사실을 보존한다.
한 광산의 위치·소유자·개별 사실은 mine.profile이며 mine_name에 질문의 광산명을 넣는다.
여러 기간 창의 가격 변화를 비교하면 price.compare 하나에 slots.windows=[3,6,12]처럼 모든
개월 창을 넣고 period에는 임의의 단일 창을 넣지 않는다.
광종을 여러 개 언급한 인과·시나리오·영향 설명은 가격·가격변화·가격비교를 명시하지 않는 한
price.compare로 만들지 말고, 해당 설명의 출처를 찾는 document 또는 concept으로 둔다.
기간은 Period(kind, explicit, 필요한 값)으로 정규화한다. JSON 외 텍스트를 출력하지 않는다."""

INTENT_PLAN_PROMPT = """질문의 독립 정보요구를 빠짐없이 requirements IntentCall 목록으로 분해한 closed intent JSON을 출력한다.
intent는 price_series, price_compare, price_claim, trade_rank, trade_monthly, trade_hs,
trade_concentration, trade_indicator, resource_rank, mine_rank, mine_profile, indicator, document, okf_lookup, concept, stockpile_methodology, menu, dataset, diagnosis, forecast_demand,
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
price_claim의 수치 검증과 가격상승 원인은 각각 data와 content로 분리한다. slots에는 질문에
명시된 값만 채운다. 개별 광산의 생산량·매장량 순위와 국가 안의 광산 1위는 mine_rank,
국가별 생산량·매장량 순위는 resource_rank이며 trade_rank는 수출입 금액·중량
국가 순위에만 쓴다. 아직 관측되지 않은 월과 실제 관측범위를 구분하는 요구는 forecast가 아니라
trade_monthly data의 기간·관측범위 요구다. forecast는 미래 예측값 자체를 요청한 경우에만 쓴다.
공급망 취약점의 설명은 기존 수치 data를 해석하는 metadata이고, 진단 점수·등급 자체를 요구할 때만
diagnosis를 쓴다. 명시 HS 코드의 품목명·수입 현황·광종 전체와의 범위 구분은 trade_hs 하나의
data와 metadata로 표현하며 HS가 없는 별도 광종 action이나 document를 만들지 않는다. trade_concentration은
수입·수출 국가 집중도(HHI) 자체를 요청할 때만 쓰며, 생산국 비중과 수입국 비중의 비교는 resource_rank와
trade_rank data의 조합이다. 전기차 수요 둔화처럼 여러 광종의 조건부 영향·상관·시나리오를 설명하는
요청은 가격 수치·가격변화·기간별 가격 비교를 명시하지 않는 한 concept 또는 document content 하나 이상으로
표현하며 price_compare data를 추가하지 않는다. JSON 외 텍스트를 출력하지 않는다."""

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
    return ActionPlan(actions=actions)


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
        ("country_dependency", ("의존도", "의존율")),
        ("trade_growth", ("증감률", "증가율", "감소율")),
        ("tsi", ("무역특화", "tsi")),
        ("rca", ("현시비교우위", "rca")),
        ("tii", ("무역결합도", "tii")),
    )
    metric = next((value for value, markers in metric_markers
                   if any(marker.casefold() in compact for marker in markers)), None)
    mineral_markers = (("리튬", "리튬"), ("니켈", "니켈"), ("코발트", "코발트"),
                       ("구리", "구리"), ("동", "동"), ("희토류", "희토류"))
    mineral = next((value for marker, value in mineral_markers if marker in compact), None)
    call = ActionCall(
        requirement_id="trade_indicator_followup", action_id="trade.indicator",
        slots=ActionSlots(mineral=mineral, trade_metric=metric),
        intent="trade_indicator", role="data",
    )
    plan = ActionPlan(actions=[call])
    _normalize_trade_indicator_slots(plan.actions, message)
    return plan


def _normalize_trade_indicator_slots(actions: list[ActionCall], message: str) -> None:
    """질문에 명시된 무역지표 조건만 typed 슬롯으로 정규화한다.

    LLM이 연도나 수입·수출 같은 표면 조건을 누락해도 새 trade.indicator의
    HITL이 불필요하게 반복되지 않게 한다. 국가·기간을 추정하지 않는다.
    """
    year = re.search(r"(20\d{2})\s*년", message)
    compact = "".join(message.split())
    partner = _dependency_partner_from_message(message)
    for call in actions:
        if call.action_id != "trade.indicator":
            continue
        slots = call.slots
        if slots.trade_metric is None:
            metric_markers = (
                (("country_dependency", ("의존도", "의존율")),),
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
        if year and (slots.period is None or slots.period.kind != "calendar_year"):
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
    return plan


def _dependency_partner_from_message(message: str) -> str | None:
    """특정국 의존도 문맥에서만 질문에 명시된 상대국을 정규화한다.

    ``trade.indicator``의 partner_country는 자유 국가명 추측 슬롯이 아니다.
    수입·수출과 의존도 사이에 명시된 국가, 또는 ``국가산 수입 의존도``처럼
    관계가 완결된 표기만 읽는다. HHI·일반 국가순위에는 적용하지 않는다.
    """
    compact = "".join(message.split())
    patterns = (
        r"(?:수입|수출)(?:의|에서|중)?([가-힣]{2,}|[A-Z]{2,3})(?:산)?(?:의)?(?:의존도|의존율|비중)",
        r"([가-힣]{2,}|[A-Z]{2,3})산(?:[가-힣]{0,12})?(?:수입|수출)(?:의)?(?:의존도|의존율|비중)",
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
        if year and (slots.period is None or slots.period.kind != "calendar_year"):
            slots.period = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
        if slots.flow is None:
            if "수입" in compact:
                slots.flow = "import"
            elif "수출" in compact:
                slots.flow = "export"
        if slots.partner_country is None and partner:
            slots.partner_country = partner
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
    # 특정국 의존도는 HHI와의 경계가 명확한 typed 관계다. 모델이 HHI를
    # 별도 requirement로 과분해하면 validation/repair 전에 실패할 수 있으므로
    # 해당 문맥에서만 결정적 계획을 먼저 사용한다.
    if (_dependency_partner_from_message(message)
            and any(marker in "".join(message.split()) for marker in ("의존도", "의존율"))):
        return trade_indicator_plan_from_question(message)
    intent_plan = extract_intent_plan(message, llm, history)
    semantic_failure = _intent_plan_semantic_failure(intent_plan)
    if semantic_failure:
        intent_plan = repair_intent_plan(message, llm, semantic_failure, history)
    plan = action_plan_from_intent(intent_plan, message)
    assessment = validate_action_plan(plan)
    if assessment.approved or assessment.failure_reason not in {"slot_unresolved", "unsupported_combination"}:
        return plan
    # 모델 출력의 role/중복 오류만 한 번 고친다. 원천 미연결은 재시도로
    # available action처럼 바꾸지 않는다.
    repaired = action_plan_from_intent(repair_intent_plan(message, llm, assessment.failure_reason, history), message)
    if (validate_action_plan(repaired).failure_reason == "slot_unresolved"
            and _has_source_unavailable_predecessor(history or [], repaired)):
        repaired.predecessor_source_unavailable = True
    return repaired


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
    if slots.period is None or slots.period.kind != "calendar_year":
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
        if call.action_id.startswith("price.") and call.slots.metric in {"import_amount", "import_weight", "export_amount", "export_weight"}:
            return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if missing_trade_indicator_slots(call):
            return PlanAssessment(approved=False, failure_reason="slot_required")
    # 미연결 원천을 쓰는 action은 그 action의 선택 자체로 제공 불가가 확정된다.
    # 다른 action의 후속 슬롯이나 의존성 오류가 이 원천 상태를 slot 오류로
    # 가리지 않게 먼저 분류한다.
    if any(call.action_id in UNAVAILABLE for call in plan.actions):
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
        if call.action_id == "mine.rank":
            if call.slots.mine_order == "increase" and call.slots.mine_metric != "production":
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
            if call.slots.period and call.slots.period.kind == "future_horizon":
                return PlanAssessment(approved=False, failure_reason="slot_unresolved")
        if call.action_id == "indicator.series" and call.slots.indicator == "composite_index" and call.slots.mineral:
            # 광물종합지표는 광종별 시계열이 아니다. 잘못된 슬롯이 아니라
            # 현재 연결된 원천이 제공하지 않는 데이터 범위다.
            return PlanAssessment(approved=False, failure_reason="source_unavailable")
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
    if (len(plan.actions) > 1 and frozenset(action_ids) not in ALLOWED_MULTI
            and not market_outlook_with_document):
        # 독립 문서 설명과 함께 기간·창·기준이 전혀 없는 가격 비교가 나온
        # 경우, 비교 관측을 요구한 것이 아니라 모델이 "데이터와 추론 구분"을
        # 가격 action으로 과잉 분해한 상태다. 이 슬롯에는 조회 가능한 비교
        # 조건이 없으므로 조합 미지원으로 숨기지 않고 원천 부족으로 종결한다.
        # 기간/창이 있는 정상 가격 비교와 다른 미지원 조합은 기존 계약을 따른다.
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
        if has_unbounded_price_compare and has_independent_document:
            return PlanAssessment(approved=False, failure_reason="source_unavailable")
        return PlanAssessment(approved=False, failure_reason="unsupported_combination")
    return PlanAssessment(approved=True, plan=plan)
