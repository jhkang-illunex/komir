"""rag_chat(/pubchat·/prichat) SSE 클라이언트 — Streamlit 개발 데모 전용.

원본(komis-report-generator-main/streamlit_demo/api_client.py)의 `KomisApiClient.query()`
는 `/api/v1/chatbot/query` 에 JSON 을 보내고 `SearchResponse` 하나를 받았다. komir
챗봇은 SSE 스트림이라 여기서는 httpx 스트리밍으로 이벤트를 하나씩 흘려보내고
(`chat_stream()` 제너레이터), 화면(chatbot.py)이 delta 를 이어 붙이며 실시간으로
그린다. SSE 이벤트 계약은 `services/rag_chat/app/routers/chat.py` 모듈독스트링이 정본.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

import httpx

_log = logging.getLogger(__name__)

Profile = Literal["public", "private"]

#: 프로필 → 엔드포인트. `/chat` 은 라우터 미등록(404)이라 여기에도 없다.
ENDPOINT_BY_PROFILE: dict[str, str] = {"public": "/pubchat", "private": "/prichat"}


class RagChatError(RuntimeError):
    """rag_chat 서버가 유효한 응답을 주지 못했을 때."""


def client_from_env() -> "RagChatClient":
    """view·엔트리포인트가 공유하는 클라이언트 팩토리 — 환경변수로 대상 서버를 바꾼다.

    app.py 가 아니라 여기 두는 이유: Streamlit 은 app.py 를 `__main__` 으로 실행하므로
    view 에서 `from streamlit_demo.app import ...` 하면 app.py 가 모듈로 한 번 더
    실행돼 `st.set_page_config`/`st.navigation` 이 중복 호출된다."""

    import os

    base_url = os.getenv("KOMIR_RAG_CHAT_BASE_URL", "http://localhost:18002")
    timeout = float(os.getenv("KOMIR_RAG_CHAT_TIMEOUT_SECONDS", "300"))
    return RagChatClient(base_url, timeout_seconds=timeout)


@dataclass(frozen=True)
class ChatEvent:
    """SSE 이벤트 1건. event 는 session|status|delta|table|image|done.

    session·delta 는 서버가 `event:` 필드 없이(무명) 보내므로 data 의 키로 추론한다."""

    event: str
    data: dict[str, Any]


class RagChatClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 300.0) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.base_url = normalized
        self.timeout_seconds = timeout_seconds

    def health(self) -> bool:
        try:
            with httpx.Client(base_url=self.base_url, timeout=2.0) as client:
                response = client.get("/healthz")
                response.raise_for_status()
            return response.json() == {"status": "ok"}
        except (httpx.HTTPError, ValueError):
            _log.debug("rag_chat health check 실패(base_url=%s)", self.base_url, exc_info=True)
            return False

    def chat_stream(
        self,
        message: str,
        *,
        profile: Profile,
        session_id: str | None = None,
        user_id: str = "streamlit-demo",
        mode: str = "auto",
        top_k: int = 6,
    ) -> Iterator[ChatEvent]:
        """한 턴을 보내고 SSE 이벤트를 도착 순서대로 낸다(제너레이터 — 소비하는
        동안 HTTP 연결이 열려 있다)."""

        payload: dict[str, Any] = {"user_id": user_id, "message": message, "mode": mode, "top_k": top_k}
        if session_id:
            payload["session_id"] = session_id
        path = ENDPOINT_BY_PROFILE[profile]
        # read 타임아웃은 이벤트 사이 간격이다 — 서버가 15초마다 ping 을 보내고
        # 근거 조회 단계도 status 를 내보내므로 넉넉히 잡되 무한은 아니다.
        timeout = httpx.Timeout(self.timeout_seconds, connect=5.0)
        try:
            with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
                with client.stream("POST", path, json=payload) as response:
                    if response.status_code != 200:
                        body = response.read().decode("utf-8", "replace")
                        _log.warning("rag_chat %s 요청 실패(status=%s): %s", path, response.status_code, body[:200])
                        raise RagChatError(f"{path} 요청이 실패했습니다. ({response.status_code}: {body[:200]})")
                    yield from self._parse_sse(response.iter_lines())
        except httpx.RequestError as exc:
            _log.warning("rag_chat 연결 실패(profile=%s, base_url=%s): %s", profile, self.base_url, exc)
            raise RagChatError(f"rag_chat 서버({self.base_url})에 연결할 수 없습니다.") from exc

    @staticmethod
    def _parse_sse(lines: Iterable[str]) -> Iterator[ChatEvent]:
        """text/event-stream 파서 — `event:`/`data:` 필드, 빈 줄이 이벤트 경계,
        `:` 로 시작하는 줄은 주석(sse_starlette 의 `: ping`)."""

        event_name: str | None = None
        data_lines: list[str] = []

        def flush() -> ChatEvent | None:
            if not data_lines:
                return None
            raw = "\n".join(data_lines)
            try:
                data = json.loads(raw)
            except ValueError:
                data = {"raw": raw}
            if not isinstance(data, dict):
                data = {"raw": data}
            return ChatEvent(event_name or _infer_unnamed(data), data)

        for line in lines:
            if line == "":
                event = flush()
                event_name, data_lines = None, []
                if event is not None:
                    yield event
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())
        event = flush()
        if event is not None:
            yield event


def _infer_unnamed(data: dict[str, Any]) -> str:
    if "session_id" in data:
        return "session"
    if "delta" in data:
        return "delta"
    return "unknown"
