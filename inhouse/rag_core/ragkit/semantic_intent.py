# -*- coding: utf-8 -*-
"""Typed semantic normalization layer for the RAG action contract.

This module deliberately stops at *what* the user asks for.  It never emits a
physical action id.  ``action_contract`` remains the owner of intent-to-action
resolution, slot validation, and the existing adapter contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import logging
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


_logger = logging.getLogger(__name__)

SemanticDomain = Literal[
    "trade", "price", "resource", "mine", "inventory", "document", "indicator",
    "forecast", "stockpile", "menu", "dataset", "concept", "unknown",
]
SemanticMetric = Literal[
    "concentration", "country_rank", "dependency", "monthly", "indicator",
    "price_series", "price_compare", "price_claim", "volatility", "current",
    "resource_rank", "resource_yoy", "mine_rank", "mine_profile", "latest",
    "price_forecast", "demand_forecast", "quantity_forecast", "retrieve",
    "lookup", "facts", "methodology", "navigate", "series", "unknown",
]


class SemanticPeriod(BaseModel):
    """Natural-language period represented without binding to an Action."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["trailing_months", "calendar_year", "range", "latest", "future_horizon", "relative"]
    trailing_months: int | None = Field(default=None, ge=1, le=240)
    calendar_year: int | None = Field(default=None, ge=1900, le=2200)
    start: str | None = None
    end: str | None = None
    future_horizon: int | None = Field(default=None, ge=1, le=120)
    relative_value: int | None = Field(default=None, ge=1, le=240)
    relative_unit: Literal["day", "week", "month", "year"] | None = None
    relative_anchor: Literal["today", "latest_available"] | None = None
    frequency: Literal["daily", "weekly", "monthly", "yearly"] | None = None
    explicit: bool = False


class SemanticSelection(BaseModel):
    """Composable selection operator, independent of a physical Action.

    ``argmin``/``argmax`` are normalized to ``mode=extremum`` and
    ``find(n)`` to ``mode=ordinal``.  The resolver decides which existing
    Action contract can safely execute the operator.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["extremum", "rank", "ordinal"]
    direction: Literal["min", "max"] | None = None
    position: int | None = Field(default=None, ge=1, le=100)
    limit: int | None = Field(default=None, ge=1, le=100)
    measure: Literal["price", "production", "reserves", "value"] | None = None
    return_fields: list[Literal["value", "date", "country", "rank"]] = Field(default_factory=list)


class SemanticRequirement(BaseModel):
    """Composable WHAT representation.

    ``metric`` is intentionally primitive and never contains a flow or an
    action name.  For example, import concentration is represented as
    ``domain=trade, metric=concentration, flow=import``.
    """

    model_config = ConfigDict(extra="forbid")

    domain: SemanticDomain
    metric: SemanticMetric
    flow: Literal["import", "export"] | None = None
    mineral: str | None = None
    minerals: list[str] | None = None
    scope: Literal["KR", "GLOBAL", "WORLD"] | None = None
    reporter_country: str | None = None
    partner_country: str | None = None
    period: SemanticPeriod | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    price_basis: str | None = None
    currency: str | None = None
    price_group: Literal["strategic", "strategic_six", "strategic_ten", "battery_five"] | None = None
    metric_unit: Literal["amount", "weight"] | None = None
    operation: Literal[
        "direction", "next_month_value", "period_average_delta", "monthly_streak",
        "yearly_average", "significant_daily_rise", "latest_delta", "period_change",
        "period_extrema", "level", "increase", "decrease", "yoy_increase",
        "yoy_decrease", "argmin", "argmax", "ordinal", "reserves",
    ] | None = None
    selection: SemanticSelection | None = None
    relation: Literal["independent", "refine_previous"] = "independent"
    context_ref: Literal["previous_successful_price_series"] | None = None
    comparison: Literal["same_month_previous_year"] | None = None
    aggregation: Literal["monthly_average", "monthly_latest"] | None = None
    topic: str | None = None
    document_type: Literal["resource_news", "report", "concept"] | None = None
    hs_code: str | None = None
    trade_metric: Literal["tsi", "rca", "tii", "trade_growth", "country_dependency"] | None = None
    # A percentage change can exceed 100% (for example, a price that triples
    # is a 200% increase and user claims may state 300%).  Keep a generous
    # finite bound for the typed boundary instead of rejecting a valid claim
    # before the resolver can verify it against observations.
    claimed_change_pct: float | None = Field(default=None, ge=-10000, le=10000)
    comparator: Literal["greater_than", "less_than", "equals"] | None = None
    indicator: Literal["supply_stability", "market_outlook", "composite_index"] | None = None
    indicator_variant: Literal["composite", "major_metals", "minor_metals"] | None = None
    mine_name: str | None = None
    target_page: str | None = None
    dataset: Literal["supply_stability", "market_outlook"] | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    unresolved_reason: str | None = None


class SemanticPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[SemanticRequirement] = Field(min_length=1)
    # Gemma declares the semantic outputs requested by the user.  Validation
    # compares this set with capability outputs; it never reparses the query.
    requested_outputs: set[str] = Field(default_factory=set)
    status: Literal["resolved", "unresolved"] = "resolved"
    unresolved_reason: str | None = None


SEMANTIC_PROMPT = """사용자 질문을 물리적 Action 이름이 없는 typed semantic requirement로 정규화한다.
반드시 SemanticPlan JSON Schema만 따른다. requirements의 각 항목은 WHAT만 표현하고,
trade.concentration, price.series 같은 action_id를 만들지 않는다.
사용자가 요구한 의미 출력은 requested_outputs에 capability output 이름으로 명시한다.
예: 용도와 최신 가격을 함께 요구하면 requested_outputs=["usage","latest_price"]로
기록하고, requirements에도 concept/retrieve와 price/current를 각각 만든다.
requested_outputs와 requirements의 output coverage가 맞지 않으면 불완전한 계획이다.

의미 요소는 조합 가능한 primitive로 분리한다.
- 수입 집중도: domain=trade, metric=concentration, flow=import, scope=KR
- 수출 집중도: domain=trade, metric=concentration, flow=export
- 수입 상위국: domain=trade, metric=country_rank, flow=import
- 특정국 수입 의존도: domain=trade, metric=dependency, flow=import, partner_country 필수
- LME 재고·재고량: domain=inventory, metric=latest, mineral 필수. resource/current로
  우회하지 않는다. 재고는 생산·매장량의 현재값과 다른 inventory 의미다.
