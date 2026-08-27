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

인용강제 답변 생성(ABSTAIN_TEXT·_strip_uncited_sentences)은 rag/ragkit/generate.py
를 재사용한다(재구현 금지 — 가이드 §4 "증명 가능한 것만 말하고 나머지는 기권"
원칙이 이미 거기 구현돼 있음). 다만 어투·유형별 지시(아래 CHATBOT_SYSTEM_PROMPT
단락)가 붙어 인용 규칙 자체는 같지만 프롬프트 상수는 generate.SYSTEM_PROMPT를
fork한 별도 상수를 쓴다. 프롬프트의 [근거]
섹션은 RetrievedChunk가 아니라 Evidence(services/shared/retrieval/evidence.py,
세 도구 공통 계약)로 조립하므로 generate.build_user_prompt()는 쓰지 않고
_build_evidence_prompt()를 새로 둔다. generate.answer()는 완성 응답 하나를
blocking으로 돌려주는 동기 함수라 스트리밍 UX에는 못 쓰므로, 여기서는 같은
프롬프트를 OpenAICompatChat.complete_stream()(동기 제너레이터, requests 기반)을
별도 스레드에서 소비해 진짜 비동기 이벤트로 바꾼다(_iter_async).

멀티턴: 기존 routers/chat.py 구현은 대화를 저장만 하고 프롬프트에 실제로 넣지
않았다(페이지추천 그래프 경로만 히스토리를 썼다) — 이번 이관에서 문서 Q&A
경로도 최근 대화를 프롬프트에 포함하도록 고쳤다(_history_block). 다만 [근거]
밖의 내용을 인용하면 안 되므로(CHATBOT_SYSTEM_PROMPT 규칙) 히스토리는 "참고용, 인용
대상 아님"이라고 프롬프트에서 명시적으로 구분해둔다.

다중매체: 인용된(=날조 아닌) 근거의 본문에 마크다운 표가 있으면 table 이벤트로,
그 표에 완전한 숫자열이 있으면 즉석에서 matplotlib 차트를 그려 image 이벤트로도
낸다(chatbot_events.py) — 표/그림이 없는 게 정상인 턴도 많다, 강제로 만들지
않는다. 정형(structured) 근거는 evidence.py가 이미 마크다운 표로 렌더링해 넣어
주므로 이 경로가 kind 상관없이 동일하게 동작한다.

어투·유형별 대응(2026-08-28, documents/order/chatbot_rule.txt 반영): 격식체 통일·
출처 표기·원인 해석 주의 문구·처리 상태값 4단계·범위 밖 질문 사유 안내를 이
모듈에 추가했다. generate.SYSTEM_PROMPT(인용강제 규칙)는 레거시 generate.answer()
도 같이 쓰므로 그대로 두고, 어투·유형 지시를 얹은 CHATBOT_SYSTEM_PROMPT를 이
파일에 별도로 둔다(최소 변경 — 검증된 경로 보존). _strip_uncited_sentences가
인용 없는 문장을 전부 지우므로, 출처 footer·주의 문구처럼 모델에게 시키면 잘릴
고정 문구는 strip 이후 코드로 덧붙인다(_source_footer·_caution_notice). 상태값
4단계(질문 조건 확인/답변 준비중/데이터 분석 중/답변 생성 중)는 retrieve_evidence
가 blocking 단일 호출이라 내부를 더 쪼개지 않고 chat_turn 단계 경계에서만 낸다.
범위 밖 질문(유형8) 사유 분류는 근거가 아예 0건일 때만 LLM 1회 추가 호출한다
(_classify_abstain) — 답은 찾았는데 인용이 전부 날조/공백인 나머지 두 기권
분기는 검색 자체는 성공한 경우라 사유 분류 대상이 아니다(과잉 분류 금지)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Literal

from geo.llm.openai_compat import OpenAICompatChat
from pydantic import BaseModel

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from shared.llm_client import LLM_TRANSIENT_ERRORS, KomirJsonLLM  # noqa: E402

