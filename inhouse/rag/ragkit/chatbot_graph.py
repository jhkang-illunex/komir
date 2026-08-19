# -*- coding: utf-8 -*-
"""검색 도구 오케스트레이션(LangGraph) — 정형(Postgres)·dense(pgvector)·
PageIndex(OKF 트리) 세 근거 도구 중 무엇을 쓸지 LLM 1회로 정하고(route), 고른
도구들을 스레드로 병렬 조회해(retrieve) 공통 근거(Evidence, evidence.py) 리스트로
합친다. `chat_turn()`(chatbot.py)이 이 모듈의 `retrieve_evidence()` 하나만 부른다.

`인수인계서_TODO_대조_260813.md` §1-2/§3-3 "챗봇 조정 서비스(정형·비정형 도구
선택+혼합 조회)" 항목의 구현 — 세 도구(services/shared/retrieval/{structured,
dense_pg,pageindex}.py)는 이미 완성돼 있었고 호출자가 없었을 뿐이다(재구현 금지).

그래프: route -> retrieve -> verify -> (불충분하면) reformulate -> retrieve ->
verify -> ... 최대 MAX_ATTEMPTS번 -> finalize -> END.

- route/reformulate(2026-08-13 1차 확장): retrieve가 근거를 하나도 못 찾으면
  검색어를 바꿔 재시도한다 — 사용자 실측 지적: "인도네시아에서 니켈 다음으로
  많이 나는 광종"이 1차 검색(한국어 그대로)에선 0건이었는데, 실제로는 영어
  키워드("Indonesia bauxite mine production")로 USGS/Argus 코퍼스에 관련
  내용이 있었다 — 검색어 구성 문제였지 데이터가 없는 게 아니었다.
- verify(2026-08-13 2차 확장, 사용자 요청 "correct 체크"): "근거가 0건인가"
  뿐 아니라 "찾은 근거가 실제로 이 질문에 답이 되는가"까지 확인한다. 계기는
  구리(CU) 실측 사례 — dense/pageindex가 8건을 찾아왔지만 전부 가격·재고
  차트/뉴스였고 "구리 많이 나는 나라"의 답은 하나도 없었다. 그때는 검증 없이
  바로 생성으로 넘어가 LLM이 "근거에 없다"며 뒤늦게(그리고 정확하게) 기권했다
  — 결과는 맞았지만 재시도 기회 자체가 없었다. verify가 이제 그 판단을
  retrieve 직후로 당겨서, 불충분하면 evidence가 비어있을 때와 똑같이
  reformulate 경로를 탄다(finalize가 최종 판정을 그대로 evidence=[]로
  반영해 chat_turn()의 "근거 0건 -> 기권" 경로를 그대로 재사용 — 소비측 계약
  안 바뀜).

structured.py가 이미 자유형 NL→SQL을 금지하고("어떤 템플릿+어떤 광종"만 LLM이
고른다) pageindex.py가 에이전틱 트리 탐색을 후속과제로 미룬 것과 같은 원칙으로,
재시도도 무한 루프가 아니라 딱 1회로 못박았다(빠른 응답 요구사항 — 매 시도가
라우팅+병렬조회+검증 왕복 하나). `app/page_recommend/graph.py`가 이 프로젝트의
LangGraph 관례(StateGraph+TypedDict+KomirJsonLLM.invoke, 동기 노드)라 그
스타일을 그대로 따랐다.

session/history: session_id는 그래프 로직을 바꾸진 않는다(도구 선택·재시도
판단 어디에도 관여 안 함) — 로그·경고 메시지에 실어 어느 세션의 어느 턴에서
어떤 재시도·검증 판정이 났는지 추적 가능하게만 한다(MCP/tool로 노출할 때도
호출 추적에 그대로 쓸 수 있음). history는 route(대용어 해소)·reformulate(재질의
맥락)·verify(불완전한 resolved_query라도 history를 보면 무엇을 찾는지 판단
가능) 세 LLM 호출 모두에 같은 창(HISTORY_WINDOW)으로 일관되게 넘긴다 —
전엔 route/reformulate가 각자 `[-4:]`를 따로 하드코딩해 나중에 하나만 고치고
잊기 쉬웠다.

동기 함수다(psycopg2·파일 I/O가 전부 블로킹) — 비동기 호출자(chatbot.chat_turn)는
asyncio.to_thread로 감싼다. MCP/tool로 향후 노출할 걸 염두에 두고 노드는 도구
함수를 얇게 호출만 한다(로직을 노드 안에 박아넣지 않음 — 사용자 요청 메모)."""
from __future__ import annotations

