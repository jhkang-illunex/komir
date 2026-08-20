# -*- coding: utf-8 -*-
"""서빙 레이어(commodity_api·rag_chat·report_gen) 공통 DB 접근점.

mineral_supply_risk/db/dbio.py를 그대로 재노출한다(재구현 금지) — 이 모듈이
유일한 DB 진입점이 되어 서비스 코드가 duckdb/sqlalchemy를 직접 임포트하지
않게 한다(엔진 쪽 mineral_supply_risk/scripts/*는 예외 — 배치 파이프라인은
별도 사이클로 이관).

2026-08-11: dbio.apply_schema()의 DuckDB 분기 버그(정의 안 된 schema 변수
참조)는 dbio.py 자체에서 직접 수정함(재노출판을 따로 두지 않음 — 원본이
고쳐졌으니 그대로 재노출하면 됨)."""
from __future__ import annotations

import sys
from pathlib import Path


def _find_msr_root(start: Path) -> Path:
    """`mineral_supply_risk/db/dbio.py`를 담은 디렉토리를 위로 훑어 찾는다.

    소스트리(inhouse/services/shared/db.py, 2단 위가 inhouse/)와 컨테이너
    배포본(Containerfile이 services/shared→./shared로 한 단 평평하게 COPY,
    1단 위가 /app)의 상대 깊이가 달라 고정 depth 대신 탐색한다(services/
    ingestion/parsers/pdf.py의 geo 탐색과 같은 이유·같은 패턴, 2026-08-11)."""

    for candidate in (start, *start.parents):
        if (candidate / "mineral_supply_risk" / "db" / "dbio.py").is_file():
            return candidate
    raise ImportError(f"mineral_supply_risk/db/dbio.py를 {start} 상위에서 찾지 못함")


_MSR_PARENT = _find_msr_root(Path(__file__).resolve())
_MSR_DB_PKG_ROOT = _MSR_PARENT / "mineral_supply_risk"
if str(_MSR_DB_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_MSR_DB_PKG_ROOT))

from db.dbio import apply_schema, connect_ro, is_url, read_sql, upsert_df, write_df  # noqa: E402,F401

from .config import get_settings


def read_sql_msr(query: str):
    """MSR_DB(정형 팩트·마트·out_* — cutover 전엔 duckdb, 이후 PG_DSN) 조회."""

    return read_sql(query, target=get_settings().MSR_DB)


def write_df_msr(df, table: str, if_exists: str = "append", pk: list | None = None):
    """MSR_DB에 적재. schema는 MSR_PUBLISH_SCHEMA(비어있으면 미지정)."""

    settings = get_settings()
    return write_df(
        df, table, settings.MSR_DB, if_exists=if_exists, pk=pk,
        schema=settings.MSR_PUBLISH_SCHEMA or None,
    )


def upsert_df_msr(df, table: str, del_where: str | None = None):
    """MSR_DB에 멱등 적재(delete-then-insert, 2026-08-19 upsert_df 추가에 맞춰
    write_df_msr 옆에 대칭으로 노출). schema 인자는 dbio.upsert_df가 아직 지원하지
    않음(MSR_PUBLISH_SCHEMA 쓰는 서비스가 아직 없어 write_df_msr처럼 미리 배선하지
    않았다 — 필요해지면 db.dbio.upsert_df에 schema 인자부터 추가할 것)."""

    return upsert_df(df, table, get_settings().MSR_DB, del_where=del_where)


