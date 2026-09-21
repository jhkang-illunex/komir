# -*- coding: utf-8 -*-
"""질문 요구사항과 데이터 원천의 중앙 계약."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from common.llm_client import KomirJsonLLM


Intent = Literal["numeric_result", "document_content", "concept", "menu"]
SourceDomain = Literal[
    "active_price", "active_trade", "active_production", "active_reserve", "active_indicator",
    "unavailable_diagnosis", "unavailable_demand_forecast", "unavailable_price_forecast",
    "unavailable_quantity_forecast", "unavailable_geopolitical_index", "unavailable_geopolitical_article",
    "unknown",
]

_UNAVAILABLE_LABELS = {
    "unavailable_diagnosis": "수급위기 진단",
    "unavailable_demand_forecast": "수요 예측",
    "unavailable_price_forecast": "가격 예측",
    "unavailable_quantity_forecast": "수요량·물량 예측",
    "unavailable_geopolitical_index": "지정학위기 지수",
    "unavailable_geopolitical_article": "지정학위기 관련 기사",
}
_ACTIVE_DOMAINS = {"active_price", "active_trade", "active_production", "active_reserve", "active_indicator"}


class RequestRequirement(BaseModel):
    """한 절이 요구하는 결과와 슬롯. availability는 이 타입에 넣지 않는다."""

    clause: str
    intent: Intent
    source_domain: SourceDomain
    mineral: str | None = None
    region: str | None = None
    period: str | None = None
    as_of: str | None = None
    metric: str | None = None
    aggregation: str | None = None
    output: str | None = None
    standalone: bool = True


class RequirementPlan(BaseModel):
    requirements: list[RequestRequirement] = Field(min_length=1)


@dataclass(frozen=True)
class SourceAssessment:
    unavailable_domains: tuple[str, ...] = ()
    blocked: bool = False
    unsupported_combination: bool = False
    extraction_valid: bool = True

    @property
    def notice(self) -> str:
        if self.unavailable_domains:
            labels = ", ".join(_UNAVAILABLE_LABELS[name] for name in self.unavailable_domains)
            return f"요청하신 {labels} 데이터는 새 DB 연계 전이라 현재 제공할 수 없습니다."
        if self.unsupported_combination:
            return "수치 데이터와 문서 내용을 함께 요청하는 경우의 요구별 근거 매핑은 현재 제공하지 않습니다."
        if not self.extraction_valid:
            return "질문의 정보요구를 안전하게 구분할 수 없어 현재 제공할 수 없습니다."
        return ""


REQUIREMENT_PLAN_PROMPT = """질문을 독립 정보요구 절 목록으로 분해해 JSON만 출력한다.
각 requirement에는 clause, intent, source_domain, mineral, region, period, as_of,
metric, aggregation, output, standalone을 채운다. availability를 판단하거나 대체 원천을 고르지 않는다.

intent: numeric_result(수치·순위·추이), document_content(문서/보고서/정책 내용),
concept(정의·개념), menu(화면·메뉴 안내).
source_domain: active_price, active_trade, active_production, active_reserve, active_indicator,
unavailable_diagnosis, unavailable_demand_forecast, unavailable_price_forecast,
unavailable_quantity_forecast, unavailable_geopolitical_index, unavailable_geopolitical_article, unknown.

가격 보고서 요약처럼 지표가 문서 제목을 수식하면 document_content 하나다.
가격 수치와 정책 문서 요약을 함께 요구하면 numeric_result와 document_content 두 개다.
진단 점수·등급·순위, 수요/가격/물량 예측, 지정학 지수·사건·연계 기사는 각각 unavailable domain이다.
확신할 수 없는 절은 unknown으로 둔다."""


def extract_requirement_plan(message: str, llm: "KomirJsonLLM") -> RequirementPlan:
    """기존 JSON LLM으로 요구·슬롯만 추출한다. 호출자는 실패를 fail-closed한다."""

    invocation = llm.invoke(
        task="source_requirement_plan", instructions=REQUIREMENT_PLAN_PROMPT,
        payload={"question": message}, output_model=RequirementPlan, max_tokens=800,
    )
    return invocation.output


def assess_requirement_plan(plan: RequirementPlan | None) -> SourceAssessment:
    """정규화된 요구 목록을 capability registry로 결정적으로 판정한다."""

    if plan is None or not plan.requirements:
        return SourceAssessment(blocked=True, extraction_valid=False)
    domains = tuple(dict.fromkeys(
        requirement.source_domain for requirement in plan.requirements
        if requirement.source_domain in _UNAVAILABLE_LABELS
    ))
    has_unknown = any(
        requirement.source_domain == "unknown" and requirement.intent == "numeric_result"
        for requirement in plan.requirements
    )
    has_document = any(requirement.intent == "document_content" for requirement in plan.requirements)
    has_active_numeric = any(
        requirement.intent == "numeric_result" and requirement.source_domain in _ACTIVE_DOMAINS
        for requirement in plan.requirements
    )
    unsupported_combination = has_document and has_active_numeric
    return SourceAssessment(
        unavailable_domains=domains,
        blocked=bool(domains) or has_unknown or unsupported_combination,
        unsupported_combination=unsupported_combination,
        extraction_valid=not has_unknown,
    )


def assess_source_request(message: str) -> SourceAssessment:
    """LLM plan이 없는 소비자를 위한 fail-closed fallback."""

    del message
    return SourceAssessment(blocked=True, extraction_valid=False)