import sys
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel


def _find_shared_root(start: Path) -> Path:
    """`shared.llm_client`/`shared.retrieval.*`를 최상위 패키지로 import할 수
    있는 sys.path 루트를 찾는다.

    services/rag_chat/app/routers/chat.py의 `_find_root`(조상 방향 탐색)와
    달리 이 파일(rag/ragkit/chatbot_graph.py)에선 그 패턴이 안 통한다 —
    `rag/ragkit`과 `services/shared`는 **형제** 디렉토리라, `rag/ragkit`에서
    조상 쪽으로 아무리 올라가도 `services/shared`를 절대 지나치지 않는다
    (dense_pg.py의 `_find_rag_parent`가 반대 방향으로 이 문제를 풀 때는 컨테이너가
    `rag/ragkit` 상대경로를 그대로 보존해줘서 마커 하나로 됐지만, 이쪽 방향은
    소스트리(`services/shared/llm_client.py`)와 컨테이너(services→./shared로
    평평화된 `shared/llm_client.py`)의 마커 경로 자체가 다르다 — 마커 하나로는
    못 풀어 두 경우를 각각 확인한다)."""

    for candidate in (start, *start.parents):
        if (candidate / "shared" / "llm_client.py").is_file():
            return candidate  # 컨테이너 배포본: services/shared→./shared로 평평화됨
        if (candidate / "services" / "shared" / "llm_client.py").is_file():
            return candidate / "services"  # 소스트리: inhouse/services/shared/...
    raise ImportError(f"shared/llm_client.py를 {start} 상위에서 찾지 못함(소스트리·컨테이너 배포본 둘 다 확인함)")


_ROOT = _find_shared_root(Path(__file__).resolve())
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.llm_client import LLM_TRANSIENT_ERRORS, KomirJsonLLM  # noqa: E402
from shared.retrieval import dense_pg, pageindex, pageindex_agent, structured  # noqa: E402
from shared.retrieval.evidence import Evidence, from_dense_chunk, from_pageindex_hit, from_structured  # noqa: E402