def execute_msr(sql: str, params: list | None = None) -> None:
    """MSR_DB에 파라미터화된 단일 DML 문 하나를 실행한다(dbio.py엔 없는 기능 —
    dbio는 DataFrame 벌크 적재/스키마 파일 적용만 지원해 out_report 저장 같은
    point CRUD(delete-then-insert 멱등성 보장용 DELETE)엔 안 맞는다).

    sql은 항상 DuckDB의 `?`(qmark) 자리표시자로 작성한다 — 호출부(report_gen의
    generator.py·analysis/store.py)를 postgres 전용으로 고치지 않아도 되게,
    postgres(URL) 분기에서 내부적으로 `?`→`%s`(psycopg2 paramstyle)로 치환한다
    (2026-08-20 postgres cutover 후속 수정 — WORKLOG 2026-08-20 "out_report 저장
    경로 파손" 기록 참고. 현재 실제 호출부 2곳 모두 `?` 1개짜리 단순 DELETE라
    문자열 리터럴 안에 `?`가 섞일 위험은 없음, 확인됨)."""

    target = get_settings().MSR_DB
    if is_url(target):
        import sqlalchemy as sa

        pg_sql = sql.replace("?", "%s")
        con = sa.create_engine(target).raw_connection()
        try:
            with con.cursor() as cur:
                cur.execute(pg_sql, params)
            con.commit()
        finally:
            con.close()
    else:
        import duckdb

        con = duckdb.connect(target)
        try:
            con.execute(sql, params or [])
        finally:
            con.close()


def read_sql_pg(query: str):
    """komis_demo(PG_DSN)의 mineral_risk 스키마 조회 전용.

    public 스키마(ko_*·ai_*, 타 팀 소유)는 이 함수의 대상이 아니다 — 쿼리 문자열
    안에서 스키마를 명시할 때 반드시 get_settings().PG_SCHEMA를 쓸 것, "public"을
    하드코딩하지 말 것."""

    return read_sql(query, target=_pg_dsn())


# ────────────────────────────────────────────────────────────────────
# PostgreSQL 전용 헬퍼 (2026-08-11, pgvector 적재·조회용)
#
# dbio.py는 DataFrame 벌크 적재/DDL 파일 적용만 제공하고 파라미터 바인딩이
# 있는 단문 실행이 없다(execute_msr가 DuckDB용으로 그 구멍을 메운 것과 같은
# 이유). pgvector 적재는 384차원 벡터 리터럴을 %s::vector로 캐스팅해 넣어야
# 해서 pandas to_sql 경로로는 안 되고, psycopg2 execute_values가 필요하다.
# 벡터를 파이썬 객체로 넘기는 pgvector-python 패키지는 설치돼 있지 않다
# (airgap이라 pip 설치도 전제 못 함) — 텍스트 리터럴 + 명시 캐스트로 간다.
#
# ⚠ paramstyle은 psycopg2 규약(%s) — execute_msr의 DuckDB `?`와 다르다.
# ⚠ 대상 스키마는 항상 get_settings().PG_SCHEMA(mineral_risk). public에는
#    어떤 DDL/DML도 보내지 않는다.
# ────────────────────────────────────────────────────────────────────


def _pg_dsn() -> str:
    settings = get_settings()
    if not settings.PG_DSN:
        raise RuntimeError("PG_DSN이 설정되지 않음(.env 확인)")
    return settings.PG_DSN


def pg_connect():
    """komis_demo에 대한 psycopg2 DBAPI 커넥션(SQLAlchemy 엔진 경유).

    호출자가 close()할 것. 커밋은 호출자 책임(psycopg2 기본 = 트랜잭션 시작 후
    수동 commit)."""

    import sqlalchemy as sa

    return sa.create_engine(_pg_dsn()).raw_connection()


def execute_pg(sql: str, params: tuple | list | None = None) -> None:
    """단일 DML/DDL 문 실행(psycopg2 paramstyle: %s)."""

    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
        con.commit()
    finally:
        con.close()


def apply_schema_pg(sql_path: str) -> int:
    """DDL 파일을 komis_demo에 적용하고 실행한 statement 수를 돌려준다.

    dbio.apply_schema를 그대로 쓴다(재구현 금지). IF NOT EXISTS를 제거하지
    않는다 — Postgres는 그 문법을 지원하고, 멱등성이 이 마이그레이션의 전제다."""

    return apply_schema(sql_path, _pg_dsn())
