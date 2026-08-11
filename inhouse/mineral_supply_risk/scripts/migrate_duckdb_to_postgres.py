# -*- coding: utf-8 -*-
"""duckdb(minerals.duckdb) 전체 테이블 -> postgres(komis_demo, mineral_risk 스키마) 이관.

komis_demo DB의 public 스키마엔 KOMIS 쪽이 이미 쓰는 ko_* 테이블 9개(데이터 있음)가
있어 손대지 않는다 — 우리 duckdb 테이블은 전용 스키마 `mineral_risk`에 그대로 이름
보존해 적재한다(2026-08-10 사용자 확인, 구조 변환 없음).

일회성 벌크 이관. duckdb postgres 확장(ATTACH ... TYPE postgres)으로 스키마 간
CREATE TABLE AS SELECT를 직접 수행(pandas 왕복 없이 duckdb가 처리 — 대용량
geo_event 296,679행 포함이라 이 경로가 빠름). 원본 duckdb는 read_only로 열어
라이브 프로세스(streamlit·cron)와 충돌하지 않는다. MSR_DB/크론/streamlit의 실제
접속 대상은 이 스크립트가 바꾸지 않는다 — 데이터 적재까지만.

실행: cd inhouse/mineral_supply_risk && python -m scripts.migrate_duckdb_to_postgres
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import duckdb
from msr.config import DB_PATH  # noqa: E402 (.env 로딩 부작용)

PG_SCHEMA = os.environ.get("PG_SCHEMA", "mineral_risk")


def _pg_conn_str() -> str:
    return "host={} port={} dbname={} user={} password={}".format(
        os.environ["PG_HOST"], os.environ["PG_PORT"], os.environ["PG_DATABASE"],
        os.environ["PG_USER"], os.environ["PG_PASSWORD"],
    )


def main():
    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    # 원본 duckdb는 read_only(라이브 프로세스와 충돌 방지)로 열지만, 그 상태에서
    # ATTACH한 postgres까지 덩달아 read-only로 취급돼(duckdb 실측 확인) 쓰기가 막힘
    # — READ_ONLY false로 명시해 postgres 쪽만 쓰기 허용.
    con.execute(f"ATTACH '{_pg_conn_str()}' AS pg (TYPE postgres, READ_ONLY false)")
    con.execute(f'CREATE SCHEMA IF NOT EXISTS pg."{PG_SCHEMA}"')

    tables = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY 1").fetchall()]
    print(f"이관 대상 {len(tables)}개 테이블 -> postgres:{PG_SCHEMA}")

    results = []
    for t in tables:
        src_n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        con.execute(f'DROP TABLE IF EXISTS pg."{PG_SCHEMA}"."{t}"')
        con.execute(f'CREATE TABLE pg."{PG_SCHEMA}"."{t}" AS SELECT * FROM "{t}"')
        dst_n = con.execute(f'SELECT COUNT(*) FROM pg."{PG_SCHEMA}"."{t}"').fetchone()[0]
        ok = "OK" if src_n == dst_n else "MISMATCH"
        print(f"  {t}: 원본{src_n} -> 대상{dst_n} [{ok}]", flush=True)
        results.append((t, src_n, dst_n, ok))

    n_mismatch = sum(1 for r in results if r[3] != "OK")
    print(f"\n완료: {len(results)}개 테이블, 불일치 {n_mismatch}건")
    con.close()
    return results


if __name__ == "__main__":
    main()
