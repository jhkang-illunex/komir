# -*- coding: utf-8 -*-
"""사용자 메시지를 두 경로 중 하나로 보내는 의도 분류 — 문서 Q&A vs KOMIS 페이지추천.

배경: /chat은 원래 비정형 문서검색(RAG) 한 경로뿐이었는데, 2026-08-11 페이지·필터
추천(app/page_recommend, komis-report-generator-main `search/` 이식)이 같은 챗봇 안에
들어오면서 매 턴 어느 경로로 보낼지 정해야 한다.

방식 선택 이유: 완벽한 자동판별을 노리지 않고 (a) 요청 바디의 명시적 `mode`가 있으면
그대로 따르고 (b) mode=auto일 때만 LLM 1회 호출로 분류한다. 분류에 실패하면 문서
Q&A로 보낸다 — 먼저 구현돼 실제로 돌던 기본 경로이고, 문서에 근거가 없으면 이미
기권(ABSTAIN)하도록 돼 있어(rag/ragkit/generate.py) 오분류 비용이 더 작다.
LLM 호출 자체가 안 되는 환경(서버 다운 등)에서도 문서 경로는 검색결과 0건 → 기권으로
안전하게 끝난다."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from shared.llm_client import KomirJsonLLM

ROUTES = ("document", "page")

#: 2026-08-28(챗봇_룰준수_감사_260828.md 라운드3) — 기존 기준("화면·메뉴·경로를
#: 찾는 질문이면 page")은 "어디서 봐?"류처럼 화면 위치를 명시적으로 묻는
#: 질문만 page로 잡고, "최근 1년간 니켈 가격 추이를 보여줘"처럼 화면 위치는
#: 안 묻지만 KOMIS 페이지가 이미 가진 정형 수치·시계열을 그대로 보여달라는
#: 질문은 document로 오분류했다(실측 확인 — page_recommend 레지스트리에
#: price_base_metals.yaml·map_korea.yaml이 정확히 이 두 질문에 대응하는 페이지를
#: 이미 갖고 있는데도 intent 단계에서 document로 걸러져 애초에 page_recommend에
#: 안 넘어갔다). 기준을 "화면 위치를 묻는가"에서 "정확한 수치·표·그래프 조회를
#: 원하는가(page) vs 배경·원인·해석 서술을 원하는가(document)"로 넓혔다 — 기존
#: document 예시 3개는 문구 그대로 유지(회귀 방지, 재실측으로 route 불변 확인).
#:
#: 2026-08-28 라운드4(같은 문서, 회귀 수정) — 위 확장이 과했다: "코발트
#: 광물종합지표의 최근 12개월 변화를 보여줘"(라운드1·2가 document 경로에서
#: 이미 다뤘던 질문)까지 "수치 조회"로 오인해 page로 넘겨버렸고, 실제
#: page_recommend는 이 질문을 개별 광종 "가격" 페이지(price_minor_metals)로
#: 잘못 추천했다(main-agent 실배포 재현 3/3 확인) — "광물종합지표"는 원자료
#: 표 하나가 아니라 여러 지표를 합성한 지수라 화면의 원자료 조회만으론 안
#: 되고 산출 배경까지 설명이 필요한데, page_recommend 레지스트리엔 이런
#: 합성지수 전용 페이지가 없어(가장 가까운 것도 개별 가격 페이지) 엉뚱한
#: 곳으로 안내됐다. 화면 위치를 지금 여기서 정확히 알 수는 없으니(그건
#: page_recommend/graph.py 소관, 이번에도 범위 밖), intent 단계에서 이
#: 유형만 document로 되돌리는 예외 규칙을 추가한다 — "가격 추이"(page 유지,
#: price_base_metals가 정확히 커버)와 "종합지표류"(document로 복귀)를
#: 구분하는 게 핵심이다.
#:
#: 같은 라운드4, 커밋 전 재검증 — 위 예외 초안을 chatbot_rule.txt 자체의
#: 예시 질문으로 경계 검증했더니 두 건이 걸렸다: 유형6 원문 예시("니켈
#: 수급동향지표 전체 데이터 보여줘", 원 감사에서 page(indicator_supply)로
#: 정상 처리돼 §8을 "준수"로 판정한 근거)가 예외에 걸려 document로
#: 잘못 떨어졌고, 유형7 두번째 예시("핵심광물지표는 어느 메뉴에서 확인할
#: 수 있어?")도 실행마다 page/document가 갈렸다. 둘 다 예외가 "지표
#: 이름"만 보고 "질문이 실제로 뭘 원하는지"는 안 봐서 생긴 과잉적용 —
#: "전체 데이터를 통째로 달라"·"어느 메뉴냐" 요청은 합성지수라도 화면
#: 안내가 정답(chatbot_rule.txt 유형6·유형7 그 자체)이므로, 예외의
#: 예외로 두 가지를 명시해 좁혔다: (1) 화면 위치를 직접 묻는 질문,
#: (2) "전체 데이터"·"원자료"를 통째로 요청하는 질문. 둘 다 20개 기존
#: 케이스 + 이 두 건까지 재검증(3회 반복)해 전부 기대대로 안정화된 것을
#: 확인한 뒤 반영했다(챗봇_룰준수_감사_260828.md 라운드4 §5 참고).
#: 2026-08-31(사용자 요청, komis_raw_lookup MCP 도구 신설에 따른 재조정) —
#: 위 라운드3/4의 "화면 위치는 안 물어도 그 화면이 보여주는 수치 자체를
#: 원하면 page"라는 기준을 없앴다. 그 기준이 있던 이유는 그 시점엔 document
#: 경로(chatbot_graph.py)가 komir 자체 산출물(수급위기 진단·수입예측·
#: 위기지수) 3종만 조회할 수 있어 "가격"·"교역"·"매장량" 같은 KOMIS 공개
#: 원천 데이터는 document로 보내봐야 못 답했기 때문이다(그래서 page로
#: 대신 보내 화면 위치라도 안내했다). 이제 chatbot_graph.py가 komis_raw_lookup
#: (public.KO_*, 화이트리스트 검증된 KOMIS 원천 조회)을 갖게 되어 document
#: 경로가 이런 수치 질문에 직접 답할 수 있다 — page는 다시 "화면·기능의
#: 위치 자체"를 묻는 질문(원래 최초 설계 의도)으로 좁힌다. 이 변경으로
#: 예전의 "합성지수 예외"·"예외의 예외" 2단 구조가 필요 없어졌다(둘 다
#: page 기준에서 "수치 조회" 갈래를 걷어내면 자동으로 사라지는 특수
#: 케이스였다) — 아래 세 조건이 예전 구조를 완전히 대체한다(모든 기존
#: 회귀 테스트 케이스 + chatbot_rule.txt 유형6·7 원문 예시로 재검증 완료,
#: 아래 예시에 전부 반영).
INTENT_PROMPT = """당신은 핵심광물 챗봇의 질문을 두 경로 중 하나로 분류한다.

