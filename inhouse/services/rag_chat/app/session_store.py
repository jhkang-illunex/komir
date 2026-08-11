# -*- coding: utf-8 -*-
"""chat_session/chat_message CRUD.

대상 테이블: `data_lake/db/schema_addendum_v2.sql`(§4)의 chat_session/chat_message
— 2026-08-11 이 두 테이블만(벡터·tsvector 확장분 제외, 그쪽은 Postgres 전용 문법이라
DuckDB인 현재 MSR_DB에 못 씀 — cutover 이후 별도 적용) MSR_DB에 직접 생성해뒀다.

CHAT_SESSION_TTL_DAYS 지난 세션 정리는 아직 구현 안 함(운영 반영 시 배치로 추가)."""
from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# 컨테이너 배포본은 Containerfile이 services/shared→./shared로 평평하게 COPY하므로
# (commodity_api·rag_chat Containerfile 기존 컨벤션과 동일), import도 짧은 이름
# `shared`를 쓴다 — 소스트리에서 그대로 돌릴 때는 inhouse/services를 sys.path에 얹어
# 같은 이름이 resolve되게 맞춘다(services.ingestion처럼 inhouse/ 전체를 path에 얹는
# 방식과는 다른 컨벤션 — 이 서비스는 기존 Containerfile 관례를 따름).
_SERVICES_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICES_ROOT))

from shared.db import execute_msr, read_sql_msr  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChatMessage:
    message_id: str
    session_id: str
    role: str
    content: str
    citations_json: str | None = None
    created_at: datetime = field(default_factory=_now)


def get_or_create_session(session_id: str | None, user_id: str, title: str | None = None) -> str:
    """session_id가 있으면 존재 확인 후 그대로, 없으면 새로 발급."""

    if session_id:
        existing = read_sql_msr(
            f"SELECT session_id FROM chat_session WHERE session_id = '{_escape(session_id)}'"
        )
        if len(existing):
            return session_id

    new_id = session_id or str(uuid.uuid4())
    now = _now()
    execute_msr(
        "INSERT INTO chat_session (session_id, user_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [new_id, user_id, title, now, now],
    )
    return new_id


def touch_session(session_id: str) -> None:
    """세션의 updated_at을 현재 시각으로 갱신(새 메시지 저장 시 호출)."""

    execute_msr(
        "UPDATE chat_session SET updated_at = ? WHERE session_id = ?",
        [_now(), session_id],
    )


def append_message(
    session_id: str,
    role: str,
    content: str,
    citations_json: str | None = None,
) -> ChatMessage:
    """메시지 하나를 저장하고 세션 updated_at을 같이 갱신한다."""

    message = ChatMessage(
        message_id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        citations_json=citations_json,
    )
    execute_msr(
        "INSERT INTO chat_message (message_id, session_id, role, content, citations_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [message.message_id, message.session_id, message.role, message.content,
         message.citations_json, message.created_at],
    )
    touch_session(session_id)
    return message


def list_messages(session_id: str, limit: int = 50):
    """세션의 최근 메시지를 오래된순으로 반환(대화 히스토리 컨텍스트 구성용)."""

    df = read_sql_msr(
        f"SELECT message_id, session_id, role, content, citations_json, created_at "
        f"FROM chat_message WHERE session_id = '{_escape(session_id)}' "
        f"ORDER BY created_at DESC LIMIT {int(limit)}"
    )
    return df.iloc[::-1].to_dict("records")


def _escape(value: str) -> str:
    """단순 식별자(uuid)용 최소 이스케이프 — 자유입력 문자열엔 쓰지 말 것."""

    return value.replace("'", "''")
