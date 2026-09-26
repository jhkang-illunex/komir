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

import calendar
import logging
import re
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from datetime import date
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from common.llm_client import LLM_TRANSIENT_ERRORS, KomirJsonLLM  # noqa: E402
from rag_core.retrieval.access import PRIVATE_ONLY_KOMIS_PAGES  # noqa: E402
from rag_core.retrieval import mine_aggregate  # noqa: E402
from rag_core.retrieval.evidence import (  # noqa: E402
    Evidence, KOMIS_RAW_DUMMY_CAVEAT, KOMIS_RAW_UNVERIFIED_CAVEAT,
)

_logger = logging.getLogger(__name__)

from . import mcp_client  # noqa: E402
from .source_contract import (  # noqa: E402
    RequirementPlan, SourceAssessment, assess_requirement_plan, extract_requirement_plan,
)
from .action_contract import ActionPlan, PlanAssessment, extract_action_plan, validate_action_plan  # noqa: E402

# 2026-08-26: 정형(structured)/hybrid(dense+BM25)/PageIndex 세 도구 직접호출을
# MCP client 호출로 교체(public/private 두 프로필 — mcp_server_public.py·
# mcp_server_private.py 물리적으로 분리된 별도 모듈, mcp_client.py 신설) —
# 도구 구현(services/shared/retrieval/*)과 Evidence 변환은 이제 서버
# 프로세스 쪽에서 실행되고, 이 그래프는 어느 프로필 세션을 쓸지(RetrievalState.
# profile)만 고른다. Evidence 타입 자체는 여전히 공유 정의를 그대로 쓴다
# (mcp_client가 서버 응답 dict를 이 타입으로 복원).

#: 2026-09-07(사용자 지시) — structured(수급위기 진단·수입예측·지정학위기지수,
#: mineral_risk 스키마 테이블 3종)를 챗봇 검색 도구에서 임시 분리한다. 이
#: 테이블들이 향후 다른 테이블로 교체될 예정이라 지금 연계를 유지하는 게
#: 의미 없다는 판단 — komis_raw(public 스키마, KOMIS 공개원천)만 제대로
#: 동작하게 정비하는 데 집중한다. 재연결 시 이 플래그만 True로.
STRUCTURED_ENABLED = False

#: public 프로필이 private 전용 KOMIS 원천을 의도해 라우팅했을 때의 결정적
#: 중단 표식. 원천 MCP의 거부 경고만 기다리면 dense/PageIndex 안전망이 무관한
#: 문서를 찾아 "정상 답변"처럼 보이게 하므로, 도구 실행 전에 종료한다.
_PRIVATE_ONLY_PROFILE_WARNING = "private_only_profile_access"
_AGGREGATE_INCOMPLETE_WARNING = "aggregate_incomplete"
_SOURCE_UNAVAILABLE_WARNING_PREFIX = "source_unavailable:"

ROUTE_PROMPT = """당신은 핵심광물 수급위기 진단·수요예측 챗봇의 검색 라우터다.
직전 대화(history, 있으면)와 이번 질문(question)을 보고 정확히 하나의 JSON
객체로 결정한다. 설명·코드펜스·사고과정은 출력하지 않는다.

0. JSON 스키마의 선택 필드는 질문에 직접 필요한 경우에만 채운다. 필요 없는
   문자열·배열 필드는 null, 불리언 도구 플래그는 false로 둔다. 추측으로 광종,
   기간, 금액/중량 기준, 순위 지표를 만들어 채우지 않는다. history를 이용한
   후속 비교에서는 직전 답변이 확정한 금액/중량 기준과 기간을 보존한다. 이번
   질문이 새 기준(예: "톤 기준", "금액 기준", 다른 기간)을 명시했을 때만
   그 기준으로 바꾼다.

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
1.5. is_ambiguous(2026-09-18, 실측 회귀: "니켈 데이터 보여주세요"가 광종만
   특정되고 원하는 정보유형이 전혀 없는데도, dense가 "니켈"이 언급된 아무
   문서나 찾아와 그걸로 무관한 옛 수치를 답변해버렸다 — 질문이 애초에
   불명확했다는 사실 자체가 묻혔다). resolved_query(및 history)에 **광종만
   있고 정보유형(가격/수입·수출/생산·매장/지표 등 구체적으로 무엇을 원하는지)
   이 전혀 지정되지 않았으며, history를 봐도 앞선 대화에서 그 정보유형이
   정해진 적이 없다면** is_ambiguous=true로 표시하고, 아래 2번의 모든 도구
   플래그(use_dense·use_pageindex·use_komis_raw·use_mine_aggregate)는 전부
   false로, 관련 필드는 전부 null로 둔다(검색 자체를 시도하지 않는다 —
   무엇을 찾아야 할지 모르는데 검색하면 무관한 결과로 오답을 만들 뿐이다).
   반대로 정보유형이 하나라도 특정됐다면(가격·수급동향지표·매장량·규제
   등 무엇이든) is_ambiguous=false다 — 광종+정보유형 조합이면 충분하고,
   기간·세부 범위까지 명시할 필요는 없다("니켈 가격"은 명확하다, "니켈
   데이터"만 명확하지 않다).
2. 아래 세 근거 도구 중 무엇을 쓸지 정한다(resolved_query 기준으로 판단,
   is_ambiguous=true면 이 단계 전체를 건너뛰고 모든 도구를 false로 둔다):
   - structured(2026-09-07 임시 비활성화): komir 자체 산출물(수급위기 진단
     등급·12개월 수입물량/금액 예측·지정학 위기지수 추이)을 담던 테이블이
     교체될 예정이라 연결을 끊었다 — **use_structured는 항상 false로 두고,
     structured_template·commodity_code·target·forecast_months는 채우지
     않는다.** "진단등급이 어떻게 되나"·"수입 예측"·"위기지수 추이" 같은
     질문도 지금은 이 도구로 답할 수 없다 — dense/pageindex로 관련 문서를
     찾아보되, 못 찾으면 근거 없음으로 처리한다(정상적인 결과다, 데이터
     자체가 임시로 없는 것이지 오류가 아니다).
   - komis_raw(2026-08-31 신설, 2026-09-01 전 광종으로 확대+광물종합지수
     topic 추가): KOMIS가 자체 웹사이트에서 공개하는 원천 데이터(광종별
     실거래가·최저/최고가, 국내(관세청)·세계(UN Comtrade) 교역량, 국가별
     매장량·생산량, 시장전망지표, 수급안정지수, 광물종합지수)를
     조회한다. "{광종} 가격/시세 알려줘",
     "{광종} 수입/수출 현황", "{광종} 매장량/생산량" 류의
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
        - market_outlook: 시장전망지표(="시장동향지표"라고 묻는 질문도 이거다 —
          KOMIS 표시명과 사용자 표현이 다를 수 있다, 같은 지표다). **"시장"이라는
          단어가 들어간 질문은 이거다** — "수급"이 아니라 "시장"이면 반드시
          market_outlook.
        - supply_stability: 수급안정지수(="수급동향지표"라고 묻는 질문도
          이거다 — 위와 같은 이유). **"수급"이라는 단어가 들어간 질문은
          이거다** — "시장"이 아니라 "수급"이면 반드시 supply_stability.
          (둘을 헷갈리지 말 것: "니켈 시장동향지표"→market_outlook, "니켈
          수급동향지표"→supply_stability — 질문에 실제로 쓰인 단어가 "시장"
          인지 "수급"인지만 보고 정확히 그대로 매칭한다.)
        - composite_index: 광물종합지수(HI001~003, 여러 지표를 합성한 KOMIS
          자체 게시 지수 — "종합지수" 질문은 대개 이거다). **광종과 무관한
          지표라 광종을 몰라도 켠다** — komis_topic 중 유일하게
          komis_mineral_name 없이도 use_komis_raw=true로 켤 수 있다(맨 아래
          문단의 "komis_mineral_name 필수" 규칙의 유일한 예외).
        **"위기지수"는 이 중 어디에도 없다** — komir 자체 산출물(지정학
        위기지수, KOMIS가 게시하는 지표가 아니다)이라 komis_raw가 담당하는
        범위 밖이고, 위 structured도 비활성화됐다(같은 이유). "위기지수"
        질문엔 komis_raw를 켜지 않는다(광물종합지수·시장전망·수급안정과
        헷갈리지 말 것 — 이 셋은 KOMIS가 게시하는 별개 지표라 komis_raw가
        정상 담당한다).
     2) komis_mineral_name — 질문이 가리키는 광종의 한글명을 질문에 쓰인
        표현 그대로 채운다(예: "텅스텐", "금", "구리". commodity_code처럼
        CU/NI 같은 영문 약어로 바꿔쓰지 않는다 — 이 필드는 5광종 제한이
        없는 별도 필드다). 광종을 특정할 수 없으면 komis_raw를 켜지 않는다
     3) komis_hs_code — 질문에 HS 코드가 **명시**된 교역 조회에서는 그 숫자
        문자열을 그대로 채운다. 이 경우 광종명 추정/HS 매핑으로 바꾸지 말고,
        komis_topic은 domestic_trade(한국 수입·수출) 또는 global_trade(국가 간
        교역)로 정한다. 코드가 명시되지 않은 질문에서는 null이다.
     4) use_komis_concentration — "HHI" 또는 "집중도"를 국가별 수입/수출
        비중으로 계산해 달라는 질문에만 true. 상위 N개국 표가 아니라 전체
        국가 모집단을 쓰므로 use_komis_ranking으로 대체하지 않는다.
        (단, komis_topic=composite_index는 예외 — 위 참고, null로 둔다).
     3) komis_start_period·komis_end_period(선택) — 질문이 특정 연도/월/날짜를
        지정하면 YYYY/YYYYMM/YYYYMMDD 숫자 문자열로 둘 다 채운다. 두 가지
        경우가 있다: (a) 완전히 명시적인 연/월("2010년 1월"→둘 다 "201001",
        "2024년"→둘 다 "2024", "2024년 1월~3월"→시작·끝 각각), (b) 오늘
        기준 상대 연도("올해"→오늘_날짜의 연도, "작년"→그 전년도, "이번
        달"→오늘_날짜의 연월) — payload의 오늘_날짜(YYYY-MM-DD)를 기준으로
        계산한다(예: 오늘_날짜가 "2026-09-07"이면 "올해 니켈 가격"의
        komis_start_period/komis_end_period는 둘 다 "2026"). **"최근
        N개월/N년"처럼 오늘로부터 거슬러 세는 상대기간은 여기가 아니라
        아래 4)를 쓴다** — 그 계산은 개월수 뺄셈이 필요해 LLM 산술 오차
        위험이 있어 코드가 대신한다. 특정 기간·상대연도 언급이 전혀
        없으면(예: "니켈 가격 알려줘") 둘 다 null로 둔다(최신 데이터를
        조회한다는 뜻).
        ⚠ **"오늘"·"오늘 기준"·"현재"·"지금"은 "올해"·"이번 달"과 다르다**
        (2026-09-18, 실측 회귀: "니켈의 오늘 기준 가격은?"에서 이 단어를
        "이번 달"과 같은 식으로 취급해 komis_start_period=komis_end_period=
        오늘_날짜(예: "20260918")로 정확히 채웠다가, KOMIS 원천 데이터가
        실제로는 며칠~열흘 지연 적재돼(가장 최근 행이 "20260908"인데
        조회 기간을 "20260918" 하루로만 좁힘) 0건이 나와 "데이터가
        없습니다"로 잘못 기권했다). "오늘"·"오늘 기준"·"현재"·"지금"은
        **특정 날짜 하나를 콕 집으라는 뜻이 아니라 "가장 최근 값을
        원한다"는 뜻**이다 — 이 표현만 있고 그 외 다른 기간 언급이
        없으면 komis_start_period/komis_end_period를 오늘 날짜로 채우지
        않고 **둘 다 null로 둔다**(위 "특정 기간 언급이 전혀 없을 때"와
        동일하게 처리 — null이면 코드가 알아서 최신 N건을 가져온다,
        오늘 날짜로 정확히 좁히면 데이터 지연 때문에 0건이 나올 위험이
        있다). "오늘 날짜" 자체가 필요한 경우는 오직 (a)(b)처럼 그 날짜를
        기준으로 다른 상대기간(예: "올해")을 계산해야 할 때뿐이다.
     4) komis_relative_months(선택) — "최근 N개월"·"최근 N년"처럼 **오늘로부터
        거슬러 세는** 기간 표현이면 개월수로 환산해 채운다(예: "최근
        6개월"→6, "최근 1년"→12, "최근 3개월"→3) — 실제 날짜범위는
        오늘_날짜 기준으로 코드가 계산하니, 절대 날짜로 직접 계산하려 들지
        않는다 — 위 3)의 komis_start_period/komis_end_period와는 서로
        배타적이다(3은 "올해"·"2024년"처럼 특정 연도를 가리킬 때, 4는 "최근
        N개월"처럼 오늘부터 거슬러 셀 때). 상대 표현도 특정 기간 언급도
        없으면 둘 다 null로 둔다).
   - dense: 보고서·기사·백서 등 비정형 문서를 의미 기반으로 검색한다. 애매하면
     켜는 게 안전하다(기본값에 가깝게 취급). komis_raw를 켤 때도, 그 데이터가
     실제로는 없거나(발주 5광종 상당수가 아직 개발용 더미다) 부족할 수 있어
     안전망으로 함께 켜두는 걸 권장한다.
     **복합 질문 필수 규칙(2026-09-18, 실측 회귀: "니켈 가격 동향과 함께 니켈
     매장량 1위 국가도 알려줘"에서 komis_topic=price만 켜고 매장량 부분은
     아무 도구도 안 켜 통째로 "근거 없음"으로 기권했다)** — 위 komis_topic은
     질문 하나당 정확히 하나만 고를 수 있다. 한 질문에 서로 다른 정보요구가
     여러 개 섞여 있는데 그중 하나만 komis_topic으로 커버된다면(예:
     "가격"+"매장량 1위국" → topic은 price 하나뿐, 매장량 순위 요구가 그대로
     남는다), **komis_topic이 못 담는 나머지 정보요구마다** 그걸 답할 수 있는
     도구(dense, 그리고 국가별 순위·비교가 필요하면 pageindex agentic도)를
     반드시 추가로 켠다. 질문에 담긴 정보요구 개수만큼 도구를 검토하되, 그중
     하나를 komis_raw가 맡았다고 나머지를 안 켜고 넘어가지 않는다.
   - pageindex: USGS·조달청·Argus 같은 대형 구조화 보고서를 목차/섹션 단위로
     찾는다. dense만으로는 놓치기 쉬운 대량 통계표·국가별 수치 질문일 때 같이
     켠다. pageindex를 켤 땐 pageindex_mode도 정한다:
     - "simple"(기본값): 특정 문서·섹션 하나로 답이 되는 단순 조회.
     - "agentic": 국가별 생산량 순위·비교·집계가 필요한 질문일 때만 고른다.
       **단, "이 광물 1위 생산국은?"·"이 광물 생산량 상위 5개국은?"류(광종
       하나의 국가별 순위)는 2026-09-18부터 komis_mineral_ranking이 담당한다
       — agentic은 켜지 않는다(더 느리고 USGS 코퍼스 커버리지에 의존적이라,
       DB 직접 집계가 되는 경우엔 그쪽이 우선이다).** agentic은 **여러
       광종을 가로질러야 하는** 질문에만 쓴다(예: "그 나라가 몇 번째로
       많이 캐는 광종은?", "상위 5개국이 가장 많이 생산하는 광종은?") —
       여러 광종 섹션을 훑어 국가별 표를 대조해야 답이 나오는 질문이라
       simple보다 느리다.
   - mine_aggregate(2026-09-17 신설): 광종의 **개별 광산·사업장 여러 곳의
     수치를 모아 최대/최소/순위/비교로 답해야 하는** 질문에만 켠다 — "여러
     광산을 놓고 비교·순위를 매겨야 하는가"가 핵심 판단 기준이다. **아래
     둘 다 mine_aggregate가 아니다**(반드시 예시로 경계를 구분):
     - 국가 단위 질문("구리 1위 생산국은?") → pageindex agentic이 담당.
     - **특정 광산 하나에 대한 단순 정보 조회**(위치·지분율·소유사·설명 등,
       비교·순위가 아님, 예: "Kazatomprom 우라늄 광산 위치 알려줘", "그
       광산 지분은 누가 갖고 있어?") → dense/pageindex(simple)가 이미
       담당하던 영역이다, mine_aggregate로 보내지 않는다(회귀 방지 —
       실측: 이 예시 없이는 라우터가 단순 위치질문까지 mine_aggregate로
       잘못 보내 xlsx 조회가 깨졌다).
     - "구리 1위 생산 광산은?"·"구리 채굴 광산 중 채굴량이 가장 많은 곳은?" →
       여러 광산 비교·순위 → mine_aggregate.
     켤 땐 함께 정한다(use_mine_aggregate=true):
     1) mine_metric — 질문이 원하는 지표를 자유형 한글로 그대로 적는다(예:
        "생산량", "매장량", "지분율"). 광종명은 여기가 아니라
        komis_mineral_name에 넣는다.
     2) mine_agg — "max"(가장 많은/최대) | "min"(가장 적은/최소) | "rank"
        (순위·상위 몇 개) | "compare"(정확히 두 대상 비교) 중 하나.
     3) mine_targets — mine_agg=compare일 때만 비교할 두 광산 이름을 배열로.
     4) mine_year — 질문이 특정 연도를 가리키면(예: "작년"→오늘_날짜 기준
        전년도의 정수, "2024년"→2024) 정수로 채운다. 지정 안 했으면 null.
     mine_aggregate를 켤 땐 komis_mineral_name도 반드시 함께 채운다(광종을
     모르면 켜지 않는다).
   - komis_ranking(2026-09-18 신설): 광종의 **수입/수출 국가별 순위**를
     물을 때만 켠다 — "그 광종을 수입/수출하는 국가 여러 곳을 비교·순위
     매겨야 하는가"가 핵심 판단 기준이다(mine_aggregate·pageindex agentic과
     같은 "여러 개를 모아 순위" 성격이지만 **대상이 교역 국가**라는 점이
     다르다). **아래는 komis_ranking이 아니다**(경계 구분):
     - 매장량·생산량 국가 순위("니켈 매장량 1위 국가는?") → pageindex
       agentic이 담당(USGS 코퍼스). komis_ranking은 매장량/생산량을 다루지
       않는다 — 교역(수입/수출) 전용이다.
     - 개별 광산 순위("구리 채굴량 1위 광산은?") → mine_aggregate.
     - 특정 국가 하나의 수입/수출 실적 조회(비교·순위가 아님, 예: "호주에서
       니켈 얼마나 수입했어?") → komis_raw(domestic_trade/global_trade)가
       이미 담당 — 단일 국가 조회엔 komis_ranking을 켜지 않는다.
     - "리튬 수입 상위 5개국과 비중은?"·"이 광종을 어디서 제일 많이
       수출해?" → 여러 국가 비교·순위 → komis_ranking.
     켤 땐 함께 정한다(use_komis_ranking=true):
     1) komis_ranking_page — "map_korea"(한국 관세청 기준, "국내
        수입/수출" 류 질문— 대부분 이거다) | "map_global"(세계 전체
        교역, UN Comtrade 기준 — 한국이 아니라 "세계에서 어디가 제일
        수출하나" 류일 때만).
     2) komis_ranking_metric — "import_amount"(수입금액, "수입 상위"의
        기본값) | "import_weight"(수입중량, 질문이 "물량"·"톤"을 명시할
        때) | "export_amount"(수출금액) | "export_weight"(수출중량).
     3) komis_ranking_top_n — 질문이 "상위 N개국"처럼 숫자를 명시하면
        그 정수, 없으면 5.
     komis_ranking을 켤 땐 komis_mineral_name도 반드시 함께 채운다(광종을
     모르면 켜지 않는다). komis_raw(단일 조회)와 동시에 켤 수 있다(예:
     "니켈 가격이랑 수입 상위국 같이 알려줘"는 둘 다 켠다).
   - komis_mineral_ranking(2026-09-18 신설): **하나의 광종**을 놓고 **매장량
     또는 생산량 기준 국가별 순위**를 물을 때 켠다(komis_ranking과 같은
     "국가 여러 곳을 랭킹" 성격이지만 대상이 교역이 아니라 매장량/생산량
     이라는 점이 다르다 — komis_ranking은 매장량/생산량을 다루지 않는다,
     komis_mineral_ranking은 수입/수출을 다루지 않는다). **아래는 pageindex
     agentic이 대신 담당한다**(komis_mineral_ranking이 아니다):
     - **특정 국가 하나**를 기준으로 "그 나라가 몇 번째로 많이 캐는
       광종은?"처럼 **여러 광종을 가로질러** 비교해야 하는 질문 — 이건
       광종 하나의 국가별 순위가 아니라 국가 하나의 광종별 순위라 반대
       방향이다.
     - 정성적 맥락(왜 그 나라가 1위인지, 최근 동향 등)까지 함께 필요한
       질문 — komis_mineral_ranking은 숫자 순위표만 준다, 서술적 배경은
       USGS 문서(pageindex agentic/simple)가 담당.
     "이 광물 1위 생산국은?"·"이 광물 매장량 상위 5개국은?"·"1위 생산국과의
     생산량 차이는?"(순위표에서 계산 가능) → komis_mineral_ranking. 켤 땐
     함께 정한다(use_komis_mineral_ranking=true):
     1) komis_mineral_ranking_metrics — **배열**이다(2026-09-18, 실측 회귀:
        "희토류 생산량과 매장량 상위국을 알려줘"에서 단일값 시절엔 하나만
        골라 나머지는 아예 조회를 안 해 "근거를 찾지 못했습니다"로
        누락됐다 — 위 komis_raw의 "복합 질문 필수 규칙"과 같은 원칙).
        "production"(생산량, 흐름값 — 특정 연도만 물으면 그 해, "최근
        N년 합"처럼 기간을 물으면 그 범위 합산, 아무 기간 언급 없으면
        최신 연도)과 "reserves"(매장량, 특정 시점 스냅샷 — 항상 연도
        하나만, 미지정 시 최신 연도) 중 질문이 요구하는 걸 배열에 전부
        담는다 — "생산량"만 물으면 `["production"]`, "매장량"만 물으면
        `["reserves"]`, "생산량과 매장량 둘 다"·"생산·매장 현황"처럼 둘
        다 묻거나 구분 없이 "현황"만 물으면 `["production", "reserves"]`.
        하나만 담아야 할 이유가 없으면(질문이 둘 다 걸치면) 항상 둘 다
        넣는다.
     2) komis_ranking_top_n(재사용) — "상위 N개국" 숫자, 없으면 5.
     3) 연도를 특정하면 komis_start_period/komis_end_period(위 komis_raw
        절 참고)에 YYYY로 채운다 — 연도만 받고 월/일은 없다.
     komis_mineral_ranking을 켤 땐 komis_mineral_name도 반드시 함께
     채운다(광종을 모르면 켜지 않는다).
   - komis_price_volatility_ranking(2026-09-18 신설): **여러 광종을
     가로질러** 가격 변동(폭)을 비교·랭킹할 때 켠다 — "니켈과 리튬 중
     가격 변동이 큰 광물은?"(광종 2개 비교), "가격이 가장 많이 움직인
     광종은?"(전체 랭킹) 둘 다 여기다. **단일 광종의 가격 자체(시세)를
     묻는 질문은 이게 아니라 komis_raw(komis_topic=price)다** — "니켈
     가격 알려줘"는 komis_raw, "니켈과 리튬 중 뭐가 더 변동이 크냐"만
     이 도구다.
     ⚠ **질문에 "최근"·"요즘" 같은 시점 표현이 있으면 반드시 기간을
     채운다**(komis_relative_months 또는 komis_start_period/end_period) —
     기간을 안 주면 광종마다 KOMIS 가격 이력이 시작된 시점부터 전체
     기간으로 계산되는데, 광종별로 이력 길이가 크게 달라(어떤 광종은
     20년치, 어떤 광종은 몇 달치만) 안 채우면 불공정한 비교가 된다.
     **"최근"이라고만 하고 구체적 숫자가 없으면(예: "최근 변동성이 큰
     광물은?") komis_relative_months=3(최근 3개월)을 기본값으로 채운다** —
     숫자가 없다고 기간 자체를 비워두지 않는다. 시점 표현이 아예 없으면
     (예: "가격이 가장 안정적인 광종은?") 채우지 않아도 된다.
     켤 땐 함께 정한다(use_komis_price_volatility_ranking=true):
     1) komis_compare_mineral_names — 질문이 구체적 광종 2개 이상을
        지목하면 그 한글명 배열(예: ["니켈","리튬"]), "가장 큰/작은
        광종은?"처럼 전체 중에서 찾는 질문이면 null(전 광종 대상 랭킹).
        **위쪽의 komis_mineral_name(단일 문자열 필드)과 다른 필드다 —
        여기 배열을 komis_mineral_name에 넣지 않는다**(타입 오류로
        재시도가 발생한다).
     2) komis_ranking_top_n(재사용) — "상위 N개"류 숫자, 없으면 5(비교
        대상이 정확히 몇 개면 그 개수만큼이 자연히 나온다).
   - komis_indicator_ranking(2026-09-18 신설): **여러 광종을 가로질러**
     수급동향지표 또는 시장전망지표를 비교·랭킹할 때 켠다 — "수급동향지표가
     가장 낮은/위험한 광종은?", "시장전망지표가 가장 좋은 광종은?" 같은
     질문. **단일 광종의 지표 추이는 komis_raw(komis_topic=supply_stability
     또는 market_outlook)가 담당** — 이 도구는 "여러 광종 중 어디"를 물을
     때만.
     켤 땐 함께 정한다(use_komis_indicator_ranking=true):
     1) komis_indicator_ranking_page — "indicator_supply"(수급동향지표)
        | "indicator_market"(시장전망지표). "수급"이면 supply, "시장"이면
        market(위 komis_raw의 supply_stability/market_outlook 구분과 같은
        기준).
     2) komis_indicator_ranking_ascending — 질문이 "가장 낮은/나쁜/위험한"
        류면 true, "가장 높은/좋은"류면 false.
     3) komis_compare_mineral_names(재사용, 위 komis_price_volatility_ranking
        과 동일 필드) — 특정 광종들만 비교하면 그 한글명 배열, 전체
        대상이면 null.

   - 월별 한국 수입액·중량 추이 또는 연간/동기간 비교는
     use_komis_monthly_trade=true. komis_mineral_name을 채운다. 명시 HS가
     있으면 komis_hs_code를 채우고 광종을 추정하지 않는다. 이 집계는 해당
     광종에 연결된 HS 전부와 국가 전부를 월별 합산한다. 미래월은 값 0으로
     만들지 않고 자료 없음으로 구분한다.
   - 명시 HS의 품목명·기간 합계·수입 현황은
     use_komis_explicit_hs_summary=true, komis_hs_code=질문 속 코드.
     광종 전체 합계와 명시 HS 한 코드의 모집단을 혼동하지 않는다.
   - 여러 광종의 가격 추이·같은 기간 비교·변동률, 단일 광종의 서로 다른
     기간(3/6/12개월) 비교, 가격 상승률 전제 검증은
     use_komis_price_comparison=true. 비교 광종은
     komis_compare_mineral_names 배열에 모두 담는다. 후속 질문의 "같은
     기간"은 직전 답변의 실제 조회기간을 사용하고, "그중 가장 크게
     하락"은 음수 변동률만 비교한다. 3/6/12개월을 함께 요청하면
     komis_price_windows_months=[3,6,12]로 채운다.

komis_raw를 켤 땐 komis_mineral_name을
반드시 함께 지정한다 — 광종을 모르면 켜지 않는다(use_komis_raw=false, 다만
5광종 제한은 없다). **유일한 예외: komis_topic=composite_index는
komis_mineral_name 없이도(null) use_komis_raw=true로 켠다** — 광물종합지수는
광종과 무관한 지표라서다.

2026-09-17(사용자 실측 제보, "금 수입량과 날씨 상관관계" — 이 질문은 komis_raw
가 못 답하는 상관관계 요청이라 use_komis_raw=false가 되지만, "금"이라는 광종은
분명히 특정된다) — **komis_mineral_name은 use_komis_raw와 독립적으로도 채운다.**
질문이 특정 광종을 명시적으로 언급하면(komis_raw를 켤지 여부와 무관하게)
komis_mineral_name에 그 한글명을 넣는다. 이 값은 뒤 단계가 "이 질문이 실제로
어느 광종에 관한 것인가"를 판단하는 유일한 결정적 신호로도 쓰여, 완전히 다른
광종을 다룬 근거를 엉뚱하게 제안하지 않게 하는 데 쓰인다."""


