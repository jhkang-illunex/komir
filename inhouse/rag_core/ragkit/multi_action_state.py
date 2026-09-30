# -*- coding: utf-8 -*-
"""복합 Action의 2턴 상태 계약.

대화 본문을 다시 해석해 슬롯을 복원하지 않는다. 성공한 같은 action-family의
복합 계획에서 허용된 조회 조건만 저장하고, 후속 문장의 명시 조건만 덮어쓴다.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .action_contract import ActionCall, ActionPlan, ActionSlots, Period, validate_action_plan
from .action_results import ActionResult


RAG_TURN_KEY = "rag_turn"
MULTI_ACTION_KEY = "multi_action_v1"
PRICE_CONTEXT_KEY = "price_context_v1"
NON_CARRY_KEY = "multi_action_non_carry_v1"
_MAX_ACTIONS = 4
_MAX_ENVELOPE_BYTES = 3800


class CarrySlotsV1(BaseModel):
    """후속 조회에 안전하게 재사용 가능한 슬롯만 담는 allow-list."""

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
    indicator: Literal["supply_stability", "market_outlook", "composite_index"] | None = None
    country_scope: str | None = None
    trade_scope: Literal["korea", "global"] | None = None
    denominator_scope: Literal["reporter_product_trade"] | None = None
    mine_metric: Literal["production", "reserves"] | None = None
    mine_order: Literal["level", "increase", "yoy_increase", "yoy_decrease"] | None = None
    mine_name: str | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    price_basis: str | None = None
    currency: str | None = None
    price_operation: Literal[
        "period_average_delta", "monthly_streak", "yearly_average",
        "year_over_year", "period_extrema", "significant_daily_rise",
    ] | None = None
    price_yoy_basis: Literal["monthly_average", "monthly_latest"] | None = None
    selection_mode: Literal["extremum", "rank", "ordinal"] | None = None
    selection_direction: Literal["min", "max"] | None = None
    selection_position: int | None = Field(default=None, ge=1, le=100)
    selection_limit: int | None = Field(default=None, ge=1, le=100)


class CarryActionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: str
    action_id: str
    slots: CarrySlotsV1
    observed_period: str | None = None


class RagTurnStateV1(BaseModel):
    """성공한 복합 수치 action의 최소 세션 상태. 원문·인용·결과값은 저장하지 않는다."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    profile: Literal["public", "private"]
    actions: list[CarryActionV1] = Field(min_length=2, max_length=_MAX_ACTIONS)

    @model_validator(mode="after")
    def same_family_only(self) -> "RagTurnStateV1":
        if len({item.action_id for item in self.actions}) != 1:
            raise ValueError("cross_family_multi_action_state")
        return self


class PriceContextV1(BaseModel):
    """한 개의 성공한 price.series를 위한 1-hop 후속 문맥 계약.

    원문 표·가격값은 저장하지 않고, 후속 선택 연산에 필요한 typed 슬롯만
    보존한다. 복합 Action 상태(RagTurnStateV1)의 min_length=2 계약은 그대로
    유지한다.
    """

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    profile: Literal["public", "private"]
    action: CarryActionV1


def price_context_from_action_results(
    plan: ActionPlan | None,
    results: list[ActionResult],
    *,
    profile: Literal["public", "private"],
) -> PriceContextV1 | None:
    """성공한 단일 price.series의 다음 턴 상속 문맥을 만든다."""

    if plan is None or not validate_action_plan(plan).approved or len(plan.actions) != 1:
        return None
    call = plan.actions[0]
    if call.action_id != "price.series":
        return None
    if not any(item.requirement_id == call.requirement_id and item.status == "success" for item in results):
        return None
    result = next((item for item in results if item.requirement_id == call.requirement_id), None)
    return PriceContextV1(profile=profile, action=CarryActionV1(
        requirement_id=call.requirement_id, action_id=call.action_id,
        slots=_carry_slots(call.slots),
        observed_period=_single_observed_period(result) if result is not None else None,
    ))


class FollowupBindingV1(BaseModel):
    """현재 턴이 어떤 이전 요구사항을 상속했는지 남기는 내부 계약."""

    model_config = ConfigDict(extra="forbid")
    relation: Literal["refine", "repeat"]
    source_requirement_ids: list[str] = Field(min_length=2, max_length=_MAX_ACTIONS)
    inherit_fields: set[Literal["mineral", "period", "metric", "top_n"]]


class FollowupResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_candidate", "merged", "ambiguous"]
    plan: ActionPlan | None = None
    binding: FollowupBindingV1 | None = None


def _carry_slots(slots: ActionSlots) -> CarrySlotsV1:
    names = CarrySlotsV1.model_fields
    return CarrySlotsV1.model_validate({name: getattr(slots, name) for name in names})


