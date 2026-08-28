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
INTENT_PROMPT = """당신은 핵심광물 챗봇의 질문을 두 경로 중 하나로 분류한다.

정확히 하나의 JSON 객체만 반환한다. 설명·코드펜스·사고과정은 출력하지 않는다.

- page: KOMIS 웹서비스가 화면에서 보여주는 정형 데이터(가격·수급지표·교역 통계 등)를
  찾는다 — "어느 화면·메뉴로 가야 하는지"를 직접 묻는 질문뿐 아니라, 화면 위치는
  안 물어도 그 화면이 보여주는 정확한 수치·표·시계열 그래프 자체를 보고 싶어하는
  질문도 포함한다. 예) "리튬 수입 현황은 어디서 봐?", "가격 비교 화면 알려줘",
  "관심광종 설정은 어느 메뉴야?", "최근 1년간 니켈 가격 추이를 보여줘",
  "한국의 리튬 수입 상위국과 국가별 비중을 알려줘"
- document: 수집된 보고서·문서를 근거로 한 서술형 답(원인·배경·전망·정의·요약 등)을
  원한다 — 수치를 언급하더라도 그 수치를 "설명"하거나 배경을 묻는 등 해석을
  원하면 document다. 예) "코발트 공급위기 원인이 뭐야?", "니켈 2025년 수입량 추이
  설명해줘", "DRC 광산 정책 변화 요약해줘"

핵심 구분: 정확한 수치·표·그래프 데이터 조회를 원하면 page, 배경·원인·해석
서술을 원하면 document다. "보여줘"·"알려줘"처럼 데이터 자체를 요청하는 동사는
page 쪽 신호, "설명해줘"·"요약해줘"·"원인이 뭐야"처럼 해석을 요청하는 동사는
document 쪽 신호다. 판단이 애매하면 document를 반환한다."""


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
