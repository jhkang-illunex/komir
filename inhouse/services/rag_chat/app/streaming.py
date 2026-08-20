# -*- coding: utf-8 -*-
"""ChatEvent(dict payload) → SSE 이벤트 딕셔너리 변환.

2026-08-11 확인 결과: services/shared/llm_client.py가 재노출하는
geo/llm/openai_compat.OpenAICompatChat은 원래 스트리밍을 지원하지 않았음
(complete()는 항상 완성된 응답 하나를 blocking으로 반환) — 이 요구사항
때문에 OpenAICompatChat.complete_stream()을 새로 추가했다(기존 complete()는
그대로 둠, 다수 호출자가 이미 씀).

sse_event()는 완성된 "data: ...\\n\\n" 텍스트가 아니라 dict를 반환한다 —
sse_starlette.EventSourceResponse가 자체적으로 SSE 프레이밍을 하므로, 여기서
직접 문자열을 조립해 넘기면 "data: data: {...}"처럼 이중 래핑된다(실측으로
발견한 버그, 2026-08-11 — TestClient로 /chat 응답을 직접 찍어보고 확인).

2026-08-13: 토큰 스트림 → SSE 이벤트 조립 로직(멀티턴 프롬프트·인용강제·
표/차트 다중매체 판단 포함) 자체는 rag.ragkit.chatbot.chat_turn()으로
이관했다(routers/chat.py가 그 async generator를 소비해 이 sse_event()로
감싼다) — 이 모듈에는 순수 프레이밍 함수만 남는다(구 stream_answer()는
chat_turn()이 대체해 제거)."""
from __future__ import annotations

import json


def sse_event(data: dict, event: str | None = None) -> dict:
    """sse_starlette가 그대로 소비하는 이벤트 딕셔너리를 만든다."""

    payload = {"data": json.dumps(data, ensure_ascii=False)}
    if event:
        payload["event"] = event
    return payload
