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

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from shared.llm_client import LLM_TRANSIENT_ERRORS, KomirJsonLLM  # noqa: E402
from shared.retrieval.evidence import Evidence  # noqa: E402

_logger = logging.getLogger(__name__)

from . import mcp_client  # noqa: E402

# 2026-08-26: 정형(structured)/hybrid(dense+BM25)/PageIndex 세 도구 직접호출을
# MCP client 호출로 교체(public/private 두 프로필 — mcp_server_public.py·
# mcp_server_private.py 물리적으로 분리된 별도 모듈, mcp_client.py 신설) —
# 도구 구현(services/shared/retrieval/*)과 Evidence 변환은 이제 서버
# 프로세스 쪽에서 실행되고, 이 그래프는 어느 프로필 세션을 쓸지(RetrievalState.
# profile)만 고른다. Evidence 타입 자체는 여전히 공유 정의를 그대로 쓴다
# (mcp_client가 서버 응답 dict를 이 타입으로 복원).

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
   그대로 쓴다. **resolved_query는 대용어 해소(대명사→실제 개체명)만 한다 —
   아래 2번에서 고른 도구·지표에 맞춰 질문의 용어 자체를 바꿔쓰지 않는다.**
   예: 질문이 "가격"을 물었다면 골라야 할 도구가 가격을 못 다루더라도
   resolved_query는 "가격"을 그대로 유지한다("수입금액"·"수입물량" 등 available한
   지표 이름으로 슬쩍 바꿔쓰면 안 됨 — 뒤 단계가 질문이 실제로 바뀐 것으로
   착각해 오답을 정답처럼 통과시킨다).
