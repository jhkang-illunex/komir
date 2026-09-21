# -*- coding: utf-8 -*-
"""DB 입출력 어댑터 — 대상(target)을 문자열로 받아 DuckDB/서버DB를 동일 API로 처리.
  target 예:
    'data/processed/minerals.duckdb'                  → DuckDB 파일
    'oracle+oracledb://user:pw@host:1521/?service_name=ORCL'
    'mariadb+pymysql://user:pw@host:3306/mineral'
    'mssql+pyodbc://user:pw@host/db?driver=ODBC+Driver+17+for+SQL+Server'
서버DB는 SQLAlchemy 필요(pip install sqlalchemy + 해당 드라이버). DuckDB는 내장.
"""
import os, re


def is_url(target: str) -> bool:
    return "://" in target


def _coerce_decimal_cols(df):
    """postgres NUMERIC 컬럼이 psycopg2를 거치면 `decimal.Decimal` object 열로 온다
    (duckdb DECIMAL(20,4) 등은 자체 Python 드라이버가 fetch 시 float64로 자동 변환하는
    것과 대조적 — 2026-08-19 postgres cutover 실측으로 발견: nowcast.py의 표준편차 계산이
    "unsupported operand type(s) for -: 'float' and 'decimal.Decimal'"로 크래시). 이
    읽기 경계 한 곳에서 duckdb와 동일한 float64로 맞춰, 스키마가 DECIMAL/NUMERIC인 컬럼을
    쓰는 나머지 코드 전체(수십 개 SQL 조회 지점)를 손대지 않아도 되게 한다."""
    import decimal
    for col in df.columns:
        if df[col].dtype != object:
            continue
        vals = df[col].dropna()
        if len(vals) and all(isinstance(v, decimal.Decimal) for v in vals.head(20)):
            df[col] = df[col].astype(float)
    return df


# ---------- 스키마 적용 ----------
def _split_sql(sql_text: str):
    # 주석 제거 후 ; 기준 분할
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def apply_schema(sql_path: str, target: str, drop_if_not_exists_for_server=False):
    """DDL 파일을 target에 실행. 서버DB면 'IF NOT EXISTS'를 자동 제거(옵션)."""
    sql = open(sql_path, encoding="utf-8").read()
    stmts = _split_sql(sql)
    if is_url(target):
        import sqlalchemy as sa
        eng = sa.create_engine(target)
        with eng.begin() as con:
            for st in stmts:
                if drop_if_not_exists_for_server:
                    st = re.sub(r"IF NOT EXISTS", "", st, flags=re.I)
                con.execute(sa.text(st))
    else:
        # 2026-08-11 버그수정: 정의되지 않은 schema/table 변수를 참조해 DuckDB 대상
        # 호출 시 무조건 NameError였음(docs/CONTAINER_ARCHITECTURE.md §1에 문서화된
        # 기지 버그) — apply_schema는 DDL 파일 전체를 그대로 실행하는 함수라 테이블별
        # schema 접두는 원래 의미가 없었음(그 값도 이후 아무데도 안 쓰임, 죽은 코드).
        import duckdb
        con = duckdb.connect(target)
        for st in stmts:
            con.execute(st)
        con.close()
    return len(stmts)


# ---------- DataFrame 적재 ----------
def write_df(df, table: str, target: str, if_exists: str = "append", pk: list = None,
             schema: str = None):
    """df를 table에 적재. if_exists: append|replace. pk 지정 시 중복 제거(append 전).
    schema: 서버DB 스키마/데이터베이스명(예: Oracle 스키마, MariaDB DB) — env
    MSR_PUBLISH_SCHEMA로 외부 주입(2026-07-12). DuckDB면 스키마 자동 생성 후 사용."""
    if df is None or len(df) == 0:
        return 0
    if pk:  # 문서화된 계약 실구현: pk 기준 dedup(뒤 행 우선)
        df = df.drop_duplicates(subset=pk, keep="last")
    if is_url(target):
        import sqlalchemy as sa
        eng = sa.create_engine(target)
        df.to_sql(table, eng, if_exists=("replace" if if_exists == "replace" else "append"),
                  index=False, chunksize=1000, schema=schema)
    else:
        import duckdb
        con = duckdb.connect(target)
        if schema:
            con.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            table = f'{schema}"."{table}'   # 아래 f'"{table}"' 조합 시 "schema"."table"이 됨
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [table]).fetchone()[0]
        con.register("_df", df)
        if if_exists == "replace" or not exists:
            con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM _df')
        else:
            # 부분 컬럼도 허용: df 컬럼만 명시 삽입(나머지는 기본값/NULL)
            collist = ",".join(f'"{c}"' for c in df.columns)
            con.execute(f'INSERT INTO "{table}" ({collist}) SELECT {collist} FROM _df')
        con.unregister("_df"); con.close()
    return len(df)


