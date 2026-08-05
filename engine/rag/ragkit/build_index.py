# -*- coding: utf-8 -*-
"""documents/산출물 -> DuckDB 인덱스(rag/index/rag.duckdb) 빌드.
- doc/chunk 테이블 적재
- dense: multilingual-e5-small 임베딩(FLOAT[384], list_cosine_similarity로 질의)
- sparse: DuckDB FTS(BM25) + 한글 바이그램 토크나이저(tokenize_ko) 조합
재실행 시 전체 재빌드(멱등) — 코퍼스가 작아(문서<100, 청크<2000) 수 분 내 완료.
"""
from __future__ import annotations

import os

import duckdb

from .chunk import chunk_document
from .embed import DIM, encode_passages
from .ingest import load_documents
from .tokenize_ko import to_fts_text

DB_PATH = "rag/index/rag.duckdb"

DDL = f"""
CREATE OR REPLACE TABLE doc (
    doc_id VARCHAR PRIMARY KEY,
    source_path VARCHAR,
    week VARCHAR,
    series_key VARCHAR,
    doc_date VARCHAR,
    title VARCHAR,
    ext VARCHAR
);
CREATE OR REPLACE TABLE chunk (
    chunk_id VARCHAR PRIMARY KEY,
    doc_id VARCHAR,
    chunk_order INTEGER,
    section_heading VARCHAR,
    text VARCHAR,
    fts_text VARCHAR,
    char_len INTEGER,
    embedding FLOAT[{DIM}]
);
"""


def build(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    docs = load_documents()
    all_chunks = []
    for d in docs:
        all_chunks.extend((d, c) for c in chunk_document(d))
    print(f"문서 {len(docs)}건, 청크 {len(all_chunks)}개 — 임베딩 계산 중...")

    texts = [c.text for _, c in all_chunks]
    vectors = encode_passages(texts)

    con = duckdb.connect(db_path)
    con.execute(DDL)
    con.executemany(
        "INSERT INTO doc VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(d.doc_id, d.source_path, d.week, d.series_key, d.doc_date, d.title, d.ext) for d in docs],
    )
    rows = []
    for (d, c), vec in zip(all_chunks, vectors):
        rows.append((
            c.chunk_id, c.doc_id, c.chunk_order, c.section_heading, c.text,
            to_fts_text(c.text), len(c.text), vec.tolist(),
        ))
    con.executemany(
        "INSERT INTO chunk VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows,
    )
    con.execute("INSTALL fts; LOAD fts;")
    con.execute("PRAGMA create_fts_index('chunk', 'chunk_id', 'fts_text', stemmer='none', overwrite=1)")
    con.close()
    print(f"인덱스 빌드 완료: {db_path} (doc {len(docs)}, chunk {len(all_chunks)})")


if __name__ == "__main__":
    build()