ROUTE_PROMPT = """당신은 핵심광물 수급위기 진단·수요예측 챗봇의 검색 라우터다.
직전 대화(history, 있으면)와 이번 질문(question)을 보고 정확히 하나의 JSON
객체로 결정한다. 설명·코드펜스·사고과정은 출력하지 않는다.

1. resolved_query: 이번 질문을 history 없이도 이해되는 완전한 문장으로 새로
   쓴다. "그 나라", "거기", "그거", "그 광종" 같은 대용어는 실제 대상으로
   바꿔 채운다(예: 직전 답변이 인도네시아 얘기였고 이번 질문이 "그 나라
   생산량은?"이면 resolved_query는 "인도네시아의 니켈 생산량은?"). **대용어를
   풀 때는 반드시 last_answer(직전 어시스턴트 답변, 가장 최근에 확정된
   사실)에서 개체명을 가져온다 — history 앞부분의 더 오래된 턴에 나온
   개체명이 아니다.** 예: 1턴에서 코발트 얘기를 했더라도 2턴 답변(last_answer)
   이 "그 나라의 2위 광종은 구리"라고 확정했다면, 3턴 "그 광종의 1위 생산국은?"
   의 "그 광종"은 코발트가 아니라 구리다(직전 답변이 방금 확정한 대상이
   최우선). history가 없거나 이번 질문이 이미 완전한 문장이면 question을
   그대로 쓴다.
2. 아래 세 근거 도구 중 무엇을 쓸지 정한다(resolved_query 기준으로 판단):
   - structured: komir 자체 산출물(수급위기 진단 등급, 12개월 수입물량/금액
     예측, 지정학 위기지수 추이)을 특정 광종 기준으로 조회한다. "{광종}
     진단등급이/예측이/위기지수가 어떻게 되나" 류의 수치 질문일 때만 켠다.
     광종(CU=동, NI=니켈, CO=코발트, LI=리튬, REE=네오디뮴 또는 그 별칭)을
     특정할 수 없으면 절대 켜지 않는다. 켤 때는 structured_template을 정확히
     하나 고른다: latest_diagnosis(최근 진단등급 1건) | import_forecast
     (12개월 수입 예측, target=volume(물량)|value(금액)) | geo_index_trend
     (위기지수 추이).
   - dense: 보고서·기사·백서 등 비정형 문서를 의미 기반으로 검색한다. 애매하면
     켜는 게 안전하다(기본값에 가깝게 취급).
   - pageindex: USGS·조달청·Argus 같은 대형 구조화 보고서를 목차/섹션 단위로
     찾는다. dense만으로는 놓치기 쉬운 대량 통계표·국가별 수치 질문일 때 같이
     켠다. pageindex를 켤 땐 pageindex_mode도 정한다:
     - "simple"(기본값): 특정 문서·섹션 하나로 답이 되는 단순 조회.
     - "agentic": 국가별 생산량 순위·비교·집계가 필요한 질문일 때만 고른다
       (예: "이 광물 1위 생산국은?", "그 나라가 몇 번째로 많이 캐는 광종은?",
       "1위 생산국과의 생산량 차이는?", "상위 5개국이 가장 많이 생산하는
       광종은?"). 여러 광종 섹션을 훑어 국가별 표를 대조해야 답이 나오는
       질문이라 simple보다 느리다 — 필요할 때만 켤 것.

structured를 켤 땐 commodity_code(CU|NI|CO|LI|REE)를 반드시 함께 지정한다 —
광종을 모르면 structured는 켜지 않는다(use_structured=false)."""


REFORMULATE_PROMPT = """직전 검색이 근거를 하나도 찾지 못했다. 같은 의도를
유지하면서 검색 성공률을 높이도록 검색어를 다시 쓴다. 정확히 하나의 JSON
객체만 출력한다.

이 코퍼스는 두 갈래로 섞여 있다: 한국어 조달청 주간동향 보고서(가격·재고
위주)와 영어 USGS/Argus 보고서(광종별 세계 생산량·매장량·국가별 통계 위주).
"어느 나라가 어떤 광물을 얼마나 생산하나" 같은 국가별·순위 질문은 한국어
그대로 검색하면 조달청 가격 보고서만 걸리고 정작 있는 USGS/Argus 자료는
못 찾는 경우가 많다(실측 확인) — 이럴 땐 핵심 개체(국가명·광종명)를 영어
전문용어로 바꾸거나 병기해서 다시 써라(예: "인도네시아 보크사이트 생산" ->
"Indonesia bauxite mine production"). 완전히 다른 질문으로 바꾸지 말고, 원래
질문이 묻는 것은 그대로 유지한다."""


VERIFY_PROMPT = """직전 검색으로 근거 후보를 찾았다. 이 근거들이 실제로 질문에
대한 답을 담고 있는지 확인한다(단순히 같은 광종·주제를 언급한다고 충분한 게
아니다 — 질문이 묻는 구체적인 사실이 있어야 한다). 정확히 하나의 JSON 객체만
출력한다.

예: 질문이 "구리가 많이 나는 나라는 어디야?"인데 근거가 전부 구리 가격 차트·
재고 동향·시장뉴스뿐이고 국가별 생산량·순위를 언급한 문장이 하나도 없다면
sufficient=false다. 근거 중 일부라도 질문에 실제로 답하는 문장이 있으면
sufficient=true다(모든 근거가 완벽할 필요는 없다)."""


class GroundingCheck(BaseModel):
    sufficient: bool
    reason: str = ""


class ReformulatedQuery(BaseModel):
    query: str


