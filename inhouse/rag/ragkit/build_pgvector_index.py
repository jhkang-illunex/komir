# -*- coding: utf-8 -*-
"""documents/산출물 -> PostgreSQL(komis_demo) `mineral_risk.doc_chunk` pgvector 적재.

build_index.py(DuckDB)와 **병렬 구조**다 — 로딩(ingest.load_documents)·청킹
(chunk.chunk_document)·임베딩(embed.encode_passages)은 완전히 같은 코드를 쓰고,
저장소만 DuckDB 대신 Postgres+pgvector다. 기존 rag/index/rag.duckdb는 건드리지
않는다(이번 작업은 추가이지 대체가 아님 — BM25 절반은 여전히 DuckDB FTS).

왜 pgvector인가: 2026-08-11 사용자 결정. komis_demo에 pgvector 0.8.2가 이미
설치돼 있어(실측) Qdrant 컨테이너를 새로 띄울 이유가 없어졌다. 상세는
data_lake/db/schema_pgvector.sql 헤더와 CONTAINER_ARCHITECTURE.md §0·§4.

실행(cwd=inhouse/ — CLAUDE.md §2 표준 실행 관례):
    cd inhouse && python -m rag.ragkit.build_pgvector_index
    cd inhouse && python -m rag.ragkit.build_pgvector_index --schema-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .chunk import chunk_document
from .embed import DIM, encode_passages
from .ingest import load_documents

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
_SERVICES = _INHOUSE_ROOT / "services"
if str(_SERVICES) not in sys.path:
    sys.path.insert(0, str(_SERVICES))

from shared.config import get_settings  # noqa: E402
from shared.db import apply_schema_pg, pg_connect  # noqa: E402

SCHEMA_SQL = _INHOUSE_ROOT / "data_lake/db/schema_pgvector.sql"

#: 벡터 저장소 구분(§4 addendum의 source_type) — 이 스크립트는 비정형 문서만 넣는다.
SOURCE_TYPE = "unstructured"

_COLUMNS = (
    "chunk_id", "doc_id", "commodity_code", "src", "pub_date", "seq", "txt",
    "source_path", "week", "title", "section_heading", "char_len",
    "source_type", "indexed_at", "embedding",
)


def _vector_literal(vec) -> str:
    """pgvector 텍스트 리터럴. pgvector-python이 없어(airgap, pip 전제 불가)
    파이썬 객체 어댑터를 쓸 수 없으므로 '[v1,v2,...]' 문자열 + ::vector 캐스트로
    넣는다. str(list)의 공백 포맷에 기대지 않고 명시적으로 만든다."""

    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _pub_date(doc_date: str):
    """DocRecord.doc_date(YYMMDD, 없으면 "")를 DATE로. 파싱 실패 시 None."""

    if not doc_date or len(doc_date) != 6 or not doc_date.isdigit():
        return None
    try:
        return dt.date(2000 + int(doc_date[:2]), int(doc_date[2:4]), int(doc_date[4:6]))
    except ValueError:
        return None


def _src(week: str) -> str:
    """schema_core.doc_chunk.src(VARCHAR(40)) — 원천 구분. EXTRA_ROOTS 문서는
    week가 "외부자료:<라벨>" 형태(ingest.py)라 접두사로 구분된다."""

    return week.split(":", 1)[0] if ":" in week else "documents/산출물"


def build(schema_only: bool = False) -> int:
    settings = get_settings()
    schema = settings.PG_SCHEMA  # 항상 mineral_risk — public에는 절대 쓰지 않는다
    n_stmt = apply_schema_pg(str(SCHEMA_SQL))
    print(f"스키마 적용 완료: {SCHEMA_SQL.name} ({n_stmt} statements) -> {schema}.doc_chunk")
    if schema_only:
        return 0

    docs = load_documents()
    all_chunks = []
    for d in docs:
        all_chunks.extend((d, c) for c in chunk_document(d))
    print(f"문서 {len(docs)}건, 청크 {len(all_chunks)}개 — 임베딩 계산 중(e5-small, {DIM}차원)...")

    vectors = encode_passages([c.text for _, c in all_chunks])

    now = dt.datetime.now()
    rows = []
    for (d, c), vec in zip(all_chunks, vectors):
        rows.append((
            c.chunk_id, c.doc_id, None, _src(d.week), _pub_date(d.doc_date), c.chunk_order,
            c.text, d.source_path, d.week, d.title, c.section_heading, len(c.text),
            SOURCE_TYPE, now, _vector_literal(vec),
        ))

    from psycopg2.extras import execute_values

    collist = ",".join(_COLUMNS)
    template = "(" + ",".join(["%s"] * (len(_COLUMNS) - 1)) + ",%s::vector)"

    con = pg_connect()
    try:
        with con.cursor() as cur:
            # 전량 재적재(build_index.py의 CREATE OR REPLACE와 동일 의미) — 이
            # 파이프라인이 이 테이블의 유일한 writer라 upsert 기계장치가 불필요하다.
            cur.execute(f"DELETE FROM {schema}.doc_chunk")
            deleted = cur.rowcount
            execute_values(
                cur, f"INSERT INTO {schema}.doc_chunk ({collist}) VALUES %s",
                rows, template=template, page_size=200,
            )
            cur.execute(f"SELECT count(*) FROM {schema}.doc_chunk")
            total = cur.fetchone()[0]
        con.commit()
    finally:
        con.close()

    print(f"적재 완료: {schema}.doc_chunk — 기존 {deleted}행 삭제, {len(rows)}행 삽입, 현재 {total}행")
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema-only", action="store_true", help="DDL만 적용하고 적재는 건너뜀")
    args = ap.parse_args()
    build(schema_only=args.schema_only)
