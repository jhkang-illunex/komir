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

2026-08-19 postgres 지원 추가: 컨테이너화(§0 "DB는 외부서비스" 원칙 — 이미지에 로컬
DuckDB 파일을 마운트하는 건 그 원칙에 어긋난다) 준비로 URL 타깃(postgres) 분기를
구현했다. `services/shared/db.py`엔 의존하지 않는다(모듈 상단 설명대로 rag 패키지
단독 동작 유지) — 대신 이 파일 안에서 psycopg2를 직접 쓰고, DuckDB의 `?` 자리표시자를
psycopg2 paramstyle(`%s`)로 그때그때 변환한다(쿼리 문자열에 리터럴 `?`가 없는 이
모듈의 쿼리들에선 안전한 치환). 스키마는 `PG_SCHEMA` 환경변수(기본 `mineral_risk`)로
지정 — "public" 하드코딩 금지 규약은 services/shared/db.py와 동일하게 따른다."""
from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

_PG_SCHEMA = os.environ.get("PG_SCHEMA", "mineral_risk")
_QMARK_RE = re.compile(r"\?")

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
        import psycopg2

        # PG_DSN은 SQLAlchemy 관례(services/shared/db.py와 동일 값 공유)로
        # "postgresql+psycopg2://..."인데, psycopg2.connect()는 순수
        # "postgresql://..."만 이해한다(+드라이버명은 SQLAlchemy 전용 문법) —
        # 여기서 벗겨낸다(services/shared는 SQLAlchemy 엔진을 쓰므로 이 문제가
        # 없었음, chatbot_store는 그 의존을 안 지므로 직접 처리).
        dsn = db_path.replace("postgresql+psycopg2://", "postgresql://", 1)
        return psycopg2.connect(dsn)
    import duckdb

    return duckdb.connect(db_path)


def _tbl(db_path: str, name: str) -> str:
    """테이블명 앞에 스키마를 붙일지 여부 — URL(postgres) 타깃일 때만
    `PG_SCHEMA`로 한정한다("public" 하드코딩 금지 규약, 그 외 DuckDB는 그대로)."""

    return f"{_PG_SCHEMA}.{name}" if _is_url(db_path) else name


def _execute(db_path: str, sql: str, params: list | None = None) -> None:
    con = _connect(db_path)
    try:
        if _is_url(db_path):
            with con.cursor() as cur:
                cur.execute(_QMARK_RE.sub("%s", sql), params or [])
            con.commit()
        else:
            con.execute(sql, params or [])
    finally:
        con.close()


def _read(db_path: str, sql: str, params: list | None = None):
    """skeptic-code 감사(2026-08-28) 반영 — 이전엔 params가 없어 get_or_create_session·
    list_messages 두 호출부가 `_escape()`로 문자열을 직접 SQL에 이어붙였다.
    session_id는 ChatRequest.session_id로 사용자가 자유롭게 넣는 값이라
    `_escape()`의 "자유입력 문자열엔 쓰지 말 것" 경고 대상 그 자체였다(당장
    익스플로잇 가능한 인젝션은 아니었지만 — 단순 quote-doubling이 DuckDB·
    기본설정 Postgres 양쪽에서 작은따옴표 breakout을 막는 것까지 실측 확인함).
    `_execute()`가 이미 하던 대로 `?`→`%s`(postgres) 변환+params 바인딩으로
    통일한다."""

    import pandas as pd

    con = _connect(db_path)
    try:
        if _is_url(db_path):
            with con.cursor() as cur:
                cur.execute(_QMARK_RE.sub("%s", sql), params or [])
                cols = [d[0] for d in cur.description]
                return pd.DataFrame(cur.fetchall(), columns=cols)
        return con.execute(sql, params or []).fetchdf()
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
            db_path,
            f"SELECT session_id FROM {_tbl(db_path, 'chat_session')} WHERE session_id = ?",
            [session_id],
        )
        if len(existing):
            return session_id

    new_id = session_id or str(uuid.uuid4())
    now = _now()
    _execute(
        db_path,
        f"INSERT INTO {_tbl(db_path, 'chat_session')} "
        "(session_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        [new_id, user_id, title, now, now],
    )
    return new_id


def touch_session(session_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """세션의 updated_at을 현재 시각으로 갱신(새 메시지 저장 시 호출)."""

    _execute(
        db_path,
        f"UPDATE {_tbl(db_path, 'chat_session')} SET updated_at = ? WHERE session_id = ?",
        [_now(), session_id],
    )


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
        f"INSERT INTO {_tbl(db_path, 'chat_message')} "
        "(message_id, session_id, role, content, citations_json, created_at) "
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
        f"FROM {_tbl(db_path, 'chat_message')} WHERE session_id = ? "
        f"ORDER BY created_at DESC LIMIT {int(limit)}",
        [session_id],
    )
    return df.iloc[::-1].to_dict("records")
