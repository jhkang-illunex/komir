# -*- coding: utf-8 -*-
"""DuckDB 연결·적재·내보내기(운영 DB 이관용)"""
import duckdb, pandas as pd
from ..config import DB_PATH

def connect(read_only=False):
    return duckdb.connect(DB_PATH, read_only=read_only)

def upsert_df(df: pd.DataFrame, table: str, del_where: str = None):
    """멱등 적재: del_where로 기존행 삭제 후 append (테이블 없으면 생성)."""
    if df is None or df.empty: return 0
    con = connect()
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [table]).fetchone()[0]
    if not exists:
        con.register("_t", df); con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _t'); con.unregister("_t")
    else:
        if del_where: con.execute(f'DELETE FROM "{table}" WHERE {del_where}')
        con.register("_t", df); con.execute(f'INSERT INTO "{table}" SELECT * FROM _t'); con.unregister("_t")
    con.execute("CHECKPOINT"); con.close()
    return len(df)

def export_parquet(out_dir):
    """전 테이블 Parquet 내보내기(운영 DB 이관/백업)."""
    import os; os.makedirs(out_dir, exist_ok=True)
    con = connect(read_only=True)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'").fetchall():
        con.execute(f"COPY \"{t}\" TO '{out_dir}/{t}.parquet' (FORMAT PARQUET)")
    con.close()
