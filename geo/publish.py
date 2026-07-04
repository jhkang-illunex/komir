# -*- coding: utf-8 -*-
"""[3-후속] geo 최종 결과(지정학 지수)만 공유/운영 DB에 publish.
   원문·manifest·이벤트는 geo_data 볼륨에만 남기고, geo_index만 DB로.
  python -m geo publish [--db <target>]
  target: env GEO_PUBLISH_DB 또는 --db. 파일경로=DuckDB, '://' 포함=SQLAlchemy URL.
"""
import argparse, os
from datetime import datetime
import pandas as pd
from . import config as C, store


def _write(df, table, target):
    if "://" in target:                       # 서버DB(SQLAlchemy)
        import sqlalchemy as sa
        df.to_sql(table, sa.create_engine(target), if_exists="replace", index=False, chunksize=1000)
    else:                                      # DuckDB
        import duckdb
        con = duckdb.connect(target); con.register("_d", df)
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [table]).fetchone()[0]
        if exists:
            # DDL 보존: CREATE OR REPLACE는 스키마 정의(PK·타입)를 추론 스키마로 덮어쓰므로
            # DELETE+INSERT(명시 컬럼, 단일 트랜잭션)로 계약 유지.
            cols = ",".join(f'"{c}"' for c in df.columns)
            con.execute("BEGIN")
            con.execute(f'DELETE FROM "{table}"')
            con.execute(f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM _d')
            con.execute("COMMIT")
        else:
            con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _d')
        con.unregister("_d"); con.close()


def run(target=None):
    from .store import _read
    idx = _read(C.INDEX)
    if len(idx) == 0:
        print("[publish] geo_index 없음(먼저 index)"); return
    target = target or os.environ.get("GEO_PUBLISH_DB") or str(C.STORE / "geo_published.duckdb")
    # 스키마 컬럼명으로 정규화 (geo_index 테이블 계약)
    out = idx.rename(columns={"commodity": "commodity_code", "index": "idx_value"}).copy()
    out["index_config_version"] = os.environ.get("GEO_INDEX_VERSION", "v1")
    out["generated_at"] = datetime.utcnow().isoformat(timespec="seconds")
    out = out[["commodity_code", "freq", "period", "raw_score", "n_events",
               "idx_value", "index_config_version", "generated_at"]]
    _write(out, "geo_index", target)
    print(f"[publish] geo_index {len(out)}행 → {target} (테이블 geo_index)")
    return len(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default=None)
    run(ap.parse_args().db)
