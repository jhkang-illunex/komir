"""PG 접속 — komis_demo `public` 스키마 읽기/쓰기.

`common/db.py`의 read_sql_pg/execute_pg는 mineral_risk 전용이고 public 쓰기를
금지한다(타 팀 소유 원칙). 이 모듈은 사용자 결정(2026-09-15)으로 신설한
`public.ai_rpt_overall`·`public.ai_rpt_mnrl` 두 보고서 테이블과, 이 모듈이 소유하는
보조 테이블 `ai_rpt_engine_ver`(엔진 버전 등록부)·`ai_rpt_gen_run`(실행 로그)에만
쓰고, 그 외 public 테이블은 읽기만 한다 — 그래서 공용 헬퍼를 우회해 자체 엔진을 갖는다.
"""
from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from .config import pg_dsn

#: 이 모듈이 쓰기를 허용하는 public 테이블(그 외는 읽기 전용).
WRITABLE_TABLES = frozenset({"ai_rpt_overall", "ai_rpt_mnrl", "ai_rpt_engine_ver", "ai_rpt_gen_run"})

_engine: sa.engine.Engine | None = None


def engine() -> sa.engine.Engine:
    global _engine
    if _engine is None:
        _engine = sa.create_engine(pg_dsn(), pool_pre_ping=True, future=True)
    return _engine


def fetch_all(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    with engine().connect() as c:
        rows = c.execute(sa.text(sql), params or {})
        return [dict(r._mapping) for r in rows]


def fetch_one(sql: str, params: dict | None = None) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: dict | None = None) -> int:
    with engine().begin() as c:
        return c.execute(sa.text(sql), params or {}).rowcount
