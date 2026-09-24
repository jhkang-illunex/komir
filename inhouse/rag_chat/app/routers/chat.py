# -*- coding: utf-8 -*-
"""POST /pubchat, /prichat — 요청 바디: {user_id, session_id(선택, 없으면
신규 발급), message, mode}. 응답: SSE 스트림(streaming.py) — 최종 청크에
citations_json 또는 페이지추천 결과 포함. 이 두 엔드포인트가 프론트가 직접
붙는 실제 API 표면이다.

**2026-08-26 public/private MCP 분리**: 문서 Q&A 경로가 참조하는 hybrid_search·
pageindex_lookup 두 도구는 이제 `rag.ragkit.mcp_client`의 public/private 세션
중 하나를 거친다(라이선스 제한 제3자 문서 접근 여부가 갈림 — 두 프로필은
`rag_core/ragkit/mcp_server_public.py`·`mcp_server_private.py` 물리적으로 분리된
별도 모듈, 모듈독스트링 참고). `/pubchat`은 `profile="public"`,
`/prichat`은 `profile="private"`로 `chat_turn()`을 부른다. 페이지추천
(`page`) 경로는 이 세 도구를 안 써서 profile 무관, 두 엔드포인트 전부 같은
`_run_page_recommend()`를 공유한다.

**같은 날 후속(사용자 요청)**: 하위호환 별칭이던 `/chat`(profile="public")은
**구현(`chat()` 함수)은 남기되 `@router.post` 등록을 빼서 외부 HTTP 인터페이스
에서는 제거**했다 — POST /chat은 이제 404. 재도입하려면 함수 정의 위에
`@router.post("/chat")`만 다시 붙이면 된다(로직 변경 불필요).

두 경로가 있다(2026-08-11 페이지추천 편입):
- document: 정형(Postgres out_*)·dense(pgvector doc_chunk)·PageIndex(OKF 트리) 세
  근거 도구를 LangGraph로 조합(rag.ragkit.chatbot_graph, "어떤 도구를 쓸지" LLM
  1회 판단 후 병렬조회) + 인용강제 생성 + 멀티턴 + 다중매체(표/차트) 이벤트.
  2026-08-13부터 이 경로의 코어 로직 전체(도구 선택·조회·프롬프트 조립·
  스트리밍·인용검증·세션/히스토리 적재·표·차트 이벤트 생성)는 rag.ragkit.
  chatbot.chat_turn()으로 이관됐다(재구현 금지 — rag 패키지 chatbot
  엔트리포인트, chatbot.py·chatbot_graph.py 참고). 여기서는 그 async
  generator를 SSE 프레이밍으로 감싸기만 한다. chat_turn()은 진짜 async
  generator지만, 이 함수(그리고 smoke_chat_routing.py의 동기 호출 계약)는
  그대로 동기 제너레이터로 유지해야 해서 _drain_sync()로 브리지한다.
- page: KOMIS 43개 페이지·필터 추천(app/page_recommend, LangGraph 그래프). 답변이
  LLM 토큰 스트림이 아니라 그래프가 렌더한 완성 텍스트라 delta 한 번으로 내보낸다
  (스트림 계약은 동일하게 유지 — 클라이언트가 경로를 구분하지 않아도 되게).

경로 선택은 요청 바디의 `mode`(auto|document|page)를 따르고, auto면 app/intent.py가
LLM 1회로 분류한다.

SSE 이벤트 계약(프론트 연동 기준, 2026-08-13 table·image 추가, 2026-08-27 status
신설(문자열 stage) → 2026-08-28 정수 stage 1-4 계약으로 확정 —
documents/order/chatbot_rule.txt "기타. 질문 입력 후 상태 값 표출"·유형8 반영,
main-agent가 streamlit-agent와 이 정수 계약으로 조율 완료):
  event: (무명)  data: {"session_id": "..."}                              — 매 턴 최초
  event: status  data: {"stage": 1|2|3|4, "label": "질문 조건 확인|답변 준비중|
                         데이터 분석 중|답변 생성 중"}                      — 처리 진행 표시.
                         문서 경로: retrieve_evidence 내부(route/retrieve/verify/
                         reformulate) 진행상황이 실시간 콜백으로 stage 1-3에 매핑돼
                         나오고(재시도 시 3이 여러 번 올 수 있음), stage 4는 생성 시작
                         직전 1회. 근거 0건/조회 실패 시엔 status 없이 곧장 delta+done.
                         페이지 경로: 1·4만(중간 단계를 안 쪼갬, rag.ragkit.chatbot의
                         _GRAPH_STAGE_TO_STATUS·STATUS_STAGES가 정본).
  event: (무명)  data: {"delta": "..."}                                    — 텍스트 조각
                         (출처 footer·원인해석 주의문구도 델타로 추가 전송될 수 있음.
                         2026-09-16: streaming.StrikethroughFilter를 거쳐 취소선
                         스팬은 제거, 단일 `~`는 `\~`로 이스케이프된 마크다운)
  event: table   data: {"schema_version": 1, "block_id": "t1-1", "columns": [...],
                         "rows": [[...]], "columns_meta": [...], "rows_typed": [...],
                         "markdown": "...", "chart_hint": {"recommended": "line"|
                         "bar"|"pie"|null, "alternatives": [...], "reason": "..."},
                         "meta": {...}, "source_index": n, "source": "..."}
                         — 2026-09-13 /prichat 도입, 2026-09-16 /pubchat 공통 적용
  event: chart   data: {"schema_version": 1, "block_id": "c1-1", "data_ref": "t1-1",
                         "spec": {"kind", "alternatives", "x", "x_type", "x_format",
                         "series", "group", "sort_x_ascending", "title"},
                         "source_index": n, "source": "..."}
                         — 추천 차트가 있을 때만. 구 `image`(PNG) 이벤트는 2026-09-16
                         제거(명세: documents/산출물/2026-W38_0914-0920/
                         rag_chat_구조화블록_공통명세_차트추천_260916.md)
  event: done    data: {"done": true, "abstained": bool, "bogus_citations": [...],
                         "abstain_reason": "off_topic|unsupported_commodity|
                         no_data_for_period|ambiguous|unknown|generation_error"|null,
                         (generation_error: 2026-09-08 skeptic-code SC-2 신설 — 근거는
                         찾았으나 답변 생성 스트리밍 도중 예외로 중단된 경우)
                         "citations": [{"index": n, "kind": "structured|dense|
                         pageindex", "source": "...", "section": "...",
                         "as_of": "..."|null, "unit": "..."|null}, ...]}    — 문서 경로
                         (abstain_reason은 abstained=false면 없음/null)
  event: done    data: {"done": true, "mode": "page", "status": ..., "relation": ...,
                         "recommendations": [...], "warnings": [...]}      — 페이지 경로
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import threading
from contextlib import contextmanager
from contextvars import copy_context
from pathlib import Path
from typing import Iterator, Literal
from uuid import UUID


def _find_root(start: Path, marker: str) -> Path:
    """marker(상대경로 파일)를 담은 디렉토리를 위로 훑어 찾는다.

    소스트리(inhouse/rag_chat/app/routers/chat.py)와 컨테이너 배포본
    (Containerfile이 services/rag_chat/app→./app, services/shared→./shared,
    rag_core/ragkit→./rag_core/ragkit로 평평하게 COPY)의 상대 깊이가 다르다 — 고정 depth
    대신 탐색으로 두 경우를 다 맞춘다(services/shared/db.py·ingest/
    parsers/pdf.py와 같은 패턴)."""

    for candidate in (start, *start.parents):
        if (candidate / marker).is_file():
            return candidate
    raise ImportError(f"{marker}를 {start} 상위에서 찾지 못함")


_HERE = Path(__file__).resolve()
for _root in (
    _find_root(_HERE, "common/llm_client.py"),
    _find_root(_HERE, "rag_core/ragkit/generate.py"),
):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from fastapi import APIRouter  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402
from common.langfuse_tracing import chat_trace, update_observation  # noqa: E402

from rag_core.ragkit.chatbot import STATUS_STAGES, chat_turn  # noqa: E402
from rag_core.ragkit.action_contract import (  # noqa: E402
    ActionPlan, extract_action_plan, merge_trade_indicator_followup,
    trade_indicator_plan_from_question,
    missing_trade_indicator_slots, validate_action_plan,
)
from rag_core.ragkit.messages import chat_message  # noqa: E402
from rag_core.ragkit import mcp_client  # noqa: E402
from common.llm_client import KomirJsonLLM  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.llm_client import get_chat_client  # noqa: E402

from .. import session_store  # noqa: E402
from ..intent import classify_intent, is_unverified_import_demand_forecast_menu  # noqa: E402
from ..page_recommend.service import get_service as get_page_recommend_service  # noqa: E402
from ..page_recommend.registry import RegistryError  # noqa: E402
from ..streaming import StrikethroughFilter, sse_event, strip_strikethrough  # noqa: E402

router = APIRouter()
_logger = logging.getLogger(__name__)

# A chat turn reads its prior state and later appends its answer.  Serializing a
# session in this process prevents interleaved user/assistant rows from being
# mistaken for a coherent conversation.  Multi-process deployments still need
# a shared lock or a transactional session-version check at the DB boundary.
_session_locks: dict[str, threading.Lock] = {}
_session_lock_counts: dict[str, int] = {}
_session_locks_guard = threading.Lock()


@contextmanager
def _session_turn_lock(session_id: str) -> Iterator[None]:
    with _session_locks_guard:
        lock = _session_locks.setdefault(session_id, threading.Lock())
        _session_lock_counts[session_id] = _session_lock_counts.get(session_id, 0) + 1
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _session_locks_guard:
            _session_lock_counts[session_id] -= 1
            if _session_lock_counts[session_id] == 0:
                del _session_lock_counts[session_id]
                del _session_locks[session_id]

def _status_event(stage: int) -> dict:
    """document 경로(chat_turn)의 STATUS_STAGES를 page 경로에서도 재사용 —
    라벨 문구가 두 경로에서 갈라지지 않게 한 곳(chatbot.py)만 정본으로 둔다."""

    return sse_event({"stage": stage, "label": STATUS_STAGES[stage]}, event="status")


# chat_message.citations_json에 페이지추천 대화상태를 실어 나를 때 쓰는 키.
# 원본(komis-report-generator-main)은 이 상태를 LangGraph SqliteSaver에 뒀지만 komir는
# 대화 저장소를 chat_session/chat_message 하나로 유지한다(page_recommend/service.py 주석).
_PAGE_STATE_KEY = "page_recommend"
_MINE_CLARIFICATION_KEY = "mine_country_clarification"
_TRADE_CLARIFICATION_KEY = "trade_indicator_clarification"
_KOMIS_MINERAL_ACTIONS = frozenset({
    "price.series", "price.compare", "price.verify_claim", "trade.country_rank",
    "trade.monthly", "trade.concentration", "trade.indicator", "resource.rank", "indicator.series",
})


def _unsupported_mineral_in_plan(plan: ActionPlan, profile: Literal["public", "private"], *, session=None) -> str | None:
    """슬롯이 가리킨 광물이 실제 KOMIS 목록에 없으면 이름을 돌려준다.

    문서 검색은 KOMIS 등록 광물 밖의 보고서도 근거가 될 수 있으므로 막지 않는다.
    결정적 RDB action에 한해서만, 조회를 시작하기 전에 실제 resolver 결과로
    지원 여부를 확인한다. MCP 장애는 미지원으로 오인하지 않고 기존 조회 오류
    처리로 넘긴다.
    """
    resolver = session or (mcp_client.private if profile == "private" else mcp_client.public)
    for call in plan.actions:
        if call.action_id not in _KOMIS_MINERAL_ACTIONS:
            continue
        names = ([call.slots.mineral] if call.slots.mineral else []) + (call.slots.minerals or [])
        for name in dict.fromkeys(name for name in names if name):
            try:
                resolved = resolver.call_komis_resolve_mineral(name)
            except Exception:  # resolver 장애는 광물 미지원으로 바꾸지 않는다.
                continue
            if resolved.get("mineral_code") is None and any(
                "KOMIS 광종 목록" in warning for warning in resolved.get("warnings", [])
            ):
                return name
    return None


def _unsupported_mineral_response(session_id: str, message: str):
    answer = chat_message("unsupported_commodity")
    session_store.append_message(session_id, "user", message)
    session_store.append_message(session_id, "assistant", answer)
    yield sse_event({"session_id": session_id})
    yield sse_event({"stage": 1, "label": STATUS_STAGES[1], "status": "조회불가",
                     "failure_reason": "unsupported_commodity",
                     "message_key": "unsupported_commodity"}, event="status")
    yield sse_event({"delta": answer})
    yield sse_event({"done": True, "abstained": True,
                     "abstain_reason": "unsupported_commodity",
                     "message_key": "unsupported_commodity"}, event="done")


def _pending_mine_clarification(session_id: str) -> dict | None:
    messages = session_store.list_messages(session_id, limit=1)
    if not messages or messages[-1]["role"] != "assistant":
        return None
    try:
        payload = json.loads(messages[-1].get("citations_json") or "")
    except (TypeError, ValueError):
        return None
    state = payload.get(_MINE_CLARIFICATION_KEY) if isinstance(payload, dict) else None
    return state if isinstance(state, dict) else None


def _pending_trade_clarification(session_id: str) -> dict | None:
    # 현재 턴의 가장 최근 assistant 결과만 pending 후보로 삼는다. 완료된
    # 답변 뒤에 과거 clarification metadata를 다시 찾으면 다음 독립 질문이
    # 오래된 무역 계획으로 오염된다.
    messages = session_store.list_messages(session_id, limit=10)
    latest_assistant = next((message for message in reversed(messages)
                             if message.get("role") == "assistant"), None)
    if latest_assistant is None:
        return None
    message = latest_assistant
    try:
        payload = json.loads(message.get("citations_json") or "")
    except (TypeError, ValueError):
        payload = None
    state = payload.get(_TRADE_CLARIFICATION_KEY) if isinstance(payload, dict) else None
    if isinstance(state, dict):
        return state
    # 구버전 저장 행이나 DB driver가 citations_json을 비워 반환하는 경우에도
    # 바로 직전의 무역 명확화 문장을 typed 계획으로 복원한다.
    if "무역 지표를 계산하려면" not in (message.get("content") or ""):
        return None
    index = messages.index(message)
    previous = next((item for item in reversed(messages[:index]) if item.get("role") == "user"), None)
    if previous:
        plan = trade_indicator_plan_from_question(previous.get("content") or "")
        return {"question": previous.get("content") or "", "plan": plan.model_dump(mode="json")}
    return None


def _recover_trade_followup(session_id: str, message: str) -> ActionPlan | None:
    """저장된 clarification metadata가 없어도 직전 trade 질문을 복원한다."""
    compact = "".join(message.split())
    if not ("한국" in compact and any(re.search(pattern, compact) for pattern in (r"20\d{2}년", r"20\d{2}"))):
        return None
    history = session_store.list_messages(session_id, limit=10)
    previous = next(
        (
            row.get("content") or ""
            for row in reversed(history)
            if row.get("role") == "user"
            and row.get("content") != message
            and any(marker in (row.get("content") or "").casefold()
                    for marker in ("tsi", "rca", "tii", "의존도", "증감률", "증가율", "감소율"))
        ),
        "",
    )
    # assistant 본문 저장 여부는 DB driver마다 다를 수 있다. 직전 질문이
    # typed 무역 지표 문맥이고 현재 턴이 한국·연도를 보충하면, 명확화
    # metadata가 없어도 해당 계획을 복원할 수 있다.
    if not previous:
        return None
    return merge_trade_indicator_followup(
        trade_indicator_plan_from_question(previous), message,
    )


def _trade_indicator_call(plan: ActionPlan):
    calls = [call for call in plan.actions if call.action_id == "trade.indicator"]
    return calls[0] if len(plan.actions) == 1 and len(calls) == 1 else None


_TRADE_SLOT_LABELS = {
    "trade_metric": "무역 지표(TSI, RCA, TII, 수출입증감률, 특정국 의존도)",
    "reporter_country": "기준국", "partner_country": "상대국",
    "period": "대상 연도 또는 기간", "mineral_or_hs_code": "광종 또는 HS 코드",
    "flow": "수입 또는 수출 구분",
}


def _trade_clarification_response(session_id: str, message: str, plan: ActionPlan):
    call = _trade_indicator_call(plan)
    assert call is not None
    missing = missing_trade_indicator_slots(call)
    labels = ", ".join(_TRADE_SLOT_LABELS[name] for name in missing)
    answer = f"무역 지표를 계산하려면 {labels}을(를) 알려주세요."
    session_store.append_message(session_id, "user", message)
    session_store.append_message(
        session_id, "assistant", answer,
        citations_json=json.dumps({_TRADE_CLARIFICATION_KEY: {
            "question": message, "plan": plan.model_dump(mode="json"), "missing_slots": list(missing),
        }}, ensure_ascii=False),
    )
    yield sse_event({"session_id": session_id})
    yield _status_event(1)
    yield sse_event({"delta": answer})
    yield sse_event({"done": True, "needs_clarification": True,
                     "clarification": {"action_id": "trade.indicator", "slots": list(missing)}}, event="done")


def _mine_country_choice(message: str, country: str | None = None) -> str | None:
    """광산 국가 기준에 대한 명시적 선택만 읽는다. 다른 슬롯은 재해석하지 않는다."""
    compact = "".join(message.split()).casefold()
    location = any(term in compact for term in ("소재", "위치"))
    if country:
        country_key = "".join(country.split()).casefold()
        location = location or any(
            term in compact for term in (f"{country_key}내", f"{country_key}에있는")
        )
    ownership = any(term in compact for term in ("소유", "보유"))
    if location and not ownership:
        return "location"
    if ownership and not location:
        return "ownership"
    return None


def _mine_country_call(plan: ActionPlan):
    calls = [call for call in plan.actions if call.action_id == "mine.rank"]
    if len(plan.actions) != 1 or len(calls) != 1:
        return None
    call = calls[0]
    return call if call.slots.country_scope else None


def _mine_clarification_response(session_id: str, message: str, plan: ActionPlan):
    call = _mine_country_call(plan)
    assert call is not None
    country = call.slots.country_scope
    answer = f"'{country}'은 광산 소재지를 뜻하시나요, 소유 기업의 국가를 뜻하시나요? 소재 또는 소유 중 하나를 선택해 주세요."
    session_store.append_message(session_id, "user", message)
    session_store.append_message(
        session_id, "assistant", answer,
        citations_json=json.dumps({_MINE_CLARIFICATION_KEY: {
            "question": message, "plan": plan.model_dump(mode="json"),
        }}, ensure_ascii=False),
    )
    yield sse_event({"session_id": session_id})
    yield _status_event(1)
    yield sse_event({"delta": answer})
    yield sse_event({"done": True, "needs_clarification": True,
                     "clarification": {"slot": "mine_country_relation",
                                       "options": ["location", "ownership"]}}, event="done")


def _unsupported_mine_ownership(session_id: str, message: str):
    answer = "광산 소유 기업의 국가별 생산량 순위는 현재 검증된 집계 기준이 없어 제공할 수 없습니다."
    session_store.append_message(session_id, "user", message)
    session_store.append_message(session_id, "assistant", answer)
    yield sse_event({"session_id": session_id})
    yield _status_event(1)
    yield sse_event({"delta": answer})
    yield sse_event({"done": True, "abstained": True,
                     "abstain_reason": "source_unavailable",
                     "message_key": "action_unavailable",
                     "failure_reason": "mine_ownership_unavailable"}, event="done")


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    session_id: UUID | None = None
    # skeptic-code 감사(2026-08-28) — 빈 문자열이 그대로 통과해 근거 없는 턴을
    # 만들고, top_k는 상한이 없어 임의로 큰 값이 dense_k로 그대로 SQL LIMIT에
    # 실렸다(크래시는 아니지만 자원낭비). 상한은 top_k=6 기본값보다 넉넉히 잡아
    # 실사용 조정 여지는 남긴다.
    message: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=6, ge=1, le=50)
    mode: str = "auto"  # auto | document | page


def _history_for_graph(session_id: str) -> list[dict]:
    """직전 대화와 구조화된 기권 상태를 action planner에 전달한다."""
    history = []
    for row in session_store.list_messages(session_id, limit=10):
        turn = {"role": row["role"], "content": row["content"]}
        try:
            payload = json.loads(row.get("citations_json") or "")
            state = payload.get("rag_turn") if isinstance(payload, dict) else None
            if isinstance(state, dict):
                turn.update({key: state[key] for key in ("abstain_reason", "action_ids") if key in state})
        except (TypeError, ValueError):
            pass
        history.append(turn)
    return history


def _load_page_state(session_id: str) -> dict | None:
    """마지막 assistant 메시지에 실린 페이지추천 상태(active_artifact)를 복원한다.

    마지막 턴이 문서 Q&A였다면 None을 돌려준다 — 그쪽 경로(rag.ragkit.chatbot.
    chat_turn())는 citations_json에 인용 청크 배열(JSON list)을 넣으므로
    json.loads는 성공하지만 isinstance(payload, dict) 체크에서 걸러진다(2026-08-13
    이관 전엔 파이썬 repr 문자열이라 json.loads 자체가 실패했음 — 지금은 유효한
    JSON이라도 최상위가 dict가 아니라 결과는 같다). 의도한 동작: 무관한 문서
    질문 뒤에 페이지 상태를 물려주면 relation 분류가 오히려 헷갈린다."""

    messages = session_store.list_messages(session_id, limit=1)
    if not messages or messages[-1]["role"] != "assistant":
        return None
    raw = messages[-1].get("citations_json")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or _PAGE_STATE_KEY not in payload:
        return None
    return payload[_PAGE_STATE_KEY].get("active_artifact")


def _drain_sync(async_gen):
    """async generator를 동기 이터레이터로 브리지한다 — 전용 이벤트루프 하나를
    계속 재사용하며 항목 하나당 run_until_complete 한 번씩(매 항목마다 새 루프를
    만들지 않는다). chat_turn() 자체는 진짜 비동기(스레드로 LLM HTTP 스트림을
    소비)라 이 브리지가 필요한 건 라우터·smoke_chat_routing.py가 동기 제너레이터
    계약을 요구하기 때문일 뿐(async def로 바꾸면 두 곳 다 깨진다)."""

    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(async_gen.__anext__())
            except StopAsyncIteration:
                return
    finally:
        loop.close()


def _run_document_qa(request: ChatRequest, session_id: str, profile: Literal["public", "private"], action_plan=None):
    """비정형+정형 혼합 문서 Q&A 경로 — 코어 로직(정형·dense·PageIndex 도구 선택+
    병렬조회를 위한 LangGraph 오케스트레이션·멀티턴 프롬프트·인용강제·표/차트
    다중매체 이벤트·세션저장)은 rag.ragkit.chatbot.chat_turn()에 있다(2026-08-13
    이관, 같은 날 재작업 — 최초엔 DuckDB 인덱스 하나만 썼다가 pgvector+정형+
    PageIndex 3도구 조합으로 교체했다). session_id는 이미 _run_chat이
    session_store로 확정해둔 값을 그대로 넘긴다 — chat_turn()이 내부에서 다시
    get_or_create_session을 부르지만 기존 session_id를 그대로 확인만 하므로 새
    세션이 만들어지진 않는다.

    `profile`은 어느 엔드포인트(/pubchat|/prichat|/chat)로 들어왔는지에 따라
    호출자(_run_chat)가 정해 그대로 chat_turn()에 넘긴다."""

    settings = get_settings()
    events = chat_turn(
        session_id=session_id,
        user_id=request.user_id,
        message=request.message,
        dense_k=request.top_k,
        store_db_path=settings.MSR_DB,
        chat=get_chat_client(),
        profile=profile,
        action_plan=action_plan,
    )
    # 2026-09-16(사용자 지시) — SSE로 나가기 직전 취소선 제거(streaming.py 주석
    # 참고). delta는 청크 경계를 넘어 판정해야 해서 상태 유지 필터, 비-delta
    # 이벤트 직전엔 보류분을 flush한다. 표 블록의 `markdown`(본문 안 표 원문)도
    # 본문과 같은 규칙을 거쳐야 프론트의 문자열 치환이 어긋나지 않는다.
    strike = StrikethroughFilter()
    terminal_sent = False
    try:
        for event in _drain_sync(events):
            if event.type == "delta":
                text = strike.feed(event.data["delta"])
                if text:
                    yield sse_event({"delta": text})
                continue
            pending = strike.flush()
            if pending:
                yield sse_event({"delta": pending})
            data = event.data
            if event.type == "table" and data.get("markdown"):
                data = {**data, "markdown": strip_strikethrough(data["markdown"])}
            yield sse_event(data, event=event.sse_name)
            if event.type == "done":
                # 코어의 terminal event 뒤에는 어떠한 SSE도 내보내지 않는다.
                # 따라서 코어 구현이 회귀해도 외부 계약은 done 정확히 1회다.
                terminal_sent = True
                return
    except Exception:
        _logger.exception("document Q&A stream failed for session %s", session_id)
        if terminal_sent:
            return
        failure_message = chat_message("action_unavailable")
        yield sse_event({"code": "document_qa_failed"}, event="error")
        yield sse_event({"stage": 3, "label": STATUS_STAGES[3], "status": "조회실패",
                         "failure_reason": "source_unavailable",
                         "message_key": "action_unavailable"}, event="status")
        yield sse_event({"delta": failure_message})
        yield sse_event({"done": True, "abstained": True,
                         "abstain_reason": "source_unavailable",
                         "message_key": "action_unavailable"}, event="done")


def _persistable_artifact(artifact: dict | None) -> dict | None:
    """다음 턴에 그래프가 실제로 읽는 키만 남긴다.

    그래프가 돌려주는 active_artifact에는 temporal_resolutions·metadata_bindings·
    metadata_issues·tool도 들어 있지만, 다음 턴 노드(_classify_relation·
    _extract_filters·_finalize_ambiguous)가 읽는 건 아래 6개뿐이다. chat_message.
    citations_json이 VARCHAR(4000)이라(DuckDB는 길이를 강제하지 않지만 Postgres
    cutover 후엔 잘린다) 안 읽는 값까지 실어 보낼 이유가 없다."""

    if not artifact:
        return None
    kept = (
        "selected_page_id",
        "pending_candidate_page_ids",
        "original_question",
        "effective_filters",
        "defaulted_filters",
        "inherited_filters",
    )
    return {key: artifact[key] for key in kept if key in artifact}


def _run_page_recommend(request: ChatRequest, session_id: str, action_target: str | None = None, action_mineral: str | None = None):
    """KOMIS 페이지·필터 추천 경로."""

    # 히스토리·상태는 이번 질문을 저장하기 "전"에 읽어야 한다 — 먼저 저장하면
    # 그래프가 자기 질문을 직전 턴으로 오인하고, _finalize가 같은 질문을 한 번 더
    # 이어붙인다.
    message_history = _history_for_graph(session_id)
    active_artifact = _load_page_state(session_id)
    session_store.append_message(session_id, "user", request.message)

    yield sse_event({"session_id": session_id})
    yield _status_event(1)  # 질문 조건 확인

    try:
        service = get_page_recommend_service()
        if action_target:
            try:
                service.registry.resolve_action_targets(action_target)
            except RegistryError:
                # LLM의 넓은 표현("가격" 등)은 등록 ID를 추측해 고정하지 않는다.
                # 전체 질문을 기존 페이지 추천 그래프에 넘겨 후보를 고른다.
                action_target = None
        turn = (service.recommend_action_target(action_target, thread_id=session_id, mineral=action_mineral)
                if action_target else service.recommend(
            request.message,
            thread_id=session_id,
            message_history=message_history,
            active_artifact=active_artifact,
        ))
    except Exception:
        _logger.exception("page recommendation failed for session %s", session_id)
        try:
            session_store.append_message(
                session_id,
                "assistant",
                "페이지 추천을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            )
        except Exception:
            session_store.append_message(session_id, "user", request.message)
            session_store.append_message(session_id, "assistant", "질문의 조건을 확인할 수 없어 현재 제공할 수 없습니다.")
            _logger.exception("could not persist page recommendation failure for session %s", session_id)
        yield sse_event({"code": "page_recommend_failed"}, event="error")
        yield sse_event(
            {
                "done": True,
                "mode": "page",
                "status": "error",
                "relation": None,
                "recommendations": [],
                "warnings": ["page_recommend_failed"],
            },
            event="done",
        )
        return
    response = turn.response
    recommendations = [item.model_dump(mode="json") for item in response.recommendations]

    yield _status_event(4)  # 답변 생성 중 — 그래프 호출 자체가 blocking 단일 호출이라
    # 2(답변 준비중)·3(데이터 분석 중)은 이 경로에선 안 쪼갠다(모듈독스트링 SSE 계약 참고).

    session_store.append_message(
        session_id,
        "assistant",
        response.answer,
        citations_json=json.dumps(
            {
                _PAGE_STATE_KEY: {
                    "active_artifact": _persistable_artifact(turn.active_artifact),
                    "status": response.status,
                    "relation": response.relation,
                    "page_ids": [item["page_id"] for item in recommendations],
                }
            },
            ensure_ascii=False,
            default=str,
        ),
    )

    # 그래프 답변은 LLM 토큰 스트림이 아니라 렌더 완료된 텍스트라 한 번에 내보낸다.
    yield sse_event({"delta": strip_strikethrough(response.answer)})
    yield sse_event(
        {
            "done": True,
            "mode": "page",
            "status": response.status,
            "relation": response.relation,
            "recommendations": recommendations,
            "warnings": response.warnings,
        },
        event="done",
    )


def _run_unverified_menu_path(request: ChatRequest, session_id: str):
    """레지스트리에 없는 수입수요 예측 메뉴는 추측 추천 없이 안내한다."""

    answer = "요청하신 메뉴 경로를 확인하지 못했습니다. 상단 전체메뉴에서 확인해 주십시오."
    session_store.append_message(session_id, "user", request.message)
    session_store.append_message(
        session_id,
        "assistant",
        answer,
        citations_json=json.dumps(
            {_PAGE_STATE_KEY: {"status": "not_found", "relation": "first_turn", "page_ids": []}},
            ensure_ascii=False,
        ),
    )
    yield sse_event({"session_id": session_id})
    yield _status_event(1)
    yield _status_event(4)
    yield sse_event({"delta": answer})
    yield sse_event(
        {
            "done": True,
            "mode": "page",
            "status": "not_found",
            "relation": "first_turn",
            "recommendations": [],
            "warnings": ["unverified_menu_path"],
        },
        event="done",
    )


def _run_chat_session(
    request: ChatRequest, profile: Literal["public", "private"], session_id: str,
):
    """세션과 Langfuse trace가 확정된 뒤 실제 챗봇 턴을 실행한다."""

    with _session_turn_lock(session_id):
        pending = _pending_mine_clarification(session_id)
        pending_trade = _pending_trade_clarification(session_id)
        try:
            pending_plan = ActionPlan.model_validate(pending["plan"]) if pending else None
        except (KeyError, TypeError, ValueError):
            pending_plan = None
        pending_call = _mine_country_call(pending_plan) if pending_plan else None
        choice = _mine_country_choice(
            request.message, pending_call.slots.country_scope if pending_call else None,
        )
        resumed = False
        try:
            if pending_call and choice:
                action_plan = pending_plan
                resumed = True
            elif pending_trade:
                # 이전 질문의 typed action을 보존하고 후속 문장에 명시된
                # reporter/period/flow 슬롯만 병합한다. 후속 문장만 LLM에
                # 재분류하면 정상 보충 답변이 off_topic으로 바뀔 수 있다.
                action_plan = merge_trade_indicator_followup(
                    ActionPlan.model_validate(pending_trade["plan"]), request.message,
                )
            else:
                recovered = _recover_trade_followup(session_id, request.message)
                action_plan = recovered or extract_action_plan(
                    request.message, KomirJsonLLM(), history=_history_for_graph(session_id),
                )
            assessment = validate_action_plan(action_plan)
        except Exception:
            failure_message = "질문의 조건을 확인할 수 없어 현재 제공할 수 없습니다."
            session_store.append_message(session_id, "user", request.message)
            session_store.append_message(session_id, "assistant", failure_message)
            yield sse_event({"session_id": session_id})
            yield sse_event({"stage": 1, "label": STATUS_STAGES[1], "status": "조회실패",
                             "failure_reason": "slot_unresolved"}, event="status")
            yield sse_event({"delta": failure_message})
            yield sse_event({"done": True, "abstained": True, "abstain_reason": "slot_unresolved"}, event="done")
            return
        trade_call = _trade_indicator_call(action_plan)
        if trade_call and missing_trade_indicator_slots(trade_call):
            yield from _trade_clarification_response(session_id, request.message, action_plan)
            return
        if not assessment.approved:
            failure_message = ("광물 관련 정보만 조회할 수 있습니다."
                               if assessment.failure_reason == "out_of_scope"
                               else chat_message("action_unavailable"))
            failure_message_key = (
                None if assessment.failure_reason == "out_of_scope" else "action_unavailable"
            )
            session_store.append_message(session_id, "user", request.message)
            session_store.append_message(session_id, "assistant", failure_message)
            yield sse_event({"session_id": session_id})
            status = {"stage": 1, "label": STATUS_STAGES[1], "status": "조회실패",
                      "failure_reason": assessment.failure_reason}
            if failure_message_key:
                status["message_key"] = failure_message_key
            yield sse_event(status, event="status")
            yield sse_event({"delta": failure_message})
            done = {"done": True, "abstained": True, "abstain_reason": assessment.failure_reason}
            if failure_message_key:
                done["message_key"] = failure_message_key
            yield sse_event(done, event="done")
            return
        if _unsupported_mineral_in_plan(action_plan, profile):
            yield from _unsupported_mineral_response(session_id, request.message)
            return
        mine_call = _mine_country_call(action_plan)
        if mine_call and request.mode != "page":
            if resumed:
                if choice == "ownership":
                    yield from _unsupported_mine_ownership(session_id, request.message)
                    return
                request = request.model_copy(update={
                    "message": f"{pending['question']} (광산 소재지 기준: {mine_call.slots.country_scope})",
                })
            else:
                choice = _mine_country_choice(request.message, mine_call.slots.country_scope)
                if choice == "ownership":
                    yield from _unsupported_mine_ownership(session_id, request.message)
                    return
                if choice is None:
                    yield from _mine_clarification_response(session_id, request.message, action_plan)
                    return
        action_page = any(call.action_id in {"menu.navigate", "dataset.navigate"} for call in action_plan.actions)
        if request.mode in {"document", "page"} and (request.mode == "page") != action_page:
            message = "요청 mode와 검증된 action 유형이 일치하지 않습니다."
            session_store.append_message(session_id, "user", request.message)
            session_store.append_message(session_id, "assistant", message)
            yield sse_event({"session_id": session_id})
            yield sse_event({"stage": 1, "label": STATUS_STAGES[1], "status": "조회실패",
                             "failure_reason": "mode_action_conflict"}, event="status")
            yield sse_event({"delta": message})
            yield sse_event({"done": True, "abstained": True, "abstain_reason": "mode_action_conflict"}, event="done")
            return
        mode = "page" if action_page else "document"
        if mode == "page":
            page_call = next(call for call in action_plan.actions if call.action_id in {"menu.navigate", "dataset.navigate"})
            yield from _run_page_recommend(request, session_id, action_target=page_call.slots.target_page or page_call.slots.dataset,
                                           action_mineral=page_call.slots.mineral)
            return
        yield from _run_document_qa(request, session_id, profile, action_plan=action_plan)


def _run_chat(request: ChatRequest, profile: Literal["public", "private"]):
    """제너레이터 — 한 턴 전체를 Langfuse root trace로 감싸 SSE로 넘긴다."""

    requested_session_id = str(request.session_id) if request.session_id else None
    try:
        session_id = session_store.get_or_create_session(requested_session_id, request.user_id)
    except session_store.SessionOwnershipError:
        # Do not disclose whether another user's session ID exists.
        yield sse_event({"code": "invalid_session"}, event="error")
        yield sse_event({"done": True, "warnings": ["invalid_session"]}, event="done")
        return

    def traced_turn():
        with chat_trace(
            user_id=request.user_id,
            session_id=session_id,
            message=request.message,
            profile=profile,
        ) as trace:
            for event in _run_chat_session(request, profile, session_id):
                if event.get("event") == "done":
                    try:
                        update_observation(trace, output=json.loads(event["data"]))
                    except (KeyError, TypeError, ValueError):
                        update_observation(trace, output={"done": True})
                yield event

    # SSE-Starlette는 동기 제너레이터를 이벤트마다 새 contextvars context에서
    # 재개한다. Langfuse의 root trace는 enter와 exit가 같은 context여야 하므로,
    # 이 턴 제너레이터만 하나의 캡처한 context에서 끝까지 재개한다.
    turn = traced_turn()
    trace_context = copy_context()
    while True:
        try:
            yield trace_context.run(next, turn)
        except StopIteration:
            return


@router.post("/pubchat")
def pubchat(request: ChatRequest) -> EventSourceResponse:
    """SSE 스트림 응답 — public MCP 프로필(라이선스 제한 제3자 문서 제외)."""

    return EventSourceResponse(_run_chat(request, "public"))


@router.post("/prichat")
def prichat(request: ChatRequest) -> EventSourceResponse:
    """SSE 스트림 응답 — private MCP 프로필(라이선스 제한 제3자 문서 포함)."""

    return EventSourceResponse(_run_chat(request, "private"))


def chat(request: ChatRequest) -> EventSourceResponse:
    """`/pubchat`과 동일(profile="public") — 구현은 남겨두되(재도입·내부 호출
    대비) **의도적으로 `@router.post` 미등록**이라 HTTP로는 노출되지 않는다
    (2026-08-26 사용자 요청: "chat 엔드포인트는 구현은 두고, 외부 인터페이스
    노출은 막아달라" — `/chat` 하위호환 별칭을 외부 API 표면에서 제거).
    필요해지면 `@router.post("/chat")`만 다시 붙이면 된다."""

    return EventSourceResponse(_run_chat(request, "public"))