2. 아래 네 근거 도구 중 무엇을 쓸지 정한다(resolved_query 기준으로 판단):
   - structured: komir 자체 산출물(수급위기 진단 등급, 12개월 수입물량/금액
     예측, 지정학 위기지수 추이)을 특정 광종 기준으로 조회한다. "{광종}
     진단등급이/예측이/위기지수가 어떻게 되나" 류의 수치 질문일 때만 켠다.
     광종(CU=동, NI=니켈, CO=코발트, LI=리튬, REE=네오디뮴 또는 그 별칭)을
     특정할 수 없으면 절대 켜지 않는다. 켤 때는 structured_template을 정확히
     하나 고른다: latest_diagnosis(최근 진단등급 1건) | import_forecast
     (수입 예측, target=volume(수입"물량")|value(수입"금액", 가격이 아니다))
     | geo_index_trend(위기지수 추이). import_forecast를 고르고 질문이 특정
     개월수를 요구하면(예: "3개월치", "6개월 예측") forecast_months에 그
     숫자를 넣는다 — 지정이 없으면 forecast_months=null(=12개월 전체).
     **이 세 가지에 없는 지표(가격·교역·매장량·생산량·시장전망·수급안정 등)는
     structured가 아니라 아래 komis_raw가 담당한다** — 그런 질문에 structured를
     같이 켤 필요는 없다(commodity_code가 있으면 komis_raw만으로 충분).
   - komis_raw(2026-08-31 신설, 2026-09-01 전 광종으로 확대): KOMIS가 자체
     웹사이트에서 공개하는 원천 데이터(광종별 실거래가·최저/최고가,
     국내(관세청)·세계(UN Comtrade) 교역량, 국가별 매장량·생산량, 시장전망
     지표, 수급안정지수, 가격예측)를 조회한다. "{광종} 가격/시세 알려줘",
     "{광종} 수입/수출 현황", "{광종} 매장량/생산량", "{광종} 가격 전망" 류의
     **구체적 수치를 원하는 질문**일 때 켠다(화면·메뉴 위치 자체를 묻는
     질문이 아니라 수치 자체를 원할 때 — 화면 위치 질문은 이 그래프가 아니라
     별도의 page 안내 경로로 이미 분류되어 여기로 오지 않는다). **발주
     5광종(CU/NI/CO/LI/REE)에 한정하지 않는다** — KOMIS가 다루는 광종이면
     무엇이든(예: 텅스텐·금·은·주석·알루미늄·우라늄 등) 이 도구로 조회를
     시도한다. 켤 땐 두 가지를 정한다:
     1) komis_topic — 정확히 하나:
        - price: 실거래가·최저가·최고가·시세(단가) — "가격"·"시세" 질문은
          거의 항상 이거다.
        - domestic_trade: 한국 관세청 기준 수입/수출 물량·금액(국가별).
        - global_trade: UN Comtrade 기준 세계 교역(국가 간 수출입).
        - reserves_production: 국가별 매장량·생산량(세계 공급 구조).
        - market_outlook: 시장전망지표.
        - supply_stability: 수급안정지수.
        - price_forecast: KOMIS 자체 가격예측(위 structured의 import_forecast
          와 다르다 — 이건 komir가 만든 예측이 아니라 KOMIS가 게시하는
          예측이다).
        "종합지수"·"위기지수"·"수급동향지표"·"시장동향지표"처럼 여러 지표를
        합성한 지수는 komis_topic 어디에도 없다 — 그런 질문은 komis_raw를
        켜지 않는다(이 그래프로 오기 전 단계에서 이미 걸러졌어야 정상이지만,
        혹시 오더라도 이 도구로는 못 답한다는 뜻).
     2) komis_mineral_name — 질문이 가리키는 광종의 한글명을 질문에 쓰인
        표현 그대로 채운다(예: "텅스텐", "금", "구리". commodity_code처럼
        CU/NI 같은 영문 약어로 바꿔쓰지 않는다 — 이 필드는 5광종 제한이
        없는 별도 필드다). 광종을 특정할 수 없으면 komis_raw를 켜지 않는다.
   - dense: 보고서·기사·백서 등 비정형 문서를 의미 기반으로 검색한다. 애매하면
     켜는 게 안전하다(기본값에 가깝게 취급). komis_raw를 켤 때도, 그 데이터가
     실제로는 없거나(발주 5광종 상당수가 아직 개발용 더미다) 부족할 수 있어
     안전망으로 함께 켜두는 걸 권장한다.
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
광종을 모르거나 이 5개 밖이면 켜지 않는다(use_structured=false, komir 자체
산출물은 이 5광종만 계산되어 있다). komis_raw를 켤 땐 komis_mineral_name을
반드시 함께 지정한다 — 광종을 모르면 켜지 않는다(use_komis_raw=false, 다만
5광종 제한은 없다)."""


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
sufficient=true다(모든 근거가 완벽할 필요는 없다).

**주제만 같고 지표가 다른 경우도 불충분이다** — 특히 정형(structured) 근거는
"12개월 수입물량 예측"·"12개월 수입금액 예측"·"수급위기 진단 등급"·"지정학
위기지수" 중 정확히 하나의 지표만 담고 있다. 질문이 "가격"을 물었는데 근거가
"수입금액"(수입 총액, 가격이 아니다)이거나, "생산량"을 물었는데 근거가
"수입물량"(한국의 수입량, 세계 생산량이 아니다)이면 — 같은 광종·비슷한 숫자
단위로 보여도 다른 지표이므로 sufficient=false다."""


class GroundingCheck(BaseModel):
    sufficient: bool
    reason: str = ""


class ReformulatedQuery(BaseModel):
    query: str


class RetrievalRoute(BaseModel):
    resolved_query: str = ""
    use_structured: bool
    use_komis_raw: bool = False  # 2026-08-31 신설(komis_raw_lookup MCP tool)
    use_dense: bool
    use_pageindex: bool
    pageindex_mode: Literal["simple", "agentic"] = "simple"
    structured_template: Literal["latest_diagnosis", "import_forecast", "geo_index_trend"] | None = None
    komis_topic: Literal[
        "price", "domestic_trade", "global_trade", "reserves_production",
        "market_outlook", "supply_stability", "price_forecast",
    ] | None = None
    # 2026-09-01: komis_raw 전용 광종명 필드 신설(자유형, 5광종 제한 없음) —
    # commodity_code(바로 아래)는 structured(komir 자체 산출물, latest_diagnosis
    # 등)가 실제로 5광종만 계산하기 때문에 그대로 5개로 제한한다. komis_raw는
    # KOMIS가 다루는 18개 광종 전체를 조회할 수 있어(ai_mnrl_mst 실측) 별도
    # 필드로 뒀다 — 사용자 지시("5대 광종 제한은 이 프로젝트 일부(진단·예측)
    # 에서만 쓰는 것, 챗봇 전체는 아니다")로 CHATBOT_SYSTEM_PROMPT 규칙11도
    # 같이 제거했다(chatbot.py 참고).
    komis_mineral_name: str | None = None
    commodity_code: Literal["CU", "NI", "CO", "LI", "REE"] | None = None
    target: Literal["volume", "value"] | None = None
    forecast_months: int | None = None  # import_forecast 전용 — "N개월치만" 요청 시 1~N만 반환


