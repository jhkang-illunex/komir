# -*- coding: utf-8 -*-
"""POST /pubchat, /prichat — 요청 바디: {user_id, session_id(선택, 없으면
신규 발급), message, mode}. 응답: SSE 스트림(streaming.py) — 최종 청크에
citations_json 또는 페이지추천 결과 포함. 이 두 엔드포인트가 프론트가 직접
붙는 실제 API 표면이다.

**2026-08-26 public/private MCP 분리**: 문서 Q&A 경로가 참조하는 hybrid_search·
pageindex_lookup 두 도구는 이제 `rag.ragkit.mcp_client`의 public/private 세션
중 하나를 거친다(라이선스 제한 제3자 문서 접근 여부가 갈림 — 두 프로필은
`rag/ragkit/mcp_server_public.py`·`mcp_server_private.py` 물리적으로 분리된
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

SSE 이벤트 계약(프론트 연동 기준, 2026-08-13 table·image 추가, 2026-08-28 status·
abstain_reason 추가 — documents/order/chatbot_rule.txt "기타. 질문 입력 후 상태
값 표출"·유형8 반영):
  event: (무명)  data: {"session_id": "..."}                              — 매 턴 최초
  event: status  data: {"stage": 1|2|3|4, "label": "질문 조건 확인|답변 준비중|
                         데이터 분석 중|답변 생성 중"}                      — 처리 진행 표시,
                         여러 번 옴(문서 경로 최대 4회, 페이지 경로 2회: 1·4만)
  event: (무명)  data: {"delta": "..."}                                    — 텍스트 조각
                         (출처 footer·원인해석 주의문구도 델타로 추가 전송될 수 있음)
  event: table   data: {"columns": [...], "rows": [[...]], "source_index": n}
  event: image   data: {"mime": "image/png", "data_base64": "...",
                         "caption": "...", "source_index": n}
  event: done    data: {"done": true, "abstained": bool, "bogus_citations": [...],
                         "abstain_reason": "off_topic|unsupported_commodity|
                         no_data_for_period|ambiguous|unknown"|null,
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
import sys
from pathlib import Path
from typing import Literal


def _find_root(start: Path, marker: str) -> Path:
    """marker(상대경로 파일)를 담은 디렉토리를 위로 훑어 찾는다.

    소스트리(inhouse/services/rag_chat/app/routers/chat.py)와 컨테이너 배포본
    (Containerfile이 services/rag_chat/app→./app, services/shared→./shared,
    rag/ragkit→./rag/ragkit로 평평하게 COPY)의 상대 깊이가 다르다 — 고정 depth
    대신 탐색으로 두 경우를 다 맞춘다(services/shared/db.py·services/ingestion/
    parsers/pdf.py와 같은 패턴)."""

    for candidate in (start, *start.parents):
        if (candidate / marker).is_file():
            return candidate
    raise ImportError(f"{marker}를 {start} 상위에서 찾지 못함")


_HERE = Path(__file__).resolve()
for _root in (
    _find_root(_HERE, "shared/llm_client.py"),
    _find_root(_HERE, "rag/ragkit/generate.py"),
):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from fastapi import APIRouter  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sse_starlette.sse import EventSourceResponse  # noqa: E402

from rag.ragkit.chatbot import STATUS_STAGES, chat_turn  # noqa: E402

from shared.config import get_settings  # noqa: E402
from shared.llm_client import get_chat_client  # noqa: E402

from .. import session_store  # noqa: E402
from ..intent import classify_intent  # noqa: E402
from ..page_recommend.service import get_service as get_page_recommend_service  # noqa: E402
from ..streaming import sse_event  # noqa: E402

router = APIRouter()

def _status_event(stage: int) -> dict:
    """document 경로(chat_turn)의 STATUS_STAGES를 page 경로에서도 재사용 —
    라벨 문구가 두 경로에서 갈라지지 않게 한 곳(chatbot.py)만 정본으로 둔다."""

    return sse_event({"stage": stage, "label": STATUS_STAGES[stage]}, event="status")


# chat_message.citations_json에 페이지추천 대화상태를 실어 나를 때 쓰는 키.
# 원본(komis-report-generator-main)은 이 상태를 LangGraph SqliteSaver에 뒀지만 komir는
# 대화 저장소를 chat_session/chat_message 하나로 유지한다(page_recommend/service.py 주석).
_PAGE_STATE_KEY = "page_recommend"


class ChatRequest(BaseModel):
    user_id: str
    session_id: str | None = None
    message: str
    top_k: int = 6
    mode: str = "auto"  # auto | document | page


def _history_for_graph(session_id: str) -> list[dict]:
    """직전 턴들의 role/content만 뽑아 그래프 입력 형태로 변환."""

    return [
        {"role": row["role"], "content": row["content"]}
        for row in session_store.list_messages(session_id, limit=10)
    ]


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


def _run_document_qa(request: ChatRequest, session_id: str, profile: Literal["public", "private"]):
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
    )
    for event in _drain_sync(events):
        yield sse_event(event.data, event=event.sse_name)


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


def _run_page_recommend(request: ChatRequest, session_id: str):
    """KOMIS 페이지·필터 추천 경로."""

    # 히스토리·상태는 이번 질문을 저장하기 "전"에 읽어야 한다 — 먼저 저장하면
    # 그래프가 자기 질문을 직전 턴으로 오인하고, _finalize가 같은 질문을 한 번 더
    # 이어붙인다.
    message_history = _history_for_graph(session_id)
    active_artifact = _load_page_state(session_id)
    session_store.append_message(session_id, "user", request.message)

    yield sse_event({"session_id": session_id})
    yield _status_event(1)  # 질문 조건 확인

    turn = get_page_recommend_service().recommend(
        request.message,
        thread_id=session_id,
        message_history=message_history,
        active_artifact=active_artifact,
    )
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
    yield sse_event({"delta": response.answer})
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


def _run_chat(request: ChatRequest, profile: Literal["public", "private"]):
    """제너레이터 — SSE로 그대로 넘긴다(테스트에서 list()로 직접 소비 가능).

    `profile`은 page 경로엔 영향 없다(그 경로는 hybrid_search/pageindex_lookup을
    안 씀) — document 경로에만 전달."""

    session_id = session_store.get_or_create_session(request.session_id, request.user_id)
    mode = request.mode if request.mode in {"document", "page"} else classify_intent(request.message)
    if mode == "page":
        yield from _run_page_recommend(request, session_id)
        return
    yield from _run_document_qa(request, session_id, profile)


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
