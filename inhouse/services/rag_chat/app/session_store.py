# -*- coding: utf-8 -*-
"""chat_session/chat_message CRUD — rag.ragkit.chatbot_store 재노출.

2026-08-13: 실제 CRUD 로직을 rag/ragkit/chatbot_store.py로 이관했다(rag 패키지
chatbot 엔트리포인트 신설과 함께 — 재구현 금지 원칙, 로직은 한 곳만 둔다). 이
모듈은 서빙 레이어의 설정 해석(get_settings().MSR_DB — DuckDB/Postgres cutover를
아는 유일한 곳)을 ragkit의 범용 CRUD에 주입하는 얇은 어댑터로만 남는다. 호출부
(routers/chat.py의 session_store.get_or_create_session 등, page_recommend 경로)는
시그니처가 그대로라 바뀌는 게 없다."""
from __future__ import annotations

import sys
from pathlib import Path


def _find_root(start: Path, marker: str) -> Path:
    """marker(상대경로 파일)를 담은 디렉토리를 위로 훑어 찾는다 — 소스트리와
    컨테이너 배포본(Containerfile이 services/shared→./shared, rag/ragkit→
    ./rag/ragkit로 평평하게 COPY)의 상대 깊이가 달라 고정 depth 대신 탐색한다
    (routers/chat.py의 같은 이름 헬퍼와 동일 패턴 — 이 파일도 독립적으로 임포트될
    수 있어 자체 path 설정을 갖는다)."""

    for candidate in (start, *start.parents):
        if (candidate / marker).is_file():
            return candidate
    raise ImportError(f"{marker}를 {start} 상위에서 찾지 못함")


_HERE = Path(__file__).resolve()
for _root in (
    _find_root(_HERE, "shared/llm_client.py"),
    _find_root(_HERE, "rag/ragkit/generate.py"),
):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from rag.ragkit import chatbot_store as _store  # noqa: E402
from rag.ragkit.chatbot_store import ChatMessage  # noqa: E402,F401

from shared.config import get_settings  # noqa: E402


def get_or_create_session(session_id: str | None, user_id: str, title: str | None = None) -> str:
    """session_id가 있으면 존재 확인 후 그대로, 없으면 새로 발급."""

    return _store.get_or_create_session(session_id, user_id, title, db_path=get_settings().MSR_DB)


def touch_session(session_id: str) -> None:
    """세션의 updated_at을 현재 시각으로 갱신(새 메시지 저장 시 호출)."""

    _store.touch_session(session_id, db_path=get_settings().MSR_DB)


def append_message(
    session_id: str,
    role: str,
    content: str,
    citations_json: str | None = None,
) -> ChatMessage:
    """메시지 하나를 저장하고 세션 updated_at을 같이 갱신한다."""

    return _store.append_message(session_id, role, content, citations_json, db_path=get_settings().MSR_DB)


def list_messages(session_id: str, limit: int = 50):
    """세션의 최근 메시지를 오래된순으로 반환(대화 히스토리 컨텍스트 구성용)."""

    return _store.list_messages(session_id, limit, db_path=get_settings().MSR_DB)