#: structured_template 이름 -> (session, commodity_code, target) 받는 호출부.
#: structured.py의 "화이트리스트 템플릿만, 자유형 NL→SQL 금지" 규약을 그대로
#: 따른다 — 여기서 하는 일은 템플릿 이름을 mcp_client 세션 메서드로 매핑하는
#: 것뿐이다. session이 profile(public/private)에 따라 달라지므로 모듈 전역이
#: 아니라 `_retrieve_node` 안에서 그때그때 만든다(아래).
_STRUCTURED_CALL_NAMES = {
    "latest_diagnosis": "call_latest_diagnosis",
    "import_forecast": "call_import_forecast",
    "geo_index_trend": "call_geo_index_trend",
}

#: komis_topic -> komis_raw_lookup page_id(price 제외 — 광종과 무관하게
#: 페이지가 고정된 5개 topic만). 이건 KOMIS 사이트의 고정 페이지 구조라
#: 하드코딩해도 안전하다(광종이 새로 추가돼도 안 바뀜).
_KOMIS_TOPIC_TO_PAGE = {
    "domestic_trade": "map_korea",
    "global_trade": "map_global",
    "reserves_production": "map_mineral",
    "market_outlook": "indicator_market",
    "supply_stability": "indicator_supply",
    "price_forecast": "forecast_price",
}
#: price_category(ai_mnrl_mst.prc_cat_cd, HP001~004 — 광종이 아니라 KOMIS
#: 가격 서브메뉴 4종의 고정 분류코드) -> komis_raw_lookup page_id. 이것도
#: 페이지 구조라 하드코딩 — 광종명→코드 매핑만 2026-09-01부터 ai_mnrl_mst
#: 실조회(komis_resolve_mineral MCP tool)로 바꿨다(사용자 지시: "5광종
#: 화이트리스트는 이 프로젝트 일부 기능용, 챗봇 전체는 아니다" — 하드코딩
#: 딕셔너리는 KOMIS가 광종을 추가로 등록할 때마다 코드를 고쳐야 해서
#: 유지보수 부담이 컸다).
_PRICE_CATEGORY_TO_PAGE = {
    "HP001": "price_base_metals", "HP002": "price_minor_metals",
    "HP003": "price_iron_energy", "HP004": "price_other",
}


def _komis_raw_page_id(topic: str, price_category: str | None) -> str | None:
    if topic == "price":
        return _PRICE_CATEGORY_TO_PAGE.get(price_category or "")
    return _KOMIS_TOPIC_TO_PAGE.get(topic)


MAX_ATTEMPTS = 2  # 최초 1회 + 재시도 1회 — "빠른시간내에" 요구사항상 무한 재시도는 안 함
HISTORY_WINDOW = 4  # route/reformulate/verify 세 LLM 호출이 공유하는 히스토리 창(최근 N메시지)


class RetrievalState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    session_id: str | None  # 그래프 로직엔 관여 안 함 — 로그·경고 추적용(아래 모듈 docstring)
    profile: Literal["public", "private"]  # 그래프 판단엔 관여 안 함 — _retrieve_node가
    # mcp_client.public/private 중 어느 세션을 쓸지 고르는 데만 쓴다(session_id와
    # 같은 패스스루 필드, 2026-08-26 public/private MCP 분리)
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
        _logger.info(
            "%s route: resolved_query=%r structured=%s(%s/%s) komis_raw=%s(%s/%s) dense=%s pageindex=%s(%s)",
            _log_prefix(state), route.resolved_query, route.use_structured, route.structured_template,
            route.commodity_code, route.use_komis_raw, route.komis_topic, route.komis_mineral_name,
            route.use_dense, route.use_pageindex, route.pageindex_mode,
        )
    except LLM_TRANSIENT_ERRORS as exc:
        route = RetrievalRoute(
            resolved_query=state["question"], use_structured=False, use_dense=True, use_pageindex=True,
        )
        warnings = [f"retrieval_route_invalid_output:{type(exc).__name__}"]
    return {"route": route, "warnings": warnings}


