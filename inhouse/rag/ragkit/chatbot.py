# -*- coding: utf-8 -*-
"""RAG 챗봇 엔트리 포인트 — 멀티턴 대화 + 다중매체(텍스트·표·차트) 비동기 이벤트 스트림.

프레임워크 독립적 코어: FastAPI/sse_starlette 의존 없음. services/rag_chat/app/
routers/chat.py가 이 async generator를 SSE로 감싸기만 한다(2026-08-13 이관 —
이전엔 이 로직이 routers/chat.py 안에 있었다). CLI·노트북·다른 서빙 레이어에서도
그대로 재사용 가능하다.

근거 조회: 정형(Postgres out_*)·dense(pgvector doc_chunk)·PageIndex(OKF 트리) 세
도구를 LangGraph로 오케스트레이션하는 chatbot_graph.retrieve_evidence()가 담당한다
(2026-08-13 재작업 — 최초 구현은 `rag/index/rag.duckdb` 기반 hybrid_search 하나만
썼는데, 그 인덱스는 구 코퍼스(문서<100건)용이고 같은 날 이미 pgvector로
140,031청크 코퍼스가 구축돼 있던 걸 뒤늦게 발견해 전량 교체했다 — WORKLOG
"rag 패키지에 chatbot 엔트리포인트 신설" 절 참고).

인용강제 답변 생성(SYSTEM_PROMPT·ABSTAIN_TEXT·_strip_uncited_sentences)은
rag/ragkit/generate.py를 그대로 재사용한다(재구현 금지 — 가이드 §4 "증명 가능한
것만 말하고 나머지는 기권" 원칙이 이미 거기 구현돼 있음). 다만 프롬프트의 [근거]
섹션은 RetrievedChunk가 아니라 Evidence(services/shared/retrieval/evidence.py,
세 도구 공통 계약)로 조립하므로 generate.build_user_prompt()는 쓰지 않고
_build_evidence_prompt()를 새로 둔다. generate.answer()는 완성 응답 하나를
blocking으로 돌려주는 동기 함수라 스트리밍 UX에는 못 쓰므로, 여기서는 같은
프롬프트를 OpenAICompatChat.complete_stream()(동기 제너레이터, requests 기반)을
별도 스레드에서 소비해 진짜 비동기 이벤트로 바꾼다(_iter_async).

멀티턴: 기존 routers/chat.py 구현은 대화를 저장만 하고 프롬프트에 실제로 넣지
않았다(페이지추천 그래프 경로만 히스토리를 썼다) — 이번 이관에서 문서 Q&A
경로도 최근 대화를 프롬프트에 포함하도록 고쳤다(_history_block). 다만 [근거]
밖의 내용을 인용하면 안 되므로(SYSTEM_PROMPT 규칙) 히스토리는 "참고용, 인용
대상 아님"이라고 프롬프트에서 명시적으로 구분해둔다.

다중매체: 인용된(=날조 아닌) 근거의 본문에 마크다운 표가 있으면 table 이벤트로,
그 표에 완전한 숫자열이 있으면 즉석에서 matplotlib 차트를 그려 image 이벤트로도
낸다(chatbot_events.py) — 표/그림이 없는 게 정상인 턴도 많다, 강제로 만들지
않는다. 정형(structured) 근거는 evidence.py가 이미 마크다운 표로 렌더링해 넣어
주므로 이 경로가 kind 상관없이 동일하게 동작한다."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Literal

from geo.llm.openai_compat import OpenAICompatChat

from .chatbot_events import ChatEvent, extract_markdown_tables, png_to_data_uri_payload, render_chart_png
from .chatbot_graph import retrieve_evidence
from .chatbot_store import DEFAULT_DB_PATH as DEFAULT_STORE_DB_PATH
from .chatbot_store import append_message, get_or_create_session, list_messages
from .generate import ABSTAIN_TEXT, SYSTEM_PROMPT, _cfg_from_env, _strip_uncited_sentences

_logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 12  # 최근 6턴(user+assistant) — 프롬프트 길이 통제
_CITE_NUM_RE = re.compile(r"\[(\d+)\]")


async def _iter_async(sync_iter: Iterator[str]) -> AsyncIterator[str]:
    """블로킹 동기 제너레이터(complete_stream, requests 기반)를 별도 스레드에서
    돌리고 asyncio.Queue로 넘겨 비동기 이터레이터처럼 소비한다. LLM 호출 자체가
    requests(동기) 기반이라 이 다리 없이는 이벤트루프가 토큰 하나 받는 동안
    통째로 막힌다."""

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    def _pump() -> None:
        try:
            for item in sync_iter:
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:  # noqa: BLE001 — 소비측(chat_turn)에서 그대로 재발생
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    threading.Thread(target=_pump, daemon=True).start()
    while True:
        item = await queue.get()
        if item is _DONE:
            return
        if isinstance(item, Exception):
            raise item
        yield item


async def _run_with_status(fn, *args, **kwargs) -> AsyncIterator[tuple[str, object, dict]]:
    """`_iter_async`와 같은 Queue+스레드 브리지(2026-08-27, SSE `status` 이벤트용)
    — 다만 `fn`은 스트리밍 제너레이터가 아니라 **단일 반환값 함수**다. `fn`을
    별도 스레드에서 `fn(*args, on_status=콜백, **kwargs)`로 실행하면서, 그
    콜백이 `on_status(stage, **extra)`로 불릴 때마다 `("status", stage, extra)`를,
    `fn`이 끝나면 `("result", 반환값, {})`를 순서대로 낸다. `retrieve_evidence()`
    (route/retrieve/verify/reformulate 각 단계 진입 시점에 이 콜백을 부름,
    `chatbot_graph.py` 참고)가 이 실행 도중 SSE로 진행상황을 흘려보낼 유일한
    소비처다."""

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    def _on_status(stage: str, **extra) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("status", stage, extra))

    def _run() -> None:
        try:
            result = fn(*args, on_status=_on_status, **kwargs)
            loop.call_soon_threadsafe(queue.put_nowait, ("result", result, {}))
        except Exception as exc:  # noqa: BLE001 — 소비측(chat_turn)에서 그대로 재발생
            loop.call_soon_threadsafe(queue.put_nowait, ("error", exc, {}))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, (_DONE, None, {}))

    threading.Thread(target=_run, daemon=True).start()
    while True:
        kind, payload, extra = await queue.get()
        if kind is _DONE:
            return
        if kind == "error":
            raise payload
        yield kind, payload, extra


def _history_block(history: list[dict]) -> str:
    """[근거] 밖의 참고용 문맥 — 모델에게 여긴 인용 대상이 아니라고 명시한다."""

    if not history:
        return ""
    lines = ["[이전 대화] (참고용 — 이 부분은 인용 대상이 아닙니다, 오직 [근거]만 인용하세요)"]
    for turn in history:
        speaker = "사용자" if turn["role"] == "user" else "어시스턴트"
        lines.append(f"{speaker}: {turn['content']}")
    return "\n".join(lines) + "\n\n"


#: 여러 광종의 pageindex 근거가 섞여 들어오는 턴(agentic 순회 결과)에서만
#: 노출한다 — 실측 발견(2026-08-18, 4턴 체인 테스트): 근거에 "구리 상위5개국"
#: 순위와 "니켈"(다른 광종) 표가 같이 있을 때, 생성 LLM이 "질문이 요구하는
#: 집합(상위5개국)에 속하는지"를 확인하지 않고 그냥 근거 중 가장 큰 숫자를
#: 가진 나라(인도네시아, 구리 상위5개국엔 없음)를 답으로 냈다 — 인용 자체는
#: 진짜 근거였지만(니켈 수치는 실재) 질문의 조건을 안 지킨 논리비약. 광종이
#: 하나뿐인 턴(단순 사실조회)은 이 실패모드가 나타날 여지가 없어 프롬프트
#: 길이를 아끼려고 조건부로만 붙인다.
_CONSTRAINT_REMINDER = (
    "[유의사항] 질문이 특정 집합(예: \"상위 5개국 중에서\")으로 조건을 제한하면, "
    "그 집합에 실제로 속하는지 아래 [근거]에서 직접 확인한 뒤에만 답하십시오. "
    "근거에 있는 개별 수치라도 질문이 요구하는 조건을 만족하지 않으면 사용하지 "
    "마십시오.\n"
)


def _needs_constraint_reminder(evidence: list) -> bool:
    sections = {ev.section for ev in evidence if ev.kind == "pageindex"}
    return len(sections) > 1


def _build_evidence_prompt(question: str, evidence: list) -> str:
    """generate.build_user_prompt()과 같은 모양([질문]/[근거] + [n]번호)이되,
    입력이 RetrievedChunk가 아니라 Evidence라 별도로 둔다 — 출처 표시에 기준시점·
    단위가 있으면 같이 보여줘 모델이 그 값을 그대로 옮기지 않고 맥락과 함께
    인용하게 한다."""

    lines = [f"[질문]\n{question}\n"]
    if _needs_constraint_reminder(evidence):
        lines.append(_CONSTRAINT_REMINDER)
    lines.append("[근거]")
    for i, ev in enumerate(evidence, 1):
        meta = f"(출처: {ev.source} · {ev.section}"
        if ev.as_of:
            meta += f" · 기준시점 {ev.as_of}"
        if ev.unit:
            meta += f" · 단위 {ev.unit}"
        meta += ")"
        lines.append(f"[{i}] {meta}\n{ev.text}\n")
    return "\n".join(lines)


def _citation_sources(evidence: list) -> list[dict]:
    return [
        {"index": i, "kind": ev.kind, "source": ev.source, "section": ev.section,
         "as_of": ev.as_of, "unit": ev.unit}
        for i, ev in enumerate(evidence, 1)
    ]


def _multimodal_events(cited_indices: set[int], evidence: list) -> list[ChatEvent]:
    """인용된 근거에서 표를 뽑아 table 이벤트로, 숫자열이 있으면 차트를 렌더링해
    image 이벤트로도 낸다. 인용 안 된 근거(조회는 됐지만 답변 근거로 안 쓰인
    것)는 건너뛴다 — 표시되는 표/그림도 텍스트 답변과 같은 인용 규율을 따라야
    하므로."""

    events: list[ChatEvent] = []
    for i, ev in enumerate(evidence, 1):
        if i not in cited_indices:
            continue
        for table in extract_markdown_tables(ev.text):
            events.append(ChatEvent(
                type="table",
                data={"columns": table["columns"], "rows": table["rows"], "source_index": i},
            ))
            chart = render_chart_png(table)
            if chart is not None:
                png_bytes, caption = chart
                events.append(ChatEvent(
                    type="image", data=png_to_data_uri_payload(png_bytes, caption, source_index=i),
                ))
    return events


async def chat_turn(
    session_id: str | None,
    user_id: str,
    message: str,
    *,
    dense_k: int = 5,
    pageindex_k: int = 3,
    max_tokens: int = 800,
    store_db_path: str = DEFAULT_STORE_DB_PATH,
    chat: OpenAICompatChat | None = None,
    router_llm=None,
    profile: Literal["public", "private"] = "public",
) -> AsyncIterator[ChatEvent]:
    """한 턴을 실행하고 이벤트를 순서대로 낸다: session -> delta* -> table*/image*
    -> done. session_id가 없으면 새로 발급하고, 있으면 그 세션의 최근 히스토리를
    프롬프트에 실어 멀티턴을 지원한다. 근거 조회(정형·dense·PageIndex 도구 선택+
    병렬 실행)는 chatbot_graph.retrieve_evidence()에 위임한다. 모든 블로킹
    I/O(Postgres·PageIndex 파일·LLM HTTP)는 asyncio.to_thread/스레드 브리지로
    이벤트루프를 막지 않는다.

    router_llm은 chatbot_graph의 도구 선택 LLM(KomirJsonLLM) 주입점 — 테스트에서
    모의로 갈아끼울 때 쓴다(None이면 chatbot_graph가 기본 설정으로 새로 만든다).

    profile("public"|"private")은 routers/pubchat.py·prichat.py가 넘기는
    MCP 프로필 선택 — retrieve_evidence()에 그대로 패스스루한다(2026-08-26,
    pubchat/prichat 분리)."""

    resolved_session_id: str = await asyncio.to_thread(
        get_or_create_session, session_id, user_id, None, store_db_path
    )
    yield ChatEvent(type="session", data={"session_id": resolved_session_id})

    history_rows = await asyncio.to_thread(
        list_messages, resolved_session_id, MAX_HISTORY_MESSAGES, store_db_path
    )
    # chatbot_store.list_messages()는 DB 원본 행(message_id·citations_json·
    # created_at 등)을 그대로 돌려준다 — created_at이 pandas Timestamp라
    # retrieve_evidence()가 라우팅 LLM 호출에 그대로 실으면 json.dumps가 깨진다
    # (실측 발견, 2026-08-13 실인프라 대상 라이브 검증 2턴에서 재현). role/content
    # 두 필드만 남긴 순수 dict로 정리해 아래 두 곳(_history_block·retrieve_evidence)
    # 모두에 넘긴다.
    history = [{"role": row["role"], "content": row["content"]} for row in history_rows]
    await asyncio.to_thread(append_message, resolved_session_id, "user", message, None, store_db_path)

    evidence, route_warnings = [], []
    try:
        async for kind, payload, extra in _run_with_status(
            retrieve_evidence, message,
            session_id=resolved_session_id, history=history, llm=router_llm,
            dense_k=dense_k, pageindex_k=pageindex_k, profile=profile,
        ):
            if kind == "status":
                yield ChatEvent(type="status", data={"stage": payload, **extra})
            elif kind == "result":
                evidence, route_warnings = payload
    except Exception:
        # 정형/dense/PageIndex 셋 다 접속 자체가 안 되는 등 오케스트레이션 계층
        # 전체가 죽은 경우 — 조용히 삼키지 않고 로그는 남기되, 500으로 스트림을
        # 깨는 대신 기권 응답으로 처리한다(개별 도구 실패는 chatbot_graph 안에서
        # 이미 부분 열화로 흡수됨 — 여기 걸리는 건 그보다 더 심각한 경우다).
        _logger.exception("retrieve_evidence 실패, 기권 응답으로 대체")
        evidence, route_warnings = [], []
    if route_warnings:
        _logger.warning("근거 조회 경고: %s", route_warnings)

    if not evidence:
        await asyncio.to_thread(
            append_message, resolved_session_id, "assistant", ABSTAIN_TEXT, None, store_db_path
        )
        yield ChatEvent(type="delta", data={"delta": ABSTAIN_TEXT})
        yield ChatEvent(
            type="done",
            data={"done": True, "citations": [], "bogus_citations": [], "abstained": True},
        )
        return

    user_prompt = _history_block(history) + _build_evidence_prompt(message, evidence)
    chat = chat or OpenAICompatChat(_cfg_from_env())

    yield ChatEvent(type="status", data={"stage": "generating"})
    full_text_parts: list[str] = []
    async for delta in _iter_async(chat.complete_stream(SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens)):
        full_text_parts.append(delta)
        yield ChatEvent(type="delta", data={"delta": delta})

    full_text = "".join(full_text_parts).strip()
    citation_sources = _citation_sources(evidence)

    if not full_text or full_text == ABSTAIN_TEXT:
        await asyncio.to_thread(
            append_message, resolved_session_id, "assistant", ABSTAIN_TEXT, None, store_db_path
        )
        yield ChatEvent(
            type="done",
            data={"done": True, "citations": [], "bogus_citations": [], "abstained": True},
        )
        return

    cleaned, bogus = _strip_uncited_sentences(full_text, len(evidence))
    if not cleaned.strip():
        await asyncio.to_thread(
            append_message, resolved_session_id, "assistant", ABSTAIN_TEXT, None, store_db_path
        )
        yield ChatEvent(
            type="done",
            data={"done": True, "citations": [], "bogus_citations": bogus, "abstained": True},
        )
        return

    cited_indices = {int(n) for n in _CITE_NUM_RE.findall(cleaned)}
    for event in _multimodal_events(cited_indices, evidence):
        yield event

    await asyncio.to_thread(
        append_message,
        resolved_session_id, "assistant", cleaned,
        json.dumps(citation_sources, ensure_ascii=False), store_db_path,
    )
    yield ChatEvent(
        type="done",
        data={"done": True, "citations": citation_sources, "bogus_citations": bogus, "abstained": False},
    )


if __name__ == "__main__":
    import sys

    # 라이브러리 코드는 basicConfig를 부르지 않는다(서비스 컨텍스트에선 uvicorn이
    # 이미 루트 로거를 구성함) — 이 CLI 데모 경로만 예외로, 수동 점검 시
    # route/retrieve/reformulate/verify 진행 로그(logging.INFO)가 안 보이면
    # 디버깅이 안 되므로 여기서만 켠다.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async def _demo() -> None:
        q = sys.argv[1] if len(sys.argv) > 1 else "니켈 수급위기 진단등급이 어떻게 되나"
        async for event in chat_turn(session_id=None, user_id="cli-test", message=q):
            if event.type == "delta":
                print(event.data["delta"], end="", flush=True)
            else:
                print(f"\n[{event.type}] {event.data}")

    asyncio.run(_demo())
