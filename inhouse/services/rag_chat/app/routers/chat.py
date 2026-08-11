# -*- coding: utf-8 -*-
"""POST /chat — 요청 바디: {user_id, session_id(선택, 없으면 신규 발급), message, mode}.
응답: SSE 스트림(streaming.py) — 최종 청크에 citations_json 또는 페이지추천 결과 포함.

두 경로가 있다(2026-08-11 페이지추천 편입):
- document: 비정형 문서검색 + 인용강제 생성. 인용 강제 로직(SYSTEM_PROMPT·프롬프트
  조립·날조인용 제거)은 rag/ragkit/generate.py에서 그대로 재사용한다(재구현 금지 —
  가이드 §4 "증명 가능한 것만 말하고 나머지는 기권" 원칙이 이미 거기 구현돼 있음).
  차이는 하나: generate.answer()는 동기 완성 응답이라 스트리밍 UX(요구사항⑤)에 못
  쓰므로, 여기서는 같은 프롬프트를 OpenAICompatChat.complete_stream()으로 흘려보낸다 —
  문장 단위 날조인용 제거는 전체 텍스트가 다 와야 계산 가능해(부분 문장 상태로는 [n]
  태그가 아직 안 붙었을 수 있음) 스트리밍 도중엔 원문 그대로 보여주고, 최종 done
  이벤트에 bogus_citations 목록만 정보로 첨부한다(이미 화면에 나간 토큰을 되돌릴 순
  없음 — 알려진 단순화).
- page: KOMIS 43개 페이지·필터 추천(app/page_recommend, LangGraph 그래프). 답변이
  LLM 토큰 스트림이 아니라 그래프가 렌더한 완성 텍스트라 delta 한 번으로 내보낸다
  (스트림 계약은 동일하게 유지 — 클라이언트가 경로를 구분하지 않아도 되게).

경로 선택은 요청 바디의 `mode`(auto|document|page)를 따르고, auto면 app/intent.py가
LLM 1회로 분류한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path


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

from rag.ragkit.generate import ABSTAIN_TEXT, SYSTEM_PROMPT, _strip_uncited_sentences, build_user_prompt  # noqa: E402

from shared.llm_client import get_chat_client  # noqa: E402

from .. import session_store  # noqa: E402
from ..intent import classify_intent  # noqa: E402
from ..page_recommend.service import get_service as get_page_recommend_service  # noqa: E402
from ..retrieval.unstructured import search_documents  # noqa: E402
from ..streaming import sse_event, stream_answer  # noqa: E402

router = APIRouter()

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

    마지막 턴이 문서 Q&A였다면 None을 돌려준다 — 그쪽 경로는 citations_json에
    파이썬 repr 문자열을 넣으므로 json.loads가 실패한다(의도한 동작: 무관한 문서
    질문 뒤에 페이지 상태를 물려주면 relation 분류가 오히려 헷갈린다)."""

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


def _run_document_qa(request: ChatRequest, session_id: str):
    """비정형 문서검색 경로(기존 동작 그대로)."""

    session_store.append_message(session_id, "user", request.message)

    try:
        chunks = search_documents(request.message, k=request.top_k)
    except Exception as exc:
        # rag/index/rag.duckdb 미구축(build_index.py 실행 전) 등 검색 계층 자체가
        # 아직 준비 안 된 상태 — 500으로 스트림을 깨는 대신 기권 응답으로 처리.
        # 조용히 삼키지 않고 서버 로그엔 남긴다(원인 파악용).
        print(f"[rag_chat] search_documents 실패, 기권 응답으로 대체: {type(exc).__name__}: {exc}")
        chunks = []
    if not chunks:
        session_store.append_message(session_id, "assistant", ABSTAIN_TEXT)
        yield sse_event({"session_id": session_id})
        yield from stream_answer(iter([ABSTAIN_TEXT]), citations=[])
        return

    yield sse_event({"session_id": session_id})

    system = SYSTEM_PROMPT
    user = build_user_prompt(request.message, chunks)
    chat = get_chat_client()

    citation_sources = [
        {"index": i, "source_path": c.source_path, "section_heading": c.section_heading}
        for i, c in enumerate(chunks, 1)
    ]

    # 토큰이 도착하는 대로 즉시 내보낸다(진짜 스트리밍) — full_text_parts는 각
    # delta가 소비되는 시점에 side effect로 채워지므로, 아래 for 루프가 끝난
    # 뒤(=스트림이 끝난 뒤)에만 전체 텍스트를 대상으로 날조인용 검사를 한다.
    full_text_parts: list[str] = []
    for delta in chat.complete_stream(system, user, max_tokens=800):
        full_text_parts.append(delta)
        yield sse_event({"delta": delta})

    full_text = "".join(full_text_parts)
    _cleaned, bogus = _strip_uncited_sentences(full_text, len(chunks)) if full_text.strip() else ("", [])

    session_store.append_message(
        session_id, "assistant", full_text or ABSTAIN_TEXT,
        citations_json=str(citation_sources),
    )

    yield sse_event({"done": True, "citations": citation_sources, "bogus_citations": bogus}, event="done")


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

    turn = get_page_recommend_service().recommend(
        request.message,
        thread_id=session_id,
        message_history=message_history,
        active_artifact=active_artifact,
    )
    response = turn.response
    recommendations = [item.model_dump(mode="json") for item in response.recommendations]

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


def _run_chat(request: ChatRequest):
    """제너레이터 — SSE로 그대로 넘긴다(테스트에서 list()로 직접 소비 가능)."""

    session_id = session_store.get_or_create_session(request.session_id, request.user_id)
    mode = request.mode if request.mode in {"document", "page"} else classify_intent(request.message)
    if mode == "page":
        yield from _run_page_recommend(request, session_id)
        return
    yield from _run_document_qa(request, session_id)


@router.post("/chat")
def chat(request: ChatRequest) -> EventSourceResponse:
    """SSE 스트림 응답."""

    return EventSourceResponse(_run_chat(request))