class RetrievalRoute(BaseModel):
    resolved_query: str = ""
    use_structured: bool
    use_dense: bool
    use_pageindex: bool
    pageindex_mode: Literal["simple", "agentic"] = "simple"
    structured_template: Literal["latest_diagnosis", "import_forecast", "geo_index_trend"] | None = None
    commodity_code: Literal["CU", "NI", "CO", "LI", "REE"] | None = None
    target: Literal["volume", "value"] | None = None


#: structured_template 이름 -> (commodity_code, target) 받는 호출부.
#: structured.py의 "화이트리스트 템플릿만, 자유형 NL→SQL 금지" 규약을 그대로
#: 따른다 — 여기서 하는 일은 템플릿 이름을 함수로 매핑하는 것뿐이다.
_STRUCTURED_CALLS = {
    "latest_diagnosis": lambda cc, target: structured.latest_diagnosis(cc),
    "import_forecast": lambda cc, target: structured.import_forecast(cc, target or "volume"),
    "geo_index_trend": lambda cc, target: structured.geo_index_trend(cc, limit=8),
}


MAX_ATTEMPTS = 2  # 최초 1회 + 재시도 1회 — "빠른시간내에" 요구사항상 무한 재시도는 안 함
HISTORY_WINDOW = 4  # route/reformulate/verify 세 LLM 호출이 공유하는 히스토리 창(최근 N메시지)


class RetrievalState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    session_id: str | None  # 그래프 로직엔 관여 안 함 — 로그·경고 추적용(아래 모듈 docstring)
    route: RetrievalRoute
    evidence: list[Evidence]
    sufficient: bool
    warnings: list[str]
    attempt: int


def _recent_history(state: RetrievalState) -> list[dict[str, str]]:
    return state.get("history", [])[-HISTORY_WINDOW:]


def _last_assistant_answer(state: RetrievalState) -> str:
    """직전 어시스턴트 답변 — route가 대용어를 풀 때 가장 먼저 봐야 할 텍스트를
    history 배열 속 마지막 항목으로 묻히게 두지 않고 별도 필드로 도드라지게
    준다(실측 발견, 2026-08-18: 3턴짜리 연쇄질문에서 route가 "그 광종"을
    직전 답변이 방금 확정한 개체가 아니라 더 앞 턴의 개체로 되짚는 실패가
    재현됐다 — history 안에 묻혀 있으면 소형 LLM이 놓치기 쉬웠던 것으로 보임,
    같은 정보를 payload에 이름 붙여 중복 노출하는 값싼 보강)."""

    for turn in reversed(state.get("history", [])):
        if turn.get("role") == "assistant":
            return turn.get("content", "")
    return ""


def _log_prefix(state: RetrievalState) -> str:
    session_id = state.get("session_id")
    return f"[rag/ragkit/chatbot_graph session={session_id[:8] if session_id else '?'}]"