- 가격 연도별 평균: domain=price, metric=price_series, operation=yearly_average.
- 지정 시작일 이후 최고가·최고일자: domain=price, metric=price_series,
  operation=period_extrema, period.kind=range.
- 가격 전년 동월 변화율: domain=price, metric=price_series, operation=period_change,
  comparison=same_month_previous_year. aggregation은 기본 monthly_average이며,
  "월 최신 관측값·월말 기준"을 명시하면 monthly_latest를 사용한다.
- 다음 달 가격 전망: domain=price, metric=price_forecast, period.kind=future_horizon,
  period.future_horizon=1. 이는 관측 가격 시계열이 아니라 forecast 의미다.
- 특정 연도 가격의 수치 주장과 원인 질문(예: "니켈 가격이 2025년에 정확히 300% 올랐는데
  원인이 뭐야")은 두 개의 독립 requirement로 만든다. 첫째는
  domain=price, metric=price_claim, mineral과 period.kind=calendar_year,
  claimed_change_pct=300, comparator=equals인 검증 요구다. 둘째는
  domain=document, metric=retrieve, topic에 해당 연도·광종·가격 상승 원인을 보존한
  근거 문서 요구다. 300% 같은 값도 임의로 100% 이하로 줄이지 않는다.
- "2025년 니켈 가격이 300% 이상 올랐어?"처럼 수치 주장만 물으면
  domain=price, metric=price_claim, period.kind=calendar_year,
  claimed_change_pct=300, comparator=greater_than로 표현한다. "이하/미만"은
  less_than, "정확히/같아"는 equals를 사용하며 일반 price_series로 축약하지 않는다.
- 세계 생산국·생산량 국가순위: domain=resource, metric=resource_rank, scope=WORLD,
  mineral 필수. "생산국"은 무역 flow가 없으며 trade/export로 해석하지 않는다.
  "제일 큰·가장 큰·최대·1위·어디가 제일 커"처럼 단일 최댓값을 묻는
  최상급 표현은 operation=argmax로 표현하고, 명시적 "상위 N개"만 top_n=N으로 표현한다.
  최상급도 상위 개수도 없는 일반 순위 요청은 top_n을 생략한다(Resolver 기본 5개).
- 세계 매장량·매장량 국가순위는 domain=resource, metric=resource_rank,
  scope=WORLD, operation=reserves로 표현한다. 생산량과 매장량을 함께 물으면
  resource/resource_rank 요구사항을 각각 만들며, 매장량을 mine_profile로 만들지 않는다.
  예를 들어 "희토류 생산량과 매장량 상위 국가"는 생산량·매장량 각각의
  resource_rank 두 개이며 두 항목 모두 operation을 생략한다(기본 상위 5개).
  이 표현을 argmax(1위)로 바꾸지 않는다. argmax는 "제일/가장/최대/1위"가
  명시된 경우에만 사용한다.
- 우리나라 수입국: domain=trade, metric=country_rank, flow=import, scope=KR.
  생산국과 수입국이 함께 나오면 독립 requirements로 각각 표현한다.
- 세계 생산국 비중과 한국 수입국 비중을 비교하면서 공급망 취약성을 묻는 경우에도
  resource/resource_rank(생산, WORLD)와 trade/country_rank(수입, KR)를 각각 보존한다.
  공급망 취약성 설명은 두 관측 결과의 metadata이며 diagnosis action이나 수출국으로
  치환하지 않는다.
- 세계 수출국: domain=trade, metric=country_rank, flow=export, scope=GLOBAL.
- 전략광종 가격 현황: domain=price, metric=current, price_group=strategic.
- 2차전지 광물 5종 가격/수입국·전망은 알려진 5개 광물(리튬·니켈·코발트·망간·흑연)을
  각각 독립 requirement로 분해한다. 결과로 광물 목록을 동적으로 만들지는 않는다.
- 광물종합지수 추세: domain=indicator, metric=series, indicator=composite_index,
  indicator_variant=composite, operation=period_change. 가격 추세와 함께 요청되면
  price/price_series requirement와 indicator/series requirement를 각각 만든다.
- 월간동향·자원뉴스 내용 조회(가격 추이와 함께인 경우 포함)는 domain=document,
  metric=retrieve로 표현한다. 자원뉴스는 document_type=resource_news를 함께 기록하고
  topic에는 광종·기간 등 검색 조건을 보존한다. document 내용 요청을 trade/monthly 또는
  price/monthly로 바꾸지 않는다.
- "월간동향 게시판 검색은 어떻게 해?"처럼 사용 방법을 묻는 FAQ는 semantic data/content로
  재해석하지 말고 unresolved로 닫아 기존 FAQ/menu legacy 경로를 사용한다.
- 용도·기본특성·광석 종류 같은 개념/사실 설명은 domain=concept, metric=retrieve,
  topic에 질문 주제를 보존한다. 광물 개념 질문은 mineral도 반드시 채운다.
- "니켈 가격 추세와 광물 종합지수 추세"는 price/price_series(mineral=니켈)와
  indicator/series(indicator=composite_index, indicator_variant=composite)를 각각 만든다.
- "지난달 광물종합지수 변동"은 indicator/series + operation=period_change이며,
  문서 요약이 함께 있으면 document/retrieve를 별도 requirement로 만든다.
- "최근 3개월 월간동향에서 니켈 내용"은 document/retrieve(topic에 질문과 광종 보존)이며
  trade/monthly가 아니다. "니켈 가격 추이와 최근 월간동향"도 같은 두 requirement다.
- 세계 생산량 변화·전년 대비는 resource/resource_yoy이며 resource/series로 만들지 않는다.
- 현재 가격: domain=price, metric=current
- 가격 추이: domain=price, metric=price_series
- 기간 표현은 의미 단위로 보존한다. "최근 1주일/7일/한 주"은
  period.kind=relative, relative_value=1, relative_unit=week,
  relative_anchor=latest_available로 표현한다. "최근 3개월"은 기존
  trailing_months를 사용한다. 상대 기간은 resolver가 기존 Action 계약의
  ISO range로 결정적으로 확장하며, 임의의 관측값을 만들지 않는다.
- 선택 연산은 selection primitive로 표현한다. 기간 안의 최고/최저는
  selection={mode=extremum,direction=max|min,measure=price,
  return_fields=[value,date]}로, "상위 N개"는
  selection={mode=rank,direction=max,limit=N}로, "N번째"·find(N)은
  selection={mode=ordinal,position=N}으로 표현한다. argmax/argmin은 각각
  extremum max/min의 호환 표기이며, selection이 있으면 operation을 반복하지 않는다.
- 선택 연산의 실행 가능 여부는 resolver가 기존 Action 계약으로 검증한다.
  현재 price.series의 extrema(최고·최저)와 ordinal(관측일 순번),
  resource.rank의 production/reserves argmax만 지원한다. 지원하지 않는
  조합은 추측하지 말고 unresolved로 닫아 legacy로 fallback한다.
- "그중 가격이 제일 낮았던 날", "그 표의 세 번째 관측값"처럼 직전의 성공한
  단일 가격 시계열을 좁히는 후속 질문은 relation=refine_previous,
  context_ref=previous_successful_price_series를 사용한다. 후속 requirement에는
  새 광종·기간을 추측하지 말고 selection만 채운다. 호출 payload의
  previous_context가 제공되면 resolver가 그 typed mineral/period를 한 번만
  상속한다. 이전 문맥이 없으면 unresolved로 닫는다.
- 수입액·수입중량·최근 N개월/연도 범위 교역은 domain=trade, metric=monthly로
  표현한다. metric=price_series/price_compare를 trade에 붙이지 않는다.
  금액은 metric_unit=amount, 중량은 metric_unit=weight로 분리하며, 두 요구가
  함께 나오면 requirements를 각각 만든다.
- 광종의 HS 코드 목록은 domain=document, metric=lookup, topic에 광종과
  ``HS코드 목록``을 보존한다. 단일 10자리 HS 코드의 품목·수입현황과 구분한다.
- 수급안정화지수의 최근값·위기 여부는 domain=indicator, metric=latest,
  indicator=supply_stability, period.kind=latest 하나로 표현한다.

다음 표현은 모두 같은 canonical requirement여야 한다.
"니켈 수입 집중도를 알려줘", "니켈 수입이 특정 국가에 얼마나 몰려 있어?",
"니켈 수입선이 편중되어 있어?", "니켈을 일부 국가에 많이 의존하고 있어?",
"니켈 공급국이 몇 나라에 집중돼 있나?"
→ domain=trade, metric=concentration, flow=import, mineral=니켈, scope=KR.

중요한 경계: ``dependency``는 중국·호주처럼 특정 partner_country가 질문에
명시된 경우에만 사용한다. "일부 국가에 많이 의존", "수입선이 편중", "공급국이
몇 나라에 집중"처럼 상대국 이름이 없는 표현은 위 예시처럼 concentration이다.

동의어·구어체·존댓말·어순 변경·띄어쓰기·가벼운 오탈자는 의미로 정규화한다.
질문에 없는 값은 추측하지 않는다. 현재 Action 계약으로 안전하게 표현할 수 없거나
의미가 불명확하면 status=unresolved 또는 domain/metric=unknown으로 닫고
unresolved_reason을 채운다. 임의의 action 이름이나 enum 밖의 값은 출력하지 않는다.
복합질의는 독립적인 requirements 여러 개로 분해하되 의존성 그래프는 이번 단계에서
만들지 않는다. JSON 외 텍스트를 출력하지 않는다."""


@dataclass(frozen=True, slots=True)
class SemanticResolution:
    semantic_plan: SemanticPlan | None
    intent_plan: Any | None
    action_plan: Any | None
    reason: str | None = None


class SemanticResolutionError(ValueError):
    """Semantic output cannot be safely mapped to the existing contract."""


def semantic_mode() -> Literal["off", "shadow", "enabled"]:
    # The in-house deployment env-file sets the operational default to shadow.
    # If no env-file is loaded (for example, a standalone library/test process),
    # retain the legacy off behavior rather than introducing an implicit LLM call.
    value = os.getenv("SEMANTIC_INTENT_MODE", "off").strip().casefold()
    # ``enable`` is accepted as a deployment-friendly alias for the documented
    # ``enabled`` mode; the resolver itself only exposes the canonical value.
    if value == "enable":
        value = "enabled"
    return value if value in {"off", "shadow", "enabled"} else "off"


def canonical_signature(plan: SemanticPlan | None) -> tuple[dict[str, Any], ...] | None:
    """Stable, action-independent signature used by shadow/regression audits."""

    if plan is None:
        return None
    values: list[dict[str, Any]] = []
    for item in plan.requirements:
        values.append({
            "domain": item.domain,
            "metric": item.metric,
            "flow": item.flow,
            "mineral": item.mineral,
            "minerals": item.minerals,
            "scope": item.scope,
            "reporter_country": item.reporter_country,
            "partner_country": item.partner_country,
            "period": item.period.model_dump(mode="json", exclude_none=True) if item.period else None,
            "top_n": item.top_n,
            "metric_unit": item.metric_unit,
            "operation": item.operation,
            "selection": item.selection.model_dump(mode="json", exclude_none=True) if item.selection else None,
            "relation": item.relation,
            "context_ref": item.context_ref,
            "comparison": item.comparison,
            "aggregation": item.aggregation,
            "topic": item.topic,
            "document_type": item.document_type,
            "hs_code": item.hs_code,
            "trade_metric": item.trade_metric,
            "claimed_change_pct": item.claimed_change_pct,
            "comparator": item.comparator,
            "indicator": item.indicator,
            "indicator_variant": item.indicator_variant,
            "mine_name": item.mine_name,
            "target_page": item.target_page,
            "dataset": item.dataset,
            "price_group": item.price_group,
        })
    return tuple(sorted(values, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)))


def _period(value: SemanticPeriod | None, *, default_kind: str | None = None) -> Any:
    from .action_contract import Period

    if value is None:
        return Period(kind=default_kind) if default_kind else None
    if value.kind == "relative":
        if value.relative_value is None or value.relative_unit is None:
            raise SemanticResolutionError("relative period requires value and unit")
        # ``latest_available`` is intentionally bounded by today's date.  The
        # adapter may return fewer rows when the latest observation lags; it
        # must not be given a synthetic future observation.
        end = date.today()
        multiplier = {"day": 1, "week": 7, "month": 30, "year": 365}[value.relative_unit]
        start = end - timedelta(days=value.relative_value * multiplier - 1)
        return Period(kind="range", start=start.isoformat(), end=end.isoformat(),
                      frequency=value.frequency, explicit=value.explicit)
    return Period(**value.model_dump(exclude_none=True))


def _selection(item: SemanticRequirement) -> SemanticSelection | None:
    """Normalize compatibility operation aliases into one typed primitive."""
    if item.selection is not None:
        return item.selection
    if item.operation == "argmin":
        return SemanticSelection(mode="extremum", direction="min")
    if item.operation == "argmax":
        return SemanticSelection(mode="extremum", direction="max")
    if item.operation == "ordinal":
        return None
    if item.operation == "period_extrema":
        return SemanticSelection(mode="extremum", direction="max", measure="price",
                                 return_fields=["value", "date"])
    return None


def _mineral(value: str | None) -> str | None:
    if value is None:
        return None
    aliases = {
        "nickel": "니켈", "cobalt": "코발트", "copper": "구리", "cu": "구리",
        "lithium": "리튬", "manganese": "망간", "graphite": "흑연",
        "rare earth": "희토류", "nd": "네오디뮴", "동": "구리",
    }
    return aliases.get(value.strip().casefold(), value.strip()) or None


def _infer_topic_mineral(topic: str | None) -> str | None:
    """Complete an omitted concept mineral only when the topic is unambiguous."""
    if not topic:
        return None
    aliases = {
        "니켈": "니켈", "nickel": "니켈", "코발트": "코발트", "cobalt": "코발트",
        "구리": "구리", "copper": "구리", "동": "구리", "cu": "구리",
        "리튬": "리튬", "lithium": "리튬", "망간": "망간", "manganese": "망간",
        "흑연": "흑연", "graphite": "흑연", "희토류": "희토류", "rare earth": "희토류",
        "네오디뮴": "네오디뮴", "nd": "네오디뮴",
    }
    folded = topic.casefold()
    found = {canonical for alias, canonical in aliases.items() if alias in folded}
    return next(iter(found)) if len(found) == 1 else None


def _normalize_price_claim_cause(plan: SemanticPlan, message: str) -> SemanticPlan:
    """Recover the closed price-claim + cause-document slice.

    This is deliberately a typed repair for an unambiguous, independently
    executable capability.  It does not map a phrase to a physical action and
    it does not infer a cause; the document requirement merely preserves the
    requested topic for source retrieval.
    """
    if not message or not any(marker in message for marker in ("가격", "시세")):
        return plan
    if not any(marker in message for marker in ("원인", "이유", "왜", "때문")):
        return plan
    pct_match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*%", message)
    year_match = re.search(r"(20\d{2})\s*년", message)
    if not pct_match or not year_match:
        return plan
    mineral = _infer_topic_mineral(message)
    if not mineral:
        return plan
    pct = float(pct_match.group(1).replace(",", ""))
    year = int(year_match.group(1))
    period = SemanticPeriod(kind="calendar_year", calendar_year=year, explicit=True)
    requirements = list(plan.requirements)
    claim_index = next((i for i, item in enumerate(requirements)
                        if item.domain == "price" and item.metric == "price_claim"), None)
    # Gemma may classify the observed clause as a generic price series.  For
    # this exact numeric-claim + cause shape, retain the requirement but
    # correct its primitive metric before Action resolution.
    if claim_index is None:
        claim_index = next((i for i, item in enumerate(requirements)
                            if item.domain == "price"
                            and item.metric in {"price_series", "current"}), None)
    claim = SemanticRequirement(
        domain="price", metric="price_claim", mineral=mineral, period=period,
        claimed_change_pct=pct, comparator="equals",
    )
    if claim_index is None:
        requirements.insert(0, claim)
    else:
        requirements[claim_index] = requirements[claim_index].model_copy(update={
            "metric": "price_claim",
            "mineral": requirements[claim_index].mineral or mineral,
            "period": requirements[claim_index].period or period,
            "claimed_change_pct": requirements[claim_index].claimed_change_pct
            if requirements[claim_index].claimed_change_pct is not None else pct,
            "comparator": requirements[claim_index].comparator or "equals",
        })
    document_indices = [i for i, item in enumerate(requirements)
                        if item.domain == "document" and item.metric == "retrieve"]
    if len(document_indices) == 1:
        index = document_indices[0]
        requirements[index] = requirements[index].model_copy(update={
            "mineral": requirements[index].mineral or mineral,
            "topic": requirements[index].topic
            if requirements[index].topic and any(marker in requirements[index].topic for marker in ("원인", "이유"))
            else f"{year}년 {mineral} 가격 상승 원인",
        })
    elif not document_indices:
        requirements.append(SemanticRequirement(
            domain="document", metric="retrieve", mineral=mineral,
            topic=f"{year}년 {mineral} 가격 상승 원인",
        ))
    return plan.model_copy(update={"requirements": requirements})


def _normalize_price_claim(plan: SemanticPlan, message: str) -> SemanticPlan:
    """Normalize an explicit percentage claim before action resolution.

    Gemma sometimes labels a question such as ``2025년 니켈 가격이 300%
    이상 올랐어?`` as a normal price series.  The percentage, calendar year,
    mineral, and comparison wording together form an unambiguous typed claim;
    this repair keeps the value in the semantic layer without naming a
    physical action.  Cause/document requirements are handled separately.
    """
    if not message or not any(marker in message for marker in ("가격", "시세")):
        return plan
    if not any(marker in message for marker in ("%", "퍼센트")):
        return plan
    if not any(marker in message for marker in ("올랐", "상승", "하락", "변했", "이상", "이하", "맞아", "사실", "전제")):
        return plan
    pct_match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:%|퍼센트)", message)
    year_match = re.search(r"(20\d{2})\s*년", message)
    mineral = _infer_topic_mineral(message)
    if not pct_match or not year_match or not mineral:
        return plan
    pct = float(pct_match.group(1).replace(",", ""))
    year = int(year_match.group(1))
    compact = re.sub(r"\s+", "", message)
    comparator = (
        "greater_than" if any(marker in compact for marker in ("이상", "넘게", "초과"))
        else "less_than" if any(marker in compact for marker in ("이하", "미만"))
        else "equals"
    )
    period = SemanticPeriod(kind="calendar_year", calendar_year=year, explicit=True)
    requirements = list(plan.requirements)
    claim_index = next((i for i, item in enumerate(requirements)
                        if item.domain == "price"
                        and item.metric in {"price_claim", "price_series", "current"}), None)
    claim = SemanticRequirement(
        domain="price", metric="price_claim", mineral=mineral, period=period,
        claimed_change_pct=pct, comparator=comparator,
    )
    if claim_index is None:
        requirements.insert(0, claim)
    else:
        original = requirements[claim_index]
        requirements[claim_index] = original.model_copy(update={
            "domain": "price", "metric": "price_claim",
            "mineral": original.mineral or mineral,
            "period": original.period or period,
            "claimed_change_pct": original.claimed_change_pct if original.claimed_change_pct is not None else pct,
            "comparator": original.comparator or comparator,
        })
    return plan.model_copy(update={"requirements": requirements})


def _normalize_semantic_plan(plan: SemanticPlan, message: str = "") -> SemanticPlan:
    """Fill typed slots that are explicitly recoverable from closed capabilities."""
    plan = _normalize_price_claim(plan, message)
    plan = _normalize_price_claim_cause(plan, message)
    compact = re.sub(r"\s+", "", message)
    requirements = []
    for item in plan.requirements:
        if item.domain == "concept" and item.metric in {"retrieve", "lookup", "facts"} and not item.mineral:
            mineral = _infer_topic_mineral(item.topic)
            if mineral:
                item = item.model_copy(update={"mineral": mineral})
        # Gemma가 교역 금액/중량을 price_series 또는 price_compare로 투영하는
        # 경우가 있다. domain=trade와 flow·광종이 이미 typed로 확정된 경우에만
        # 기존 독립 trade.monthly capability로 되돌린다.
        if (item.domain == "trade" and item.metric in {"price_series", "price_compare", "series"}
                and item.flow in {"import", "export"}
                and (item.mineral or item.minerals)
                and any(marker in compact for marker in ("수입", "수출", "교역", "수입액", "수입중량", "수출액", "수출중량"))):
            item = item.model_copy(update={"metric": "monthly"})
        # HS 코드 목록은 광종에 대한 문서 원문 lookup이다. 물리 action을
        # semantic output으로 노출하지 않고 기존 document.lookup 계약으로
        # 넘겨, 명시 10자리 HS 요약과 혼동하지 않는다.
        if (item.domain == "trade" and item.metric == "lookup" and item.mineral
                and "HS" in compact and any(marker in compact for marker in ("목록", "리스트", "해당"))):
            topic = item.topic or f"{item.mineral} HS코드 목록"
            item = item.model_copy(update={"domain": "document", "metric": "lookup", "topic": topic})
        # 모델이 수급안정화지수의 값을 latest/indicator로 표현해도 동일한
        # indicator series typed contract로 정규화한다.
        if item.domain == "indicator" and item.metric == "latest" and item.indicator == "supply_stability":
            period = item.period or SemanticPeriod(kind="latest")
            item = item.model_copy(update={"metric": "series", "period": period,
                                           "operation": None})
        # 범위 시작·끝이 연도 또는 latest sentinel로만 반환된 경우 기존
        # Period validator가 이해하는 ISO 경계로 좁힌다. 실제 미래 관측값을
        # 만들어내지 않고, ``latest``는 시스템의 오늘 날짜로 닫는다.
        if item.period and item.period.kind == "range":
            start, end = item.period.start, item.period.end
            if start and re.fullmatch(r"20\d{2}", start):
                start = f"{start}-01-01"
            if end and end.casefold() in {"latest", "current", "now", "현재", "오늘"}:
                end = date.today().isoformat()
            elif end and re.fullmatch(r"20\d{2}", end):
                end = f"{end}-12-31"
            if start != item.period.start or end != item.period.end:
                item = item.model_copy(update={"period": item.period.model_copy(update={"start": start, "end": end})})
        requirements.append(item)
    return plan.model_copy(update={"requirements": requirements})


def _bind_price_context(plan: SemanticPlan, context: Any | None) -> SemanticPlan:
    """Bind one explicit ``refine_previous`` requirement to typed price slots.

    This is deliberately one-hop and single-family.  It carries dimensions
    (mineral/period/basis) but never carries a prior table value or invents a
    new dependency graph.
    """
    if context is None:
        return plan
    raw = context.model_dump(mode="python") if hasattr(context, "model_dump") else context
    if not isinstance(raw, dict):
        return plan
    action = raw.get("action") if isinstance(raw.get("action"), dict) else raw
    if action.get("action_id") != "price.series":
        return plan
    slots = action.get("slots") if isinstance(action.get("slots"), dict) else {}
    requirements = []
    for item in plan.requirements:
        if (item.relation == "refine_previous"
                and item.context_ref == "previous_successful_price_series"
                and item.domain == "price" and item.metric in {"current", "price_series"}):
            inherited_period = slots.get("period")
            if inherited_period is not None and not isinstance(inherited_period, SemanticPeriod):
                try:
                    inherited_period = SemanticPeriod.model_validate(inherited_period)
                except (TypeError, ValueError):
                    inherited_period = None
            updates = {
                "mineral": item.mineral or slots.get("mineral"),
                "period": item.period or inherited_period,
                "price_basis": item.price_basis or slots.get("price_basis"),
                "currency": item.currency or slots.get("currency"),
                "relation": "independent",
                "context_ref": None,
            }
            item = item.model_copy(update=updates)
        requirements.append(item)
    return plan.model_copy(update={"requirements": requirements})


def _period_default(value: SemanticPeriod | None, months: int = 12) -> Any:
    from .action_contract import Period

    return _period(value) or Period(kind="trailing_months", trailing_months=months)


def _requirement_id(item: SemanticRequirement, index: int) -> str:
    mineral = _mineral(item.mineral) or "multi"
    if item.domain == "trade" and item.metric == "concentration":
        return f"{'export' if item.flow == 'export' else 'import'}_concentration"
    if item.domain == "trade" and item.metric == "country_rank":
        return f"{'global_' if item.scope in {'GLOBAL', 'WORLD'} else ''}{'export' if item.flow == 'export' else 'import'}_countries"
    if item.domain == "price" and item.metric in {"current", "price_series"}:
        return "current_price" if item.metric == "current" else f"price_{mineral}"
    if item.domain == "resource" and item.metric == "resource_yoy":
        return "world_production_yoy"
    return f"semantic_{item.domain}_{item.metric}_{index}"


def _assert_requirements_preserved(intent_plan: Any, action_plan: Any) -> None:
    """Ensure semantic requirements are not silently dropped by the mapper.

    Independent requirements are represented as separate typed calls.  The
    existing mapper may intentionally merge exact duplicate calls (for
    example, a repeated formatting request), but a semantic plan must never
    lose a requirement without making that loss visible.  If that happens we
    fail closed and let the caller use the legacy path instead of returning a
    partial comparison.
    """

    has_data = any(call.role == "data" for call in intent_plan.requirements)
    # Existing mapper behavior intentionally absorbs a metadata-only
    # explanation (for example, a vulnerability narrative) into the adjacent
    # data actions.  That is not a dropped independent data requirement.
    expected = {
        call.requirement_id
        for call in intent_plan.requirements
        if not (has_data and call.role == "metadata")
    }
    resolved = {call.requirement_id for call in action_plan.actions}
    missing = sorted(expected - resolved)
    if missing:
        raise SemanticResolutionError(
            "independent_requirement_dropped:" + ",".join(missing)
        )


def _to_intent_call(item: SemanticRequirement, index: int) -> Any:
    from .action_contract import ActionSlots, IntentCall

    mineral = _mineral(item.mineral)
    scope = item.scope or "KR"
    period = _period(item.period)
    if item.domain == "trade" and item.metric == "concentration":
        if item.flow != "import" or scope != "KR" or not mineral:
            raise SemanticResolutionError("trade concentration currently supports KR import only")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="trade_concentration", role="data",
                          slots=ActionSlots(mineral=mineral, flow="import", period=_period_default(item.period)))
    if item.domain == "trade" and item.metric == "country_rank":
        if item.flow not in {"import", "export"} or scope not in {"KR", "GLOBAL", "WORLD"} or not mineral:
            raise SemanticResolutionError("trade country rank requires flow, scope, and mineral")
        is_global = scope in {"GLOBAL", "WORLD"}
        metric = ("export_" if item.flow == "export" else "import_") + ("weight" if item.metric_unit == "weight" else "amount")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="trade_rank", role="data",
                          slots=ActionSlots(mineral=mineral, metric=metric, flow=item.flow,
                                            trade_scope="global" if is_global else "korea", top_n=item.top_n or 5,
                                            period=_period_default(item.period)))
    if item.domain == "trade" and item.metric == "dependency":
        if item.flow not in {"import", "export"} or not mineral or not item.partner_country:
            raise SemanticResolutionError("trade dependency requires flow, mineral, and partner_country")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="trade_indicator", role="data",
                          slots=ActionSlots(mineral=mineral, flow=item.flow, trade_metric="country_dependency",
                                            reporter_country=item.reporter_country or "한국",
                                            partner_country=item.partner_country,
                                            denominator_scope="reporter_product_trade",
                                            period=_period_default(item.period)))
    if item.domain == "trade" and item.metric == "monthly":
        if not (mineral or item.hs_code) or item.flow not in {"import", "export"}:
            raise SemanticResolutionError("monthly trade requires mineral/HS code and flow")
        metric = ("export_" if item.flow == "export" else "import_") + ("weight" if item.metric_unit == "weight" else "amount")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="trade_monthly", role="data",
                          slots=ActionSlots(mineral=mineral, hs_code=item.hs_code, metric=metric,
                                            flow=item.flow, period=_period_default(item.period)))
    if item.domain == "trade" and item.metric == "indicator":
        if not mineral or not item.trade_metric or item.flow not in {"import", "export"}:
            raise SemanticResolutionError("trade indicator requires mineral, metric, and flow")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="trade_indicator", role="data",
                          slots=ActionSlots(mineral=mineral, flow=item.flow, trade_metric=item.trade_metric,
                                            reporter_country=item.reporter_country or "한국",
                                            partner_country=item.partner_country,
                                            denominator_scope="reporter_product_trade" if item.trade_metric == "country_dependency" else None,
                                            period=_period_default(item.period)))
    if item.domain == "inventory" and item.metric in {"latest", "current"}:
        if not mineral:
            raise SemanticResolutionError("inventory requires mineral")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="inventory_latest", role="data",
                          slots=ActionSlots(mineral=mineral))
    if item.domain == "price" and item.metric == "current" and item.price_group and not mineral:
        groups = {
            "strategic": ["strategic_six", "strategic_ten"],
            "strategic_six": ["strategic_six"],
            "strategic_ten": ["strategic_ten"],
            "battery_five": ["battery_five"],
        }[item.price_group]
        return IntentCall(requirement_id=_requirement_id(item, index), intent="price_series", role="data",
                          slots=ActionSlots(strategic_price_groups=groups))
    if item.domain == "price" and item.metric in {"current", "price_series"}:
        if not mineral:
            raise SemanticResolutionError("price requires mineral")
        price_period = _period(item.period, default_kind="latest")
        selection = _selection(item)
        if selection is not None and selection.mode == "ordinal":
            if selection.position is None or price_period.kind != "range":
                raise SemanticResolutionError("price ordinal selection requires a ranged period and position")
        if selection is not None and selection.mode == "rank":
            raise SemanticResolutionError("price rank selection is not an existing Action capability")
        if selection is not None and selection.mode == "extremum":
            if selection.direction not in {"min", "max"} or price_period.kind not in {"range", "trailing_months"}:
                raise SemanticResolutionError("price extrema requires a ranged period and direction")
        # The existing price adapter's yearly-average contract is encoded by
        # price_operation; it deliberately uses a latest period sentinel while
        # aggregating all available yearly observations.
        is_yoy = item.operation == "period_change" and item.comparison == "same_month_previous_year"
        if is_yoy:
            # 최신 보유월과 전년 동월을 모두 비교하려면 최소 13개월이 필요하다.
            price_period = _period(None, default_kind="trailing_months")
            price_period.trailing_months = 13
        elif item.operation == "yearly_average":
            price_period = _period(None, default_kind="latest")
        price_operation = item.operation if item.operation in {
            "period_average_delta", "monthly_streak", "yearly_average", "period_extrema",
            "significant_daily_rise",
        } else ("year_over_year" if is_yoy else None)
        if selection is not None and selection.mode == "extremum":
            price_operation = "period_extrema"
        slots = ActionSlots(
            mineral=mineral, period=price_period, price_operation=price_operation,
            price_yoy_basis=(item.aggregation or "monthly_average") if is_yoy else None,
            price_basis=item.price_basis, currency=item.currency,
            selection_mode=selection.mode if selection is not None else None,
            selection_direction=selection.direction if selection is not None else None,
            selection_position=selection.position if selection is not None else None,
            selection_limit=selection.limit if selection is not None else None,
        )
        return IntentCall(requirement_id=_requirement_id(item, index), intent="price_series", role="data",
                          slots=slots)
    if item.domain == "price" and item.metric == "price_compare":
        if not item.minerals or len(item.minerals) < 2:
            raise SemanticResolutionError("price comparison requires at least two minerals")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="price_compare", role="data",
                          slots=ActionSlots(minerals=[_mineral(value) for value in item.minerals],
                                             period=_period(item.period), windows=None))
    if item.domain == "price" and item.metric == "price_claim":
        if not mineral or item.claimed_change_pct is None:
            raise SemanticResolutionError("price claim requires mineral and claimed_change_pct")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="price_claim", role="data",
                          slots=ActionSlots(mineral=mineral, claimed_change_pct=item.claimed_change_pct,
                                            comparator=item.comparator or "equals", period=_period(item.period)))
    if item.domain == "resource" and item.metric == "resource_rank":
        if not mineral or (item.scope is not None and item.scope != "WORLD"):
            raise SemanticResolutionError("resource rank requires world scope and mineral")
        selection = _selection(item)
        if selection is not None and selection.mode == "extremum" and selection.direction != "max":
            raise SemanticResolutionError("resource rank currently supports max selection only")
        if selection is not None and selection.mode == "ordinal":
            raise SemanticResolutionError("resource ordinal selection requires a ranked-result binding")
        if selection is not None and selection.mode == "rank" and selection.direction not in {None, "max"}:
            raise SemanticResolutionError("resource rank currently supports descending rank only")
        top_n = (
            1 if selection is not None and selection.mode == "extremum" else
            selection.limit if selection is not None and selection.mode == "rank" and selection.limit else
            1 if item.operation == "argmax" else item.top_n or 5
        )
        metric = "reserves" if item.operation == "reserves" else "production"
        return IntentCall(requirement_id=_requirement_id(item, index), intent="resource_rank", role="data",
                          slots=ActionSlots(mineral=mineral, metric=metric, country_scope="world",
                                            top_n=top_n, period=_period(item.period)))
    if item.domain == "resource" and item.metric == "resource_yoy":
        if not mineral or scope != "WORLD":
            raise SemanticResolutionError("resource yoy requires world scope and mineral")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="resource_yoy", role="data",
                          slots=ActionSlots(mineral=mineral, metric="production", country_scope="world",
                                            period=_period(item.period)))
    if item.domain == "mine" and item.metric == "mine_rank":
        if not mineral:
            raise SemanticResolutionError("mine rank requires mineral")
        order = item.operation if item.operation in {"level", "increase", "decrease", "yoy_increase", "yoy_decrease"} else "level"
        return IntentCall(requirement_id=_requirement_id(item, index), intent="mine_rank", role="data",
                          slots=ActionSlots(mineral=mineral, mine_metric="production", mine_order=order,
                                            top_n=item.top_n or 5, period=_period(item.period)))
    if item.domain == "mine" and item.metric == "mine_profile":
        if not item.mine_name:
            raise SemanticResolutionError("mine profile requires mine_name")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="mine_profile", role="data",
                          slots=ActionSlots(mine_name=item.mine_name, topic=item.topic))
    if item.domain == "indicator" and item.metric in {"series", "indicator", "latest"}:
        if not item.indicator:
            raise SemanticResolutionError("indicator series requires indicator")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="indicator", role="data",
                          slots=ActionSlots(indicator=item.indicator, indicator_variant=item.indicator_variant,
                                            indicator_operation=item.operation if item.operation in {
                                                "latest_delta", "period_change", "period_extrema",
                                            } else None, period=_period(item.period)))
    if ((item.domain == "forecast" and item.metric == "price_forecast")
            or (item.domain == "price" and item.metric == "price_forecast")):
        if not mineral:
            raise SemanticResolutionError("price forecast requires mineral")
        forecast_operation = item.operation if item.operation in {"direction", "next_month_value"} else None
        if forecast_operation is None and item.period and item.period.kind == "future_horizon":
            forecast_operation = "next_month_value" if item.period.future_horizon == 1 else None
        return IntentCall(requirement_id=_requirement_id(item, index), intent="forecast_price", role="data",
                          slots=ActionSlots(mineral=mineral, period=_period(item.period),
                                            forecast_operation=forecast_operation))
    if item.domain == "document" and item.metric in {"retrieve", "lookup", "facts"}:
        topic = item.topic
        if item.document_type == "resource_news":
            topic = "일일 자원뉴스" + (f" {mineral}" if mineral else "")
        if not topic:
            raise SemanticResolutionError("document retrieval requires topic")
        intent = "okf_lookup" if item.metric == "lookup" else ("document_facts" if item.metric == "facts" else "document")
        selection = _selection(item)
        top_n = (selection.limit if selection is not None and selection.mode == "rank" else item.top_n)
        return IntentCall(requirement_id=_requirement_id(item, index), intent=intent, role="content",
                          slots=ActionSlots(mineral=mineral, topic=topic, hs_code=item.hs_code,
                                            period=_period(item.period), top_n=top_n))
    if item.domain == "concept" and item.metric in {"retrieve", "lookup", "facts"}:
        if not item.topic:
            raise SemanticResolutionError("concept retrieval requires topic")
        if "게시판" in item.topic and "검색" in item.topic:
            raise SemanticResolutionError("legacy_menu_faq")
        return IntentCall(requirement_id=_requirement_id(item, index), intent="concept", role="content",
                          slots=ActionSlots(mineral=mineral, topic=item.topic))
    if item.domain == "stockpile" and item.metric == "methodology":
        return IntentCall(requirement_id=_requirement_id(item, index), intent="stockpile_methodology", role="content",
                          slots=ActionSlots(topic=item.topic or "비축 부족분 계산 방법론"))
    if item.domain == "menu" and item.metric == "navigate" and item.target_page:
        return IntentCall(requirement_id=_requirement_id(item, index), intent="menu", role="data",
                          slots=ActionSlots(target_page=item.target_page, mineral=mineral))
    if item.domain == "dataset" and item.metric == "navigate" and item.dataset:
        return IntentCall(requirement_id=_requirement_id(item, index), intent="dataset", role="data",
                          slots=ActionSlots(dataset=item.dataset))
    raise SemanticResolutionError(f"unsupported semantic capability: {item.domain}/{item.metric}")


def resolve_semantic_plan(plan: SemanticPlan, message: str = "") -> tuple[Any, Any]:
    """Resolve semantic WHAT into the existing IntentPlan/ActionPlan contract."""

    plan = _normalize_semantic_plan(plan, message)
    from .semantic_capabilities import validate_requested_outputs
    output_error = validate_requested_outputs(plan.requirements, plan.requested_outputs)
    if output_error:
        raise SemanticResolutionError(output_error)
    if plan.status != "resolved" or any(item.unresolved_reason for item in plan.requirements):
        raise SemanticResolutionError(plan.unresolved_reason or "semantic plan unresolved")
    from .action_contract import IntentPlan, action_plan_from_intent, validate_action_plan

    calls = []
    for index, item in enumerate(plan.requirements):
        # Known multi-mineral groups are expanded into independent typed calls.
        # This is bounded composition, not a result-dependent worklist.
        battery_group = item.domain == "price" and item.metric == "current" and item.price_group == "battery_five"
        expand = (item.mineral is None and
                  ((item.minerals and ((item.domain == "trade" and item.metric == "country_rank") or
                                       (item.domain == "price" and item.metric in {"price_series", "price_forecast"})))
                   or battery_group))
        expansion_values = item.minerals if item.minerals else ["리튬", "니켈", "코발트", "망간", "흑연"]
        children = [item.model_copy(update={"mineral": value, "minerals": None, "price_group": None})
                    for value in expansion_values] if expand else [item]
        for child in children:
            call = _to_intent_call(child, index)
            if any(existing.requirement_id == call.requirement_id for existing in calls):
                call = call.model_copy(update={"requirement_id": f"{call.requirement_id}_{len(calls)}"})
            calls.append(call)
    intent_plan = IntentPlan(requirements=calls)
    action_plan = action_plan_from_intent(intent_plan, message)
    # ``price_series`` is the existing IntentId for the strategic overview
    # family; its typed group slot selects the overview physical action in the
    # final resolver without exposing that action name to the semantic parser.
    for action in action_plan.actions:
        if action.slots.strategic_price_groups:
            action.action_id = "price.overview"
    _assert_requirements_preserved(intent_plan, action_plan)
    assessment = validate_action_plan(action_plan)
    if not assessment.approved:
        raise SemanticResolutionError(f"action validation failed: {assessment.failure_reason}")
    return intent_plan, action_plan


def parse_and_resolve(
    message: str,
    llm: Any,
    history: list[dict[str, str]] | None = None,
    semantic_context: Any | None = None,
) -> SemanticResolution:
    """Call the constrained parser and resolve only validated capabilities."""

    if llm is None or not hasattr(llm, "invoke"):
        return SemanticResolution(None, None, None, "semantic_llm_unavailable")
    semantic_plan: SemanticPlan | None = None
    try:
        invocation = llm.invoke(
            task="semantic_intent",
            instructions=SEMANTIC_PROMPT,
            payload={"question": message, "history": history or [],
                     "previous_context": (
                         semantic_context.model_dump(mode="json")
                         if hasattr(semantic_context, "model_dump") else semantic_context
                     )},
            output_model=SemanticPlan,
            max_tokens=1000,
        )
        candidate = invocation.output
        # Some test doubles and legacy wrappers ignore ``output_model`` and
        # return an IntentPlan.  Never let that bypass the typed boundary or
        # make shadow auditing interfere with the legacy result.
        if not isinstance(candidate, SemanticPlan):
            raise SemanticResolutionError("semantic_output_schema_invalid")
        semantic_plan = _normalize_semantic_plan(candidate, message)
        from .semantic_capabilities import validate_requested_outputs
        output_error = validate_requested_outputs(semantic_plan.requirements, semantic_plan.requested_outputs)
        if output_error:
            raise SemanticResolutionError(output_error)
        semantic_plan = _bind_price_context(semantic_plan, semantic_context)
        intent_plan, action_plan = resolve_semantic_plan(semantic_plan, message)
        return SemanticResolution(semantic_plan, intent_plan, action_plan, None)
    except Exception as exc:
        _logger.info("semantic parser fallback: %s: %s", type(exc).__name__, exc)
        return SemanticResolution(semantic_plan, None, None, f"{type(exc).__name__}:{exc}")


def _action_signature(plan: Any | None) -> tuple[dict[str, Any], ...] | None:
    if plan is None:
        return None
    values = []
    for call in plan.actions:
        values.append({
            "requirement_id": call.requirement_id,
            "action_id": call.action_id,
            "mineral": call.slots.mineral,
            "minerals": call.slots.minerals,
            "flow": call.slots.flow,
            "trade_scope": call.slots.trade_scope,
            "period": call.slots.period.model_dump(mode="json", exclude_none=True) if call.slots.period else None,
            "price_operation": call.slots.price_operation,
            "selection_mode": call.slots.selection_mode,
            "selection_direction": call.slots.selection_direction,
            "selection_position": call.slots.selection_position,
            "selection_limit": call.slots.selection_limit,
        })
    return tuple(values)


def record_shadow_audit(question: str, legacy_plan: Any | None, result: SemanticResolution) -> None:
    """Emit one comparable structured record for shadow-mode evaluation."""

    legacy_sig = _action_signature(legacy_plan)
    semantic_sig = _action_signature(result.action_plan)
    legacy_actions = list(legacy_sig or ())
    semantic_actions = list(semantic_sig or ())
    record = {
        "question": question,
        "legacy_action_plan": legacy_plan.model_dump(mode="json") if legacy_plan is not None else None,
        "semantic_canonical_signature": canonical_signature(result.semantic_plan),
        "semantic_resolved_intent_plan": result.intent_plan.model_dump(mode="json") if result.intent_plan is not None else None,
        "semantic_resolved_action_plan": result.action_plan.model_dump(mode="json") if result.action_plan is not None else None,
        "legacy_semantic_diff": {
            "equal": legacy_sig == semantic_sig,
            "legacy_action_count": len(legacy_actions),
            "semantic_action_count": len(semantic_actions),
            "legacy_action_ids": [item["action_id"] for item in legacy_actions],
            "semantic_action_ids": [item["action_id"] for item in semantic_actions],
            "legacy": legacy_sig,
            "semantic": semantic_sig,
        },
        "semantic_fallback_reason": result.reason,
    }
    _logger.info("semantic_shadow_audit %s", json.dumps(record, ensure_ascii=False, sort_keys=True))


__all__ = [
    "SemanticPeriod", "SemanticSelection", "SemanticRequirement", "SemanticPlan", "SemanticResolution",
    "SEMANTIC_PROMPT", "semantic_mode", "canonical_signature", "parse_and_resolve",
    "resolve_semantic_plan", "record_shadow_audit", "SemanticResolutionError",
]