def state_from_action_results(
    plan: ActionPlan | None,
    results: list[ActionResult],
    *,
    profile: Literal["public", "private"],
) -> RagTurnStateV1 | None:
    """검증·성공한 동일 action-family만 보존한다. partial/실패 action은 제외한다."""

    if plan is None or not validate_action_plan(plan).approved:
        return None
    successful_results = {item.requirement_id: item for item in results if item.status == "success"}
    successful = set(successful_results)
    calls = [call for call in plan.actions if call.requirement_id in successful]
    if not (2 <= len(calls) <= _MAX_ACTIONS) or len({call.action_id for call in calls}) != 1:
        return None
    return RagTurnStateV1(profile=profile, actions=[
        CarryActionV1(
            requirement_id=call.requirement_id, action_id=call.action_id,
            slots=_carry_slots(call.slots),
            observed_period=_single_observed_period(successful_results[call.requirement_id]),
        )
        for call in calls
    ])


def _single_observed_period(result: ActionResult) -> str | None:
    periods = {str(item.observed_period or item.as_of) for item in result.evidence
               if item.observed_period or item.as_of}
    return next(iter(periods)) if len(periods) == 1 else None


def _bounded_citations(citations: list[dict]) -> list[dict]:
    """세션 메타데이터에는 표시용 인용의 작은 투영만 보관한다."""

    bounded = []
    for item in citations[:8]:
        if not isinstance(item, dict):
            continue
        compact = {key: item[key] for key in ("index", "kind", "source", "section", "as_of", "unit",
                                               "requirement_id", "action_id") if key in item}
        for key, value in tuple(compact.items()):
            if isinstance(value, str):
                compact[key] = value[:160]
        bounded.append(compact)
    return bounded


def encode_citation_envelope(
    citations: list[dict], state: RagTurnStateV1 | None,
    price_context: PriceContextV1 | None = None,
) -> str:
    """기존 list 저장을 보존하고, 크기 제한을 넘지 않는 경우에만 상태를 덧붙인다."""

    import json

    if state is None and price_context is None:
        encoded = json.dumps(citations, ensure_ascii=False)
        if len(encoded.encode("utf-8")) <= _MAX_ENVELOPE_BYTES:
            return encoded
        bounded = {"schema_version": 1, "citations": _bounded_citations(citations),
                   "citations_truncated": True}
        encoded = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= _MAX_ENVELOPE_BYTES:
            return encoded
        return json.dumps({"schema_version": 1, "citations": [], "citations_truncated": True},
                          ensure_ascii=False, separators=(",", ":"))
    turn: dict[str, object] = {}
    if state is not None:
        turn[MULTI_ACTION_KEY] = state.model_dump(mode="json")
    if price_context is not None:
        turn[PRICE_CONTEXT_KEY] = price_context.model_dump(mode="json")
    envelope = {"schema_version": 1, "citations": _bounded_citations(citations),
                RAG_TURN_KEY: turn}
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= _MAX_ENVELOPE_BYTES:
        return encoded
    # 슬롯 문자열 자체가 비정상적으로 커도 raw history fallback으로 되돌아가지 않는다.
    profile = state.profile if state is not None else price_context.profile
    return json.dumps({"schema_version": 1, "citations": [], "citations_truncated": True,
                       RAG_TURN_KEY: {NON_CARRY_KEY: {"profile": profile}}},
                      ensure_ascii=False, separators=(",", ":"))


def decode_multi_action_state(payload: object, *, profile: Literal["public", "private"]) -> RagTurnStateV1 | None:
    """알 수 없거나 손상된 과거 metadata는 상태 없음으로 취급한다."""

    if not isinstance(payload, dict):
        return None
    try:
        turn = payload.get(RAG_TURN_KEY, {})
        state = RagTurnStateV1.model_validate(turn.get(MULTI_ACTION_KEY) if isinstance(turn, dict) else None)
    except (TypeError, ValueError):
        return None
    return state if state.profile == profile else None


def decode_price_context(payload: object, *, profile: Literal["public", "private"]) -> PriceContextV1 | None:
    """알 수 없거나 다른 프로필의 단일 가격 문맥은 폐기한다."""

    if not isinstance(payload, dict):
        return None
    try:
        turn = payload.get(RAG_TURN_KEY, {})
        raw = turn.get(PRICE_CONTEXT_KEY) if isinstance(turn, dict) else None
        context = PriceContextV1.model_validate(raw)
    except (TypeError, ValueError):
        return None
    return context if context.profile == profile else None