def _route_node(state: RetrievalState, llm: KomirJsonLLM) -> RetrievalState:
    """도구 선택 — 실패하면 안전한 기본값(비정형 두 도구만, resolved_query는
    원 질문 그대로)으로 폴백한다(intent.py의 "분류 실패시 document로" 폴백과
    같은 원칙: structured는 commodity_code를 잘못 짚으면 엉뚱한 광종 수치를
    근거로 들이밀 위험이 있어 불확실할 땐 꺼두는 쪽이 안전하다).

    history를 함께 보내는 이유(실측으로 발견, 2026-08-13): "그 나라 생산량은?"
    같은 대용어 섞인 후속 질문을 history 없이 이번 질문 문자열만으로 판단하면
    라우터가 무엇을 찾아야 할지 못 정해 도구를 하나도 못 고르고 그대로
    기권해버린다(실제 pgvector+LLM 대상 라이브 테스트에서 재현) — history
    앞부분만(HISTORY_WINDOW) 넘겨 대용어를 resolved_query로 풀게 한다(프롬프트
    길이 통제, chatbot.py의 _history_block과 같은 절제).

    폴백 트리거는 LLM_TRANSIENT_ERRORS(LLMError뿐 아니라 RuntimeError·OSError도
    포함) — 2026-08-13 herd 코드리뷰로 실측 발견: OpenAICompatChat.complete()가
    재시도 소진 후 HTTP 429/5xx는 RuntimeError로, 타임아웃/커넥션 오류는 OSError
    서브클래스로 던지는데 둘 다 LLMError가 아니라서, 이 세 노드(route/
    reformulate/verify) 전부 `except LLMError`만으로는 가장 흔한 실제 장애
    (vLLM 일시 다운·네트워크 오류)에서 폴백이 안 걸리고 예외가 그대로 올라가
    턴 전체가 죽었다(자세한 이유는 shared.llm_client.LLM_TRANSIENT_ERRORS
    docstring)."""

    try:
        invocation = llm.invoke(
            task="retrieval_route", instructions=ROUTE_PROMPT,
            payload={
                "question": state["question"],
                "history": _recent_history(state),
                "last_answer": _last_assistant_answer(state),
            },
            output_model=RetrievalRoute, max_tokens=160,
        )
        route = invocation.output
        if not route.resolved_query.strip():
            route.resolved_query = state["question"]
        warnings: list[str] = []
        print(
            f"{_log_prefix(state)} route: resolved_query={route.resolved_query!r} "
            f"structured={route.use_structured}({route.structured_template}/{route.commodity_code}) "
            f"dense={route.use_dense} pageindex={route.use_pageindex}({route.pageindex_mode})"
        )
    except LLM_TRANSIENT_ERRORS as exc:
        route = RetrievalRoute(
            resolved_query=state["question"], use_structured=False, use_dense=True, use_pageindex=True,
        )
        warnings = [f"retrieval_route_invalid_output:{type(exc).__name__}"]
    return {"route": route, "warnings": warnings}


def _retrieve_node(
    state: RetrievalState, llm: KomirJsonLLM, *, dense_k: int, pageindex_k: int
) -> RetrievalState:
    """route가 켠 도구들을 스레드풀로 병렬 조회 — 도구 하나가 실패해도(DB
    미접속·PageIndex 트리 미구축 등) 나머지는 계속 진행한다(부분 열화, 전체
    실패가 아님). 모든 도구가 비거나 실패하면 evidence=[]로 돌아가고,
    chat_turn()의 기존 "근거 0건 -> 기권" 경로가 그대로 처리한다.

    pageindex는 route.pageindex_mode에 따라 두 갈래다: "simple"이면 기존
    결정적 단발조회(pageindex.lookup), "agentic"이면 pageindex_agent.
    agentic_lookup()(다수 스텝 LLM 왕복으로 광종 여러 개를 훑어 국가별 순위·
    집계 근거를 모음, 모듈독스트링 참고) — 후자는 이미 (evidence, warnings)
    튜플을 직접 반환하므로 병합 방식이 simple과 다르다(아래 분기)."""

    route = state["route"]
    warnings = list(state.get("warnings", []))
    jobs: dict[str, Future] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        if route.use_structured and route.structured_template and route.commodity_code:
            jobs["structured"] = pool.submit(
                _STRUCTURED_CALLS[route.structured_template], route.commodity_code, route.target
            )
        query = route.resolved_query or state["question"]
        if route.use_dense:
            jobs["dense"] = pool.submit(dense_pg.dense_search_pg, query, dense_k)
        if route.use_pageindex:
            if route.pageindex_mode == "agentic":
                jobs["pageindex"] = pool.submit(
                    pageindex_agent.agentic_lookup, query, history=_recent_history(state), llm=llm,
                )
            else:
                jobs["pageindex"] = pool.submit(pageindex.lookup, query, node_limit=pageindex_k, with_text=True)

        results: dict[str, object] = {}
        for name, future in jobs.items():
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001 — 도구 하나 실패는 부분 열화로 흡수
                print(f"{_log_prefix(state)} {name} 조회 실패: {type(exc).__name__}: {exc}")
                warnings.append(f"{name}_failed")

    evidence: list[Evidence] = []
    if "structured" in results:
        ev = from_structured(route.structured_template, route.commodity_code, results["structured"])
        if ev:
            evidence.append(ev)
    for chunk in results.get("dense", []):
        evidence.append(from_dense_chunk(chunk))
    if "pageindex" in results:
        if route.pageindex_mode == "agentic":
            pi_evidence, pi_warnings = results["pageindex"]
            evidence.extend(pi_evidence)
            warnings.extend(pi_warnings)
        else:
            for hit in results["pageindex"].get("nodes", []):
                evidence.append(from_pageindex_hit(hit))

    return {"evidence": evidence, "warnings": warnings}


