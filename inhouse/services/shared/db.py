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

from db.dbio import apply_schema, is_url, read_sql, write_df  # noqa: E402,F401

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


def execute_msr(sql: str, params: list | None = None) -> None:
    """MSR_DB에 파라미터화된 단일 DML 문 하나를 실행한다(dbio.py엔 없는 기능 —
    dbio는 DataFrame 벌크 적재/스키마 파일 적용만 지원해 chat_session/chat_message
    같은 point CRUD(rag_chat 세션 저장, 2026-08-11)엔 안 맞는다).

    ⚠ sql은 DuckDB의 `?`(qmark) 자리표시자로 작성한다 — 현재 MSR_DB는 항상 DuckDB라
    이 경로만 실사용·검증됨. is_url(target) 분기(서버DB)는 postgres의 실제
    paramstyle(psycopg2는 %s/pyformat, `?` 아님)에 맞춰 재작성이 필요해 아직 안 맞다
    — MSR_DB의 PG_DSN cutover 시점에 반드시 먼저 고칠 것(그 전엔 이 분기를 타지 않음)."""

    target = get_settings().MSR_DB
    if is_url(target):
        raise NotImplementedError(
            "execute_msr의 서버DB(URL) 경로는 아직 paramstyle 미검증 — "
            "MSR_DB cutover 시 db.py 참고 주석대로 먼저 수정할 것"
        )
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

    settings = get_settings()
    if not settings.PG_DSN:
        raise RuntimeError("PG_DSN이 설정되지 않음(.env 확인)")
    return read_sql(query, target=settings.PG_DSN)