from .chatbot_events import ChatEvent, extract_markdown_tables, png_to_data_uri_payload, render_chart_png
from .chatbot_graph import retrieve_evidence
from .chatbot_store import DEFAULT_DB_PATH as DEFAULT_STORE_DB_PATH
from .chatbot_store import append_message, get_or_create_session, list_messages
from .generate import ABSTAIN_TEXT, _cfg_from_env, _strip_uncited_sentences

_logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 12  # 최근 6턴(user+assistant) — 프롬프트 길이 통제
_CITE_NUM_RE = re.compile(r"\[(\d+)\]")

#: chatbot_rule.txt "기타. 질문 입력 후 상태 값 표출" — 처리 단계 4개를 그대로
#: label로 쓴다. chat_turn()의 단계 경계에서만 발행(내부는 안 쪼갬, 위 모듈독스트링).
STATUS_STAGES = {
    1: "질문 조건 확인",
    2: "답변 준비중",
    3: "데이터 분석 중",
    4: "답변 생성 중",
}


def _status_event(stage: int) -> ChatEvent:
    return ChatEvent(type="status", data={"stage": stage, "label": STATUS_STAGES[stage]})


#: generate.SYSTEM_PROMPT(인용강제 5개조)를 그대로 포함하되(레거시 generate.answer()
#: 와 공유하던 상수를 그대로 재사용하지 않고 fork — 그쪽 검증된 경로는 안 건드림),
#: chatbot_rule.txt 공통 규칙(어투·출처·시계열 기간)과 유형별 규칙(표·비교표·
#: 기준일자·원인 해석) 지시를 얹었다. 고정 문구(주의 문구·출처 footer)는 여기
#: 프롬프트로 시키지 않는다 — 인용 스트리퍼가 인용 없는 문장을 지우므로 코드에서
#: strip 이후 덧붙인다(_caution_notice·_source_footer).
CHATBOT_SYSTEM_PROMPT = (
    "당신은 '핵심광물 수급위기 진단·수요예측' 프로젝트의 대국민 챗봇입니다.\n"
    "어투: 모든 문장을 격식체(~습니다/~합니다)로 씁니다. 반말·해요체는 쓰지 않습니다.\n"
    "반드시 지킬 규칙:\n"
    "1. 오직 [근거] 섹션의 발췌문에만 근거해 답하세요. 외부지식·추정·일반상식 사용 금지.\n"
    "2. 모든 문장 끝에 그 문장의 근거가 된 발췌 번호를 [n] 형식으로 표기하세요"
    "(예: ...2,772건 제거되었다. [2]). 여러 근거를 종합했다면 [2][4]처럼 복수 표기.\n"
    "3. 발췌문에 없는 숫자·이름·날짜·결론을 지어내지 마세요.\n"
    f"4. 질문에 답할 근거가 발췌문에 전혀 없으면 다른 말 없이 정확히 이렇게만 답하세요: \"{ABSTAIN_TEXT}\"\n"
    "5. 인용 번호가 없는 문장은 존재해서는 안 됩니다.\n"
    "6. 사용자가 표·차트 형식을 지정하면 마크다운 표(`| 열 | 열 |` + 구분선 행)로 "
    "답하세요.\n"
    "7. 두 대상(광종·국가 등)을 비교하는 질문에는 비교표를 먼저 제시한 뒤 요약하세요.\n"
    "8. 수치를 답할 때는 그 수치의 기준일자·기준시점을 함께 표기하세요.\n"
    "9. 등급·지표 변화의 '원인'을 묻는 질문에는 인과관계를 단정하지 말고 "
    "\"~와 비슷한 시기에/동시에 ~가 있었습니다\"처럼 동시 발생 흐름으로 서술하세요.\n"
    "10. 시계열·추이 질문은 질문이 명시한 기간을 그대로 따르고, 기간을 특정하지 "
    "않았다면 최근 1개월을 기본으로 하되 근거상 필요하면 최대 3개월까지 확장해 "
    "답하세요."
)


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