# ---------- 멱등 upsert(delete-then-insert) ----------
def upsert_df(df, table: str, target: str, del_where: str = None):
    """멱등 적재: del_where로 기존행 삭제 후 append(테이블 없으면 생성).

    2026-08-19: `msr/storage/db.py`의 duckdb 전용 upsert_df를 이 모듈로 옮기고
    postgres(서버DB) 분기를 추가했다(postgres cutover 착수, WORKLOG 2026-08-19).
    duckdb 분기는 원본 로직 그대로(BEGIN/DELETE/INSERT/COMMIT 한 트랜잭션, 실패 시 롤백).

    ⚠ `del_where`는 호출자가 값을 이미 안전하게 SQL 문자열에 인라인한 WHERE절이어야
    한다(예: `"1=1"`, `f"base_month = '{d}'"`) — 내부에서 생성한 신뢰 가능한 값만 넣을 것,
    사용자 입력을 직접 넣지 말 것(파라미터 바인딩이 아니라 문자열 결합이라 SQL 인젝션
    위험이 있음)."""
    if df is None or len(df) == 0:
        return 0
    if is_url(target):
        import sqlalchemy as sa
        eng = sa.create_engine(target)
        exists = sa.inspect(eng).has_table(table)
        if not exists:
            df.to_sql(table, eng, index=False)
        else:
            with eng.begin() as conn:
                if del_where:
                    conn.execute(sa.text(f'DELETE FROM "{table}" WHERE {del_where}'))
                df.to_sql(table, conn, if_exists="append", index=False)
        return len(df)
    else:
        import duckdb
        con = duckdb.connect(target)
        con.register("_t", df)
        try:
            exists = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [table]).fetchone()[0]
            if not exists:
                con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _t')
            else:
                cols = ",".join(f'"{c}"' for c in df.columns)
                con.execute("BEGIN")
                if del_where:
                    con.execute(f'DELETE FROM "{table}" WHERE {del_where}')
                con.execute(f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM _t')
                con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            con.unregister("_t"); con.close()
            raise
        con.unregister("_t")
        con.execute("CHECKPOINT"); con.close()
        return len(df)


def read_sql(query: str, target: str):
    import pandas as pd
    if is_url(target):
        import sqlalchemy as sa
        return _coerce_decimal_cols(pd.read_sql(query, sa.create_engine(target)))
    import duckdb
    con = duckdb.connect(target, read_only=True)
    try:
        return con.execute(query).df()
    finally:
        con.close()


# ---------- 읽기 전용 커넥션 어댑터(postgres cutover, 2026-08-19) ----------
class _PgReadResult:
    """duckdb 커서 결과의 `.df()`/`.fetchone()` 서브셋만 흉내낸다."""

    def __init__(self, result):
        self._result = result

    def df(self):
        import pandas as pd
        rows = self._result.fetchall()
        return _coerce_decimal_cols(pd.DataFrame(rows, columns=list(self._result.keys())))

    def fetchone(self):
        return self._result.fetchone()

    def fetchall(self):
        return self._result.fetchall()


class _PgReadConn:
    """postgres(URL) 대상에서 duckdb Connection의 `.execute(sql).df()/.fetchone()/.close()`
    서브셋만 흉내내는 얇은 어댑터. `msr/models/*.py`·`scripts/diagnosis_*.py`의
    build_panel류 함수들이 커넥션 하나를 열어 SELECT 여러 개를 순차 실행하던 duckdb 전용
    코드를, 파일별 쿼리 리라이트 없이 `connect_ro()` 호출 한 줄만 바꿔 재사용하려고
    만들었다. 파라미터 바인딩(`?`)이 필요한 쓰기 경로는 대상이 아니다(`upsert_df()`를
    쓸 것) — 이 셸은 파라미터 없는 읽기 전용 SELECT만 지원한다."""

    def __init__(self, engine):
        self._conn = engine.connect()

    def execute(self, sql):
        import sqlalchemy as sa
        return _PgReadResult(self._conn.execute(sa.text(sql)))

    def close(self):
        self._conn.close()


def connect_ro(target: str):
    """읽기 전용 커넥션 — duckdb 파일이면 진짜 `duckdb.connect(read_only=True)`,
    URL(postgres 등)이면 `_PgReadConn` 어댑터. 반환값은 `.execute(sql).df()`/
    `.execute(sql).fetchone()`/`.close()`만 보장한다(그 이상은 duckdb 전용이라 여기서
    호환 안 됨)."""
    if is_url(target):
        import sqlalchemy as sa
        return _PgReadConn(sa.create_engine(target))
    import duckdb
    return duckdb.connect(target, read_only=True)
