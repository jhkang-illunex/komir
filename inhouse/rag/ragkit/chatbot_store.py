# -*- coding: utf-8 -*-
"""chat_session/chat_message CRUD — rag 패키지 chatbot 엔트리포인트(chatbot.py)의
세션·히스토리 저장소. 스키마는 `data_lake/db/schema_addendum_v2.sql` §4
(chat_session/chat_message)를 그대로 쓴다 — 신규 테이블 아님, 2026-08-11 서빙
레이어 설계 때 이미 MSR_DB에 만들어졌다.

2026-08-13: services/rag_chat/app/session_store.py에 있던 동일 CRUD를 여기로
이관했다(재구현 금지 원칙 — 로직은 한 곳만 두고, services/rag_chat 쪽은 이 모듈을
그대로 감싸는 얇은 어댑터로 바꿨다, services/rag_chat/app/session_store.py 참고).
ragkit은 services/shared에 의존하지 않는다(서빙 레이어 없이 rag 패키지 단독으로도
동작해야 함 — CLAUDE.md §4 "구조가 모델을 앞선다") — DB 경로는 services/shared/
config.py의 Settings를 거치지 않고 MSR_DB 환경변수 또는 명시적 db_path 인자로
받는다(mineral_supply_risk/scripts/*가 MSR_DB로 대상을 고르는 것과 같은 컨벤션,
CLAUDE.md §2 `MSR_DB=../data_lake/db/minerals.duckdb python -m scripts.xxx`).

⚠ Postgres cutover 이후: services/shared/db.py execute_msr과 동일하게 URL 타깃은
아직 미구현(psycopg2 paramstyle 미검증) — is_url이면 명시적으로 실패시킨다."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# rag/ragkit이 표준 실행 관례(CLAUDE.md §2: `cd inhouse && python -m rag ...`)로
# cwd=inhouse/일 때 맞는 상대경로 — build_index.py의 DB_PATH="rag/index/rag.duckdb"와
# 같은 패턴. 서빙 레이어(services/rag_chat)는 절대경로(get_settings().MSR_DB)를
# db_path 인자로 명시 주입하므로 이 기본값을 쓰지 않는다.
DEFAULT_DB_PATH = os.environ.get("MSR_DB", "data_lake/db/minerals.duckdb")


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


def _is_url(target: str) -> bool:
    return "://" in target


def _connect(db_path: str):
    if _is_url(db_path):
        raise NotImplementedError(
            "chatbot_store의 서버DB(URL) 경로는 아직 미구현 — MSR_DB cutover 시 "
            "services/shared/db.py execute_msr 주석의 안내(psycopg2 paramstyle이 "
            "DuckDB의 `?`와 다름)부터 맞춰 여기도 함께 고칠 것"
        )
    import duckdb

    return duckdb.connect(db_path)


def _execute(db_path: str, sql: str, params: list | None = None) -> None:
    con = _connect(db_path)
    try:
        con.execute(sql, params or [])
    finally:
        con.close()


def _read(db_path: str, sql: str):
    con = _connect(db_path)
    try:
        return con.execute(sql).fetchdf()
    finally:
        con.close()


def get_or_create_session(
    session_id: str | None,
    user_id: str,
    title: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """session_id가 있으면 존재 확인 후 그대로, 없으면 새로 발급."""

    if session_id:
        existing = _read(
            db_path, f"SELECT session_id FROM chat_session WHERE session_id = '{_escape(session_id)}'"
        )
        if len(existing):
            return session_id

    new_id = session_id or str(uuid.uuid4())
    now = _now()
    _execute(
        db_path,
        "INSERT INTO chat_session (session_id, user_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [new_id, user_id, title, now, now],
    )
    return new_id


def touch_session(session_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """세션의 updated_at을 현재 시각으로 갱신(새 메시지 저장 시 호출)."""

    _execute(db_path, "UPDATE chat_session SET updated_at = ? WHERE session_id = ?", [_now(), session_id])


def append_message(
    session_id: str,
    role: str,
    content: str,
    citations_json: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> ChatMessage:
    """메시지 하나를 저장하고 세션 updated_at을 같이 갱신한다."""

    message = ChatMessage(
        message_id=str(uuid.uuid4()), session_id=session_id, role=role, content=content,
        citations_json=citations_json,
    )
    _execute(
        db_path,
        "INSERT INTO chat_message (message_id, session_id, role, content, citations_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [message.message_id, message.session_id, message.role, message.content,
         message.citations_json, message.created_at],
    )
    touch_session(session_id, db_path=db_path)
    return message


def list_messages(session_id: str, limit: int = 50, db_path: str = DEFAULT_DB_PATH):
    """세션의 최근 메시지를 오래된순으로 반환(대화 히스토리 컨텍스트 구성용)."""

    df = _read(
        db_path,
        f"SELECT message_id, session_id, role, content, citations_json, created_at "
        f"FROM chat_message WHERE session_id = '{_escape(session_id)}' "
        f"ORDER BY created_at DESC LIMIT {int(limit)}",
    )
    return df.iloc[::-1].to_dict("records")


def _escape(value: str) -> str:
    """단순 식별자(uuid)용 최소 이스케이프 — 자유입력 문자열엔 쓰지 말 것."""

    return value.replace("'", "''")
