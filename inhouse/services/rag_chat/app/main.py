# -*- coding: utf-8 -*-
"""RAG 챗봇 API 엔트리 — POST /chat(user_id·session_id 필수) → retrieval/
unstructured.py+structured.py 병행 조회 → rag/ragkit/generate.py 인용강제 생성 →
streaming.py로 SSE 청크 전송 → session_store.py에 chat_message 적재.

2026-08-11(1차): structured.py(정형 템플릿 조회)를 매 턴 언제 부를지 동적으로 판단하는
로직(§5-4 "RAG 챗봇은 매 턴 LLM이 세 도구 중 무엇을 쓸지 동적으로 판단")은 아직
routers/chat.py에 안 붙어 있음 — 그 시점엔 비정형 문서검색 경로만 실제로 동작했다.

2026-08-11(2차): 페이지/필터 추천(komis-report-generator-main의 search/ LangGraph
그래프, 병합계획 결정①로 이 챗봇 기능 일부로 편입)을 app/page_recommend/로 이식하고
routers/chat.py에 배선했다 — 이제 두 경로(document|page)가 동작한다. 남은 것은
structured.py(정형 템플릿)를 세 번째 도구로 붙이는 일."""
from __future__ import annotations

from fastapi import FastAPI

from .routers.chat import router as chat_router

app = FastAPI(title="komir rag_chat")
app.include_router(chat_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