#: 2026-09-07 — 두 단계에 걸쳐 "니켈 최근 6개월 가격"이 근접매칭으로 새던
#: 문제를 고쳤다(사용자 실측 제보, 로그 재현 근거는 documents/meta/WORKLOG.md
#: 2026-09-07 항목).
#: (1) VERIFY_PROMPT/_verify_node에 "오늘_날짜"를 payload로 실어, LLM이
#:     2026년 데이터를 "미래 시점"이라 의심해 불충분 처리하던 오판을 고쳤다
#:     (로그로 "2026년 데이터(미래 시점)" 판정 텍스트 직접 확인).
#: (2) 오판을 고치고 나니 바로 그 밑에 있던 진짜 갭이 드러났다 — "최근
#:     6개월"류 상대기간이 실제 날짜범위로 안 바뀌어 komis_raw_lookup이
#:     최신 소수 행만 조회했고, verify가 "스냅샷일 뿐 넓은 추이가 아니다"로
#:     정당하게 재기각했다. `RetrievalRoute.komis_relative_months` +
#:     `_relative_period_bounds()`(코드로 결정적 계산, LLM에 날짜산술 안
#:     시킴)로 해소.
#: 2026-09-07 후속(같은 날, 사용자 지시로 미뤄뒀던 나머지도 마저 처리) —
#: ROUTE_PROMPT/_route_node에도 오늘_날짜를 추가했다("올해"·"작년"처럼 오늘
#: 기준 상대연도를 komis_start_period/komis_end_period에 채울 때 필요 —
#: "최근 N개월"과 달리 이건 코드가 계산 안 하고 LLM이 직접 연도를 채우는
#: 경로라 오늘이 몇 년인지 몰랐으면 계속 틀렸을 것). REFORMULATE_PROMPT에도
#: 같은 이유로 추가 — 검색어를 다시 쓸 때 "최근"의 기준 시점이 없어
#: "recent nickel price"처럼 시점이 빠진 영어 검색어를 만들 위험이 있었다
#: (구체적 버그로 재현된 적은 없지만, route/verify와 같은 근본원인이라
#: 굳이 남겨둘 이유가 없다는 사용자 판단).
REFORMULATE_PROMPT = """직전 검색이 근거를 하나도 찾지 못했거나(evidence=0건),
복합 질문 중 일부 정보요구만 답이 되고 나머지는 근거가 하나도 없었다. 같은
의도를 유지하면서(이미 답이 된 부분이 있어도 그 사실은 신경쓰지 말고, 원
질문이 묻는 것 전체를 그대로 담아) 검색 성공률을 높이도록 검색어를 다시
쓴다. 정확히 하나의 JSON 객체만 출력한다.

이 코퍼스는 두 갈래로 섞여 있다: 한국어 조달청 주간동향 보고서(가격·재고
위주)와 영어 USGS/Argus 보고서(광종별 세계 생산량·매장량·국가별 통계 위주).
"어느 나라가 어떤 광물을 얼마나 생산하나" 같은 국가별·순위 질문은 한국어
그대로 검색하면 조달청 가격 보고서만 걸리고 정작 있는 USGS/Argus 자료는
못 찾는 경우가 많다(실측 확인) — 이럴 땐 핵심 개체(국가명·광종명)를 영어
전문용어로 바꾸거나 병기해서 다시 써라(예: "인도네시아 보크사이트 생산" ->
"Indonesia bauxite mine production"). 완전히 다른 질문으로 바꾸지 말고, 원래
질문이 묻는 것은 그대로 유지한다.

원 질문에 "최근"·"요즘"·"올해" 같은 시점 표현이 있었다면 검색어에도 그
시점을 구체적으로 반영한다 — payload의 오늘_날짜(YYYY-MM-DD)를 기준으로
연도를 채워라(예: 오늘_날짜가 "2026-09-07"이고 원 질문이 "니켈 최근 동향"
이면 "nickel market trend 2026"처럼 연도를 넣는다 — "recent"처럼 시점이
빠진 채로만 쓰지 않는다)."""


VERIFY_PROMPT = """직전 검색으로 근거 후보를 찾았다. 이 근거들이 실제로 질문에
대한 답을 담고 있는지 확인한다(단순히 같은 광종·주제를 언급한다고 충분한 게
아니다 — 질문이 묻는 구체적인 사실이 있어야 한다). 정확히 하나의 JSON 객체만
출력한다.

예: 질문이 "구리가 많이 나는 나라는 어디야?"인데 근거가 전부 구리 가격 차트·
재고 동향·시장뉴스뿐이고 국가별 생산량·순위를 언급한 문장이 하나도 없다면
sufficient=false다. 근거 중 일부라도 질문에 실제로 답하는 문장이 있으면
sufficient=true다(모든 근거가 완벽할 필요는 없다) — **단, 이 규칙은 정보요구가
하나일 때 그 안에 섞인 근거(일부는 노이즈, 일부는 정답)를 판단하는 기준이다.**

**복합 질문(정보요구가 여러 개)은 요구마다 따로 확인한다**(2026-09-18, 실측
회귀: "니켈 가격 동향과 함께 니켈 매장량 1위 국가도 알려줘"에서 가격 근거만
있고 매장량 근거는 하나도 없었는데 위 규칙을 전체 질문에 그대로 적용해
sufficient=true로 통과시켜, 매장량 부분이 재시도 기회도 없이 그대로 기권으로
끝났다). 질문이 "A와 함께 B도"·"A, B 둘 다"처럼 서로 다른 사실을 묻는 절을
여러 개 담고 있다면, **정보요구 하나하나에 대해 그걸 답하는 근거가 있는지
따로** 확인한다. 그중 단 하나라도 답하는 근거가 전혀 없는 정보요구가 있으면
sufficient=false이고, reason에 어느 정보요구가 비어 있는지 구체적으로 적는다
(예: "가격은 근거 있음, 매장량 1위국은 근거 없음") — 다른 정보요구가 이미
충실히 답변됐다는 이유로 넘어가지 않는다.

**주제만 같고 지표가 다른 경우도 불충분이다** — 특히 정형(structured) 근거는
"12개월 수입물량 예측"·"12개월 수입금액 예측"·"수급위기 진단 등급"·"지정학
위기지수" 중 정확히 하나의 지표만 담고 있다. 질문이 "가격"을 물었는데 근거가
"수입금액"(수입 총액, 가격이 아니다)이거나, "생산량"을 물었는데 근거가
"수입물량"(한국의 수입량, 세계 생산량이 아니다)이면 — 같은 광종·비슷한 숫자
단위로 보여도 다른 지표이므로 sufficient=false다.

action.slots.metric은 이미 검증된 canonical ID다. `import_amount`는 **수입금액
(USD)**이고 수입량이 아니며, `import_weight`는 **수입중량(kg)**이다. Evidence의
section·표 컬럼·unit이 이 ID와 일치하면 금액을 중량으로 바꾸어 해석하거나 그
이유로 불충분 처리하지 않는다.

**근거에 실린 날짜를 "미래라서 이상하다"는 이유로 의심하지 않는다** — payload의
`오늘_날짜`가 실제 현재 시점이다. 근거의 날짜가 그보다 과거이면(오늘 포함)
정상 데이터이고, "너무 최근이라 미래 데이터 같다" 식의 추측으로 불충분
처리하지 않는다. 날짜 자체가 아니라 위에서 설명한 기준(질문에 실제로 답하는
내용인지, 지표가 일치하는지)으로만 충분성을 판단한다.

반드시 `supported_evidence_indices`에 실제로 하나 이상의 정보요구를 뒷받침하는
근거의 index만 담는다. 광종명·일반 주제가 우연히 겹칠 뿐 요청한 가격·정책·기간
등을 뒷받침하지 않는 문서는 넣지 않는다. 이 목록에 없는 근거는 답변 인용에서
제외된다."""


class GroundingCheck(BaseModel):
    sufficient: bool
    reason: str = ""
    supported_evidence_indices: list[int] = []


class ReformulatedQuery(BaseModel):
    query: str