def _source_footer(cited_indices: set[int], evidence: list) -> str:
    """chatbot_rule.txt 공통 규칙 "모든 답변에 데이터 출처 기본 표기" — 인용
    스트리퍼(_strip_uncited_sentences)가 인용 없는 문장을 전부 지우므로 이
    문구를 LLM에게 직접 쓰게 하면 같이 잘린다. cleaned 확정(스트리퍼 통과) 이후
    코드에서 덧붙인다. 인용된 근거만, 같은 (source, section, as_of)는 한 번만."""

    seen: set[tuple] = set()
    lines: list[str] = []
    for i in sorted(cited_indices):
        if not (1 <= i <= len(evidence)):
            continue
        ev = evidence[i - 1]
        key = (ev.source, ev.section, ev.as_of)
        if key in seen:
            continue
        seen.add(key)
        line = f"[{i}] {ev.source} · {ev.section}"
        if ev.as_of:
            line += f" (기준시점 {ev.as_of})"
        lines.append(line)
    if not lines:
        return ""
    return "\n\n출처:\n" + "\n".join(lines)


def _caution_notice(cited_indices: set[int], evidence: list) -> str:
    """chatbot_rule.txt 유형5(원인 해석) 규칙 "인과 단정 금지, 동시 발생 흐름으로
    서술" — 구조화 진단지표(structured)와 비정형 문서(dense/pageindex)가 함께
    인용된 답변은 "지표가 왜 바뀌었는지"류 원인 해석형일 가능성이 커 주의 문구를
    붙인다. CHATBOT_SYSTEM_PROMPT 규칙 9로도 유도하지만 모델이 빠뜨릴 수 있어
    코드로 한 번 더 못박는다 — 이 문구도 인용 스트리퍼 대상이 아니므로 strip
    이후에 붙인다(_source_footer와 동일 원칙)."""

    cited_kinds = {evidence[i - 1].kind for i in cited_indices if 1 <= i <= len(evidence)}
    if "structured" in cited_kinds and cited_kinds - {"structured"}:
        return (
            "\n\n※ 위 설명은 지표 변동과 동시에 나타난 문서상 흐름을 정리한 것으로, "
            "직접적인 인과관계를 단정하는 내용이 아닙니다."
        )
    return ""


_ABSTAIN_REASON_PROMPT = """핵심광물 챗봇이 이번 질문에 답할 근거를 하나도 찾지
못했다. 사유를 아래 네 가지 중 하나로 분류한다. 정확히 하나의 JSON 객체만
출력한다(설명·코드펜스 금지).

- off_topic: 광물·핵심광물 수급과 무관한 질문(투자 판단, 종목 추천, 일반 잡담 등).
- unsupported_commodity: 광물 질문이지만 이 챗봇이 다루는 5개 광종(CU=동, NI=니켈,
  CO=코발트, LI=리튬, REE=희토류/네오디뮴) 밖의 광종을 묻는다. 이때
  similar_commodity에 5개 광종 중 가장 관련 있는 것 하나를 채운다.
- no_data_for_period: 광종·주제는 맞지만 질문이 가리키는 기간(연도 등)에 조회
  가능한 데이터가 없다고 판단된다.
- ambiguous: 광종/기간/수입·수출/생산량·매장량 등 조회에 필요한 조건이 무엇인지
  질문만으로 특정할 수 없다.

검색 경고(retrieval_warnings, 있으면)도 참고한다 — "retrieval_insufficient"가
있으면 근거는 찾았지만 질문에 정확히 답하지 못했다는 뜻이라 ambiguous나
no_data_for_period에 가깝다. 넷 중 어디에도 뚜렷이 안 맞으면 ambiguous로 분류한다."""


class _AbstainReason(BaseModel):
    reason: Literal["off_topic", "unsupported_commodity", "no_data_for_period", "ambiguous"]
    similar_commodity: Literal["CU", "NI", "CO", "LI", "REE"] | None = None


_COMMODITY_LABELS = {
    "CU": "동(CU)", "NI": "니켈(NI)", "CO": "코발트(CO)", "LI": "리튬(LI)", "REE": "희토류(REE)",
}


