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
고정 문구는 strip 이후 코드로 덧붙인다(_source_footer·_caution_notice). 범위 밖
질문(유형8) 사유 분류(_classify_abstain)는 애초엔 근거가 아예 0건일 때만
호출했다(답은 찾았는데 인용이 전부 날조/공백인 기권 분기는 검색 자체는
성공한 경우라 대상이 아니라고 판단 — 과잉 분류 금지).

2026-08-28 실사용 감사(챗봇_룰준수_감사_260828.md §5)로 이 스코프가 실제
사용 빈도를 과소평가했다는 게 반증됐다 — "니켈 관련주 사도 될까?"(유형8
원문 예시) 같은 질문도 dense 검색이 "니켈" 키워드로 뭔가는 찾아오므로
evidence≠0이고, 생성 LLM이 스스로 규칙4(근거 없으면 ABSTAIN_TEXT)로 기권하는
경로(full_text == ABSTAIN_TEXT)를 타 abstain_reason이 항상 "unknown"으로
고정됐다 — 오히려 이 경로가 evidence=0보다 훨씬 흔한 유형8 발생 경로였다.
그래서 이 경로도 사유 분류 대상으로 넓혔다(의도적 스코프 확장, 위 "과잉
분류 금지" 결정의 재검토 — 인용이 날조/공백이라 기권하는 나머지 한 분기는
"검색은 됐지만 생성이 인용 규율을 어겼다"는 별종 실패라 유형8 사유와는
성격이 달라 그대로 대상 밖으로 남겨둔다).

