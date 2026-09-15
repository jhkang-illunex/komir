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
import re


def sse_event(data: dict, event: str | None = None) -> dict:
    """sse_starlette가 그대로 소비하는 이벤트 딕셔너리를 만든다."""

    payload = {"data": json.dumps(data, ensure_ascii=False)}
    if event:
        payload["event"] = event
    return payload


# ---- 취소선 제거(2026-09-16, 사용자 지시 "SSE로 넘기기 전에 취소선이 있는 데이터는
# 넘기지 말 것") ---------------------------------------------------------------
# 실측 경위: /prichat 답변 말미의 출처 푸터에 "기준시점 2026-08-11~2026-09-05"와
# "Argus … 2023~2026" 같은 기간 표기가 두 개 이상 들어가면, GFM 렌더러(remark-gfm의
# singleTilde 기본값 등)가 `~…~`를 취소선으로 해석해 두 물결표 사이 텍스트가
# 취소선으로 그려졌다. 서버는 마크다운을 내보내는 쪽이므로 여기서 막는다:
# - 명시적 취소선 스팬(`~~…~~`, `<s>…</s>`·`<del>`·`<strike>`)은 내용까지 통째로
#   제거한다 — 취소된 데이터는 넘기지 않는다.
# - 짝 없는 단일 `~`(기간·범위 표기)는 `\~`로 이스케이프한다 — CommonMark 백슬래시
#   이스케이프라 어느 렌더러든 `~` 글자로 보이고 취소선이 되지 않는다.
# 델타는 토큰 단위로 쪼개져 오므로 마커(`~~`)가 청크 경계에 걸릴 수 있다 —
# StrikethroughFilter가 미완성 마커를 다음 청크까지 들고 있다가 판정한다.
_STRIKE_SPAN_RE = re.compile(r"~~(?!~)[^\n]+?~~|<(s|del|strike)\b[^>\n]*>[^\n]*?</\1\s*>", re.IGNORECASE)
_STRIKE_OPEN_RE = re.compile(r"~~|<(?:s|del|strike)\b[^>\n]*>", re.IGNORECASE)
#: 청크 끝에 걸린 미완성 마커 후보 — 다음 청크가 오면 `~~`·`<del>`이 될 수 있다.
_PARTIAL_TAIL_RE = re.compile(r"(~|<[A-Za-z]{0,6})$")
_UNESCAPED_TILDE_RE = re.compile(r"(?<!\\)~")


def _escape_tildes(text: str) -> str:
    return _UNESCAPED_TILDE_RE.sub(r"\\~", text)


class StrikethroughFilter:
    """delta 텍스트 스트림에서 취소선을 걷어내는 상태 유지 필터.

    `feed(chunk)`는 지금 내보내도 안전한 텍스트만 돌려주고, 취소선 스팬이 될 수
    있는 꼬리(열린 `~~` 이후, 또는 청크 끝의 `~`/`<de`)는 버퍼에 남긴다. 열린
    마커가 같은 줄에서 닫히지 않고 줄바꿈을 만나면 취소선이 아니므로 마커를
    이스케이프해 내보낸다. `flush()`는 스트림 끝(또는 다음 비-delta 이벤트 직전)에
    남은 버퍼를 전부 내보낸다."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while self._buf:
            opened = _STRIKE_OPEN_RE.search(self._buf)
            if opened is None:
                tail = _PARTIAL_TAIL_RE.search(self._buf)
                cut = tail.start() if tail else len(self._buf)
                out.append(_escape_tildes(self._buf[:cut]))
                self._buf = self._buf[cut:]
                break
            out.append(_escape_tildes(self._buf[:opened.start()]))
            rest = self._buf[opened.start():]
            span = _STRIKE_SPAN_RE.match(rest)
            if span is not None:
                self._buf = rest[span.end():]  # 취소선 스팬 — 내용째 버림
                continue
            if "\n" in rest[opened.end():]:
                out.append(_escape_tildes(rest[:opened.end()]))  # 같은 줄에서 안 닫힘 → 글자로
                self._buf = rest[opened.end():]
                continue
            self._buf = rest  # 아직 닫힐 수 있음 — 다음 청크까지 보류
            break
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        return _escape_tildes(rest)


def strip_strikethrough(text: str) -> str:
    """스트림이 아닌 완성 텍스트용 — feed+flush 한 번."""

    f = StrikethroughFilter()
    return f.feed(text) + f.flush()