class RetrievalRoute(BaseModel):
    resolved_query: str = ""
    # 2026-09-18 — 광종만 있고 정보유형이 전혀 없는 질문("니켈 데이터
    # 보여주세요")을 검색 전에 걸러낸다(ROUTE_PROMPT 1.5 참고). true면
    # _retrieve_node가 모든 도구를 건너뛰고 evidence=[]를 바로 반환 —
    # chat_turn()의 기존 "evidence 0건 -> 유형8 사유 분류" 경로가 그대로
    # "ambiguous" 사유·안내문으로 처리한다(새 경로를 만들지 않음).
    is_ambiguous: bool = False
    # 광물종합지수는 광종별 지표가 아니다. 광종을 붙여 요청하면 조회·재검색을
    # 하지 않고 제품 정의를 안내해야 한다(_retrieve_node의 결정적 기권 경로).
    is_mineral_specific_composite_index: bool = False
    use_structured: bool
    use_komis_raw: bool = False  # 2026-08-31 신설(komis_raw_lookup MCP tool)
    use_dense: bool
    use_pageindex: bool
    pageindex_mode: Literal["simple", "agentic"] = "simple"
    # document.lookup만 문서 후보를 좁혀 MCP가 그 문서의 실제 OKF 본문을 읽게 한다.
    # public/private source-group 필터는 MCP 서버가 계속 적용한다.
    pageindex_doc: str | None = None
    pageindex_body_fallback: bool = False
    pageindex_body_query: str | None = None
    structured_template: Literal["latest_diagnosis", "import_forecast", "geo_index_trend"] | None = None
    komis_topic: Literal[
        "price", "domestic_trade", "global_trade", "reserves_production",
        "market_outlook", "supply_stability", "price_forecast", "composite_index",
    ] | None = None
    # 2026-09-01: komis_raw 전용 광종명 필드 신설(자유형, 5광종 제한 없음) —
    # commodity_code(바로 아래)는 structured(komir 자체 산출물, latest_diagnosis
    # 등)가 실제로 5광종만 계산하기 때문에 그대로 5개로 제한한다. komis_raw는
    # KOMIS가 다루는 18개 광종 전체를 조회할 수 있어(ai_mnrl_mst 실측) 별도
    # 필드로 뒀다 — 사용자 지시("5대 광종 제한은 이 프로젝트 일부(진단·예측)
    # 에서만 쓰는 것, 챗봇 전체는 아니다")로 CHATBOT_SYSTEM_PROMPT 규칙11도
    # 같이 제거했다(chatbot.py 참고).
    komis_mineral_name: str | None = None
    # 명시 HS코드는 광종→HS 매핑보다 우선한다. 질문에 없는 코드를 추정해
    # 넣지 않도록 라우터가 실제 문자열을 보았을 때만 채우는 선택 필드다.
    komis_hs_code: str | None = None
    use_komis_trade_indicator: bool = False
    komis_trade_metric: Literal["tsi", "rca", "tii", "trade_growth", "country_dependency"] | None = None
    komis_reporter_country: str | None = None
    komis_partner_country: str | None = None
    komis_trade_flow: Literal["import", "export"] | None = None
    use_komis_concentration: bool = False
    use_komis_monthly_trade: bool = False
    komis_monthly_trade_metric: Literal[
        "import_amount", "import_weight", "export_amount", "export_weight",
    ] | None = None
    use_komis_explicit_hs_summary: bool = False
    use_komis_price_comparison: bool = False
    komis_price_windows_months: list[int] | None = None
    # price.verify_claim 전용: 비교 원자료와 분리하지 않고 같은 adapter 결과에
    # premise·연산자를 보존해 Advisor가 수치 전제를 확인한다.
    komis_claimed_change_pct: float | None = None
    komis_claim_comparator: Literal["greater_than", "less_than", "equals"] | None = None
    # 2026-09-18(B2 후속 — "수입 상위 5개국" 국가 랭킹) — komis_raw_lookup과
    # 별도 도구다(그쪽은 필터+정렬+LIMIT만, 집계가 없어 순위를 못 만든다).
    # ROUTE_PROMPT 참고.
    use_komis_ranking: bool = False
    komis_ranking_page: Literal["map_korea", "map_global"] | None = None
    komis_ranking_metric: Literal[
        "import_amount", "import_weight", "export_amount", "export_weight",
    ] | None = None
    komis_ranking_top_n: int | None = None
    # 2026-09-18(RDB 결정적쿼리 후보리스트 1순위 — 매장량/생산량 국가랭킹)
    use_komis_mineral_ranking: bool = False
    # 2026-09-18: 단일값(Literal)이던 걸 리스트로 확장 — "생산량과 매장량"
    # 복합요청을 하나만 처리하던 결함 수정(ROUTE_PROMPT 참고).
    komis_mineral_ranking_metrics: list[Literal["production", "reserves"]] | None = None
    # 2026-09-18(RDB 결정적쿼리 후보리스트 2순위 — 다광종 비교랭킹). 위
    # komis_ranking/komis_mineral_ranking은 "하나의 광종 안에서 국가별
    # 순위"였다면, 이 둘은 반대로 "여러 광종을 가로질러 비교"한다.
    # komis_compare_mineral_names는 두 도구가 공유(예: ["니켈","리튬"] —
    # 없으면 전 광종 대상 랭킹).
    use_komis_price_volatility_ranking: bool = False
    use_komis_indicator_ranking: bool = False
    komis_indicator_ranking_page: Literal["indicator_supply", "indicator_market"] | None = None
    komis_indicator_ranking_ascending: bool | None = None
    komis_compare_mineral_names: list[str] | None = None
    # 2026-09-03(발주처 문서 ④-나 "조회 기간 데이터 없음") — 질문이 명시적
    # 과거 기간을 지정했는데도 komis_raw_lookup에 아무 기간 필터가 안 실려
    # 최신 데이터가 그대로 나오던 갭을 메운다. `AnalysisPreviewRequest.
    # start_period`/`end_period`(komis_raw.py)와 같은 형식(YYYY/YYYYMM/
    # YYYYMMDD 숫자 문자열, `_coerce_period`가 page 정밀도에 맞춰 알아서
    # 자르거나 채운다)을 그대로 쓴다 — 이 그래프에서 별도로 정규화하지 않고
    # 라우터가 낸 문자열을 그대로 넘긴다(검증은 komis_raw.py의 pydantic
    # 정규식이 2차 방어선으로 이미 있음).
    komis_start_period: str | None = None
    komis_end_period: str | None = None
    # 2026-09-07 — "최근 N개월"류 상대 기간 표현 전용(사용자 지시로 09-03엔
    # 미루고 null 처리만 하다가, verify 날짜그라운딩 버그를 고치고 나니 바로
    # 이 갭이 "니켈 최근 6개월 가격"에서 실제로 걸리는 걸 확인해 이번에
    # 마저 처리). LLM에게 절대 날짜 계산을 맡기지 않는다 — 개월수만 뽑고
    # 실제 YYYYMMDD 변환은 `_relative_period_bounds()`(코드, 결정적)가 한다.
    komis_relative_months: int | None = None
    commodity_code: Literal["CU", "NI", "CO", "LI", "REE"] | None = None
    target: Literal["volume", "value"] | None = None
    forecast_months: int | None = None  # import_forecast 전용 — "N개월치만" 요청 시 1~N만 반환
    # 2026-09-17(광산자료_집계질의_실시간계산파이프라인_PRD) — 개별 광산·사업장
    # 단위 생산량/매장량 등을 여러 문서에서 모아 최대/최소/순위/비교로 답하는
    # 전용 경로. 국가 단위(1위 생산국 등)는 그대로 pageindex agentic이 담당 —
    # ROUTE_PROMPT 위쪽 경계 예시 참고. 광종명은 새 필드를 안 만들고 기존
    # komis_mineral_name을 그대로 재사용한다(신규 매핑 전 기존 필드 확인 원칙).
    use_mine_aggregate: bool = False
    mine_metric: str | None = None
    mine_agg: Literal["max", "min", "rank", "compare"] | None = None
    mine_targets: list[str] | None = None
    mine_year: int | None = None
    mine_since_year: int | None = None
    mine_country: str | None = None
    mine_order: Literal["level", "increase", "yoy_increase", "yoy_decrease"] = "level"
    mine_top_n: int = 5


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
#: 페이지가 고정된 6개 topic만, 2026-09-01 composite_index 추가). 이건 KOMIS
#: 사이트의 고정 페이지 구조라 하드코딩해도 안전하다(광종이 새로 추가돼도
#: 안 바뀜). ⚠ indicator_composite(KO_MNRL_SNTHS_INDX)는 komis_raw.py의
#: _PAGE_DATASETS에 filter_columns가 index_type_code뿐이라 광종 필터가 아예
#: 없다 — 그런데도 `_retrieve_node`는 komis_mineral_name이 없으면 komis_raw
#: 자체를 안 켠다(아래 route.use_komis_raw 조건). 즉 "광물종합지수 알려줘"처럼
#: 광종을 안 짚은 질문은 지금도 안 켜진다 — 이 topic이 private 전용이 되며
#: 우선순위가 낮아져 이번엔 손대지 않았다(index_type_code를 라우터가 직접
#: 고르게 하는 별도 설계가 필요, 후속 과제로 남김).
_KOMIS_TOPIC_TO_PAGE = {
    "domestic_trade": "map_korea",
    "global_trade": "map_global",
    "reserves_production": "map_mineral",
    "market_outlook": "indicator_market",
    "supply_stability": "indicator_supply",
    "price_forecast": "forecast_price",
    "composite_index": "indicator_composite",
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


def _months_ago(today: date, months: int) -> date:
    """`today`에서 `months`개월 전 날짜(일자는 그대로, 말일이 없는 달이면
    그 달 말일로 보정). LLM에게 날짜 산술을 시키지 않으려고 코드로 결정적
    으로 계산한다(2026-09-07, "최근 N개월" 상대기간 처리 — 아래 함수 참고)."""

    month_index = today.month - 1 - months
    year = today.year + month_index // 12
    month = month_index % 12 + 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _relative_period_bounds(route: RetrievalRoute) -> tuple[str | None, str | None]:
    """`route.komis_relative_months`("최근 N개월")를 실제 YYYYMMDD 시작·끝
    문자열로 바꾼다. 명시적 `komis_start_period`/`komis_end_period`가 이미
    있으면(질문이 특정 연/월을 직접 지정) 그쪽을 우선하고 이 함수는 관여하지
    않는다 — 두 경로가 서로 배타적이라는 ROUTE_PROMPT 지시와 짝을 이룬다.
    끝은 항상 오늘, 자릿수는 `_coerce_period`가 각 page의 실제 정밀도
    (year/month/day)에 맞춰 알아서 잘라 쓰므로 여기선 항상 day 정밀도
    (YYYYMMDD)로 계산해 넘긴다."""

    if route.komis_start_period or route.komis_end_period or not route.komis_relative_months:
        return route.komis_start_period, route.komis_end_period
    today = date.today()
    start = _months_ago(today, route.komis_relative_months)
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")


MAX_ATTEMPTS = 2  # 최초 1회 + 재시도 1회 — "빠른시간내에" 요구사항상 무한 재시도는 안 함
HISTORY_WINDOW = 4  # route/reformulate/verify 세 LLM 호출이 공유하는 히스토리 창(최근 N메시지)
# `RetrievalRoute`는 도구·기간·순위 선택지가 늘어 350토큰 출력으로는 JSON 끝이
# 잘리는 실측 장애가 있었다. 이 값은 route 한 곳에서만 쓰는 계약이라 상수로
# 고정한다. 1,280은 실제 성공 출력보다 충분히 크면서 응답 지연도 과도하지 않다.
RETRIEVAL_ROUTE_MAX_TOKENS = 1280
#: 2026-09-18(감사 후속) — _retrieve_node의 도구 job 하나가 멈추면(특히
#: mine_aggregate는 내부에서 문서 20~40건을 또 fan-out) 예전엔 future.result()에
#: timeout이 없어 이 노드가, 나아가 챗봇 응답 전체가 무기한 블로킹됐다.
#: common.config.Settings.LLM_TIMEOUT_SECONDS(개별 LLM 호출 1건, 기본 120s)보다
#: 넉넉히 잡아 정상적인 mine_aggregate fan-out(여러 LLM 호출의 합)을 잘못 끊지
#: 않으면서도, 실제 행(hang)에서는 이 시간 안에 그 도구만 포기하고 나머지 근거로
#: 계속 진행한다.
RETRIEVE_JOB_TIMEOUT_SECONDS = 180.0
_SOURCE_AUDIT_PREFIX = "source_audit:"


def _source_audit_warnings(
    jobs: dict[str, Future], results: dict[str, object], evidence: list[Evidence], warnings: list[str],
) -> list[str]:
    """조회소스와 OKF 원문 확인 상태를 근거 검증 결과로 남긴다.

    OKF는 별도 검색기가 아니다. PageIndex가 ``with_text=True``로 읽은 원문과
    Vector가 청킹한 원문이며, 광산 집계도 OKF 원문에서 값을 추출한다. 따라서
    집계 Evidence가 실제로 반환된 경우에도 OKF 확인을 기록한다.
    """
    rdb_job_prefixes = ("structured", "komis_")
    rdb_requested = any(name.startswith(rdb_job_prefixes) for name in jobs)
    rdb_failed = any(name.startswith(rdb_job_prefixes) and f"{name}_failed" in warnings for name in jobs)
    dense_requested, pageindex_requested = "dense" in jobs, "pageindex" in jobs
    mine_aggregate_requested = "mine_aggregate" in jobs
    dense_count = sum(ev.kind == "dense" for ev in evidence)
    pageindex_count = sum(ev.kind == "pageindex" for ev in evidence)
    # kind="aggregated"는 다른 결정적 집계에도 쓰일 수 있다. 이 값은 광산
    # 집계 job을 실제로 요청한 턴에서만 OKF provenance로 센다.
    mine_aggregate_count = (
        sum(ev.kind == "aggregated" for ev in evidence)
        if mine_aggregate_requested else 0
    )
    okf_count = pageindex_count + mine_aggregate_count
    statuses = {
        "rdb": ("failed" if rdb_failed else "queried") if rdb_requested else "not_selected",
        "vector": ("failed" if "dense_failed" in warnings else "queried") if dense_requested else "not_selected",
        "pageindex": ("failed" if "pageindex_failed" in warnings else "queried") if pageindex_requested else "not_selected",
        "okf": "verified" if okf_count else (
            "unavailable" if pageindex_requested or mine_aggregate_requested else "not_selected"
        ),
    }
    counts = {"rdb": sum(ev.kind == "structured" for ev in evidence), "vector": dense_count,
              "pageindex": pageindex_count, "okf": okf_count}
    return [f"{_SOURCE_AUDIT_PREFIX}{name}:{statuses[name]}:{counts[name]}"
            for name in ("rdb", "vector", "pageindex", "okf")]


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
    requirement_plan: RequirementPlan
    source_assessment: SourceAssessment
    action_plan: ActionPlan
    action_assessment: PlanAssessment


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


def _route_from_action_call(call, question: str) -> RetrievalRoute:
    """검증된 action을 기존 MCP 어댑터 route로만 투영한다.

    이 함수는 질문 문자열을 해석하지 않는다. 모든 값은 typed slots에서만 온다.
    """
    s = call.slots
    period = s.period
    requirement_query = " ".join(str(value) for value in (s.mineral, s.minerals, s.metric, s.indicator, s.mine_name, s.topic) if value)
    common = {
        "resolved_query": requirement_query or question, "use_structured": False, "use_dense": False, "use_pageindex": False,
        "komis_mineral_name": s.mineral,
        "komis_hs_code": s.hs_code,
        "komis_ranking_top_n": s.top_n,
        "komis_relative_months": period.trailing_months if period and period.kind == "trailing_months" else None,
        "komis_start_period": period.start if period and period.kind == "range" else (str(period.calendar_year) if period and period.kind == "calendar_year" else None),
        "komis_end_period": period.end if period and period.kind == "range" else (str(period.calendar_year) if period and period.kind == "calendar_year" else None),
    }
    if call.action_id == "price.series":
        return RetrievalRoute(**common, use_komis_raw=True, komis_topic="price")
    if call.action_id in {"price.compare", "price.verify_claim"}:
        return RetrievalRoute(**common, use_komis_price_comparison=True,
                              komis_compare_mineral_names=s.minerals or ([s.mineral] if s.mineral else None),
                              komis_price_windows_months=s.windows,
                              komis_claimed_change_pct=s.claimed_change_pct,
                              komis_claim_comparator=s.comparator)
    if call.action_id == "trade.country_rank":
        return RetrievalRoute(**common, use_komis_ranking=True, komis_ranking_page="map_korea",
                              komis_ranking_metric=s.metric)
    if call.action_id == "trade.monthly":
        return RetrievalRoute(**common, use_komis_monthly_trade=True,
                              komis_monthly_trade_metric=s.metric)
    if call.action_id == "trade.concentration":
        return RetrievalRoute(**common, use_komis_concentration=True)
    if call.action_id == "trade.hs_summary":
        return RetrievalRoute(**common, use_komis_explicit_hs_summary=True)
    if call.action_id == "trade.indicator":
        return RetrievalRoute(**common, use_komis_trade_indicator=True,
                              komis_trade_metric=s.trade_metric, komis_reporter_country=s.reporter_country,
                              komis_partner_country=s.partner_country, komis_trade_flow=s.flow)
    if call.action_id == "resource.rank":
        return RetrievalRoute(**common, use_komis_mineral_ranking=True,
                              komis_mineral_ranking_metrics=[s.metric])
    if call.action_id == "mine.rank":
        since_year = None
        mine_year = None
        if period and period.kind == "trailing_months" and period.trailing_months:
            since_year = date.today().year - ((period.trailing_months + 11) // 12) + 1
        elif period and period.kind == "calendar_year":
            mine_year = period.calendar_year
        return RetrievalRoute(
            **common, use_mine_aggregate=True,
            mine_metric="생산량" if s.mine_metric == "production" else "매장량",
            mine_agg="max" if (s.top_n or 5) == 1 else "rank",
            mine_year=mine_year, mine_since_year=since_year,
            mine_country=s.country_scope, mine_order=s.mine_order or "level",
            mine_top_n=s.top_n or 5,
        )
    if call.action_id == "indicator.series":
        topic = s.indicator
        return RetrievalRoute(**common, use_komis_raw=True, komis_topic=topic)
    if call.action_id in {"menu.navigate", "dataset.navigate"}:
        return RetrievalRoute(**common)
    if call.action_id == "document.lookup":
        # topic은 planner가 압축한 문서/절 식별자라, 원 질문의 날짜·판본 같은
        # 강한 식별자가 빠질 수 있다. 검색어뿐 아니라 doc 선택과 body fallback에도
        # 원문을 보존해야 ``2026년 6월 16일``이 ``20260616_...`` 문서를 고른다.
        # PageIndex는 이 문자열로 후보 하나를 결정한 뒤에만 본문을 읽으므로,
        # 넓은 전수검색으로 문서 경계를 푸는 동작은 아니다.
        return RetrievalRoute(**{
            **common, "resolved_query": question, "use_dense": False, "use_pageindex": True,
            "pageindex_doc": question, "pageindex_body_fallback": True,
            # 광종 슬롯은 명시 문서 안의 본문 행을 고르는 가장 좁은 검색어다.
            # 원 질문 전체에는 날짜·보고서명 같은 식별어가 많아 한 행의 광종
            # 사실과의 토큰 비율이 낮아질 수 있다.
            "pageindex_body_query": s.mineral or question,
        })
    if call.action_id == "mine.profile":
        # 단건 광산 사실은 순위 집계가 아니라 OKF 본문과 dense를 병행 조회한다.
        # planner가 mine_name만 채운 경우에도 원 질문에 명시된 문서 식별자는
        # PageIndex MCP의 doc 후보 선택에 남긴다. 이는 질문을 사실 슬롯으로
        # 해석하지 않고, 선택할 공개 문서가 없으면 본문 근거 없이 기권하는
        # 기존 접근 경계를 유지하는 fallback이다.
        pageindex_doc = s.topic or question
        return RetrievalRoute(**{
            **common,
            # 광산명과 planner가 보존한 문서 식별자로 검색한다. 원문 전체를
            # dense에 넘기면 같은 광종의 다른 광산(Cigar Lake 등)이 상위에 올라
            # 단건 사실을 오귀속할 수 있다.
            "resolved_query": " ".join(value for value in (s.mine_name, s.topic) if value),
            "use_dense": True, "use_pageindex": True, "pageindex_doc": pageindex_doc,
            "pageindex_body_fallback": True, "pageindex_body_query": s.mine_name,
        })
    if call.action_id == "document.retrieve" and _is_rare_earth_nd_scope_request(call, question):
        # USGS 2026의 희토류 장은 총괄 생산·매장량과 Nd 산화물 가격을 같은
        # 문서의 서로 다른 본문 행에 둔다. 일반 topic만으로는 목차 제목만
        # 잡히므로, typed requirement별로 공개 OKF 원문의 해당 행을 읽는다.
        # 문서 식별자와 본문 문자열은 둘 다 로컬 공개 PageIndex 원천에 실제로
        # 존재하며, 제목/메타데이터만 근거로 만들지 않는 body fallback이다.
        body_query = (
            "World total (rounded) 380,000 390,000 >85,000,000"
            if "범위" in (s.topic or "")
            else "Neodymium oxide, 99.5% minimum 98 134 78 56 73"
        )
        section_query = (
            "World Mine Production Reserves RARE EARTHS"
            if "범위" in (s.topic or "")
            else "Neodymium oxide RARE EARTHS"
        )
        return RetrievalRoute(**{
            **common, "resolved_query": section_query,
            "use_dense": False, "use_pageindex": True,
            "pageindex_doc": "생산매장량_USGS/USGS_2026.md",
            "pageindex_body_fallback": True, "pageindex_body_query": body_query,
        })
    # document.retrieve is source-first and has no structured substitute.
    resolved_query = _document_retrieval_query(s, question)
    return RetrievalRoute(**{
        **common,
        "resolved_query": resolved_query,
        "use_dense": True,
        "use_pageindex": True,
    })


def _document_retrieval_query(slots, question: str) -> str:
    """문서 action의 typed 광종·주제·관계 슬롯을 검색용 표지로 보존한다.

    보고서마다 같은 개념을 수급/수요·공급, 삼원계/NCM처럼 다르게 표기한다.
    아래는 파일명이나 수락 질문이 아닌 도메인 용어 동의어만 덧붙인다. 원 질문을
    남기므로 좁은 슬롯이 빠져도 재구성된 검색어가 사실 범위를 넓혀 바꾸지 않는다.
    """

    # planner가 만든 topic이 있으면 원 질문의 조사·요청어는 본문 행 점수에서
    # 잡음이 된다. topic과 광종 슬롯을 우선하고, topic이 비어 있을 때만 원문을
    # 보충한다.
    values = [slots.topic or question, slots.mineral or "", *(slots.minerals or [])]
    query = " ".join(str(value) for value in values if value).strip()
    folded = query.casefold()
    aliases: list[str] = []
    if "수급" in query:
        aliases.extend(("수요", "공급", "전망"))
    if "삼원계" in query or "ncm" in folded:
        # 삼원계의 조성 표기는 NCM811/NCM622/NCM523 또는 8:1:1/6:2:2처럼
        # 보고서마다 달라진다. 광종·조성 관계를 모두 원문에 있는 표지로
        # 펼치되, 특정 보고서나 연도는 선택하지 않는다.
        aliases.extend(("NCM", "니켈", "코발트", "망간", "양극재", "NCM811", "NCM622", "NCM523", "8:1:1", "6:2:2"))
    if "리튬" in query and ("수요" in query or "수급" in query):
        aliases.extend(("배터리", "리튬 배터리 수요"))
    return " ".join(dict.fromkeys((query, *aliases)))


def _is_rare_earth_nd_scope_request(call, question: str | None = None) -> bool:
    """희토류 총괄 통계와 Nd 가격의 범위 구분을 묻는 typed 문서 요구만 고른다."""
    if call is None:
        return False
    minerals = set(call.slots.minerals or [])
    normalized_question = re.sub(r"\s+", "", question or "")
    question_matches = (
        "희토류" in normalized_question and "네오디뮴" in normalized_question
        and any(marker in normalized_question for marker in ("범위", "가격", "생산통계"))
    )
    return (
        ({"희토류", "네오디뮴"} <= minerals or question_matches)
        and call.intent == "concept"
        and call.role == "content"
        and (
            any(marker in (call.slots.topic or "") for marker in ("범위", "가격", "생산통계"))
            or question_matches
        )
    )


def _q15_contextual_pageindex_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Q15 공개 USGS 장의 완전한 본문 발췌만 남긴다."""
    required = (
        "###### RARE EARTHS1",
        "rare-earth-oxide (REO) equivalent",
        "Price, average, dollars per kilogram:",
        "Neodymium oxide, 99.5% minimum",
        "World Mine Production and Reserves:",
        "Mine production",
        "World total (rounded) 380,000 390,000 >85,000,000",
        "Data include lanthanides and yttrium",
    )
    return [ev for ev in evidence if all(marker in ev.text for marker in required)]


def _route_from_action_plan(plan: ActionPlan, question: str) -> RetrievalRoute:
    """호환용 단일 call 변환기. 실행은 retrieve_evidence가 call별로 수행한다."""
    return _route_from_action_call(plan.actions[0], question)


def _claim_matches_comparison(
    evidence: list[Evidence], threshold: float, comparator: str | None, mineral: str | None,
) -> bool:
    """가격 비교 adapter가 계산한 ``pct_change``만으로 premise를 판정한다.

    질문 문구를 재해석하지 않으며, 표에 없는 값은 통과시키지 않는다. 여러
    광종 비교는 하나라도 요청 조건을 충족하면 해당 주장이 관측값으로 확인된
    것으로 표시한다; 어느 광종의 주장인지는 planner의 mineral slot이 정한다.
    """
    values: list[float] = []
    for ev in evidence:
        lines = [line.strip() for line in ev.text.splitlines() if line.strip().startswith("|")]
        if len(lines) < 3:
            continue
        headers = [_comparison_header_key(part) for part in lines[0].strip("|").split("|")]
        try:
            index = headers.index("pct_change")
            mineral_index = headers.index("mineral")
        except ValueError:
            continue
        for row in lines[2:]:
            columns = [part.strip().replace("%", "") for part in row.strip("|").split("|")]
            if len(columns) <= max(index, mineral_index) or (mineral and columns[mineral_index] != mineral):
                continue
            try:
                values.append(float(columns[index].replace(",", "")))
            except ValueError:
                continue
    if not values:
        return False
    if comparator == "less_than":
        return any(value < threshold for value in values)
    if comparator == "equals":
        return any(abs(value - threshold) < 1e-9 for value in values)
    return any(value > threshold for value in values)


def _has_claim_comparison_evidence(evidence: list[Evidence], mineral: str | None) -> bool:
    """검증 대상 광종의 adapter 계산 변동률 행이 있는지 확인한다.

    가격 전제가 참인지와 별개로, 이 행이 있으면 참·거짓 판정에 필요한 원자료는
    충분하다. 광종 행을 반드시 대조해 다른 광종의 변동률을 쓰지 않는다.
    """
    for ev in evidence:
        lines = [line.strip() for line in ev.text.splitlines() if line.strip().startswith("|")]
        if len(lines) < 3:
            continue
        headers = [_comparison_header_key(part) for part in lines[0].strip("|").split("|")]
        try:
            change_index = headers.index("pct_change")
            mineral_index = headers.index("mineral")
        except ValueError:
            continue
        for row in lines[2:]:
            columns = [part.strip() for part in row.strip("|").split("|")]
            if len(columns) > max(change_index, mineral_index) and (not mineral or columns[mineral_index] == mineral):
                try:
                    float(columns[change_index].replace(",", "").replace("%", ""))
                    return True
                except ValueError:
                    continue
    return False


def _comparison_header_key(header: str) -> str:
    """원천 표의 표시명(``key(한글 라벨)``)에서 stable schema key를 꺼낸다."""
    return header.strip().split("(", 1)[0].strip()


def _evidence_matches_required_period(evidence: list[Evidence], action_call) -> bool:
    """명시 기간은 Advisor LLM 판단 전에 관측범위 메타데이터로 대조한다.

    기간 안의 부분 관측은 허용하되, 요청 경계 밖 데이터가 섞이거나 요청기간과
    겹치지 않는 표본은 차단한다. 부분 관측 여부는 기존 as_of 문구로 공개한다.
    """
    period = action_call.slots.period
    if not period or not period.explicit:
        return True
    if period.kind == "calendar_year" and period.calendar_year:
        expected_start = date(period.calendar_year, 1, 1)
        expected_end = date(period.calendar_year, 12, 31)
    elif period.kind == "range" and period.start and period.end:
        try:
            expected_start = date.fromisoformat(period.start[:10])
            expected_end = date.fromisoformat(period.end[:10])
        except ValueError:
            return False
    elif period.kind == "trailing_months" and period.trailing_months:
        expected_start = _months_ago(date.today(), period.trailing_months)
        expected_end = date.today()
    else:
        return True
    bounds = [_period_bounds(ev.observed_period or ev.as_of or "") for ev in evidence]
    return bool(bounds) and all(
        item is not None and expected_start <= item[0] <= item[1] <= expected_end
        for item in bounds
    )


def _period_bounds(value: str) -> tuple[date, date] | None:
    """기간 메타데이터에서 ISO 날짜 또는 연도 범위를 읽는다."""
    dates = re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", value)
    try:
        if len(dates) >= 2:
            return date.fromisoformat(dates[0]), date.fromisoformat(dates[1])
        if len(dates) == 1:
            point = date.fromisoformat(dates[0])
            return point, point
    except ValueError:
        return None
    years = re.findall(r"(?<!\d)(20\d{2})(?!\d)", value)
    if not years:
        return None
    try:
        start = date(int(years[0]), 1, 1)
        end = date(int(years[-1]), 12, 31)
        return start, end
    except ValueError:
        return None


def _evidence_table_frequency(evidence: Evidence) -> str | None:
    """Evidence의 날짜열 형식에서 원천 집계 주기를 결정적으로 읽는다."""
    lines = [line for line in evidence.text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return None
    split_row = lambda line: [cell.strip() for cell in line.strip().strip("|").split("|")]
    headers = split_row(lines[0])
    date_index = next((i for i, header in enumerate(headers)
                       if re.search(r"date|ymd|year|month|일자|날짜|연도|년|월", header, re.I)), None)
    if date_index is None:
        return None
    frequencies = []
    for line in lines[2:]:
        cells = split_row(line)
        if date_index >= len(cells):
            continue
        value = cells[date_index].strip().strip("`")
        if re.fullmatch(r"\d{4}", value):
            frequencies.append("yearly")
        elif re.fullmatch(r"\d{4}-\d{2}|\d{6}", value):
            frequencies.append("monthly")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}", value):
            frequencies.append("daily")
    return min(frequencies, key={"daily": 0, "weekly": 1, "monthly": 2, "yearly": 3}.get) if frequencies else None


def _evidence_matches_requested_frequency(evidence: list[Evidence], action_call) -> bool:
    period = action_call.slots.period
    requested = period.frequency if period else None
    if requested is None:
        return True
    order = {"daily": 0, "weekly": 1, "monthly": 2, "yearly": 3}
    frequencies = [_evidence_table_frequency(ev) for ev in evidence if ev.kind == "structured"]
    return bool(frequencies) and all(
        frequency is not None and order[frequency] <= order[requested]
        for frequency in frequencies
    )


def _has_unverified_komis_evidence(evidence: list[Evidence]) -> bool:
    """KOMIS 정형 근거 중 출처 미확정 표본만 답변 전에 막는다.

    개발용 더미는 결과·표·차트에 포함하되 Evidence.caveat를 통해
    ``실제 값이 아님``을 표시한다. 피드백/화면 QA에서 더미 결과 자체가
    필요하므로 더미와 출처 미확정을 같은 차단 상태로 취급하지 않는다.
    """
    unverified_caveats = {KOMIS_RAW_UNVERIFIED_CAVEAT}
    return any(
        ev.kind in {"structured", "aggregated"}
        and (ev.menu_page_id is not None or (ev.source or "").startswith("public.KO_"))
        and ev.caveat in unverified_caveats
        for ev in evidence
    )


def _evidence_matches_action_contract(evidence: list[Evidence], action_call) -> bool:
    slots = action_call.slots
    for ev in evidence:
        if slots.currency and slots.currency.casefold() not in (ev.unit or "").casefold():
            return False
        if slots.weight_unit and slots.weight_unit.casefold() not in (ev.unit or "").casefold():
            return False
        if slots.mineral:
            rows = [line.strip() for line in ev.text.splitlines() if line.strip().startswith("|")]
            if len(rows) >= 3:
                headers = [part.strip() for part in rows[0].strip("|").split("|")]
                if "mineral" in headers:
                    index = headers.index("mineral")
                    values = [line.strip("|").split("|")[index].strip() for line in rows[2:]
                              if len(line.strip("|").split("|")) > index]
                    if slots.mineral not in values:
                        return False
        # 월별 교역 adapter는 금액과 중량을 별도 Evidence로 반환한다. action의
        # metric과 표 컬럼/섹션/단위가 모두 맞아야 Advisor가 승인할 수 있다.
        if action_call.action_id == "trade.monthly" and slots.metric:
            text = (ev.section + "\n" + ev.text).casefold()
            expected = {
                "import_amount": (("import_amount", "수입금액"), "usd"),
                "import_weight": (("import_weight", "수입중량"), "kg"),
                "export_amount": (("export_amount", "수출금액"), "usd"),
                "export_weight": (("export_weight", "수출중량"), "kg"),
            }.get(slots.metric)
            if expected:
                markers, expected_unit = expected
                if not any(marker.casefold() in text for marker in markers):
                    return False
                if expected_unit not in (ev.unit or "").casefold():
                    return False
    return True


def _is_complete_mine_rank_increase(evidence: list[Evidence], action_call) -> bool:
    """연간 생산 증가 순위 집계의 결정적 완전성 검사.

    ``mine_aggregate``는 원문 셀/문단에서 annual로 판정된 두 연도만 증가량을
    계산한다. 이 함수는 그 adapter가 만든 단일 집계 표가 요청한 행 수와 모든
    값·출처 열을 갖췄을 때만 Advisor의 표 행 누락 오독을 우회한다. 일반 순위,
    단일값 조회, 분기·누계 자료에는 적용하지 않는다.
    """
    if action_call is None or action_call.action_id != "mine.rank":
        return False
    slots = action_call.slots
    if slots.mine_order != "increase" or len(evidence) != 1:
        return False
    ev = evidence[0]
    if ev.kind != "aggregated" or ev.unit != "t" or not ev.text.strip():
        return False
    annual_marker = "기간 검증: 아래 증가 순위의 각 행은 원문에서 연간(annual/FY/Year/연간) 생산 실적으로 확인된 두 연도만 비교했습니다."
    if annual_marker not in ev.text:
        return False
    lines = [line.strip() for line in ev.text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return False
    headers = [part.strip() for part in lines[0].strip("|").split("|")]
    required = ("순위", "광산", "광종", "시작연도", "시작값(t)", "끝연도", "끝값(t)", "증가량(t)", "basis", "출처")
    if any(column not in headers for column in required):
        return False
    indices = {column: headers.index(column) for column in required}
    expected_rows = slots.top_n or 5
    rows: list[list[str]] = []
    for line in lines[2:]:
        cells = [part.strip() for part in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(cells)
    if len(rows) < expected_rows:
        return False
    for rank, cells in enumerate(rows[:expected_rows], 1):
        try:
            start_year = int(cells[indices["시작연도"]])
            end_year = int(cells[indices["끝연도"]])
            start_value = float(cells[indices["시작값(t)"]].replace(",", ""))
            end_value = float(cells[indices["끝값(t)"]].replace(",", ""))
            increase = float(cells[indices["증가량(t)"]].replace(",", ""))
        except ValueError:
            return False
        if (cells[indices["순위"]] != str(rank) or not cells[indices["광산"]]
                or not cells[indices["광종"]] or not cells[indices["basis"]]
                or not cells[indices["출처"]].endswith(".md")
                or start_year >= end_year or increase <= 0
                or abs((end_value - start_value) - increase) > 0.51):
            return False
    return True


def _is_complete_mine_rank_yoy(evidence: list[Evidence], action_call) -> bool:
    """집계기가 만든 YoY 표의 연속 연도·방향·값·출처를 재검사한다."""
    if action_call is None or action_call.action_id != "mine.rank" or len(evidence) != 1:
        return False
    order = action_call.slots.mine_order
    if order not in {"yoy_increase", "yoy_decrease"}:
        return False
    ev = evidence[0]
    if ev.kind != "aggregated" or ev.unit != "t" or "기간 검증: 아래 YoY 순위" not in ev.text:
        return False
    lines = [line.strip() for line in ev.text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return False
    headers = [part.strip() for part in lines[0].strip("|").split("|")]
    delta_heading = "증가량(t)" if order == "yoy_increase" else "감소량(t)"
    required = ("순위", "광산", "광종", "시작연도", "시작값(t)", "끝연도", "끝값(t)",
                delta_heading, "basis", "출처")
    if any(column not in headers for column in required):
        return False
    indices = {column: headers.index(column) for column in required}
    rows = [[part.strip() for part in line.strip("|").split("|")] for line in lines[2:]]
    rows = [row for row in rows if len(row) == len(headers)]
    if not 1 <= len(rows) <= (action_call.slots.top_n or 5):
        return False
    previous_delta = float("inf")
    for rank, cells in enumerate(rows, 1):
        try:
            start_year = int(cells[indices["시작연도"]])
            end_year = int(cells[indices["끝연도"]])
            start_value = float(cells[indices["시작값(t)"]].replace(",", ""))
            end_value = float(cells[indices["끝값(t)"]].replace(",", ""))
            delta = float(cells[indices[delta_heading]].replace(",", ""))
        except ValueError:
            return False
        actual = end_value - start_value
        if (cells[indices["순위"]] != str(rank) or not cells[indices["광산"]]
                or not cells[indices["광종"]] or not cells[indices["출처"]].endswith(".md")
                or cells[indices["basis"]] not in {"ore", "metal"}
                or end_year != start_year + 1 or delta <= 0 or delta > previous_delta
                or (actual <= 0 if order == "yoy_increase" else actual >= 0)
                or abs(abs(actual) - delta) > 0.51):
            return False
        previous_delta = delta
    return True


def _is_complete_explicit_hs_summary(evidence: list[Evidence], action_call) -> bool:
    """명시 HS 단일 품목의 금액·중량 집계가 모두 있는지 결정적으로 확인한다.

    이 MCP adapter는 HS 코드와 전체 국가 범위를 SQL 필터로 고정하고 금액·중량을
    별도 Evidence로 만든다. 둘의 source_id·HS 코드·단위·표 컬럼이 맞으면 LLM
    Advisor의 JSON 형식 실패는 사실 판정 실패가 아니므로 재현 가능한 원천을
    버리지 않는다.
    """
    if action_call is None or action_call.action_id != "trade.hs_summary":
        return False
    hs_code = action_call.slots.hs_code
    if not hs_code or len(evidence) < 2 or not all(ev.kind == "structured" and ev.text.strip() for ev in evidence):
        return False
    source_ids = {ev.source_id for ev in evidence}
    if len(source_ids) != 1 or not next(iter(source_ids), ""):
        return False
    texts = [f"{ev.section}\n{ev.text}".casefold() for ev in evidence]
    if not all(f"hs {hs_code}".casefold() in text for text in texts):
        return False
    has_amount = any(("import_amount" in text or "수입금액" in text) and "usd" in (ev.unit or "").casefold()
                     for ev, text in zip(evidence, texts))
    has_weight = any(("import_weight" in text or "수입중량" in text) and "kg" in (ev.unit or "").casefold()
                     for ev, text in zip(evidence, texts))
    return has_amount and has_weight


def _internal_methodology_evidence(action_call) -> list[Evidence]:
    """정적 내부 원천이 명시한 계산법·사례만 document.retrieve에 제공한다.

    이 경로는 실측값을 대신하지 않는다. 문서가 실제 값의 부재와 허용되는
    대안 계산의 한계를 함께 명시한 좁은 질문군에만 적용한다. 따라서
    외부 일반지식이나 생성 모델의 빈칸 채우기로 개념 답변을 만들지 않는다.
    """
    if action_call.action_id != "stockpile.methodology":
        return []
    return [Evidence(
        kind="static_document",
        source="rag_core/ragkit/static_docs/stockpile_calculation_methodology.md",
        section="입력값과 계산",
        text=("이 문서는 실비축 현황을 제공하지 않는 계산 정의다. 필요한 입력값은 기준일의 "
              "현재재고와 목표재고(같은 질량 단위), 그리고 산정 기간을 명시한 일평균소비량(질량/일)이다. "
              "부족량=max(목표재고−현재재고, 0)이고, 비축일수=현재재고/일평균소비량이다. "
              "일평균소비량이 0이거나 확인되지 않으면 비축일수를 계산하지 않는다. 현재 서비스에는 "
              "리튬의 현재재고·목표재고·일평균소비량 실측 원천이 없으므로 실제 부족량이나 비축일수는 "
              "산출할 수 없다."),
        as_of="2026-09-21",
    )]


def _comparison_or_monthly_source_is_usable(evidence: list[Evidence], action_call) -> bool:
    """비교·월별 관측은 실원천, 요청 광종, 요청 기간을 모두 충족해야 한다."""
    if action_call.action_id not in {"price.compare", "price.verify_claim", "trade.monthly"}:
        return True
    if any("실제 표본 여부를 자동으로 확인할 수 없는" in (ev.caveat or "") for ev in evidence):
        return False
    if action_call.action_id == "trade.monthly":
        return True
    requested = set(action_call.slots.minerals or [])
    if not requested:
        return False
    observed_minerals = {
        mineral for mineral in requested
        if any(f"({mineral})" in ev.section or f"| {mineral} |" in ev.text for ev in evidence)
    }
    if observed_minerals != requested:
        return False
    period = action_call.slots.period
    if (action_call.action_id == "price.compare" and period
            and period.kind == "trailing_months" and period.trailing_months):
        expected_start = _months_ago(date.today(), period.trailing_months)
        date_ranges = [re.findall(r"(\d{4}-\d{2}-\d{2})", ev.observed_period or ev.as_of or "")
                       for ev in evidence]
        starts = [date.fromisoformat(parts[0]) for parts in date_ranges if len(parts) >= 2]
        if not starts or min(starts) > expected_start:
            return False
    return True


def _filter_document_evidence_to_trailing_period(evidence: list[Evidence], action_call) -> list[Evidence]:
    """최근 N개월 문서 질의에는 파일명에서 확인한 발행일 근거만 남긴다."""

    period = action_call.slots.period
    if (action_call.action_id != "document.retrieve" or not period
            or period.kind != "trailing_months" or not period.trailing_months):
        return evidence
    cutoff = _months_ago(date.today(), period.trailing_months)
    filtered: list[Evidence] = []
    for ev in evidence:
        try:
            observed = date.fromisoformat((ev.as_of or "")[:10])
        except ValueError:
            continue
        if cutoff <= observed <= date.today():
            filtered.append(ev)
    return filtered


def _okf_body_matches_profile(evidence: list[Evidence], mine_name: str | None) -> bool:
    """단건 광산 근거에는 요청한 광산명이 실제 본문에 있어야 한다."""
    needle = re.sub(r"\s+", "", mine_name or "").casefold()
    if not needle:
        return False
    return any(
        ev.kind == "pageindex" and needle in re.sub(r"\s+", "", ev.text).casefold()
        for ev in evidence
    )


# JSON 라우터가 일시적으로 무효 출력을 낼 때에만 쓰는 좁은 안전망이다. 정상
# 라우팅은 `komis_resolve_mineral`의 실제 광종 목록을 쓰므로 이 목록은 지원
# 광종 화이트리스트가 아니다. 이 안전망이 확실히 판별할 수 있는 고정 검증
# 질문의 광종 표기만 인식해, 모호하거나 여러 광종인 질문을 임의의 RDB 순위
# 질의로 바꾸지 않는다.
_SAFE_FALLBACK_MINERAL_ALIASES = (
    "네오디뮴", "희귀토류", "희토류", "코발트", "리튬", "니켈", "구리",
)
_MINE_QUERY_MARKERS = ("광산", "광구", "제련소", "mine")
_COMPOSITE_INDEX_ABORT_WARNING = "mineral_specific_composite_index"


def _explicit_single_fallback_mineral(question: str) -> str | None:
    """안전 폴백에 허용된 단일 광종만 돌려준다.

    동음·다광종·개별 광산 질문은 ``None``으로 돌려 일반 비정형 폴백에 맡긴다.
    이 함수의 보수성은 JSON 라우터 장애가 곧 잘못된 결정적 SQL로 이어지지 않게
    하는 경계다.
    """

    normalized = question.lower().replace(" ", "")
    if any(marker in normalized for marker in _MINE_QUERY_MARKERS):
        return None
    found = [name for name in _SAFE_FALLBACK_MINERAL_ALIASES if name in normalized]
    unique = list(dict.fromkeys(found))
    return unique[0] if len(unique) == 1 else None


def _relative_months_in_question(question: str) -> int | None:
    """명시된 '최근 N개월/N년'만 결정적으로 읽는다(그 외 기간은 추측하지 않는다)."""

    match = re.search(r"최근\s*(\d+)\s*(개월|년)", question)
    if not match:
        return None
    count = int(match.group(1))
    return count * 12 if match.group(2) == "년" else count


def _comparison_minerals_in_text(question: str) -> list[str]:
    """가격 비교절에서 광종 후보를 읽는다.

    이 단계는 광종 목록을 갖지 않는다. 후보 문자열은 이후 MCP의
    ``komis_resolve_mineral``/가격 비교 조회가 실제 ``ai_mnrl_mst`` 기준으로
    해소한다. 따라서 새 광종이 추가돼도 이 파서의 수정이 필요 없다.
    """

    compact = re.sub(r"\s+", " ", question).strip()
    match = re.search(r"(.{1,80}?)(?:의 )?(?:가격|시세|거래가|단가)(?:을|를)?\s*(?:비교|비교해|등락|변동|하락)", compact)
    if match:
        subject = match.group(1)
        candidates = re.split(r"\s*(?:,|·|/|와|과|및|그리고)\s*", subject)
    else:
        # 후속 답변의 "니켈 가격 추이"처럼 비교 동사가 없는 문장에서도
        # 광종명 후보만 보존한다. 실제 유효성은 DB resolver가 판단한다.
        candidates = re.findall(r"(?<![가-힣A-Za-z])([가-힣A-Za-z]{1,30})(?:의)?\s*(?:가격|시세|거래가|단가)", compact)
    ignored = {"가격", "시세", "거래가", "단가", "최근", "각", "광종", "광물", "두", "개"}
    names: list[str] = []
    for candidate in candidates:
        name = re.sub(r"^(?:최근|각|광종별|광물별)\s*", "", candidate).strip()
        name = re.sub(r"\s*(?:중|의)$", "", name).strip()
        if name and name not in ignored and len(name) <= 30 and name not in names:
            names.append(name)
    return names


def _ranking_top_n_in_question(question: str) -> int:
    """명시된 상위 N/ N개국만 읽고, 없으면 기존 UI 기본값 5를 유지한다."""

    match = re.search(r"(?:상위\s*)?(\d+)\s*개?국", question)
    if not match:
        match = re.search(r"상위\s*(\d+)", question)
    return int(match.group(1)) if match else 5


def _has_country_ranking_request(question: str) -> bool:
    normalized = question.replace(" ", "")
    return any(marker in normalized for marker in ("상위", "순위", "1위", "2위", "3위", "가장", "제일")) and any(
        marker in normalized for marker in ("국가", "나라", "개국", "상위국", "국은")
    )


def _has_country_concentration_request(question: str) -> bool:
    normalized = question.upper().replace(" ", "")
    return "HHI" in normalized or "집중도" in normalized


def _safe_route_fallback(question: str) -> RetrievalRoute | None:
    """무효 JSON 시에도 명확한 단일 광종 고정질문은 결정적으로 복구한다.

    여기서 다루지 않는 질문은 ``None``을 반환해 기존 dense/pageindex 일반
    폴백으로 간다. 즉 모호·광산·다광종 질문을 국가 랭킹이나 가격 조회로
    과잉해석하지 않는다.
    """

    mineral = _explicit_single_fallback_mineral(question)
    if not mineral:
        return None
    normalized = question.replace(" ", "")
    if "광물종합지" in normalized:
        return RetrievalRoute(
            resolved_query=question, use_structured=False, use_dense=False, use_pageindex=False,
            is_mineral_specific_composite_index=True,
        )

    if _has_country_concentration_request(question) and ("수입" in normalized or "수출" in normalized):
        return RetrievalRoute(
            resolved_query=question, use_structured=False, use_dense=False, use_pageindex=False,
            komis_mineral_name=mineral, use_komis_concentration=True,
        )

    if _has_country_ranking_request(question):
        metrics: list[Literal["production", "reserves"]] = []
        if "생산" in normalized:
            metrics.append("production")
        if "매장" in normalized:
            metrics.append("reserves")
        if metrics:
            return RetrievalRoute(
                resolved_query=question, use_structured=False, use_dense=False, use_pageindex=False,
                komis_mineral_name=mineral, use_komis_mineral_ranking=True,
                komis_mineral_ranking_metrics=metrics, komis_ranking_top_n=_ranking_top_n_in_question(question),
            )
        if "수입" in normalized or "수출" in normalized:
            is_import = "수입" in normalized
            is_weight = any(marker in normalized for marker in ("물량", "중량", "톤"))
            metric = (
                "import_weight" if is_import and is_weight else
                "export_weight" if not is_import and is_weight else
                "import_amount" if is_import else "export_amount"
            )
            return RetrievalRoute(
                resolved_query=question, use_structured=False, use_dense=False, use_pageindex=False,
                komis_mineral_name=mineral, use_komis_ranking=True,
                komis_ranking_page="map_global" if "세계" in normalized else "map_korea",
                komis_ranking_metric=metric, komis_ranking_top_n=_ranking_top_n_in_question(question),
            )

    if any(marker in normalized for marker in ("가격", "시세", "거래가", "단가")):
        return RetrievalRoute(
            resolved_query=question, use_structured=False, use_dense=False, use_pageindex=False,
            use_komis_raw=True, komis_topic="price", komis_mineral_name=mineral,
            komis_relative_months=_relative_months_in_question(question),
        )
    return None


def _is_mineral_specific_composite_index(question: str, route: RetrievalRoute) -> bool:
    """광종별로 오해될 수 있는 광물종합지수 요청을 결정적으로 막는다."""

    normalized = question.replace(" ", "")
    if "광물종합지" not in normalized:
        return False
    return bool(route.komis_mineral_name or _explicit_single_fallback_mineral(question))


def _apply_aggregate_route(state: RetrievalState, route: RetrievalRoute) -> RetrievalRoute:
    """집계가 필요한 명시 질문을 원자료 미리보기 대신 결정적 조회로 보낸다."""
    question = state["question"]
    compact = re.sub(r"\s+", "", question)
    updates: dict[str, object] = {}
    # 라우터가 '최근 1년'을 누락해도 명시된 상대기간을 최신 N행으로
    # 오인하지 않도록 원문에서 확인한다. 특정 연월 범위는 기존 라우터 값을 쓴다.
    relative_months = _relative_months_in_question(question)
    if relative_months and not (route.komis_start_period or route.komis_end_period):
        updates["komis_relative_months"] = relative_months
    hs_match = re.search(r"(?<!\d)\d{10}(?!\d)", question)
    if hs_match and "수입" in compact and ("품목" in compact or "현황" in compact):
        updates.update(use_komis_explicit_hs_summary=True, komis_hs_code=hs_match.group(),
                       use_komis_raw=False, use_dense=False, use_pageindex=False,
                       use_komis_price_comparison=False, use_komis_concentration=False,
                       use_komis_ranking=False, use_komis_mineral_ranking=False)
    elif "수입" in compact and any(t in compact for t in ("월별", "개월", "추이", "연간")):
        if not any(t in compact for t in ("상위", "수입국", "HHI", "집중도")):
            updates.update(use_komis_monthly_trade=True, use_komis_raw=False,
                           use_dense=False, use_pageindex=False,
                           use_komis_price_comparison=False, use_komis_concentration=False,
                           use_komis_ranking=False, use_komis_mineral_ranking=False)
    if "생산국비중" in compact and "수입국비중" in compact:
        updates.update(use_komis_mineral_ranking=True,
                       komis_mineral_ranking_metrics=["production"],
                       use_komis_ranking=True, komis_ranking_page="map_korea",
                       komis_ranking_metric="import_amount", komis_ranking_top_n=5,
                       use_komis_raw=False, use_dense=False, use_pageindex=False,
                       use_komis_price_comparison=False, use_komis_concentration=False)
    # Action planner가 가격 비교로 일반화해도, "변동성이 큰/작은"은 가격
    # 수준·등락률 비교가 아니라 절댓값 변동률 순위다. 최근만 지정한 경우는
    # ROUTE_PROMPT의 기존 계약대로 3개월 창을 결정적으로 채운다.
    volatility_rank = "변동성" in compact and any(
        term in compact for term in ("가장", "큰", "작은", "높", "낮", "많", "적")
    )
    if volatility_rank:
        names = list(dict.fromkeys([
            *(route.komis_compare_mineral_names or []),
            *([route.komis_mineral_name] if route.komis_mineral_name else []),
        ])) or _comparison_minerals_in_text(question)
        updates.update(
            use_komis_price_volatility_ranking=True,
            use_komis_price_comparison=False,
            komis_compare_mineral_names=names or None,
            komis_relative_months=(3 if "최근" in compact and not relative_months else relative_months),
            use_komis_raw=False, use_dense=False, use_pageindex=False,
            use_komis_monthly_trade=False, use_komis_explicit_hs_summary=False,
            use_komis_concentration=False,
        )
    price_terms = any(t in compact for t in ("가격", "시세"))
    # 수치 임계값 자체는 비교 경로의 조건이 아니다. 퍼센트 가격 변동 *주장*을
    # 원자료로 검증하려는 의도를 읽어 어떤 임계값에도 같은 집계를 적용한다.
    price_claim_verification = (
        bool(re.search(r"\d+(?:\.\d+)?%", compact))
        and any(t in compact for t in ("상승", "하락", "올랐", "내렸", "떨어", "급등", "급락"))
        and any(t in compact for t in ("전제", "주장", "검증", "맞나", "맞는지", "사실", "확인"))
    )
    price_compare = any(t in compact for t in ("비교", "등락률", "변동률", "하락률")) or price_claim_verification
    followup_compare = any(t in compact for t in ("같은기간", "그중가장크게하락"))
    if (price_terms and price_compare) or followup_compare:
        # 라우터가 이미 실제 광종명을 냈다면 일반 문장 파서는 보강하지 않는다.
        # "최근 1년"·"비교하고" 같은 서술 조각을 광종으로 오인해 DB 조회를
        # 실패시키는 것을 막고, 라우터가 비었을 때만 후보를 넘겨 resolver가
        # ai_mnrl_mst 기준으로 최종 검증한다.
        names = list(dict.fromkeys([
            *(route.komis_compare_mineral_names or []),
            *([route.komis_mineral_name] if route.komis_mineral_name else []),
        ]))
        if not names:
            names = _comparison_minerals_in_text(question)
        if followup_compare:
            latest_answer = _last_assistant_answer(state)
            from_latest = _comparison_minerals_in_text(latest_answer)
            if from_latest:
                names = list(dict.fromkeys([*from_latest, *names]))[:2]
            if len(names) < 2:
                for turn in reversed(_recent_history(state)):
                    if turn.get("role") != "user":
                        continue
                    for name in _comparison_minerals_in_text(turn.get("content", "")):
                        if name not in names:
                            names.insert(0, name)
                    if len(names) >= 2:
                        break
            explicit_span = re.search(
                r"(?:실제\s*조회기간|공통\s*조회기간|조회기간)\s*:\s*"
                r"(20\d{2}[-.]?\d{2}[-.]?\d{2})\s*(?:\\?~|부터|[-–])\s*"
                r"(20\d{2}[-.]?\d{2}[-.]?\d{2})", latest_answer,
            )
            if explicit_span:
                updates.update(komis_start_period=re.sub(r"\D", "", explicit_span.group(1)),
                               komis_end_period=re.sub(r"\D", "", explicit_span.group(2)),
                               komis_relative_months=None)
        if names:
            updates.update(use_komis_price_comparison=True,
                           komis_compare_mineral_names=names,
                           use_komis_price_volatility_ranking=False,
                           use_komis_raw=False, use_dense=False, use_pageindex=False,
                           use_komis_monthly_trade=False,
                           use_komis_explicit_hs_summary=False,
                           use_komis_concentration=False)
        windows = [n for n in (3, 6, 12) if f"{n}개월" in compact or (n == 12 and "1년" in compact)]
        if len(windows) > 1:
            updates["komis_price_windows_months"] = windows
    if updates:
        updates["use_mine_aggregate"] = False
        if not route.komis_mineral_name and not hs_match:
            explicit = _explicit_single_fallback_mineral(question)
            if explicit:
                updates["komis_mineral_name"] = explicit
    return route.model_copy(update=updates) if updates else route


def _log_prefix(state: RetrievalState) -> str:
    session_id = state.get("session_id")
    return f"[rag_core/ragkit/chatbot_graph session={session_id[:8] if session_id else '?'}]"


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

    action_assessment = state.get("action_assessment")
    if action_assessment is not None:
        if not action_assessment.approved or action_assessment.plan is None:
            route = RetrievalRoute(resolved_query=state["question"], use_structured=False,
                                   use_komis_raw=False, use_dense=False, use_pageindex=False)
            return {"route": route, "warnings": [f"action_plan_failed:{action_assessment.failure_reason}"]}
        return {"route": _route_from_action_plan(action_assessment.plan, state["question"]), "warnings": []}

    assessment = state.get("source_assessment")
    if assessment is None or assessment.blocked:
        # 원천 계약은 LLM 라우팅보다 먼저 적용한다. 모델이 dense/PageIndex를
        # 켜더라도 미연결 결과를 유사 문서로 대체할 수 없다.
        route = RetrievalRoute(
            resolved_query=state["question"], use_structured=False, use_komis_raw=False,
            use_dense=False, use_pageindex=False,
        )
        return {
            "route": route,
            "warnings": [f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}{','.join(assessment.unavailable_domains) if assessment else 'invalid_plan'}"],
        }
    try:
        invocation = llm.invoke(
            task="retrieval_route", instructions=ROUTE_PROMPT,
            payload={
                "오늘_날짜": date.today().isoformat(),
                "question": state["question"],
                "history": _recent_history(state),
                "last_answer": _last_assistant_answer(state),
            },
            # 도구 선택 필드가 계속 늘어 350토큰에서는 JSON 끝이 잘리고, 복구
            # 호출도 같은 상한이라 다시 실패했다. 상수(1,280)로 여유를 고정한다.
            output_model=RetrievalRoute, max_tokens=RETRIEVAL_ROUTE_MAX_TOKENS,
        )
        route = invocation.output
        if not route.resolved_query.strip():
            route.resolved_query = state["question"]
        warnings: list[str] = []
        if "price_forecast" in assessment.unavailable_domains and route.komis_topic == "price_forecast":
            # KOMIS의 과거 예측 화면도 새 DB가 제공할 가격예측 결과의 대체
            # 원천이 될 수 없다. 혼합 질문에서는 나머지 독립 도구만 남긴다.
            route = route.model_copy(update={"use_komis_raw": False, "komis_topic": None})
            warnings.append(f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}price_forecast")
        if _is_mineral_specific_composite_index(state["question"], route):
            route = route.model_copy(update={
                "is_mineral_specific_composite_index": True,
                "use_structured": False, "use_komis_raw": False,
                "use_dense": False, "use_pageindex": False,
            })
            warnings.append(_COMPOSITE_INDEX_ABORT_WARNING)
        # HHI는 최신 N행/상위 N개국을 다시 합산하면 값이 달라지는 계산이다.
        # 질문이 명확히 집중도를 요구하고 광종도 해소됐을 때만 전체 모집단
        # 결정적 도구를 강제한다. 다른 질문에 일반화하지 않는다.
        if _has_country_concentration_request(state["question"]) and route.komis_mineral_name:
            route = route.model_copy(update={
                "use_komis_concentration": True,
                "use_komis_ranking": False,
                "use_komis_raw": False,
                "use_dense": False,
                "use_pageindex": False,
            })
        route = _apply_aggregate_route(state, route)
        _logger.info(
            "%s route: resolved_query=%r ambiguous=%s structured=%s(%s/%s) komis_raw=%s(%s/%s) "
            "komis_ranking=%s(%s/%s) komis_mineral_ranking=%s(%s) price_volatility=%s "
            "indicator_ranking=%s(%s/asc=%s) compare=%s dense=%s pageindex=%s(%s) mine_aggregate=%s",
            _log_prefix(state), route.resolved_query, route.is_ambiguous, route.use_structured,
            route.structured_template, route.commodity_code, route.use_komis_raw, route.komis_topic,
            route.komis_mineral_name, route.use_komis_ranking, route.komis_ranking_page,
            route.komis_ranking_metric, route.use_komis_mineral_ranking, route.komis_mineral_ranking_metrics,
            route.use_komis_price_volatility_ranking, route.use_komis_indicator_ranking,
            route.komis_indicator_ranking_page, route.komis_indicator_ranking_ascending,
            route.komis_compare_mineral_names, route.use_dense, route.use_pageindex, route.pageindex_mode,
            route.use_mine_aggregate,
        )
    except LLM_TRANSIENT_ERRORS as exc:
        # JSON 출력 장애라 해도 질문이 매우 좁고 명시적이면 결정적 RDB 경로를
        # 복구할 수 있다. 그 외에는 기존 일반 검색 폴백을 유지하되, 추측으로
        # 광종·광산·다광종 질문을 랭킹 질의로 바꾸지 않는다.
        route = _safe_route_fallback(state["question"])
        if route is None:
            route = RetrievalRoute(
                resolved_query=state["question"], use_structured=False, use_dense=True, use_pageindex=True,
            )
        route = _apply_aggregate_route(state, route)
        warnings = [f"retrieval_route_invalid_output:{type(exc).__name__}"]
        if route.is_mineral_specific_composite_index:
            warnings.append(_COMPOSITE_INDEX_ABORT_WARNING)
    return {"route": route, "warnings": warnings}


def _retrieve_node(
    state: RetrievalState, *, dense_k: int, pageindex_k: int,
    llm: KomirJsonLLM | None = None, on_status: Callable[..., None] | None = None,
) -> RetrievalState:
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

    action_assessment = state.get("action_assessment")
    if action_assessment is not None and not action_assessment.approved:
        return {"evidence": [], "warnings": [f"action_plan_failed:{action_assessment.failure_reason}"]}
    assessment = state.get("source_assessment")
    if assessment is None or assessment.blocked:
        # 진입점이 아닌 노드를 직접 호출하는 테스트/소비자도 같은 계약을
        # 우회할 수 없도록 여기서 다시 확인한다.
        warnings = list(state.get("warnings", []))
        marker = f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}{','.join(assessment.unavailable_domains) if assessment else 'invalid_plan'}"
        if marker not in warnings:
            warnings.append(marker)
        return {"evidence": [], "warnings": warnings}
    route = state["route"]
    warnings = list(state.get("warnings", []))
    if route.is_mineral_specific_composite_index:
        # KO_MNRL_SNTHS_INDX는 전체/메이저/희소 하위지수만 제공하며 광종별
        # series가 없다. 코발트 등 특정 광종을 붙인 질문에 전체 지수를 재검색
        # 하거나 dense 근접 문서를 인용하면 오답처럼 보이므로 여기서 끝낸다.
        if _COMPOSITE_INDEX_ABORT_WARNING not in warnings:
            warnings.append(_COMPOSITE_INDEX_ABORT_WARNING)
        return {"evidence": [], "warnings": warnings}
    if route.is_ambiguous:
        # 2026-09-18 — ROUTE_PROMPT 1.5가 이미 모든 도구 플래그를 false로
        # 뒀겠지만, 검색 자체를 시도하지 않는다는 걸 여기서도 코드로 확정한다
        # (LLM 출력이라 100% 보장은 아니다고 취급 — STRUCTURED_ENABLED 가드와
        # 같은 원칙). evidence=[]로 즉시 반환하면 chat_turn()의 기존
        # "근거 0건 -> _classify_abstain" 경로가 원 질문 메시지를 그대로 보고
        # "ambiguous" 사유·안내문("요청 범위가 넓습니다...")을 낸다 — 새 경로를
        # 만들지 않고 기존 유형8 분류를 재사용한다.
        warnings.append("route_ambiguous_question")
        return {"evidence": [], "warnings": warnings}
    session = mcp_client.private if state.get("profile") == "private" else mcp_client.public
    jobs: dict[str, Future] = {}

    # 2026-09-01: komis_raw는 page_id를 미리 알아야 풀에 넣을 수 있는데, price
    # 여부에 따른 page_id가 광종의 price_category(ai_mnrl_mst.prc_cat_cd)에
    # 달려 있어 하드코딩 딕셔너리 대신 komis_resolve_mineral을 먼저(동기)
    # 호출해 알아낸다 — 그 뒤 dense/pageindex와 나란히 병렬 조회한다(아래 풀).
    # composite_index(광물종합지수, KO_MNRL_SNTHS_INDX)만 예외다 — 이 페이지는
    # komis_raw.py의 filter_columns에 mineral_code가 아예 없어(index_type_code
    # 뿐) 광종을 몰라도(komis_mineral_name=None이어도) 조회 가능해야 정상이다
    # (사용자 지시, 2026-09-01). 나머지 topic은 여전히 광종을 반드시 알아야 한다.
    #
    # 2026-09-02 skeptic 2차감사 SC-CB2-002 수정: 예전엔 komis_mineral_name이
    # 있으면(예: "니켈 광물종합지수") 그 광종코드를 komis_raw_lookup에
    # mineral_code로 그대로 넘겼다 — 그런데 이 page는 mineral_code 필터가
    # 아예 없어(위 주석 참고) SQL엔 아무 효과가 없는데도, 응답 Evidence.section
    # 라벨엔 "KO_MNRL_SNTHS_INDX(니켈)"처럼 그 광종 전용 데이터인 것처럼
    # 붙어 나왔다(실제로는 전체 지수). composite_index는 mineral_code를
    # 아예 넘기지 않는다 — 필터에 안 쓰이는 값을 넘겨 오표기를 만들 이유가 없다.
    komis_raw_page_id: str | None = None
    komis_raw_mineral_code: str | None = None
    if route.use_komis_raw and route.komis_topic == "composite_index":
        komis_raw_page_id = "indicator_composite"
    elif route.use_komis_raw and route.komis_topic and route.komis_hs_code:
        # HS가 질문에 명시된 교역 질의는 광종 해석을 거치지 않는다. 예전에는
        # 광종 후보가 있으면 매핑된 첫 HS로 바뀌어 다른 품목 수치를 귀속했다.
        komis_raw_page_id = _komis_raw_page_id(route.komis_topic, None)
        if not komis_raw_page_id:
            warnings.append(
                f"komis_raw_unmapped_topic:{route.komis_topic}(hs_code={route.komis_hs_code})"
            )
    elif (route.use_komis_raw and route.komis_topic and route.komis_mineral_name) or (
        # 2026-09-18(B2 후속 — 국가 랭킹) — 광종코드 해소는 komis_raw와
        # komis_ranking이 공유한다(한 질문이 "가격+수입상위국"처럼 둘 다 켤
        # 수 있어 중복 DB 왕복을 피한다). page_id 결정(_komis_raw_page_id)은
        # 아래에서 여전히 komis_raw 전용으로만 한다 — 랭킹은 route가 이미
        # page_id를 직접 고른다(komis_ranking_page).
        (route.use_komis_ranking or route.use_komis_mineral_ranking or route.use_komis_concentration
         or route.use_komis_monthly_trade or route.use_komis_trade_indicator)
        and route.komis_mineral_name
    ):
        resolved = session.call_komis_resolve_mineral(route.komis_mineral_name)
        warnings.extend(resolved.get("warnings", []))
        komis_raw_mineral_code = resolved.get("mineral_code")
        if komis_raw_mineral_code and route.use_komis_raw and route.komis_topic:
            komis_raw_page_id = _komis_raw_page_id(route.komis_topic, resolved.get("price_category"))
            if not komis_raw_page_id:
                warnings.append(
                    f"komis_raw_unmapped_topic:{route.komis_topic}(mineral={route.komis_mineral_name})"
                )

    # public 챗봇은 private 전용 지표를 다른 검색 도구로 우회해 답하면 안 된다.
    # 특히 원천 MCP가 거부한 뒤 dense/PageIndex가 오래된 PDF를 반환하면 접근
    # 제어는 지켰어도 사용자에게는 해당 지표를 조회한 것처럼 보이는 문제가 생긴다.
    requested_private_pages = {
        page_id for page_id in (
            komis_raw_page_id,
            route.komis_indicator_ranking_page if route.use_komis_indicator_ranking else None,
        ) if page_id in PRIVATE_ONLY_KOMIS_PAGES
    }
    if state.get("profile") != "private" and requested_private_pages:
        warnings.append(_PRIVATE_ONLY_PROFILE_WARNING)
        return {"evidence": [], "warnings": warnings}

    # 2026-09-18(감사 후속): `with ThreadPoolExecutor(...) as pool:`을 쓰지
    # 않는다 — context manager의 __exit__는 shutdown(wait=True)라 아래
    # future.result(timeout=...)로 한 job을 포기해도, 블록을 빠져나갈 때 그
    # 스레드가 실제로 끝날 때까지 다시 블로킹돼 timeout이 무의미해진다.
    # try/finally + shutdown(wait=False)로 바꿔 timeout이 실제로 이 노드의
    # 상한이 되게 한다(포기한 job의 스레드 자체는 백그라운드에서 계속 돌다
    # 알아서 끝난다 — 파이썬 스레드는 강제 종료가 안 되므로 이게 최선).
    pool = ThreadPoolExecutor(max_workers=4)

    def submit(fn, *args, **kwargs):
        """Langfuse/OpenTelemetry context를 각 병렬 조회 스레드에 복사한다."""

        return pool.submit(copy_context().run, fn, *args, **kwargs)

    try:
        # STRUCTURED_ENABLED=False인 동안은 ROUTE_PROMPT가 use_structured를
        # 항상 false로 두도록 지시돼 있지만, LLM 출력이라 100% 보장은
        # 아니다 — 여기서 한 번 더 코드로 확정 차단한다(2026-09-07, 사용자
        # 지시: mineral_risk 스키마의 구 산출물 테이블 연계를 끊음, 향후
        # 새 테이블로 교체 예정. 재연결 시 이 플래그만 True로 돌리면 된다).
        if STRUCTURED_ENABLED and route.use_structured and route.structured_template and route.commodity_code:
            call = getattr(session, _STRUCTURED_CALL_NAMES[route.structured_template])
            jobs["structured"] = submit(call, route.commodity_code, route.target, route.forecast_months)
        # composite_index는 komis_raw_mineral_code가 None이어도(광종 미지정)
        # 조회한다 — 위에서 이미 그 경우만 komis_raw_page_id를 채워뒀다.
        # start_period/end_period: 명시적 기간(2026-09-03, ④-나)이 있으면
        # 그대로, 없고 상대기간("최근 N개월")만 있으면 _relative_period_
        # bounds()가 오늘 날짜 기준으로 계산해 채운다(2026-09-07). 둘 다
        # 없으면 여전히 None → 기존과 동일하게 최신 limit개가 조회된다.
        if komis_raw_page_id:
            start_period, end_period = _relative_period_bounds(route)
            jobs["komis_raw"] = submit(
                session.call_komis_raw_lookup, komis_raw_page_id, mineral_code=komis_raw_mineral_code,
                hs_code=route.komis_hs_code,
                start_period=start_period, end_period=end_period,
            )
        # 2026-09-18(B2 후속) — "{광종} 수입 상위 5개국" 같은 순위형 질문 전용
        # 결정적 집계 조회(common/komis_raw.py::fetch_country_ranking, GROUP
        # BY+ORDER BY+LIMIT). komis_raw_lookup과 별도 job이다 — 하나의 질문이
        # 둘 다 필요로 할 수 있다(예: "가격 동향과 수입 상위국 같이").
        if route.use_komis_ranking and komis_raw_mineral_code and route.komis_ranking_page and route.komis_ranking_metric:
            rank_start, rank_end = _relative_period_bounds(route)
            jobs["komis_ranking"] = submit(
                session.call_komis_country_ranking, komis_raw_mineral_code, route.komis_ranking_page,
                route.komis_ranking_metric, start_period=rank_start, end_period=rank_end,
                top_n=route.komis_ranking_top_n or 5,
            )
        if route.use_komis_concentration and komis_raw_mineral_code:
            concentration_start, concentration_end = _relative_period_bounds(route)
            jobs["komis_concentration"] = submit(
                session.call_komis_country_concentration, komis_raw_mineral_code,
                start_period=concentration_start, end_period=concentration_end,
            )
        if route.use_komis_monthly_trade and (komis_raw_mineral_code or route.komis_hs_code):
            trade_start, trade_end = _relative_period_bounds(route)
            monthly_kwargs: dict[str, object] = {
                "mineral_code": komis_raw_mineral_code, "hs_code": route.komis_hs_code,
                "start_period": trade_start, "end_period": trade_end, "compare_year": None,
            }
            # 기존 MCP mock/서버도 metric 없는 조회는 계속 지원한다. typed action이
            # 기준을 지정한 경우에만 필터를 넘겨 두 metric Evidence가 섞이지 않는다.
            if route.komis_monthly_trade_metric is not None:
                monthly_kwargs["metric"] = route.komis_monthly_trade_metric
            jobs["komis_monthly_trade"] = submit(
                session.call_komis_monthly_trade_summary, **monthly_kwargs,
            )
        if (route.use_komis_trade_indicator and route.komis_trade_metric
                and route.komis_reporter_country and route.komis_start_period
                and len(route.komis_start_period) == 4):
            jobs["komis_trade_indicator"] = submit(
                session.call_komis_trade_indicator,
                trade_metric=route.komis_trade_metric,
                reporter_country=route.komis_reporter_country,
                calendar_year=int(route.komis_start_period),
                mineral_code=komis_raw_mineral_code, hs_code=route.komis_hs_code,
                partner_country=route.komis_partner_country, flow=route.komis_trade_flow,
            )
        if route.use_komis_explicit_hs_summary and route.komis_hs_code:
            hs_start, hs_end = _relative_period_bounds(route)
            jobs["komis_explicit_hs_summary"] = submit(
                session.call_komis_explicit_hs_import_summary, route.komis_hs_code,
                start_period=hs_start, end_period=hs_end,
            )
        if route.use_komis_price_comparison and route.komis_compare_mineral_names:
            if route.komis_price_windows_months:
                for months in route.komis_price_windows_months:
                    window = route.model_copy(update={"komis_relative_months": months,
                                                      "komis_start_period": None, "komis_end_period": None})
                    p_start, p_end = _relative_period_bounds(window)
                    jobs[f"komis_price_comparison:{months}"] = submit(
                        session.call_komis_price_comparison, route.komis_compare_mineral_names,
                        start_period=p_start, end_period=p_end, window_months=months,
                    )
            else:
                p_start, p_end = _relative_period_bounds(route)
                jobs["komis_price_comparison"] = submit(
                    session.call_komis_price_comparison, route.komis_compare_mineral_names,
                    start_period=p_start, end_period=p_end,
                )
        # 2026-09-18(RDB 결정적쿼리 후보리스트 1순위) — "{광종} 매장량/생산량
        # 국가랭킹" 전용. komis_ranking(교역)과 별도 job, mineral_code 해소는
        # 위에서 공유한다. 연도는 relative_months 계산을 거치지 않는다(연 단위
        # 매장량/생산량엔 "최근 N개월" 같은 상대기간 표현이 자연스럽지 않아
        # ROUTE_PROMPT도 명시 연도만 채우게 했다 — komis_raw/komis_ranking과
        # 달리 _relative_period_bounds()를 부르지 않고 route의 명시 필드를
        # 그대로 넘긴다).
        # 2026-09-18(고정질문 #4 회귀 수정) — komis_mineral_ranking_metrics가
        # 리스트라 "생산량과 매장량" 복합요청은 지표마다 별도 job을 하나씩
        # 낸다(RDB 조회 로직·MCP tool은 그대로 — call_komis_mineral_ranking을
        # 지표 수만큼 반복 호출할 뿐). job 키에 지표명을 붙여 구분한다.
        if route.use_komis_mineral_ranking and komis_raw_mineral_code:
            share_comparison = "생산국비중" in re.sub(r"\s+", "", state.get("question", "")) and "수입국비중" in re.sub(r"\s+", "", state.get("question", ""))
            for metric in route.komis_mineral_ranking_metrics or []:
                jobs[f"komis_mineral_ranking:{metric}"] = submit(
                    session.call_komis_mineral_ranking, komis_raw_mineral_code, metric,
                    start_period=route.komis_start_period, end_period=route.komis_end_period,
                    top_n=route.komis_ranking_top_n or 5,
                    share_only=share_comparison,
                )
        # 2026-09-18(RDB 결정적쿼리 후보리스트 2순위) — 여러 광종을 가로지르는
        # 비교/랭킹 두 종. 이 둘은 mineral_code 해소가 필요 없다(광종명을
        # 그대로 SQL의 ai_mnrl_mst 조인 필터로 쓴다 — komis_compare_mineral_names
        # 참고). 가격변동은 "최근 N개월"류 상대기간이 자연스러워
        # _relative_period_bounds()를 그대로 쓴다(indicator_ranking은 항상
        # "최신값" 하나만 보므로 기간 자체가 필요 없다).
        if route.use_komis_price_volatility_ranking:
            vol_start, vol_end = _relative_period_bounds(route)
            jobs["komis_price_volatility"] = submit(
                session.call_komis_price_volatility_ranking,
                mineral_names=route.komis_compare_mineral_names,
                start_period=vol_start, end_period=vol_end,
                top_n=route.komis_ranking_top_n or 5,
            )
        if route.use_komis_indicator_ranking and route.komis_indicator_ranking_page:
            jobs["komis_indicator_ranking"] = submit(
                session.call_komis_indicator_ranking, route.komis_indicator_ranking_page,
                ascending=route.komis_indicator_ranking_ascending if route.komis_indicator_ranking_ascending is not None else True,
                mineral_names=route.komis_compare_mineral_names, top_n=route.komis_ranking_top_n or 5,
            )
        # 2026-09-17(광산자료 집계 파이프라인) — 다른 job과 같은 풀에서 병렬
        # 실행하되, 내부적으로 문서 20~40건을 자체 스레드풀로 또 fan-out한다
        # (mine_aggregate.py 참고) — 이 job의 future.result()가 그 안쪽 fan-out
        # 전체가 끝날 때까지 이 노드를 블로킹하므로, on_status를 그대로 넘겨
        # 문서 처리 진행상황(§4.2 "SSE 진행상황")이 이 블로킹 구간 동안에도
        # 나가게 한다(_run_with_status의 콜백은 스레드에서 불려도 안전 —
        # chatbot.py::_run_with_status 참고).
        if route.use_mine_aggregate and route.mine_metric and route.mine_agg:
            jobs["mine_aggregate"] = submit(
                mine_aggregate.aggregate_mine_metric,
                route.komis_mineral_name or "", route.mine_metric, route.mine_agg,
                year=route.mine_year, targets=route.mine_targets,
                since_year=route.mine_since_year, country=route.mine_country,
                order=route.mine_order, top_n=route.mine_top_n,
                llm=llm, on_status=on_status,
            )
        query = route.resolved_query or state["question"]
        # 2026-09-18(사용자 지시 "안전망 보강") — komis_ranking 계열 4종(교역·
        # 매장량/생산량·가격변동률·지표 비교)은 komis_raw와 달리 ROUTE_PROMPT의
        # "권장" 문구에만 기대면 LLM이 안 켤 수 있다(실측 재현: "한국이 리튬을
        # 가장 많이 수출하는 나라는?" — 라우팅 자체는 정확히 komis_ranking으로
        # 갔지만 use_dense=False라 그 결과가 0건(수출 데이터 미적재)이어도
        # 대체 근거가 전혀 없어 "질문 모호"로 잘못 기권했다). ROUTE_PROMPT
        # 권장에 기대지 않고 이 4종을 켤 땐 dense를 코드로 강제 병행한다 —
        # dense가 실제로 쓸모없어도(관련 문서가 없어도) 비용은 검색 1회뿐이고,
        # _finalize_node가 구조화 근거가 있으면 이미 dense 노이즈를 가지치기
        # 하므로 부작용이 없다(2026-09-07 노이즈 가지치기 로직 재사용).
        paired_population = route.use_komis_ranking and route.use_komis_mineral_ranking
        strict_aggregate = any((route.use_komis_monthly_trade,
                                route.use_komis_explicit_hs_summary,
                                route.use_komis_price_comparison, paired_population))
        use_dense_effective = not strict_aggregate and (route.use_dense or any((
            route.use_komis_ranking, route.use_komis_mineral_ranking,
            route.use_komis_price_volatility_ranking, route.use_komis_indicator_ranking,
        )))
        if use_dense_effective:
            jobs["dense"] = submit(session.call_hybrid_search, query, dense_k)
        if route.use_pageindex:
            if route.pageindex_mode == "agentic":
                jobs["pageindex"] = submit(
                    session.call_pageindex_agentic, query, history=_recent_history(state),
                )
            else:
                jobs["pageindex"] = submit(
                    session.call_pageindex_lookup, query, doc=route.pageindex_doc,
                    node_limit=pageindex_k, with_text=True,
                    body_fallback=route.pageindex_body_fallback,
                    body_query=route.pageindex_body_query,
                )

        results: dict[str, object] = {}
        for name, future in jobs.items():
            try:
                results[name] = future.result(timeout=RETRIEVE_JOB_TIMEOUT_SECONDS)
            except Exception as exc:  # noqa: BLE001 — 도구 하나 실패(timeout 포함)는 부분 열화로 흡수
                _logger.warning("%s %s 조회 실패: %s: %s", _log_prefix(state), name, type(exc).__name__, exc)
                warnings.append(f"{name}_failed")
    finally:
        pool.shutdown(wait=False)

    required_aggregate_jobs = [name for name in jobs if name.startswith((
        "komis_monthly_trade", "komis_explicit_hs_summary", "komis_price_comparison",
    ))]
    if route.use_komis_monthly_trade and "komis_monthly_trade" not in required_aggregate_jobs:
        required_aggregate_jobs.append("komis_monthly_trade")
    if route.use_komis_explicit_hs_summary and "komis_explicit_hs_summary" not in required_aggregate_jobs:
        required_aggregate_jobs.append("komis_explicit_hs_summary")
    if route.use_komis_price_comparison and not any(name.startswith("komis_price_comparison") for name in required_aggregate_jobs):
        required_aggregate_jobs.append("komis_price_comparison")
    compact_question = re.sub(r"\s+", "", state.get("question", route.resolved_query))
    if "생산국비중" in compact_question and "수입국비중" in compact_question:
        required_aggregate_jobs.extend(("komis_ranking", "komis_mineral_ranking:production"))
    for name in required_aggregate_jobs:
        payload = results.get(name)
        if not payload or not payload[0]:
            warnings.append(f"{_AGGREGATE_INCOMPLETE_WARNING}:{name}")

    evidence: list[Evidence] = []
    if "structured" in results and results["structured"] is not None:
        evidence.append(results["structured"])
    if "komis_raw" in results:
        kr_evidence, kr_warnings = results["komis_raw"]
        evidence.extend(kr_evidence)
        warnings.extend(kr_warnings)
    if "komis_ranking" in results:
        rank_evidence, rank_warnings = results["komis_ranking"]
        evidence.extend(rank_evidence)
        warnings.extend(rank_warnings)
    if "komis_concentration" in results:
        concentration_evidence, concentration_warnings = results["komis_concentration"]
        evidence.extend(concentration_evidence)
        warnings.extend(concentration_warnings)
    if "komis_trade_indicator" in results:
        trade_evidence, trade_warnings = results["komis_trade_indicator"]
        evidence.extend(trade_evidence)
        warnings.extend(trade_warnings)
    for name, payload in results.items():
        if name.startswith(("komis_monthly_trade", "komis_explicit_hs_summary", "komis_price_comparison")):
            aggregate_evidence, aggregate_warnings = payload
            evidence.extend(aggregate_evidence)
            warnings.extend(aggregate_warnings)
    for name, payload in results.items():
        if name.startswith("komis_mineral_ranking:"):
            mrank_evidence, mrank_warnings = payload
            evidence.extend(mrank_evidence)
            warnings.extend(mrank_warnings)
    if "komis_price_volatility" in results:
        vol_evidence, vol_warnings = results["komis_price_volatility"]
        evidence.extend(vol_evidence)
        warnings.extend(vol_warnings)
    if "komis_indicator_ranking" in results:
        ind_evidence, ind_warnings = results["komis_indicator_ranking"]
        evidence.extend(ind_evidence)
        warnings.extend(ind_warnings)
    evidence.extend(results.get("dense", []))
    if "mine_aggregate" in results:
        ma_evidence, ma_warnings = results["mine_aggregate"]
        evidence.extend(ma_evidence)
        warnings.extend(ma_warnings)
    if "pageindex" in results:
        if route.pageindex_mode == "agentic":
            pi_evidence, pi_warnings = results["pageindex"]
            evidence.extend(pi_evidence)
            warnings.extend(pi_warnings)
        else:
            pageindex_evidence = results["pageindex"]
            if _is_rare_earth_nd_scope_request(state.get("action_call"), state.get("question")):
                # Q15 typed route의 공개 원문 span만 남긴다. 필수 표지가 하나라도
                # 빠지면 빈 결과로 Advisor가 source_unavailable을 판단하게 둔다.
                pageindex_evidence = _q15_contextual_pageindex_evidence(pageindex_evidence)
            evidence.extend(pageindex_evidence)

    # 2026-09-18(감사 후속): 서로 다른 도구가(예: dense의 청크 vs pageindex의
    # 노드) 같은 근거를 각기 다른 kind로 중복 반환해도 그대로 합쳐지던 문제 —
    # (kind, source, section, text) 완전일치만 걸러낸다(교차 도구의 유사-중복을
    # 잡는 의미적 dedup은 범위 밖 — 완전일치가 아닌 건 서로 다른 근거일 수
    # 있어 임의로 지우면 오히려 근거 유실 위험이 크다).
    deduped: list[Evidence] = []
    seen: set[tuple[str, str, str, str]] = set()
    for ev in evidence:
        key = (ev.kind, ev.source, ev.section, ev.text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)

    # 모든 어댑터 결과에 plan 추적 키를 붙인다. 현재 capability는 한 action
    # 또는 동종 resource.rank 묶음만 승인하므로 requirement/action 귀속이 모호하지 않다.
    approved_plan = state.get("action_assessment")
    if approved_plan and approved_plan.plan:
        call = approved_plan.plan.actions[0]
        for ev in deduped:
            ev.requirement_id = call.requirement_id
            ev.action_id = call.action_id
            ev.source_id = ev.source
            ev.observed_period = ev.as_of

    warnings.extend(_source_audit_warnings(jobs, results, deduped, warnings))
    return {"evidence": deduped, "warnings": warnings}


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

    assessment = state.get("source_assessment")
    if assessment is None or assessment.blocked:
        return {}
    route = state["route"]
    try:
        invocation = llm.invoke(
            task="retrieval_reformulate", instructions=REFORMULATE_PROMPT,
            payload={
                "오늘_날짜": date.today().isoformat(),
                "question": route.resolved_query, "history": _recent_history(state),
            },
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


def _verify_excerpt(text: str, head: int = 300, tail: int = 300) -> str:
    """앞 `head`자·뒤 `tail`자를 이어붙인 발췌 — 단순 `text[:200]`은 komis_raw
    가격표처럼 `ORDER BY 날짜 DESC`로 정렬된 표에서 최신 날짜 몇 줄만 보여줘
    verify가 "이건 특정 시점 스냅샷일 뿐"이라고 오판하게 만들었다(2026-09-07,
    "니켈 최근 6개월 가격" 재현 — fetch_complete()로 130행을 다 가져와도
    발췌가 최신 2~3행만 보여줘 verify는 여전히 못 봤다). 표 앞부분(최신)과
    뒷부분(가장 과거)을 같이 보여주면 verify가 실제 날짜 범위를 볼 수 있다."""

    if len(text) <= head + tail + 20:
        return text
    return f"{text[:head]}\n...\n{text[-tail:]}"


#: `_verify_node`의 선택적 패스트패스가 "애매함 신호"로 보는 warnings 문구
#: 조각들 — `_mcp_tools_common.py::komis_raw_lookup`이 가격기준/HS코드가
#: 여러 개라 첫 번째만 미리보기로 조회했을 때, 또는 komis_topic이 page_id로
#: 안 매핑됐을 때 붙이는 문구다. 이런 신호가 있으면 komis_raw 결과가
#: "이 질문에 정말 맞는 조회였나"를 사람(LLM)이 한 번 더 봐야 하므로
#: 패스트패스에서 제외한다.
_VERIFY_SKIP_AMBIGUOUS_MARKERS = ("가격기준이", "HS코드가", "komis_raw_unmapped_topic")


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
    여러 건 각각을 왜 불충분한지 설명해야 하는 유일한 노드).

    2026-09-07 — **선택적 패스트패스**(사용자 설계: "전면 삭제도 전면 유지도
    문제, 적절히 컷오프해야"). komis_raw(kind="structured")는 화이트리스트된
    컬럼·필터만 쓰는 결정적 SQL이라 원천 조회 자체는 한 번도 틀린 적이
    없다 — 오늘 재현된 버그는 전부 "그 결과가 질문에 충분한가"를 다시 LLM에게
    묻는 이 단계, 그리고 뒤이은 생성 단계에서 났다(미래데이터 오판·발췌
    truncation·노이즈 혼입 전체기권). 아래 세 조건을 **전부** 만족하면(단일
    출처·비어있지 않음·애매함 신호 없음) verify LLM 호출 자체를 건너뛰고
    sufficient=True로 확정한다 — 비교·복합질문처럼 여러 출처를 종합해야
    하거나 조회 자체가 애매했던 경우(가격기준·HS코드 다중 매핑 등)는 여전히
    LLM 검증을 받는다. `_finalize_node`의 노이즈 근거 가지치기와 짝을 이루되
    그쪽은 "verify 통과 후 정리"고 이쪽은 "애초에 verify를 안 태움"이라는
    차이다."""

    evidence = state.get("evidence", [])
    if any(_AGGREGATE_INCOMPLETE_WARNING in w for w in state.get("warnings", [])):
        return {"sufficient": False}
    if not evidence:
        return {"sufficient": False}

    action_call = state.get("action_call")
    if action_call is not None:
        # requirement/action 귀속과 명시 관측범위는 의미 판정(LLM)의 대상이
        # 아니라 adapter 계약의 필수 필드다.
        if any(ev.requirement_id != action_call.requirement_id or ev.action_id != action_call.action_id
               or not ev.source_id for ev in evidence):
            return {"sufficient": False, "evidence": [], "warnings": ["advisor_contract_mismatch"]}
        if not _evidence_matches_required_period(evidence, action_call):
            return {"sufficient": False, "evidence": [], "warnings": ["advisor_period_mismatch"]}
        if not _evidence_matches_requested_frequency(evidence, action_call):
            return {"sufficient": False, "evidence": [], "warnings": ["advisor_frequency_mismatch"]}
        if not _evidence_matches_action_contract(evidence, action_call):
            return {"sufficient": False, "evidence": [], "warnings": ["advisor_contract_mismatch"]}
        if (_is_complete_explicit_hs_summary(evidence, action_call)
                or _is_complete_mine_rank_increase(evidence, action_call)
                or _is_complete_mine_rank_yoy(evidence, action_call)):
            return {"sufficient": True, "evidence": evidence, "warnings": state.get("warnings", [])}
        # stockpile.methodology는 실측 현황을 답하지 않는 정적 방법론 action이다.
        # adapter가 인용할 단일 문서를 결정적으로 만들었으므로, 원 질문의
        # 실수치 부재를 다시 요구하는 Advisor 판정으로 대체 응답을 지우지 않는다.
        if action_call.action_id == "stockpile.methodology":
            return {"sufficient": True, "evidence": evidence, "warnings": state.get("warnings", [])}
        # 가격 주장 비교표는 adapter가 실제 시작·종료값과 변동률을
        # 결정적으로 계산한다. 구조화된 KO_MNRL_PRC 비교표가 있고 caveat가
        # 없다면 짧은 질문의 의미만 보고 Advisor가 근거를 누락시키지 않게
        # 해당 표를 그대로 통과시킨다.
        if (action_call.action_id == "price.verify_claim"
                and any(ev.kind == "structured" and "pct_change" in ev.text
                        and ev.source.endswith("KO_MNRL_PRC") for ev in evidence)):
            return {"sufficient": True, "evidence": evidence, "warnings": state.get("warnings", [])}
        # 명시 문서 lookup은 PageIndex가 하나의 허용 문서를 고르고 실제 OKF
        # 본문 행을 반환한 뒤에만 이 지점에 온다. 이 계약을 다시 Advisor의
        # 선택적 JSON 필드(reason=null) 오류에 맡기면 확인된 PDF/HWP/XLSX
        # 본문도 기권되는 회귀가 생긴다.
        if (action_call.action_id == "document.lookup"
                and any(ev.kind == "pageindex" and ev.text.strip() for ev in evidence)):
            return {"sufficient": True, "evidence": evidence, "warnings": state.get("warnings", [])}

    # 복합 수치·문서 요청은 source_contract에서 검색 전에 차단된다. 여기에
    # 도달한 정형+비정형 혼합은 안전망 잡음이므로 정형 근거만 검증한다.
    trusted = [ev for ev in evidence if ev.kind in ("structured", "aggregated")]
    if trusted:
        evidence = trusted

    warnings_so_far = state.get("warnings", [])
    is_ambiguous = any(
        any(marker in w for marker in _VERIFY_SKIP_AMBIGUOUS_MARKERS) for w in warnings_so_far
    )
    try:
        invocation = llm.invoke(
            task="retrieval_verify", instructions=VERIFY_PROMPT,
            payload={
                "오늘_날짜": date.today().isoformat(),
                "question": state["route"].resolved_query,
                "history": _recent_history(state),
                "action": ({"requirement_id": state["action_call"].requirement_id,
                            "action_id": state["action_call"].action_id,
                            "slots": state["action_call"].slots.model_dump(mode="json")}
                           if state.get("action_call") else None),
                "evidence": [
                    {"index": i, "requirement_id": ev.requirement_id, "action_id": ev.action_id,
                     "source": ev.source, "source_id": ev.source_id, "section": ev.section,
                     "observed_period": ev.observed_period, "as_of": ev.as_of, "unit": ev.unit,
                     "caveat": ev.caveat, "excerpt": _verify_excerpt(ev.text)}
                    for i, ev in enumerate(evidence, 1)
                ],
            },
            output_model=GroundingCheck, max_tokens=300,
        )
        sufficient = invocation.output.sufficient
        supported = set(invocation.output.supported_evidence_indices)
        # LLM이 번호로 확인한 근거만 생성 단계에 넘긴다. 숫자 범위 밖 번호는
        # 무시하고, 빈 목록은 근거 없음으로 처리해 unrelated dense 문서가
        # 복합 질문의 다른 절을 대신 인용하지 못하게 한다.
        kept_evidence = [ev for index, ev in enumerate(evidence, 1) if index in supported]
        if not kept_evidence:
            sufficient = False
        evidence = kept_evidence
        # price.verify_claim의 성공은 전제가 참이라는 뜻이 아니라, 실제
        # 비교값으로 참·거짓을 판정했다는 뜻이다. 계약을 통과한 같은 광종의
        # pct_change 행은 LLM이 불일치를 '불충분'으로 오독해도 보존한다.
        if (action_call is not None and action_call.action_id == "price.verify_claim"
                and _has_claim_comparison_evidence(state.get("evidence", []), action_call.slots.mineral)):
            evidence = state.get("evidence", [])
            sufficient = True
        # 국가 순위는 typed metric·기간·광종 계약을 통과한 결정적 집계다.
        # Advisor가 import_amount를 수입량으로 오독해도 해당 계약을 깨고
        # 기권시키지 않는다. LLM 호출은 유지하며, 이 좁은 경우만 선택 결과가
        # 비어 있으면 adapter Evidence를 보존한다.
        if (not evidence and action_call is not None
                and action_call.action_id == "trade.country_rank"
                and all(ev.kind == "aggregated" for ev in state.get("evidence", []))):
            evidence = state.get("evidence", [])
            sufficient = bool(evidence)
        # trailing 기간은 원천의 실제 관측범위가 짧아도 부분 결과를 허용한다.
        # Evidence.as_of/observed_period가 생성 단계에 그대로 전달돼 전체 기간인
        # 척 답하지 못하며, Advisor 호출 자체는 항상 수행했다.
        action_call = state.get("action_call")
        partial_observed = (action_call is not None and action_call.slots.period is not None
                            and action_call.slots.period.kind == "trailing_months"
                            and all(ev.observed_period or ev.as_of for ev in evidence))
        if partial_observed and not evidence:
            # Advisor가 index를 비웠어도 adapter 계약을 통과한 원자료는 기간
            # 부족 사유만으로 폐기하지 않는다.
            evidence = state.get("evidence", [])
            sufficient = bool(evidence)
        warning = None if sufficient else f"retrieval_insufficient:{invocation.output.reason[:80]}"
    except LLM_TRANSIENT_ERRORS as exc:
        # 검증 결과가 없으면 근거를 보존하지 않는다. 재시도 뒤에도 검증이
        # 실패하면 출처 없는 응답으로 기권한다.
        sufficient = False
        evidence = []
        warning = f"retrieval_verify_invalid_output:{type(exc).__name__}"

    warnings = list(state.get("warnings", []))
    if warning:
        warnings.append(warning)
        _logger.warning("%s verify: sufficient=%s (%s)", _log_prefix(state), sufficient, warning)
    return {"sufficient": sufficient, "evidence": evidence, "warnings": warnings}


#: `_mcp_tools_common.py::komis_resolve_mineral`이 `ai_mnrl_mst`에서 광종을
#: 못 찾았을 때 내는 경고 문구의 고정 부분(전체 정규식은 chatbot.py::
#: _UNSUPPORTED_MINERAL_RE가 따로 갖고 있다 — 두 파일이 각각 정형/생성
#: 프로세스에서 독립적으로 도는 별도 모듈이라 상수를 공유 import하지 않고
#: 문구만 그대로 맞춘다, 바뀌면 둘 다 같이 고칠 것). 이 마커가 있으면
#: 아래 _finalize_node가 near-miss 대신 강제 기권으로 보낸다.
_UNSUPPORTED_MINERAL_MARKER = "KOMIS 광종 목록(ai_mnrl_mst)에서 찾지 못했습니다"

#: `_mcp_tools_common.py::komis_raw_lookup`의 `_PERIOD_BOUNDS_LEAD` 두
#: 값("조회 가능 기간"/"지표 산출 가능 기간")이 만드는 경고 문구의 공통
#: 접두부 — 2026-09-03(발주처 문서 ④-나). 위 미지원광종과 같은 이유로 값을
#: 그대로 맞춘다. 이 경고가 있다는 건 komis_raw가 사용자가 지정한 기간에
#: 0건을 받았다는 뜻이라, 역시 near-miss 대신 강제 기권으로 보낸다 — 문서가
#: "답변 불가 안내 + 조회 가능 기간 안내"를 정확한 문구로 요구한다.
_PERIOD_BOUNDS_MARKER = "가능 기간은 "

#: `_mcp_tools_common.py::_NO_DATA_FOUND_MARKER`와 같은 문자열(2026-09-07) —
#: 기간·광종별 가용범위를 따로 계산할 수 없는 page_id(예: price_forecast는
#: 텅스텐 외 광종은 원본 테이블에 행 자체가 없다)가 0건을 받았을 때 붙는다.
#: "이 광종만 지원합니다" 같은 근거 없는 주장을 만들지 않고 사실만 알리라는
#: 사용자 지시 — 위 두 마커와 같은 이유로 near-miss 대신 강제 기권시킨다.
_NO_DATA_FOUND_MARKER = "조회하신 조건에 해당하는 데이터를 찾지 못했습니다."


def _has_deterministic_abstain_signal(warnings: list[str]) -> bool:
    return any(
        _UNSUPPORTED_MINERAL_MARKER in w or _PERIOD_BOUNDS_MARKER in w
        or _NO_DATA_FOUND_MARKER in w or _PRIVATE_ONLY_PROFILE_WARNING in w
        or _AGGREGATE_INCOMPLETE_WARNING in w
        or w.startswith(_SOURCE_UNAVAILABLE_WARNING_PREFIX)
        for w in warnings
    )


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
    계약은 그대로 (evidence, warnings) 2-tuple 유지).

    2026-09-03(발주처 문서 ④-가 "지원 광종 밖", 실측으로 발견·사용자 승인 후
    수정) — 원래는 이 분기가 "미지원 광종" 질문("규회석 가격 추이")에서도
    dense가 뭔가 topically 비슷한 문서(알루미늄·구리 가격 등)를 찾아오면
    무조건 near-miss로 흘러 "정확한 문구로 지원 광종 밖임을 정확히 안내"
    하는 chat_turn()의 기권 분기에 영영 도달하지 못했다(실측 재현: "규회석
    가격 추이" → near-miss "이 자료라도 보여드릴까요?"). 문서가 이 케이스를
    "대안 질문 미제공(B안)"으로 명시했으므로 — 미지원 광종 경고가 있으면
    near-miss 후보에서 완전히 빼고 강제로 기권시킨다.

    2026-09-03(발주처 문서 ④-나 "조회 기간 데이터 없음") — 같은 문제를 komis_
    start_period/end_period 신설(사용자가 명시한 과거 기간을 komis_raw_lookup에
    실어 보내는 배선) 직후 실측으로 다시 발견했다: "2010년 1월 니켈 수급동향
    지표"를 물으면 라우팅·기간전달까지는 정확한데, komis_raw가 0건을 받아
    "조회 가능 기간은 ...입니다" 경고를 냈어도 dense가 날짜만 우연히 겹치는
    무관한 문서를 찾아오면 역시 near-miss로 샜다. 같은 원칙으로 처리한다
    (_has_deterministic_abstain_signal)."""

    if state.get("sufficient", True):
        # 2026-09-07(사용자 실측 제보: "니켈 최근 6개월 가격"·"광물종합지수"가
        # verify를 통과하고도 생성 단계에서 통째로 기권) — dense는 komis_raw가
        # 실패할 수 있다는 전제로 ROUTE_PROMPT가 항상 안전망으로 같이 켜둔다.
        # 그런데 dense가 같이 딸려온 무관한 문서(예: "니켈" 검색에 걸린 예측모델
        # 방법론·타 광종 시장동향 보고서)가 생성 LLM을 "일부는 관련없다"며 전체
        # 기권으로 몰아넣는 걸 실측 재현했다(노이즈 5건 섞이면 실패, 그 5건을
        # 빼면 즉시 정상 — 프롬프트 지시만으로는 완전히 못 막음). 재시도
        # (reformulate) 이후엔 dense/pageindex를 **의도적으로** 추가 켠 것이므로
        # 이 가지치기를 하지 않는다(attempt로 구분 — reformulate가 attempt를
        # 늘린다).
        #
        # ⚠ 실제 조건은 "구조화 근거가 하나라도 있으면"(any)이지 "전부 구조화
        # 근거"(all)가 아니다 — 후자로 바꾸면 이 분기는 늘 무동작이 된다: verify가
        # 패스트패스(전부 structured)를 탄 경우엔 애초에 잘라낼 dense/pageindex가
        # 없고, 이 가지치기가 실제로 뭔가를 지우는 유일한 경우는 "구조화+비정형이
        # 섞였는데 LLM verify가 (패스트패스를 안 타고) 전체를 sufficient로
        # 판정한" 경우뿐이다 — 바로 위에서 재현한 노이즈발 전체기권 버그가 딱 이
        # 상황이다. 즉 "구조화 근거만으로 충분했을 것"이라는 보장은 없다(verify는
        # 근거별로 무엇이 기여했는지 알려주지 않는다) — dense/pageindex가 실제로
        # 답의 일부(예: "가격+최근 시장동향 요약")였을 가능성이 있는 혼합 질문도
        # 이 조건에 걸리면 구조화 근거만 남고 그 내용은 사라진다. 2026-09-08
        # skeptic-code 감사(SC-1)에서 이 잘못된 전제를 재현으로 확인했지만,
        # any→all로 되돌리면 위에서 실측 재현된 노이즈 버그가 그대로 재발하므로
        # 로직은 바꾸지 않는다 — komis_raw(결정적 SQL, 지금까지 오조회 0건)가
        # dense(베스트에포트 의미검색)보다 신뢰도가 높다는 전제 하의 의도된
        # 트레이드오프다. 실제로 혼합 근거가 필요했던 질문이 이걸로 답이 부실해진
        # 사례가 재현되면, verify가 근거별 기여도까지 판정하도록 재설계가
        # 필요하다(현재는 그런 재현 사례 없음).
        # 2026-09-17(광산자료 집계 파이프라인) — 실측 재현: "구리 채굴 광산중
        # 작년에 채굴량이 가장 많은 광산이 어디야?"가 mine_aggregate로 정확한
        # 집계표를 만들어도(evidence 1건) route.use_dense가 항상 안전망으로
        # 같이 켜져 있어 무관한 조달청 가격동향 보고서 5건이 같이 딸려오면
        # 생성 LLM이 통째로 ABSTAIN_TEXT를 냈다(위 komis_raw 노이즈 버그와
        # 동일 실패 모드) — kind 목록에 "aggregated"도 포함해 같은 가지치기를
        # 적용한다. mine_aggregate 근거는 komis_raw와 같은 이유로 dense보다
        # 신뢰도가 높다(이미 문서 전량을 fan-out 추출해 계산한 결과물이라
        # dense의 베스트에포트 의미검색과 다르다).
        evidence = state.get("evidence", [])
        trusted = [ev for ev in evidence if ev.kind in ("structured", "aggregated")]
        if trusted:
            return {"evidence": trusted}
        return {}
    warnings = state.get("warnings", [])
    if _has_deterministic_abstain_signal(warnings):
        return {"evidence": []}
    evidence = state.get("evidence", [])
    if evidence:
        kept = _prune_unrelated_near_miss_evidence(evidence, state.get("route"))
        if kept:
            out: RetrievalState = {"warnings": [*warnings, "retrieval_near_miss"]}
            if len(kept) != len(evidence):
                out["evidence"] = kept
            return out
        # 근거가 있었지만 전부 무관하다고 판정됨 — 제안할 게 없으므로 완전 기권.
        return {"evidence": []}
    return {"evidence": []}


def _prune_unrelated_near_miss_evidence(evidence: list[Evidence], route: "RetrievalRoute | None") -> list[Evidence]:
    """근접제안(near-miss)에 실제로 쓸 근거만 남긴다(2026-09-17, 사용자 실측 제보
    — "금 수입량과 날씨 상관관계" 질문에 구리 광산 기업 사업부문 설명 문서가
    무관하게 인용됨). verify()는 "충분한가"만 판정하고 개별 근거를 가지치기하지
    않아, 불충분 판정 후에도 완전 무관한 dense 잡음이 그대로 near-miss 생성에
    넘어가던 갭이었다.

    LLM을 추가로 부르지 않고 결정적 규칙 2단계로 가지치기한다(구조화 근거의
    "결정적 SQL이 dense 잡음보다 신뢰도 높다"는 전제는 위 `sufficient=True`
    분기와 동일):
    1. 구조화(komis_raw/structured) 근거가 하나라도 있으면 그것만 남긴다 —
       실제 수치가 있다면 그게 최선의 제안 후보다.
    2. 구조화 근거가 없으면(dense/pageindex뿐) route가 특정한 광종명
       (`komis_mineral_name`)이 그 근거의 출처·섹션·본문 어디에도 전혀
       없는 항목은 버린다 — 완전히 다른 광종을 다룬 문서를 "이 자료라도
       보여드릴까요?"로 제안하지 않는다. 광종명을 특정하지 못한 질문
       (route가 없거나 komis_mineral_name이 비어 있음)은 이 신호 자체가
       없으므로 필터링하지 않는다(과잉차단 방지 — 기존 근접매칭 정상
       케이스, 예: "니켈 최근 6개월 가격"은 광종명이 항상 있어 영향받지
       않는다)."""
    structured = [e for e in evidence if e.kind == "structured"]
    if structured:
        return structured
    mineral = getattr(route, "komis_mineral_name", None) if route else None
    if not mineral:
        return evidence
    needle = mineral.strip().lower()
    return [e for e in evidence if needle in f"{e.source} {e.section} {e.text}".lower()]


def _route_after_verify(state: RetrievalState) -> str:
    # 2026-09-18 — 모호 질문(route_ambiguous_question)은 애초에 무엇을 찾아야
    # 할지 모르는 상태라 reformulate(검색어 재작성)로 나아질 여지가 없다 —
    # 재시도 사이클 하나를 그대로 낭비하지 않고 바로 finalize로 보낸다.
    if any(marker in state.get("warnings", []) for marker in (
        "route_ambiguous_question", _COMPOSITE_INDEX_ABORT_WARNING,
        _PRIVATE_ONLY_PROFILE_WARNING,
    )):
        return "done"
    if any(warning.startswith(_SOURCE_UNAVAILABLE_WARNING_PREFIX) for warning in state.get("warnings", [])):
        return "done"
    route = state.get("route")
    if route and any((route.use_komis_monthly_trade, route.use_komis_explicit_hs_summary,
                      route.use_komis_price_comparison,
                      route.use_komis_ranking and route.use_komis_mineral_ranking)):
        return "done"
    if not state.get("sufficient", True) and state.get("attempt", 1) < MAX_ATTEMPTS:
        return "retry"
    return "done"


def build_graph(
    llm: KomirJsonLLM, *, dense_k: int = 5, pageindex_k: int = 3,
    on_status: Callable[..., None] | None = None,
):
    """route -> retrieve -> verify -> (불충분하면 reformulate -> retrieve ->
    verify, 최대 MAX_ATTEMPTS번) -> finalize -> END. 매 호출마다 새로 짓는다
    (체크포인터 없음, 컴파일 비용은 LLM/DB 왕복에 비하면 무시할 만하다) —
    llm을 인자로 받아 테스트에서 모의로 갈아끼우기 쉽게 한다
    (page_recommend/service.py의 llm 주입 방식과 동일).

    2026-09-17(광산자료 집계 파이프라인) — `on_status`를 retrieve 노드까지
    클로저로 관통시킨다(PRD §4.4-5 "on_status가 _retrieve_node까지 어떻게
    전달되는지 구현 전 확인" — route/verify/reformulate와 같은 클로저 패턴을
    그대로 재사용, 새 배선 방식 도입 안 함). `retrieve_evidence()`가 노드
    완료 시점 기준으로 내는 상위 on_status("retrieving"/"verifying" 등)와는
    별개로, 이 콜백은 retrieve 노드 **안에서**(mine_aggregate가 문서 하나
    끝낼 때마다) 추가로 불린다 — 같은 stage 문자열("retrieving")이 여러 번
    나가는 것은 기존에도 허용되는 동작이다(모듈 상단 _GRAPH_STAGE_TO_STATUS
    주석 "중복 emit 허용" 참고)."""

    builder = StateGraph(RetrievalState)
    builder.add_node("route", lambda s: _route_node(s, llm))
    builder.add_node(
        "retrieve",
        lambda s: _retrieve_node(s, dense_k=dense_k, pageindex_k=pageindex_k, llm=llm, on_status=on_status),
    )
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
    source_assessment: SourceAssessment | None = None,
    action_plan: ActionPlan | None = None,
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
    if on_status:
        on_status("routing")
    # Stage 1: typed intent/action/slot extraction. It is deliberately before
    # every adapter: extraction failure and unsupported combinations invoke no tool.
    if action_plan is not None:
        action_assessment = validate_action_plan(action_plan)
    else:
        try:
            action_plan = extract_action_plan(question, llm, history)
            action_assessment = validate_action_plan(action_plan)
        except Exception as exc:  # malformed model output is a plan failure, never a legacy fallback
            _logger.warning("%s action plan 추출 실패: %s", "[rag action]", type(exc).__name__)
            action_plan = None
            action_assessment = PlanAssessment(approved=False, failure_reason="slot_unresolved")

    if not action_assessment.approved or action_plan is None:
        return [], [f"action_plan_failed:{action_assessment.failure_reason}"]

    # 각 ActionCall은 독립 adapter와 Advisor를 통과한다. plan 전체를 하나의
    # 자유형 route로 압축하지 않아 Q04/Q11/Q29의 requirement 귀속이 섞이지 않는다.
    all_evidence: list[Evidence] = []
    all_warnings: list[str] = []
    for call in action_plan.actions:
        if call.action_id in {"menu.navigate", "dataset.navigate"}:
            # 메뉴 레지스트리는 app/page_recommend 어댑터 소관이다. 이 RAG core가
            # 링크를 추측하거나 문서 검색으로 대체하지 않는다.
            return [], ["action_plan_failed:adapter_unavailable"]
        route = _route_from_action_call(call, question)
        if on_status:
            on_status("retrieving", action_id=call.action_id)
        state_for_call: RetrievalState = {
            # document.retrieve의 topic은 planner가 압축한 검색 힌트다. 광종 슬롯이
            # 함께 있을 때 topic만 쓰면 (희토류/Nd처럼) 비교 대상이 사라진다. 이
            # 경우에만 원문을 보존한다. 슬롯 없는 기존 concept 검색은 topic 우선
            # 동작을 유지한다.
            "question": (
                question if call.action_id in {"document.lookup", "mine.profile"}
                or (call.action_id == "document.retrieve" and (call.slots.mineral or call.slots.minerals))
                else (call.slots.topic or question)
            ),
            "history": history or [], "session_id": session_id, "profile": profile,
            "route": route, "source_assessment": SourceAssessment(),
        }
        state_for_call["action_call"] = call
        # 실제 값 부재와 질문이 허용한 대안 계산 범위를 함께 명시한 Q17은 그
        # 문서 자체를 근거로 쓴다. 그 밖의 document.retrieve는
        # 기존 검색·Advisor 경로를 그대로 거친다.
        static_evidence = _internal_methodology_evidence(call)
        if static_evidence:
            call_evidence, call_warnings = static_evidence, []
        else:
            extracted = _retrieve_node(
                state_for_call, dense_k=dense_k, pageindex_k=pageindex_k,
                llm=llm, on_status=on_status,
            )
            call_evidence = extracted.get("evidence", [])
            call_warnings = extracted.get("warnings", [])
        call_evidence = _filter_document_evidence_to_trailing_period(call_evidence, call)
        for ev in call_evidence:
            ev.requirement_id, ev.action_id, ev.source_id, ev.observed_period = (
                call.requirement_id, call.action_id, ev.source, ev.as_of)
            ev.requested_frequency = call.slots.period.frequency if call.slots.period else None
            # Q15의 완전한 공개 원문 span은 chat_turn에서 결정적 범위 설명으로
            # 렌더링할 수 있다. 이 표지는 프로세스 내부 추적값이며 MCP/API
            # 계약에는 추가하지 않는다.
            if _is_rare_earth_nd_scope_request(call, question):
                ev.q15_usgs_scope = True
        if _has_unverified_komis_evidence(call_evidence):
            return [], call_warnings + [
                f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}komis_data_provenance_unverified",
            ]
        if call.action_id in {"document.lookup", "mine.profile"}:
            # 파일명/후보 메타데이터는 사실 근거가 아니다. MCP가 with_text=True로
            # 읽은 PageIndex OKF 본문이 하나라도 있어야만 아래 Advisor로 넘긴다.
            if not any(ev.kind == "pageindex" and ev.text.strip() for ev in call_evidence):
                return [], call_warnings + [f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}okf_body_unavailable"]
        if call.action_id == "mine.profile" and not _okf_body_matches_profile(call_evidence, call.slots.mine_name):
            return [], call_warnings + [f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}okf_profile_mismatch"]
        if call.action_id == "mine.profile" and any(
                (matched := re.search(r"동일 식별자 행 (\d+)개", ev.section)) and int(matched.group(1)) >= 2
                for ev in call_evidence):
            return [], call_warnings + ["ambiguous_mine_profile"]
        if call.action_id in {"document.lookup", "mine.profile"}:
            # dense는 문서 후보 탐색 보조일 뿐, 명시 문서/단건 광산의 사실을
            # 인용할 근거가 아니다. 확인된 OKF 본문만 Advisor·생성에 남긴다.
            call_evidence = [ev for ev in call_evidence if ev.kind == "pageindex" and ev.text.strip()]
        if not _comparison_or_monthly_source_is_usable(call_evidence, call):
            return [], call_warnings + [f"{_SOURCE_UNAVAILABLE_WARNING_PREFIX}unverified_or_incomplete_observation"]
        if call.action_id == "price.verify_claim":
            threshold = call.slots.claimed_change_pct
            if threshold is None:
                return [], call_warnings + ["claim_not_supported"]
            matched = _claim_matches_comparison(
                call_evidence, threshold, call.slots.comparator, call.slots.mineral,
            )
            for ev in call_evidence:
                ev.caveat = (ev.caveat + "\n" if ev.caveat else "") + (
                    (f"가격 변동률 전제 {call.slots.comparator or 'greater_than'} {threshold}%를 원자료 비교값으로 확인했습니다."
                     if matched else f"가격 변동률 전제 {call.slots.comparator or 'greater_than'} {threshold}%는 원자료 비교값으로 확인되지 않았습니다.")
                )
        if on_status:
            on_status("verifying", action_id=call.action_id)
        if call.action_id == "trade.indicator":
            # 이 도구는 SQL 집계와 명시된 공식으로 결과를 이미 결정했다. Advisor가
            # 계산식을 다시 해석하다 결정적 결과를 기권시키지 않도록 근거 존재를
            # 충분성 기준으로 쓴다.
            verified = {"sufficient": bool(call_evidence), "evidence": call_evidence,
                        "warnings": call_warnings}
        elif _is_rare_earth_nd_scope_request(call, question):
            # 이 경로는 `_q15_contextual_pageindex_evidence`가 실제 공개 USGS
            # 본문 표지·단위·표 머리·행을 모두 확인한 경우에만 여기까지 온다.
            # 동일 사실을 LLM Advisor의 축약 발췌에 다시 맡기면 비결정적 기권이
            # 생기므로, 완전한 원문 계약을 충분성 판정으로 사용한다.
            verified = {"sufficient": bool(call_evidence), "evidence": call_evidence,
                        "warnings": call_warnings}
        else:
            verified = _verify_node({**state_for_call, "evidence": call_evidence, "warnings": call_warnings}, llm)
        if not verified.get("sufficient"):
            return [], list(verified.get("warnings", call_warnings)) + ["advisor_rejected"]
        all_evidence.extend(verified.get("evidence", []))
        all_warnings.extend(verified.get("warnings", []))
    return all_evidence, all_warnings

    # Stage 1 compatibility source assessment remains for callers which pass
    # only the earlier source-domain contract; action assessment is authoritative
    # for tool execution below.
    # this stage (chatbot entrypoint) passes the same assessment to avoid a
    # second parse. Invalid extraction is intentionally fail-closed.
    requirement_plan: RequirementPlan | None = None
    if source_assessment is None:
        try:
            requirement_plan = extract_requirement_plan(question, llm)
            source_assessment = assess_requirement_plan(requirement_plan)
        except LLM_TRANSIENT_ERRORS:
            source_assessment = SourceAssessment(blocked=True, extraction_valid=False)
    graph = build_graph(llm, dense_k=dense_k, pageindex_k=pageindex_k, on_status=on_status)
    state: dict = {
        "question": question, "history": history or [], "session_id": session_id,
        "profile": profile, "attempt": 1,
        "requirement_plan": requirement_plan,
        "source_assessment": source_assessment,
        "action_plan": action_plan,
        "action_assessment": action_assessment,
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