def _reformulate_node(state: RetrievalState, llm: KomirJsonLLM) -> RetrievalState:
    """verify가 "불충분"이라고 판정했을 때만 호출된다(조건부 엣지, 아래
    _route_after_verify) — evidence가 0건인 경우와 "근거는 있는데 질문에
    답이 안 되는" 경우 둘 다 여기로 온다(verify가 이미 둘을 통합했다).
    resolved_query를 검색 성공률이 높은 형태로 다시 쓰고 attempt를 늘려서
    retrieve로 돌려보낸다 — route/도구선택 자체(structured 여부·commodity_code
    등)는 이미 1차에서 정한 걸 그대로 쓰고 검색어만 바꾼다(도구 선택이 틀렸을
    가능성보다 검색어가 그 도구에 안 맞았을 가능성이 훨씬 커서 — 1차에서 이미
    실측으로 확인된 실패모드)."""

    route = state["route"]
    try:
        invocation = llm.invoke(
            task="retrieval_reformulate", instructions=REFORMULATE_PROMPT,
            payload={"question": route.resolved_query, "history": _recent_history(state)},
            output_model=ReformulatedQuery, max_tokens=80,
        )
        new_query = invocation.output.query.strip() or route.resolved_query
        warning = "retrieval_reformulated"
    except LLM_TRANSIENT_ERRORS as exc:
        new_query = route.resolved_query  # 재구성 실패 — 원 질의 그대로 재시도(그래도 attempt는 소진)
        warning = f"retrieval_reformulate_invalid_output:{type(exc).__name__}"

    print(f"{_log_prefix(state)} reformulate: {route.resolved_query!r} -> {new_query!r}")
    return {
        "route": route.model_copy(update={"resolved_query": new_query}),
        "attempt": state.get("attempt", 1) + 1,
        "warnings": [*state.get("warnings", []), warning],
    }


def _verify_node(state: RetrievalState, llm: KomirJsonLLM) -> RetrievalState:
    """"correct 체크"(사용자 요청, 2026-08-13) — 근거가 실제로 질문에 답이
    되는지 확인한다. evidence가 애초에 비어있으면 LLM을 부를 필요도 없이
    바로 불충분(비용 절감) — 계기가 된 구리 사례처럼 evidence는 8건 있는데
    전부 주제만 겹치고 질문엔 안 답하는 경우를 잡아내는 게 이 노드의 핵심
    역할이다."""

    evidence = state.get("evidence", [])
    if not evidence:
        return {"sufficient": False}

    try:
        invocation = llm.invoke(
            task="retrieval_verify", instructions=VERIFY_PROMPT,
            payload={
                "question": state["route"].resolved_query,
                "history": _recent_history(state),
                "evidence": [
                    {"index": i, "source": ev.source, "section": ev.section, "excerpt": ev.text[:200]}
                    for i, ev in enumerate(evidence, 1)
                ],
            },
            output_model=GroundingCheck, max_tokens=150,
        )
        sufficient = invocation.output.sufficient
        warning = None if sufficient else f"retrieval_insufficient:{invocation.output.reason[:80]}"
    except LLM_TRANSIENT_ERRORS as exc:
        # 검증 호출 자체가 실패하면(LLM 장애 등) "일단 있는 근거로 진행"이 더
        # 안전하다 — 생성 단계의 인용강제·기권(_strip_uncited_sentences)이
        # 최종 방어선이라 이중 안전망이고, 검증 실패를 곧장 재시도로 몰면
        # LLM이 계속 죽어있는 상황에서 매 턴 재시도만 반복하다 끝난다.
        sufficient = True
        warning = f"retrieval_verify_invalid_output:{type(exc).__name__}"

    warnings = list(state.get("warnings", []))
    if warning:
        warnings.append(warning)
        print(f"{_log_prefix(state)} verify: sufficient={sufficient} ({warning})")
    return {"sufficient": sufficient, "warnings": warnings}