def _abstain_reason_text(decision: "_AbstainReason") -> str:
    if decision.reason == "off_topic":
        return "광물 관련 정보만 조회할 수 있습니다. 투자 판단, 종목 추천 등은 답변드릴 수 없습니다."
    if decision.reason == "unsupported_commodity":
        hint = _COMMODITY_LABELS.get(decision.similar_commodity or "", "")
        suffix = f" 유사한 광종으로 {hint} 관련 정보는 조회하실 수 있습니다." if hint else ""
        return (
            "현재 동(CU)·니켈(NI)·코발트(CO)·리튬(LI)·희토류(REE) 5개 광종만 지원합니다."
            f"{suffix}"
        )
    if decision.reason == "no_data_for_period":
        return "질문하신 기간에는 조회 가능한 데이터가 없습니다. 다른 기간으로 다시 질문해 주세요."
    return "질문의 광종·기간·수입/수출·생산량/매장량 등 조건을 조금 더 구체적으로 말씀해 주시면 답변드릴 수 있습니다."


def _classify_abstain(message: str, warnings: list[str], llm: "KomirJsonLLM | None") -> tuple[str, str]:
    """근거가 0건이라 기권을 확정할 때만 호출 — chatbot_rule.txt 유형8(범위 밖
    질문) 사유별 안내문. LLM 호출 자체가 실패하면 현행 ABSTAIN_TEXT로 폴백한다
    (분류를 억지로 밀어붙이지 않음 — 안전 우선). 근거는 찾았는데 인용이 전부
    날조/공백이라 기권하는 나머지 두 분기는 이 분류 대상이 아니다(검색은 이미
    성공한 경우라 유형8 사유와 무관 — chat_turn() 호출부 주석 참고)."""

    client = llm or KomirJsonLLM()
    try:
        invocation = client.invoke(
            task="chat_abstain_reason", instructions=_ABSTAIN_REASON_PROMPT,
            payload={"question": message, "retrieval_warnings": warnings},
            output_model=_AbstainReason, max_tokens=80,
        )
    except LLM_TRANSIENT_ERRORS as exc:
        # "LLM 경과" 로깅(사용자 요청, 2026-08-28) — 이 폴백은 지금까지 호출부에
        # 어떤 로그도 안 남기고 조용히 ABSTAIN_TEXT로 넘어갔다. KomirJsonLLM.
        # invoke() 자체의 복구재시도 실패는 이제 shared/llm_client.py에서
        # 로깅하지만(task="chat_abstain_reason"으로 찍힘), 여기서 잡는
        # LLM_TRANSIENT_ERRORS는 RuntimeError/OSError(HTTP 429·타임아웃 등)까지
        # 포함해 그쪽 로그가 아예 안 남는 경로도 있어 별도로 남긴다.
        _logger.warning(
            "chat_abstain_reason 분류 실패, ABSTAIN_TEXT로 폴백: %s: %s", type(exc).__name__, exc
        )
        return "unknown", ABSTAIN_TEXT
    decision = invocation.output
    return decision.reason, _abstain_reason_text(decision)


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
    """한 턴을 실행하고 이벤트를 순서대로 낸다: session -> status(1) -> status(2)
    -> status(3) -> [status(4) -> ]delta* -> table*/image* -> done(근거 0건이면
    status(3) 다음 곧장 delta 1회+done, status(4) 없음). session_id가 없으면
    새로 발급하고, 있으면 그 세션의 최근 히스토리를
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
    yield _status_event(1)  # 질문 조건 확인

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

    yield _status_event(2)  # 답변 준비중
    try:
        evidence, route_warnings = await asyncio.to_thread(
            retrieve_evidence, message,
            session_id=resolved_session_id, history=history, llm=router_llm,
            dense_k=dense_k, pageindex_k=pageindex_k, profile=profile,
        )
    except Exception:
        # 정형/dense/PageIndex 셋 다 접속 자체가 안 되는 등 오케스트레이션 계층
        # 전체가 죽은 경우 — 조용히 삼키지 않고 로그는 남기되, 500으로 스트림을
        # 깨는 대신 기권 응답으로 처리한다(개별 도구 실패는 chatbot_graph 안에서
        # 이미 부분 열화로 흡수됨 — 여기 걸리는 건 그보다 더 심각한 경우다).
        _logger.exception("retrieve_evidence 실패, 기권 응답으로 대체")
        evidence, route_warnings = [], ["retrieve_evidence_crashed"]
    if route_warnings:
        _logger.warning("근거 조회 경고: %s", route_warnings)
    yield _status_event(3)  # 데이터 분석 중

    if not evidence:
        # chatbot_rule.txt 유형8(범위 밖 질문) — 근거 0건일 때만 사유 분류 1회
        # (LLM 호출, router_llm과 같은 클라이언트 재사용). 나머지 두 기권 분기
        # (아래)는 검색 자체는 성공한 경우라 이 분류 대상이 아니다.
        #
        # 단, route_warnings에 도구 자체 실패(dense_failed·pageindex_failed·
        # structured_failed·retrieve_evidence_crashed)가 있으면 이건 "질문이
        # 범위 밖"이 아니라 "조회 인프라가 죽은" 경우다 — 이걸 유형8 4분류에
        # 태우면 정상 질문("코발트 공급위기 원인이 뭐야?")도 "질문이 모호하다"는
        # 식으로 사용자 탓을 하게 된다(실측: smoke_chat_routing.py가 Postgres·
        # PageIndex 미구축 상태에서 dense_failed·pageindex_failed를 그대로
        # 재현). 이 경우엔 분류를 건너뛰고 조회 실패 사유를 그대로 전달한다.
        if any(w.startswith(("dense_failed", "pageindex_failed", "structured_failed",
                              "retrieve_evidence_crashed")) for w in route_warnings):
            abstain_reason, abstain_text = "retrieval_error", ABSTAIN_TEXT
        else:
            abstain_reason, abstain_text = await asyncio.to_thread(
                _classify_abstain, message, route_warnings, router_llm
            )
        await asyncio.to_thread(
            append_message, resolved_session_id, "assistant", abstain_text, None, store_db_path
        )
        yield ChatEvent(type="delta", data={"delta": abstain_text})
        yield ChatEvent(
            type="done",
            data={
                "done": True, "citations": [], "bogus_citations": [], "abstained": True,
                "abstain_reason": abstain_reason,
            },
        )
        return

    user_prompt = _history_block(history) + _build_evidence_prompt(message, evidence)
    chat = chat or OpenAICompatChat(_cfg_from_env())

    yield _status_event(4)  # 답변 생성 중
    full_text_parts: list[str] = []
    async for delta in _iter_async(
        chat.complete_stream(CHATBOT_SYSTEM_PROMPT, user_prompt, max_tokens=max_tokens)
    ):
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
            data={
                "done": True, "citations": [], "bogus_citations": [], "abstained": True,
                "abstain_reason": "unknown",
            },
        )
        return

    cleaned, bogus = _strip_uncited_sentences(full_text, len(evidence))
    if not cleaned.strip():
        await asyncio.to_thread(
            append_message, resolved_session_id, "assistant", ABSTAIN_TEXT, None, store_db_path
        )
        yield ChatEvent(
            type="done",
            data={
                "done": True, "citations": [], "bogus_citations": bogus, "abstained": True,
                "abstain_reason": "unknown",
            },
        )
        return

    cited_indices = {int(n) for n in _CITE_NUM_RE.findall(cleaned)}

    # chatbot_rule.txt 공통 규칙(출처 표기)·유형5(주의 문구) — 인용 스트리퍼를
    # 통과한 뒤에만 코드로 덧붙인다(모델에게 시키면 인용 없는 문장으로 잘림,
    # 위 CHATBOT_SYSTEM_PROMPT·_source_footer·_caution_notice 독스트링 참고).
    extra = _caution_notice(cited_indices, evidence) + _source_footer(cited_indices, evidence)
    if extra:
        yield ChatEvent(type="delta", data={"delta": extra})
    final_text = cleaned + extra

    for event in _multimodal_events(cited_indices, evidence):
        yield event

    await asyncio.to_thread(
        append_message,
        resolved_session_id, "assistant", final_text,
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