정확히 하나의 JSON 객체만 반환한다. 설명·코드펜스·사고과정은 출력하지 않는다.

- page: 사용자가 원하는 게 "화면·기능의 위치" 자체이거나, 화면의 데이터를
  그대로 통째로 보고 싶어하는 경우만 해당한다. 아래 세 가지뿐이다.
  1) 어느 화면·메뉴로 가야 하는지 직접 묻는 질문.
     예) "리튬 수입 현황은 어디서 봐?", "가격 비교 화면 알려줘",
     "핵심광물지표는 어느 메뉴에서 확인할 수 있어?"
  2) 데이터 조회가 아니라 기능·설정의 위치를 묻는 질문.
     예) "관심광종 설정은 어느 메뉴야?"
  3) "전체 데이터"·"원자료"처럼 화면의 데이터를 통째로 보여달라는 질문
     (특정 수치 하나·요약된 추이가 아니라 표 전체를 그대로 원할 때).
     예) "니켈 수급동향지표 전체 데이터 보여줘"
- document: 위 세 가지가 아니면 전부 document다.
  - 특정 수치·시계열 조회도 document다(근거 조회 단계가 komir 자체
    산출물과 KOMIS 공개원천 원자료를 직접 찾아 답한다).
    예) "니켈 가격 알려줘", "최근 1년간 니켈 가격 추이를 보여줘",
    "한국의 리튬 수입 상위국을 알려줘", "코발트 광물종합지표의 최근
    12개월 변화를 보여줘"
  - 원인·배경·전망·정의·요약 등 서술형 답을 원하는 질문도 document다.
    예) "코발트 공급위기 원인이 뭐야?", "니켈 2025년 수입량 추이
    설명해줘", "DRC 광산 정책 변화 요약해줘"

핵심 구분: "어디서/어느 메뉴·화면에서 보나"처럼 화면 위치 자체를 묻거나
"전체 데이터"를 통째로 요청하면 page, 그 외 모든 수치 조회·서술형 질문은
document다. 판단이 애매하면 document를 반환한다."""


class IntentDecision(BaseModel):
    """분류 결과 — 라우팅에 쓰는 경로 이름 하나."""

    route: Literal["document", "page"]


_llm: KomirJsonLLM | None = None


def _default_llm() -> KomirJsonLLM:
    """프로세스당 1개만 만든다 — 매 요청마다 새로 만들면 OpenAICompatChat의
    커넥션풀(2026-07-08 실측으로 도입된 처리량 개선)이 매번 버려진다."""

    global _llm
    if _llm is None:
        _llm = KomirJsonLLM()
    return _llm


def classify_intent(message: str, llm: KomirJsonLLM | None = None) -> str:
    """메시지를 'document' | 'page'로 분류한다(실패 시 'document')."""

    client = llm or _default_llm()
    try:
        invocation = client.invoke(
            task="chat_intent",
            instructions=INTENT_PROMPT,
            payload={"message": message},
            output_model=IntentDecision,
            max_tokens=16,
        )
    except Exception as exc:
        # 조용히 삼키지 않고 로그엔 남긴다 — 분류가 계속 실패하면 페이지추천 경로가
        # 영영 안 타므로 운영에서 알아챌 수 있어야 한다.
        print(f"[rag_chat] 의도분류 실패, 문서 Q&A로 폴백: {type(exc).__name__}: {exc}")
        return "document"
    return invocation.output.route