def _finalize_node(state: RetrievalState) -> RetrievalState:
    """verify가 재시도 소진 후에도 "불충분"이면 evidence를 비워서 반환한다 —
    chat_turn()이 evidence 비어있음만 보고 그대로 기권 처리하도록(citations_json
    구조·done 이벤트 계약이 바뀌지 않게, retrieve_evidence()의 반환 계약도
    그대로 (evidence, warnings) 2-tuple 유지)."""

    if not state.get("sufficient", True):
        return {"evidence": []}
    return {}


def _route_after_verify(state: RetrievalState) -> str:
    if not state.get("sufficient", True) and state.get("attempt", 1) < MAX_ATTEMPTS:
        return "retry"
    return "done"


def build_graph(llm: KomirJsonLLM, *, dense_k: int = 5, pageindex_k: int = 3):
    """route -> retrieve -> verify -> (불충분하면 reformulate -> retrieve ->
    verify, 최대 MAX_ATTEMPTS번) -> finalize -> END. 매 호출마다 새로 짓는다
    (체크포인터 없음, 컴파일 비용은 LLM/DB 왕복에 비하면 무시할 만하다) —
    llm을 인자로 받아 테스트에서 모의로 갈아끼우기 쉽게 한다
    (page_recommend/service.py의 llm 주입 방식과 동일)."""

    builder = StateGraph(RetrievalState)
    builder.add_node("route", lambda s: _route_node(s, llm))
    builder.add_node("retrieve", lambda s: _retrieve_node(s, llm, dense_k=dense_k, pageindex_k=pageindex_k))
    builder.add_node("verify", lambda s: _verify_node(s, llm))
    builder.add_node("reformulate", lambda s: _reformulate_node(s, llm))
    builder.add_node("finalize", _finalize_node)
    builder.add_edge(START, "route")
    builder.add_edge("route", "retrieve")
    builder.add_edge("retrieve", "verify")
    builder.add_conditional_edges("verify", _route_after_verify, {"retry": "reformulate", "done": "finalize"})
    builder.add_edge("reformulate", "retrieve")
    builder.add_edge("finalize", END)
    return builder.compile(name="komir-rag-retrieval")


def retrieve_evidence(
    question: str, *,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    llm: KomirJsonLLM | None = None,
    dense_k: int = 5,
    pageindex_k: int = 3,
) -> tuple[list[Evidence], list[str]]:
    """`chat_turn()`이 부르는 단일 진입점 — question(+history) -> (근거 리스트,
    경고 리스트). history는 대용어("그 나라" 등) 해소용으로만 라우팅 노드에
    쓰이고, 실제 검색 질의는 route.resolved_query로 대체된다. session_id는
    그래프 판단에 관여하지 않고 로그 추적용으로만 실린다(_log_prefix). 1차
    검색이 0건이거나 verify가 "질문에 안 답한다"고 판정하면 검색어를 재구성해
    1회 재시도한다(_reformulate_node).

    동기 함수다(psycopg2/파일 I/O가 전부 블로킹) — 호출자가 asyncio.to_thread로
    감쌀 것. llm을 주입하지 않으면 프로세스 기본 설정(get_settings().llm_cfg())의
    KomirJsonLLM을 새로 만든다."""

    llm = llm or KomirJsonLLM()
    graph = build_graph(llm, dense_k=dense_k, pageindex_k=pageindex_k)
    result = graph.invoke(
        {"question": question, "history": history or [], "session_id": session_id, "attempt": 1}
    )
    return result.get("evidence", []), result.get("warnings", [])


if __name__ == "__main__":  # 수동 점검용
    import json
    import sys as _sys

    q = _sys.argv[1] if len(_sys.argv) > 1 else "니켈 수급위기 진단등급이 어떻게 되나"
    ev, warn = retrieve_evidence(q)
    print(json.dumps(
        {"warnings": warn, "evidence": [vars(e) for e in ev]}, ensure_ascii=False, indent=2,
    ))
