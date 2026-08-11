# -*- coding: utf-8 -*-
"""LLM 토큰 스트림 → SSE 청크 변환.

2026-08-11 확인 결과: services/shared/llm_client.py가 재노출하는
geo/llm/openai_compat.OpenAICompatChat은 원래 스트리밍을 지원하지 않았음
(complete()는 항상 완성된 응답 하나를 blocking으로 반환) — 이 요구사항
때문에 OpenAICompatChat.complete_stream()을 새로 추가했다(기존 complete()는
그대로 둠, 다수 호출자가 이미 씀). 이 모듈은 그 제너레이터를 SSE 이벤트
딕셔너리로 감싸기만 한다.

sse_event()는 완성된 "data: ...\\n\\n" 텍스트가 아니라 dict를 반환한다 —
sse_starlette.EventSourceResponse가 자체적으로 SSE 프레이밍을 하므로, 여기서
직접 문자열을 조립해 넘기면 "data: data: {...}"처럼 이중 래핑된다(실측으로
발견한 버그, 2026-08-11 — TestClient로 /chat 응답을 직접 찍어보고 확인)."""
from __future__ import annotations

import json
from collections.abc import Iterator


def sse_event(data: dict, event: str | None = None) -> dict:
    """sse_starlette가 그대로 소비하는 이벤트 딕셔너리를 만든다."""

    payload = {"data": json.dumps(data, ensure_ascii=False)}
    if event:
        payload["event"] = event
    return payload


def stream_answer(
    token_iter: Iterator[str],
    *,
    citations: list[dict] | None = None,
) -> Iterator[dict]:
    """토큰 델타 제너레이터를 SSE 이벤트 시퀀스로 변환한다.

    각 델타는 {"delta": "..."}로, 마지막에 citations를 포함한
    {"done": true, "citations": [...]}로 마무리한다(routers/chat.py의
    응답 계약 — POST /chat 문서화 참고)."""

    for delta in token_iter:
        yield sse_event({"delta": delta})
    yield sse_event({"done": True, "citations": citations or []}, event="done")