병합 통합(같은 날, main 브랜치가 이 작업과 병행해 근거조회 진행상태 콜백
(`_run_with_status`·`retrieve_evidence(on_status=...)`, 문자열 stage: routing/
retrieving/verifying/reformulating/generating)과 근거 근접(near-miss) 재제안
기능(NEAR_MISS_SYSTEM_PROMPT)을 이미 추가해뒀다 — 이 작업의 status 4단계와
동시에 개발돼 서로 몰랐던 병렬 기능이다. 병합 시 main의 콜백 메커니즘(더
정교함, retrieve_evidence 내부 단계 진입 시점을 실시간으로 앎)은 그대로 살리고,
그 문자열 stage를 `_GRAPH_STAGE_TO_STATUS`로 이 파일의 정수 1-4 계약에 매핑해
emit한다(프론트와는 main-agent가 정수 계약으로 조율 완료) — chat_turn이 직접
내던 stage 1/2/3 단독 yield는 전부 이 콜백 기반으로 대체했고, stage 4(답변
생성 중)만 main의 "generating" 문자열 대신 그대로 유지한다(콜백 경유가 아니라
chat_turn 자신이 내는 지점이라 매핑이 필요 없음). NEAR_MISS_SYSTEM_PROMPT에도
격식체 지시를 추가해 어투 규칙이 근접매칭 응답에도 적용되게 했다.

2026-08-31(komis_raw_lookup 그래프 라우팅 배선) — KOMIS 공개원천(public.KO_*)
조회 결과 중 개발용 더미 데이터(발주 5광종 상당수가 아직 이 상태다)가
인용되면 `_dummy_data_notice`가 강제 경고를 붙인다 — `_caution_notice`·
`_source_footer`와 같은 원칙(인용 스트리퍼 통과 후 코드로 덧붙임)."""
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

#: chatbot_graph._finalize_node가 "근거는 찾았지만 질문이 요구한 지표와는 다르다"고
#: 표시(retrieval_near_miss 경고)했을 때만 쓰는 대체 프롬프트(2026-08-27, 사용자
#: 요청: "사용자가 항상 바른 요청을 하는 건 아니니 유사 데이터가 있으면 제시하고
#: 제공할지 물어봐라"). 기존 SYSTEM_PROMPT(generate.py, 비-챗봇 RAG 경로와 공유)는
#: 안 건드리고 이 경로 전용으로 별도 정의 — 인용 규율(오직 [근거]만, 숫자 날조
#: 금지, 무인용 문장 금지)은 그대로 이어받되 4번 규칙만 "기권" 대신 "제안"으로
#: 바꾼다. 마지막 확인 질문에 인용 [n]을 반드시 함께 붙이라고 명시한 이유:
#: `generate._strip_uncited_sentences`의 CLAUSE_RE가 "[n] 태그로 끝나는 구간"만
#: 잘라내므로, 인용 없이 끝나는 마지막 문장은 화면에 아예 안 나온다(기존
#: 코드의 원래 동작 — 이 프롬프트가 그 제약에 맞춰 쓴 것뿐, 새 함정 아님).
#:
#: 2026-08-28(chatbot_rule.txt 병합 통합): 어투 규칙(격식체)만 추가했다 —
#: near-miss는 CHATBOT_SYSTEM_PROMPT가 아니라 이 프롬프트를 쓰므로, 격식체
#: 통일은 여기도 별도로 명시해야 적용된다(그 외 인용·제안형 규칙은 무수정).
NEAR_MISS_SYSTEM_PROMPT = (
    "당신은 '핵심광물 수급위기 진단·수요예측' 프로젝트의 내부 문서 기반 Q&A 어시스턴트입니다.\n"
    "어투: 모든 문장을 격식체(~습니다/~합니다)로 씁니다. 반말·해요체는 쓰지 않습니다.\n"
    "질문이 정확히 원하는 자료는 찾지 못했지만, [근거] 섹션에 주제가 비슷한 자료가 있습니다.\n"
    "반드시 지킬 규칙:\n"
    "1. 오직 [근거] 섹션의 발췌문에만 근거해 답하세요. 외부지식·추정·일반상식 사용 금지, 숫자·이름을 지어내지 마세요.\n"
    "2. 먼저 질문이 요구한 자료 자체는 없다고 분명히 밝히세요(있는 척하지 마세요).\n"
    "3. 이어서 [근거]에 있는 자료가 무엇인지 한 문장으로 소개하고, 그 자료를 보여줄지 사용자에게 물어보세요"
    "(자료를 요청과 동일한 것처럼 단정하지 마세요).\n"
    "4. 전체 답변을 하나로 이어 쓰고, 인용 번호 [n]은 마지막 문장(사용자에게 묻는 문장) 끝에 딱 한 번만 붙이세요"
    "(예: ...수입금액 예측 자료는 있습니다. 이 자료라도 보여드릴까요? [1]).\n"
    "5. 인용 번호가 전혀 없는 답변은 존재해서는 안 됩니다."
)

_logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 12  # 최근 6턴(user+assistant) — 프롬프트 길이 통제
_CITE_NUM_RE = re.compile(r"\[(\d+)\]")

#: chatbot_rule.txt "기타. 질문 입력 후 상태 값 표출" — 처리 단계 4개를 그대로
#: label로 쓴다. main-agent가 streamlit-agent와 조율한 프론트 계약(정수 stage
#: 1-4 + 서버가 포맷한 label, tools 필드 없음)이 정본 — 아래 _GRAPH_STAGE_TO_STATUS
#: 매핑을 바꿀 땐 그쪽에도 영향이 감을 염두에 둘 것.
STATUS_STAGES = {
    1: "질문 조건 확인",
    2: "답변 준비중",
    3: "데이터 분석 중",
    4: "답변 생성 중",
}

#: retrieve_evidence(on_status=...)가 넘기는 문자열 stage(2026-08-27, main
#: 병합분 — route/retrieve/verify/reformulate 각 노드 진입 시점)를 위 정수
#: 계약으로 매핑한다. "routing"(도구 선택 시작)은 아직 답이 뭘 찾는지 정하는
#: 단계라 1(질문 조건 확인)에, "retrieving"(실제 조회 시작)은 2(답변 준비중)에,
#: "verifying"·"reformulating"(찾은 근거가 맞는지 확인·재시도)은 둘 다 3(데이터
#: 분석 중)에 묶는다 — reformulating이 한 번 더 3을 내보내는 건 재시도로 아직
#: 분석 단계가 끝나지 않았다는 뜻이라 문제 없다(중복 emit 허용). "generating"은
#: chat_turn 자신이 이 콜백 경유가 아니라 직접 _status_event(4)를 내므로 여기
#: 매핑 대상이 아니다(아래 chat_turn 본문 참고). 모르는 문자열이 오면 3으로
#: 안전하게 떨어진다(무단계보다 "분석 중"이 사용자에게 덜 혼란스럽다).
_GRAPH_STAGE_TO_STATUS = {
    "routing": 1,
    "retrieving": 2,
    "verifying": 3,
    "reformulating": 3,
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
    "답하세요.\n"
    "11. 이 챗봇은 동(CU)·니켈(NI)·코발트(CO)·리튬(LI)·희토류(REE) 5개 광종만 "
    "다룹니다. [근거]에 이 5개 광종이 아닌 다른 광종(금·은·주석·알루미늄 등)의 "
    "자료만 있거나, 질문이 어떤 광종을 묻는지 특정할 수 없다면(예: 광종 언급 "
    "없이 \"가격 알려줘\") 그 근거로 답변을 만들지 말고 규칙 4의 문구로만 "
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


def _citation_sources(cited_indices: set[int], evidence: list) -> list[dict]:
    """done.citations(=streamlit_demo 등 프런트의 "[근거 데이터 보기]" 패널이
    그대로 렌더링하는 필드) — 검색된 evidence 전체가 아니라 답변 본문에 실제로
    인용된 것만 담는다. _source_footer와 동일하게 cited_indices로 필터링(2026-08-28
    실사용 감사 챗봇_룰준수_감사_260828.md §2 — 예전엔 필터링이 없어 답변에
    안 쓰인 근거까지 "근거 N건"으로 노출됐다)."""

    return [
        {"index": i, "kind": ev.kind, "source": ev.source, "section": ev.section,
         "as_of": ev.as_of, "unit": ev.unit}
        for i, ev in enumerate(evidence, 1)
        if i in cited_indices
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
    이후에 붙인다(_source_footer와 동일 원칙).

    2026-08-28 실사용 감사(챗봇_룰준수_감사_260828.md §3)로 트리거 조건을
    넓혔다 — 원래는 "structured + 다른 kind가 함께 인용"일 때만 붙었는데,
    룰 원문이 유형5 대표 예시로 든 질문("코발트 수급동향지표 등급이 왜
    '주의'로 바뀌었어?")조차 latest_diagnosis 하나만 인용되고 문서 근거는
    검색됐어도 실제 인용까진 안 되는 경우가 흔해 문구가 안 붙었다.
    latest_diagnosis 근거 자체가 "사유:" 라벨(evidence.py::from_structured)을
    담고 있어 단독 인용이라도 인과 단정으로 읽힐 소지가 있으므로, 이 템플릿이
    인용됐으면 다른 근거 유무와 무관하게 문구를 붙인다."""

    cited = [evidence[i - 1] for i in cited_indices if 1 <= i <= len(evidence)]
    cited_kinds = {ev.kind for ev in cited}
    has_diagnosis = any(ev.kind == "structured" and "latest_diagnosis(" in ev.source for ev in cited)
    if has_diagnosis or ("structured" in cited_kinds and cited_kinds - {"structured"}):
        return (
            "\n\n※ 위 설명은 지표 변동과 동시에 나타난 문서상 흐름을 정리한 것으로, "
            "직접적인 인과관계를 단정하는 내용이 아닙니다."
        )
    return ""


def _dummy_data_notice(cited_indices: set[int], evidence: list) -> str:
    """2026-08-31(komis_raw_lookup 신설) — 인용된 근거 중 `Evidence.caveat`가
    채워진 게 있으면(현재는 komis_raw_lookup의 "KOMIS 실제 표본이 아니라
    개발용 더미" 경고뿐) 강제로 붙인다. `_caution_notice`·`_source_footer`와
    같은 이유로 코드에서 붙인다 — LLM이 [근거] 텍스트를 읽고 스스로 이 사실을
    문장으로 옮겨 적을 거라 기대하면 인용 스트리퍼가 그 문장을 지워버릴 수
    있다(그 문장에 [n] 인용이 없으면). 발주 5광종 데이터가 대부분 더미인
    현재 상태에서 이 경고를 놓치면 "가짜 수치를 실제 값처럼 안내"하는,
    이 기능 전체가 막으려던 바로 그 사고가 난다 — 안전에 직결되므로
    캐시(같은 문구 중복 방지) 없이 인용될 때마다 매번 명시한다."""

    cited = [evidence[i - 1] for i in cited_indices if 1 <= i <= len(evidence)]
    caveats = {ev.caveat for ev in cited if ev.caveat}
    if not caveats:
        return ""
    return "\n\n" + "\n".join(f"⚠ {c}" for c in sorted(caveats))


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
    """근거 0건 기권과, 근거는 찾았지만 생성 LLM이 스스로 ABSTAIN_TEXT로 기권한
    경우(2026-08-28부터, 아래 chat_turn() 참고) 둘 다에서 호출 — chatbot_rule.txt
    유형8(범위 밖 질문) 사유별 안내문. LLM 호출 자체가 실패하면 현행 ABSTAIN_TEXT로
    폴백한다(분류를 억지로 밀어붙이지 않음 — 안전 우선). 근거는 찾았는데 인용이
    전부 날조/공백이라 기권하는 나머지 한 분기(_strip_uncited_sentences 이후
    cleaned가 빈 문자열)는 이 분류 대상이 아니다(검색·생성 모두 일단 성공했다가
    인용 규율에서 걸린 별종 실패라 유형8 사유와 성격이 다름 — chat_turn() 호출부
    주석 참고)."""

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
    하므로.

    2026-08-31: "최저/최고 조회는 표만" 하는 질문 문구 기반 조건부 억제를
    시도했다가 사용자가 "표가 제공되면 차트도 같이 제공해야 한다"고 정정 —
    표가 나가는 모든 경우에 차트도 함께 낸다. 차트 생성 여부는 순수하게 표
    모양(숫자열 존재 여부, chatbot_events.render_chart_png)만으로 정해진다."""

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
    """한 턴을 실행하고 이벤트를 순서대로 낸다: session -> status(1..3, retrieve_
    evidence의 on_status 콜백이 실시간으로 냄, 재시도 시 3이 여러 번 올 수 있음)
    -> status(4) -> delta* -> table*/image* -> done(근거 0건/조회 실패면 status
    없이 곧장 delta 1회+done). session_id가 없으면 새로 발급하고, 있으면 그 세션의
    최근 히스토리를
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
                yield _status_event(_GRAPH_STAGE_TO_STATUS.get(payload, 3))
            elif kind == "result":
                evidence, route_warnings = payload
    except Exception:
        # 정형/dense/PageIndex 셋 다 접속 자체가 안 되는 등 오케스트레이션 계층
        # 전체가 죽은 경우 — 조용히 삼키지 않고 로그는 남기되, 500으로 스트림을
        # 깨는 대신 기권 응답으로 처리한다(개별 도구 실패는 chatbot_graph 안에서
        # 이미 부분 열화로 흡수됨 — 여기 걸리는 건 그보다 더 심각한 경우다).
        _logger.exception("retrieve_evidence 실패, 기권 응답으로 대체")
        evidence, route_warnings = [], ["retrieve_evidence_crashed"]
    if route_warnings:
        _logger.warning("근거 조회 경고: %s", route_warnings)

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

    near_miss = "retrieval_near_miss" in route_warnings
    system_prompt = NEAR_MISS_SYSTEM_PROMPT if near_miss else CHATBOT_SYSTEM_PROMPT
    user_prompt = _history_block(history) + _build_evidence_prompt(message, evidence)
    chat = chat or OpenAICompatChat(_cfg_from_env())

    yield _status_event(4)  # 답변 생성 중
    full_text_parts: list[str] = []
    async for delta in _iter_async(chat.complete_stream(system_prompt, user_prompt, max_tokens=max_tokens)):
        full_text_parts.append(delta)
        yield ChatEvent(type="delta", data={"delta": delta})

    full_text = "".join(full_text_parts).strip()

    if not full_text or full_text == ABSTAIN_TEXT:
        # 2026-08-28(챗봇_룰준수_감사_260828.md §5) — 예전엔 이 경로가 무조건
        # abstain_reason="unknown"이었다. 실사용 감사로 이 경로가 evidence=0
        # 경로보다 훨씬 흔한 유형8(범위 밖 질문) 발생 지점이라는 게 드러나
        # (예: "니켈 관련주 사도 될까?"도 dense 검색이 "니켈"로 뭔가는 찾아와
        # evidence≠0이라 여기로 옴), 같은 분류기를 재사용해 사유를 채운다
        # (chatbot.py 모듈 docstring "어투·유형별 대응" 절·_classify_abstain
        # 독스트링에 스코프 확장 배경 기록).
        #
        # abstain_reason뿐 아니라 abstain_text(유형8 사유별 안내문, 예:
        # "유사한 광종으로 니켈(NI) 관련 정보는 조회하실 수 있습니다")도 화면에
        # 실려야 룰이 요구하는 문구가 실제로 사용자에게 도달한다 — done 이벤트의
        # abstain_reason 코드값만으론 프런트가 이 문장을 재구성할 수 없다
        # (_abstain_reason_text의 similar_commodity 힌트 등은 서버에만 있음).
        # abstain_text가 폴백값(그냥 ABSTAIN_TEXT, 분류 실패 시)이면 이미 스트림된
        # 내용과 같으므로 중복 delta를 보내지 않는다(evidence=0 분기와 달리 이
        # 분기는 full_text가 이미 한 번 스트림됐을 수 있어 무조건 델타를 더 보내면
        # 같은 문장이 두 번 노출된다).
        abstain_reason, abstain_text = await asyncio.to_thread(
            _classify_abstain, message, route_warnings, router_llm
        )
        stored_text = full_text or ABSTAIN_TEXT
        if abstain_text != ABSTAIN_TEXT:
            delta_text = ("\n\n" + abstain_text) if full_text else abstain_text
            yield ChatEvent(type="delta", data={"delta": delta_text})
            stored_text = f"{stored_text}\n\n{abstain_text}" if full_text else abstain_text
        await asyncio.to_thread(
            append_message, resolved_session_id, "assistant", stored_text, None, store_db_path
        )
        yield ChatEvent(
            type="done",
            data={
                "done": True, "citations": [], "bogus_citations": [], "abstained": True,
                "abstain_reason": abstain_reason,
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
    citation_sources = _citation_sources(cited_indices, evidence)

    # chatbot_rule.txt 공통 규칙(출처 표기)·유형5(주의 문구) — 인용 스트리퍼를
    # 통과한 뒤에만 코드로 덧붙인다(모델에게 시키면 인용 없는 문장으로 잘림,
    # 위 CHATBOT_SYSTEM_PROMPT·_source_footer·_caution_notice 독스트링 참고).
    extra = (
        _dummy_data_notice(cited_indices, evidence)
        + _caution_notice(cited_indices, evidence)
        + _source_footer(cited_indices, evidence)
    )
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