def _retrieve_node(state: RetrievalState, *, dense_k: int, pageindex_k: int) -> RetrievalState:
    """route가 켠 도구들을 스레드풀로 병렬 조회 — 도구 하나가 실패해도(DB
    미접속·PageIndex 트리 미구축 등) 나머지는 계속 진행한다(부분 열화, 전체
    실패가 아님). 모든 도구가 비거나 실패하면 evidence=[]로 돌아가고,
    chat_turn()의 기존 "근거 0건 -> 기권" 경로가 그대로 처리한다.

    pageindex는 route.pageindex_mode에 따라 두 갈래다: "simple"이면 기존
    결정적 단발조회(pageindex.lookup), "agentic"이면 pageindex_agent.
    agentic_lookup()(다수 스텝 LLM 왕복으로 광종 여러 개를 훑어 국가별 순위·
    집계 근거를 모음, 모듈독스트링 참고) — 후자는 이미 (evidence, warnings)
    튜플을 직접 반환하므로 병합 방식이 simple과 다르다(아래 분기). komis_raw도
    같은 (evidence, warnings) 튜플 계약이다(2026-08-31 신설 — mcp_client.
    call_komis_raw_lookup, KOMIS 공개원천 public.KO_* 조회. page_id는 LLM이
    직접 고르지 않는다 — komis_topic(사람이 이해하는 주제)·komis_mineral_name
    (자유형 한글 광종명)만 고르게 하고, 실제 page_id·광종코드(MNRL0xxx) 번역은
    이 노드가 komis_resolve_mineral(2026-09-01 신설, ai_mnrl_mst 실조회 —
    하드코딩 딕셔너리였던 걸 사용자 지시로 바꿈)을 먼저 부른 뒤 결정적으로
    한다(_komis_raw_page_id) — structured.py의 "자유형 NL→SQL 금지, 화이트
    리스트 템플릿만" 원칙과 같다).

    2026-08-26: 세 도구 모두 mcp_client 세션(state["profile"]로 고른 public/
    private — 각각 mcp_server_public.py/mcp_server_private.py 물리적으로 분리된
    서버 프로세스) 경유 호출로 바뀌었다 — 서버가 이미 Evidence 모양을 돌려주므로
    여기선 더 이상 from_structured/from_dense_chunk/from_pageindex_hit 변환이
    필요 없다(그 변환은 서버 쪽으로 옮겨감)."""

    route = state["route"]
    warnings = list(state.get("warnings", []))
    session = mcp_client.private if state.get("profile") == "private" else mcp_client.public
    jobs: dict[str, Future] = {}

    # 2026-09-01: komis_raw는 page_id를 미리 알아야 풀에 넣을 수 있는데, price
    # 여부에 따른 page_id가 광종의 price_category(ai_mnrl_mst.prc_cat_cd)에
    # 달려 있어 하드코딩 딕셔너리 대신 komis_resolve_mineral을 먼저(동기)
    # 호출해 알아낸다 — 그 뒤 dense/pageindex와 나란히 병렬 조회한다(아래 풀).
    komis_raw_page_id: str | None = None
    komis_raw_mineral_code: str | None = None
    if route.use_komis_raw and route.komis_topic and route.komis_mineral_name:
        resolved = session.call_komis_resolve_mineral(route.komis_mineral_name)
        warnings.extend(resolved.get("warnings", []))
        komis_raw_mineral_code = resolved.get("mineral_code")
        if komis_raw_mineral_code:
            komis_raw_page_id = _komis_raw_page_id(route.komis_topic, resolved.get("price_category"))
            if not komis_raw_page_id:
                warnings.append(
                    f"komis_raw_unmapped_topic:{route.komis_topic}(mineral={route.komis_mineral_name})"
                )

    with ThreadPoolExecutor(max_workers=4) as pool:
        if route.use_structured and route.structured_template and route.commodity_code:
            call = getattr(session, _STRUCTURED_CALL_NAMES[route.structured_template])
            jobs["structured"] = pool.submit(call, route.commodity_code, route.target, route.forecast_months)
        if komis_raw_page_id and komis_raw_mineral_code:
            jobs["komis_raw"] = pool.submit(
                session.call_komis_raw_lookup, komis_raw_page_id,
                mineral_code=komis_raw_mineral_code, mineral_label=route.komis_mineral_name,
            )
        query = route.resolved_query or state["question"]
        if route.use_dense:
            jobs["dense"] = pool.submit(session.call_hybrid_search, query, dense_k)
        if route.use_pageindex:
            if route.pageindex_mode == "agentic":
                jobs["pageindex"] = pool.submit(
                    session.call_pageindex_agentic, query, history=_recent_history(state),
                )
            else:
                jobs["pageindex"] = pool.submit(
                    session.call_pageindex_lookup, query, node_limit=pageindex_k, with_text=True,
                )

        results: dict[str, object] = {}
        for name, future in jobs.items():
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001 — 도구 하나 실패는 부분 열화로 흡수
                _logger.warning("%s %s 조회 실패: %s: %s", _log_prefix(state), name, type(exc).__name__, exc)
                warnings.append(f"{name}_failed")

    evidence: list[Evidence] = []
    if "structured" in results and results["structured"] is not None:
        evidence.append(results["structured"])
    if "komis_raw" in results:
        kr_evidence, kr_warnings = results["komis_raw"]
        evidence.extend(kr_evidence)
        warnings.extend(kr_warnings)
    evidence.extend(results.get("dense", []))
    if "pageindex" in results:
        if route.pageindex_mode == "agentic":
            pi_evidence, pi_warnings = results["pageindex"]
            evidence.extend(pi_evidence)
            warnings.extend(pi_warnings)
        else:
            evidence.extend(results["pageindex"])

    return {"evidence": evidence, "warnings": warnings}