def is_non_carry_payload(payload: object, *, profile: Literal["public", "private"]) -> bool:
    if not isinstance(payload, dict):
        return False
    turn = payload.get(RAG_TURN_KEY, {})
    marker = turn.get(NON_CARRY_KEY) if isinstance(turn, dict) else None
    return isinstance(marker, dict) and marker.get("profile") == profile


_MINERALS = ("구리", "니켈", "코발트", "리튬", "희토류", "흑연", "망간", "아연", "철광석", "우라늄")
_METRICS = (("생산량", "production"), ("산출량", "production"), ("매장량", "reserves"),
            ("수입액", "import_amount"), ("수입중량", "import_weight"),
            ("수출액", "export_amount"), ("수출중량", "export_weight"))


def is_reference_message(message: str) -> bool:
    compact = re.sub(r"\s+", "", message)
    return any(token in compact for token in ("그럼", "같은기간", "같은조건", "그기간", "그대상", "그지표", "이것도"))


def _explicit_overlay(message: str) -> tuple[dict[str, object], bool]:
    compact = re.sub(r"\s+", "", message)
    overlay: dict[str, object] = {}
    mineral = next((name for name in _MINERALS if name in compact), None)
    if mineral:
        overlay["mineral"] = mineral
    metric = next((value for marker, value in _METRICS if marker in compact), None)
    if metric:
        overlay["metric"] = metric
    year = re.search(r"(20\d{2})년", compact)
    relative = re.search(r"최근(\d+)(개월|년)", compact)
    if year:
        overlay["period"] = Period(kind="calendar_year", calendar_year=int(year.group(1)), explicit=True)
    elif relative:
        months = int(relative.group(1)) * (12 if relative.group(2) == "년" else 1)
        overlay["period"] = Period(kind="trailing_months", trailing_months=months, explicit=True)
    top_n = re.search(r"상위(\d+)개", compact)
    if top_n:
        overlay["top_n"] = int(top_n.group(1))
    return overlay, "같은기간" in compact


def _closed_followup(message: str) -> bool:
    """허용된 슬롯 표기 외의 새 의미 토큰은 Planner로 넘긴다."""

    compact = re.sub(r"\s+", "", message)
    for token in ("그럼", "같은기간", "같은조건", "그기간", "그대상", "그지표", "이것도"):
        compact = compact.replace(token, "")
    for mineral in _MINERALS:
        compact = compact.replace(mineral, "")
    for marker, _ in _METRICS:
        compact = compact.replace(marker, "")
    compact = re.sub(r"20\d{2}년|최근\d+(?:개월|년)|상위\d+개", "", compact)
    compact = re.sub(r"(?:으로|로|도|만|을|를|은|는|의|에|주세요|보여줘|알려줘|표시해줘|계산해줘|[?.!,])", "", compact)
    return not compact


def _observed_range(actions: list[CarryActionV1]) -> Period | None:
    values = {item.observed_period for item in actions}
    if len(values) != 1:
        return None
    value = next(iter(values))
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\s*", value)
    if not match:
        return None
    return Period(kind="range", start=match.group(1), end=match.group(2), explicit=True)


def merge_multi_action_followup(state: RagTurnStateV1, message: str) -> FollowupResolution:
    """명시값만 덮어쓴다. 다중 지표 action의 지표 축소 같은 모호한 변경은 닫는다."""

    if not is_reference_message(message) or not _closed_followup(message):
        return FollowupResolution(status="not_candidate")
    overlay, same_period = _explicit_overlay(message)
    if not overlay and not same_period:
        return FollowupResolution(status="ambiguous")
    calls = [ActionCall(requirement_id=item.requirement_id, action_id=item.action_id,
                        slots=ActionSlots.model_validate(item.slots.model_dump(mode="python")))
             for item in state.actions]
    inherited: set = {"mineral", "period", "metric", "top_n"}
    if "metric" in overlay and len({call.slots.metric for call in calls}) != 1:
        return FollowupResolution(status="ambiguous")
    if "mineral" in overlay and any(call.slots.mineral is None for call in calls):
        return FollowupResolution(status="ambiguous")
    if same_period and "period" not in overlay:
        observed = _observed_range(state.actions)
        if observed is None:
            return FollowupResolution(status="ambiguous")
        overlay["period"] = observed
    try:
        for call in calls:
            call.slots = ActionSlots.model_validate({**call.slots.model_dump(mode="python"), **overlay})
    except ValueError:
        return FollowupResolution(status="ambiguous")
    plan = ActionPlan(actions=calls)
    if not validate_action_plan(plan).approved:
        return FollowupResolution(status="ambiguous")
    return FollowupResolution(status="merged", plan=plan, binding=FollowupBindingV1(
        relation="refine" if overlay else "repeat",
        source_requirement_ids=[call.requirement_id for call in calls], inherit_fields=inherited,
    ))
