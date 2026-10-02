"""AST 앞단의 저비용 route gate."""
from __future__ import annotations

import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from common.llm_client import KomirJsonLLM

_logger = logging.getLogger(__name__)


class GateDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    type: Literal["none", "previous_turn", "previous_result"] = "none"


class QueryGateDecision(BaseModel):
    """Gate output. It does not contain an AST or a physical action."""

    model_config = ConfigDict(extra="forbid")

    route: Literal["NAVIGATION", "FAQ_CONCEPT", "SIMPLE_LOOKUP", "COMPLEX"] = "COMPLEX"
    dependency: GateDependency = Field(default_factory=GateDependency)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    target_page: str | None = None


GATE_PROMPT = """사용자 질문의 가장 저렴한 처리 경로와 이전 턴 의존 여부만 분류한다.
AST, 실행계획, slot, Action, tool 이름은 만들지 않는다.

route는 NAVIGATION, FAQ_CONCEPT, SIMPLE_LOOKUP, COMPLEX 중 하나다.
NAVIGATION은 데이터값이 아니라 등록된 화면·메뉴·페이지 위치를 묻는 경우다.
FAQ_CONCEPT는 등록된 FAQ/개념 설명으로 바로 처리할 수 있는 경우다.
SIMPLE_LOOKUP은 단일 명확한 값 조회처럼 보이지만 현재 gate에서는 실행하지 않는다.
비교·순위·집계·복합조회·문서+정형·불확실한 질문은 COMPLEX다.
확실하지 않으면 COMPLEX를 선택한다. NAVIGATION이 아니면 target_page는 null이다.
이전 결과를 가리키는 표현이나 현재 질문에 없는 조건을 복원해야 하면
dependency.required=true로 두고 type은 previous_turn 또는 previous_result로 둔다.
독립 질문이면 dependency는 required=false, type=none이다."""


def gate_enabled() -> bool:
    return os.getenv("QUERY_GATE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _history_summary(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Gate에는 대형 결과 대신 typed history의 최소 표면만 전달한다."""

    result: list[dict[str, str]] = []
    for row in (history or [])[-8:]:
        role = str(row.get("role", ""))
        content = str(row.get("content", ""))
        if role in {"user", "assistant"} and content:
            result.append({"role": role, "content": content[:500]})
    return result


def classify_query_gate(
    message: str,
    *,
    llm: KomirJsonLLM | None = None,
    history: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
) -> QueryGateDecision:
    """실패 시 안전하게 COMPLEX로 승격한다."""

    decision = QueryGateDecision()
    try:
        invocation = (llm or KomirJsonLLM()).invoke(
            task="query_gate",
            instructions=GATE_PROMPT,
            payload={"question": message, "history": _history_summary(history)},
            output_model=QueryGateDecision,
            max_tokens=120,
        )
        decision = invocation.output
    except Exception as exc:
        _logger.warning("query gate failed; escalating to AST: %s: %s", type(exc).__name__, exc)
    if decision.route != "NAVIGATION":
        decision = decision.model_copy(update={"target_page": None})
    _logger.info(
        "query_gate session=%s route=%s confidence=%.3f dependency=%s:%s target_page=%s",
        session_id or "-", decision.route, decision.confidence,
        decision.dependency.required, decision.dependency.type, decision.target_page,
    )
    return decision


def navigation_fast_path_applicable(
    decision: QueryGateDecision, *, request_mode: str = "auto"
) -> bool:
    # self-reported confidence를 임의의 확률 threshold로 해석하지 않는다.
    # 대신 navigation route와 typed resource hint가 함께 있을 때만 fast path를
    # 허용한다. hint가 없거나 의존성이 있으면 기존 AST로 승격한다.
    return (
        request_mode == "auto"
        and decision.route == "NAVIGATION"
        and not decision.dependency.required
        and bool(decision.target_page and decision.target_page.strip())
    )