def _reformulate_node(state: RetrievalState, llm: KomirJsonLLM) -> RetrievalState:
    """verify가 "불충분"이라고 판정했을 때만 호출된다(조건부 엣지, 아래
    _route_after_verify) — evidence가 0건인 경우와 "근거는 있는데 질문에
    답이 안 되는" 경우 둘 다 여기로 온다(verify가 이미 둘을 통합했다).
    resolved_query를 검색 성공률이 높은 형태로 다시 쓰고 attempt를 늘려서
    retrieve로 돌려보낸다.

    도구 선택은 1차에서 정한 것에 dense+pageindex를 **더한다**(끄지는 않는다,
    합집합) — 원래는 "검색어가 안 맞았을 가능성이 도구 선택 실패보다 훨씬
    크다"는 전제로 도구를 그대로 뒀지만, 실측(2026-08-27, "구리 12개월 가격")
    으로 그 전제가 깨지는 사례가 나왔다: structured만 켠 1차 조회가
    import_forecast(수입금액)를 "가격"의 대용으로 잘못 골라 verify를 통과시켜
    버렸다(같은 턴에서 재현·확인). structured에는 애초에 가격 시리즈가 없고
    실제 가격은 dense/pageindex(조달청·Argus 보고서)에만 있을 수 있으므로,
    1차가 불충분으로 판정된 재시도에서는 두 비정형 도구를 추가로 열어 놓쳤을
    수 있는 실제 문서 근거를 찾을 기회를 준다."""

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

    _logger.info("%s reformulate: %r -> %r", _log_prefix(state), route.resolved_query, new_query)
    return {
        "route": route.model_copy(update={
            "resolved_query": new_query, "use_dense": True, "use_pageindex": True,
        }),
        "attempt": state.get("attempt", 1) + 1,
        "warnings": [*state.get("warnings", []), warning],
    }


