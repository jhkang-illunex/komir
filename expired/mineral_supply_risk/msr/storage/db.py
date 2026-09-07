# -*- coding: utf-8 -*-
"""DuckDB 연결·적재·내보내기(운영 DB 이관용)

2026-08-19(postgres cutover): `upsert_df()`는 `db.dbio.upsert_df()`로 실제 로직을
옮기고 이 함수는 `DB_PATH`(duckdb든 postgres URL이든)로 위임하는 얇은 래퍼로 축소했다
— 호출부(`msr/pipeline.py`·`msr/models/alert.py` 등 6곳)는 그대로 `from ..storage
import db as store; store.upsert_df(...)`를 쓰면 되고 아무것도 바꿀 필요 없다.

`connect()`/`export_parquet()`는 여전히 duckdb 전용이다(`duckdb.connect()` 하드코딩) —
`DB_PATH`가 postgres URL이면 이 두 함수는 호출하지 말 것(크래시함). `export_parquet()`은
백업용 유틸이라 이번 postgres 전환 스코프 밖으로 남겨뒀다 — duckdb 냉동 백업 파일에서
내보낼 때만 쓴다."""
import duckdb, pandas as pd
from ..config import DB_PATH
from db.dbio import upsert_df as _dbio_upsert_df

def connect(read_only=False):
    return duckdb.connect(DB_PATH, read_only=read_only)

def upsert_df(df: pd.DataFrame, table: str, del_where: str = None):
    """멱등 적재: del_where로 기존행 삭제 후 append(테이블 없으면 생성). 실제 구현은
    `db.dbio.upsert_df()`(duckdb/postgres 자동 분기) — DB_PATH만 넘겨준다."""
    return _dbio_upsert_df(df, table, DB_PATH, del_where=del_where)

def export_parquet(out_dir):
    """전 테이블 Parquet 내보내기(운영 DB 이관/백업)."""
    import os; os.makedirs(out_dir, exist_ok=True)
    con = connect(read_only=True)
    safe = out_dir.replace("'", "''")   # 경로 내 작은따옴표 이스케이프
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'").fetchall():
        con.execute(f"COPY \"{t}\" TO '{safe}/{t}.parquet' (FORMAT PARQUET)")
    con.close()
