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
        import duckdb
        con = duckdb.connect(target)
        for st in stmts:
            con.execute(st)
        con.close()
    return len(stmts)


# ---------- DataFrame 적재 ----------
def write_df(df, table: str, target: str, if_exists: str = "append", pk: list = None):
    """df를 table에 적재. if_exists: append|replace. pk 지정 시 중복 제거(append 전)."""
    if df is None or len(df) == 0:
        return 0
    if pk:  # 문서화된 계약 실구현: pk 기준 dedup(뒤 행 우선)
        df = df.drop_duplicates(subset=pk, keep="last")
    if is_url(target):
        import sqlalchemy as sa
        eng = sa.create_engine(target)
        df.to_sql(table, eng, if_exists=("replace" if if_exists == "replace" else "append"),
                  index=False, chunksize=1000)
    else:
        import duckdb
        con = duckdb.connect(target)
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


def read_sql(query: str, target: str):
    import pandas as pd
    if is_url(target):
        import sqlalchemy as sa
        return pd.read_sql(query, sa.create_engine(target))
    import duckdb
    con = duckdb.connect(target, read_only=True)
    try:
        return con.execute(query).df()
    finally:
        con.close()