def _verify_node(state: RetrievalState, llm: KomirJsonLLM) -> RetrievalState:
    """"correct 체크"(사용자 요청, 2026-08-13) — 근거가 실제로 질문에 답이
    되는지 확인한다. evidence가 애초에 비어있으면 LLM을 부를 필요도 없이
    바로 불충분(비용 절감) — 계기가 된 구리 사례처럼 evidence는 8건 있는데
    전부 주제만 겹치고 질문엔 안 답하는 경우를 잡아내는 게 이 노드의 핵심
    역할이다.

    2026-08-28(챗봇_룰준수_감사_260828.md §P0-1, 라운드2) — `max_tokens`가
    150이던 시절엔 "코발트 광물종합지표의 최근 12개월 변화를 보여줘"류
    질문(reformulate 이후 evidence가 9건까지 늘어 근거별로 왜 불충분한지
    나열하는 응답)에서 반복 재현됐다: `finish_reason="length"`로 `reason`
    문자열이 중간에 잘려(`JSONDecodeError: Unterminated string`) 복구
    재시도까지 같은 길이 상한에 걸려 또 잘리고, 결국 `LLMOutputError` →
    안전 폴백 `sufficient=True`인데 evidence는 이미 비어 하류(chat_turn)가
    완전 기권으로 끝나던 버그. 실측(docker exec 트레이스, 6회 반복 중 4회
    재현): 성공한 호출은 `completion_tokens` 최대 144, 실패한 호출은 전부
    정확히 150에서 `finish_reason="length"`로 잘림 — 모델이 근거 여러 건을
    "1) ... 2) ... 3) ..."처럼 항목별로 설명하는 습성이 있어 150으로는
    구조적으로 부족했다(JSON 포맷 문제가 아니라 순수 토큰 상한 부족).
    300으로 올려 여유를 둔다(관찰된 성공 케이스의 약 2배 — route(160)·
    reformulate(80)보다 verify의 reason이 원래 더 길 수밖에 없다: 근거
    여러 건 각각을 왜 불충분한지 설명해야 하는 유일한 노드)."""

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
            output_model=GroundingCheck, max_tokens=300,
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
        _logger.warning("%s verify: sufficient=%s (%s)", _log_prefix(state), sufficient, warning)
    return {"sufficient": sufficient, "warnings": warnings}


