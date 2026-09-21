# -*- coding: utf-8 -*-
"""하이브리드 검색: BM25(sparse) + dense(cosine) 각각 후보를 뽑고 RRF로 융합.
가이드 §2 원칙: "top-k를 무작정 키우기보다 실패모드가 다른 리트리버를 추가".
현재는 dense(의미)+sparse(정확 토큰/숫자/코드) 2계열 — 표·그래프 리트리버는
평가(§eval_retrieval) 결과 실제 실패모드가 확인되면 추가 검토."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .build_index import DB_PATH
from .embed import encode_query
from .tokenize_ko import to_fts_text

RRF_K = 60


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    source_path: str
    week: str
    title: str
    section_heading: str
    text: str
    dense_rank: int | None
    bm25_rank: int | None
    rrf_score: float


def _connect(db_path: str = DB_PATH) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(db_path, read_only=True)
    con.execute("INSTALL fts; LOAD fts;")
    return con


def dense_search(con: duckdb.DuckDBPyConnection, query: str, k: int) -> list[str]:
    qvec = encode_query(query).tolist()
    rows = con.execute(
        "SELECT chunk_id FROM chunk ORDER BY list_cosine_similarity(embedding, ?::FLOAT[384]) DESC LIMIT ?",
        [qvec, k],
    ).fetchall()
    return [r[0] for r in rows]


def bm25_search(con: duckdb.DuckDBPyConnection, query: str, k: int) -> list[str]:
    q = to_fts_text(query)
    if not q.strip():
        return []
    rows = con.execute(
        """
        SELECT chunk_id FROM (
            SELECT chunk_id, fts_main_chunk.match_bm25(chunk_id, ?) AS score FROM chunk
        ) WHERE score IS NOT NULL ORDER BY score DESC LIMIT ?
        """,
        [q, k],
    ).fetchall()
    return [r[0] for r in rows]


def hybrid_search(query: str, k: int = 8, fanout: int = 30, db_path: str = DB_PATH) -> list[RetrievedChunk]:
    con = _connect(db_path)
    try:
        dense_ids = dense_search(con, query, fanout)
        bm25_ids = bm25_search(con, query, fanout)

        dense_rank = {cid: i + 1 for i, cid in enumerate(dense_ids)}
        bm25_rank = {cid: i + 1 for i, cid in enumerate(bm25_ids)}
        candidates = set(dense_ids) | set(bm25_ids)

        scored = []
        for cid in candidates:
            s = 0.0
            if cid in dense_rank:
                s += 1.0 / (RRF_K + dense_rank[cid])
            if cid in bm25_rank:
                s += 1.0 / (RRF_K + bm25_rank[cid])
            scored.append((cid, s))
        scored.sort(key=lambda x: -x[1])
        top = scored[:k]
        if not top:
            return []

        ids = [cid for cid, _ in top]
        placeholders = ",".join("?" * len(ids))
        rows = con.execute(
            f"""
            SELECT c.chunk_id, c.doc_id, d.source_path, d.week, d.title, c.section_heading, c.text
            FROM chunk c JOIN doc d USING (doc_id)
            WHERE c.chunk_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        by_id = {r[0]: r for r in rows}

        out = []
        for cid, score in top:
            r = by_id.get(cid)
            if not r:
                continue
            out.append(RetrievedChunk(
                chunk_id=r[0], doc_id=r[1], source_path=r[2], week=r[3], title=r[4],
                section_heading=r[5], text=r[6],
                dense_rank=dense_rank.get(cid), bm25_rank=bm25_rank.get(cid), rrf_score=score,
            ))
        return out
    finally:
        con.close()


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "진단모델 AUC는 얼마인가?"
    for r in hybrid_search(q, k=5):
        print(f"[{r.rrf_score:.4f}] dense={r.dense_rank} bm25={r.bm25_rank} {r.source_path} :: {r.section_heading}")
        print("   ", r.text[:120].replace("\n", " "))