def _finalize_node(state: RetrievalState) -> RetrievalState:
    """verify가 재시도 소진 후에도 "불충분"이면 어떻게 할지 결정한다.

    2026-08-27까지는 무조건 evidence를 비워 기권시켰다 — "사용자가 항상 정확한
    지표명으로 묻는 건 아니다"(예: "가격"이라 묻지만 실제로는 수입금액 자료가
    있는 경우)는 사용자 지적으로, **불충분해도 근거를 뭔가 찾긴 했다면** 버리지
    않고 남겨서 chat_turn()이 "정확히 원하는 자료는 아니지만 이런 관련 자료가
    있다, 이거라도 보여줄까?"라는 제안형 답변(NEAR_MISS 프롬프트)의 재료로 쓸
    수 있게 한다 — retrieval_near_miss 경고로 표시. **evidence가 애초에 0건**
    (조회 자체가 아무것도 못 찾음)이면 제안할 게 없으므로 그대로 기권 경로
    (chat_turn의 "evidence 없음" 분기)로 보낸다(retrieve_evidence()의 반환
    계약은 그대로 (evidence, warnings) 2-tuple 유지)."""

    if state.get("sufficient", True):
        return {}
    if state.get("evidence"):
        return {"warnings": [*state.get("warnings", []), "retrieval_near_miss"]}
    return {"evidence": []}


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
    builder.add_node("retrieve", lambda s: _retrieve_node(s, dense_k=dense_k, pageindex_k=pageindex_k))
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
    profile: Literal["public", "private"] = "public",
    on_status: Callable[..., None] | None = None,
) -> tuple[list[Evidence], list[str]]:
    """`chat_turn()`이 부르는 단일 진입점 — question(+history) -> (근거 리스트,
    경고 리스트). history는 대용어("그 나라" 등) 해소용으로만 라우팅 노드에
    쓰이고, 실제 검색 질의는 route.resolved_query로 대체된다. session_id는
    그래프 판단에 관여하지 않고 로그 추적용으로만 실린다(_log_prefix). 1차
    검색이 0건이거나 verify가 "질문에 안 답한다"고 판정하면 검색어를 재구성해
    1회 재시도한다(_reformulate_node).

    `profile`도 session_id와 같은 패스스루 필드다(그래프 판단엔 관여 안 함) —
    `_retrieve_node`가 mcp_client.public/private 중 어느 세션으로 hybrid_search·
    pageindex_lookup을 호출할지만 정한다(2026-08-26, pubchat/prichat 분리).

    `on_status(stage: str, **extra)`(2026-08-27)는 route/retrieve/verify/
    reformulate 각 단계 진입 시점에 호출된다 — `chat_turn()`이 이걸로 SSE
    `status` 이벤트를 낸다(`chatbot.py::_run_with_status` 참고). 이 함수는
    여전히 동기라 `on_status`도 동기 콜백이어야 한다(스레드 안전한 브리징은
    호출자 책임).

    구현은 `graph.invoke()` 대신 `graph.stream(stream_mode=["updates",
    "values"])`를 쓴다 — LangGraph가 "updates" 모드로 매 노드 **완료** 직후
    그 노드명+반환 delta를, "values" 모드로 그 시점까지 누적된 전체 state를
    내주므로(실측 확인, 2026-08-27), on_status를 노드 함수 4개+build_graph에
    일일이 관통시키지 않고 여기 한 곳에서만 처리할 수 있다(skeptic-code
    SC-001, 최초 구현은 노드마다 손으로 콜백을 심었었음). 그래프를 두 번
    돌리는 게 아니다 — 같은 스트림의 "values" 마지막 항목이 `graph.invoke()`
    반환값과 동일한 최종 state다.

    ⚠ "updates"는 진입이 아니라 **완료** 시점이다(2차 감사 실측 — 첫 구현은
    완료 시점에 그 노드 이름을 그대로 내서 모든 status가 한 단계씩 늦었고,
    가장 긴 대기인 첫 route LLM 호출 동안엔 아무것도 안 나갔다). 그래서
    "완료된 노드 → 다음에 실행될 노드"로 매핑한다: 시작 전 routing,
    route/reformulate 완료 → retrieving, retrieve 완료 → verifying, verify
    완료 → 재시도면 reformulating(재시도 판단은 엣지 함수 `_route_after_verify`
    를 그대로 재사용). 이 매핑은 build_graph()의 엣지 구성과 짝이다 — 엣지를
    바꾸면 여기도 같이 볼 것."""

    llm = llm or KomirJsonLLM()
    graph = build_graph(llm, dense_k=dense_k, pageindex_k=pageindex_k)
    state: dict = {
        "question": question, "history": history or [], "session_id": session_id,
        "profile": profile, "attempt": 1,
    }
    if on_status:
        on_status("routing")  # 첫 노드(route)는 완료 이벤트가 오기 전에 알려야 한다
    for mode, chunk in graph.stream(state, stream_mode=["updates", "values"]):
        if mode == "values":
            state = chunk
            continue
        if not on_status:
            continue
        node_name, delta = next(iter(chunk.items()))
        if node_name in ("route", "reformulate"):
            # 두 노드 다 다음 엣지가 retrieve. 켜진 도구 목록은 이 노드가 방금
            # 돌려준 delta의 route에서 읽는다 — 폴백 경로도 route를 항상 반환하고,
            # values 청크와의 인터리빙 순서에 기대지 않아도 된다.
            route = delta["route"]
            tools = [
                name for name, flag in (
                    ("structured", route.use_structured), ("komis_raw", route.use_komis_raw),
                    ("dense", route.use_dense), ("pageindex", route.use_pageindex),
                ) if flag
            ]
            on_status("retrieving", tools=tools)
        elif node_name == "retrieve":
            on_status("verifying")
        elif node_name == "verify" and _route_after_verify({**state, **delta}) == "retry":
            # state는 아직 verify 반영 전(values 청크가 updates 뒤에 온다)이라 delta를 덧씌운다.
            on_status("reformulating")
    return state.get("evidence", []), state.get("warnings", [])


if __name__ == "__main__":  # 수동 점검용
    import json
    import sys as _sys

    # 라이브러리 코드는 basicConfig를 안 부른다(서비스 컨텍스트는 uvicorn이
    # 루트 로거를 이미 구성함) — 이 CLI 경로만 예외로, route/retrieve/
    # reformulate/verify 진행 로그(logging.INFO)가 수동 점검 때도 보이게 켠다.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    q = _sys.argv[1] if len(_sys.argv) > 1 else "니켈 수급위기 진단등급이 어떻게 되나"
    ev, warn = retrieve_evidence(q)
    print(json.dumps(
        {"warnings": warn, "evidence": [vars(e) for e in ev]}, ensure_ascii=False, indent=2,
    ))
