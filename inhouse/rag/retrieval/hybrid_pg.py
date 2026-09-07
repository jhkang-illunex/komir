# -*- coding: utf-8 -*-
"""dense(`dense_pg.py`) + sparse(`bm25_pg.py`) RRF 융합 — pgvector 코퍼스용.

RRF 공식·상수(`RRF_K=60`)는 `rag/ragkit/retrieve.py::hybrid_search()`와 **동일**
(재구현이 아니라 같은 알고리즘을 새 데이터소스에 재적용 — 그 모듈 자체는 구
DuckDB 코퍼스<100건 전용이라 못 씀, 2026-08-19 조사 근거는 dense_pg.py 상단
주석 참고). fanout(각 리트리버에서 몇 개씩 뽑아 융합 풀에 넣을지)은 기존과
같은 기본값(30) 유지."""
from __future__ import annotations

import sys
from dataclasses import dataclass

from .bm25_pg import bm25_search_pg
from .dense_pg import dense_search_pg

RRF_K = 60  # rag/ragkit/retrieve.py와 동일 값


@dataclass
class PgHybridChunk:
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


def hybrid_search_pg(
    query: str, k: int = 8, fanout: int = 30, *, exclude_src: frozenset[str] = frozenset()
) -> list[PgHybridChunk]:
    """`exclude_src`는 dense/bm25 양쪽에 그대로 전달한다(둘 다 같은 `doc_chunk.src`
    규약, `dense_search_pg`/`bm25_search_pg` docstring 참고) — MCP public 프로필이
    라이선스 제한 소스를 걸러내는 지점."""

    dense_chunks = dense_search_pg(query, fanout, exclude_src=exclude_src)
    bm25_chunks = bm25_search_pg(query, fanout, exclude_src=exclude_src)

    dense_rank = {c.chunk_id: c.dense_rank for c in dense_chunks}
    bm25_rank = {c.chunk_id: c.bm25_rank for c in bm25_chunks}
    by_id = {c.chunk_id: c for c in dense_chunks}
    by_id.update({c.chunk_id: c for c in bm25_chunks if c.chunk_id not in by_id})

    scored = []
    for cid in set(dense_rank) | set(bm25_rank):
        s = 0.0
        if cid in dense_rank:
            s += 1.0 / (RRF_K + dense_rank[cid])
        if cid in bm25_rank:
            s += 1.0 / (RRF_K + bm25_rank[cid])
        scored.append((cid, s))
    scored.sort(key=lambda x: -x[1])

    out = []
    for cid, score in scored[:k]:
        c = by_id[cid]
        out.append(PgHybridChunk(
            chunk_id=c.chunk_id, doc_id=c.doc_id, source_path=c.source_path, week=c.week,
            title=c.title, section_heading=c.section_heading, text=c.text,
            dense_rank=dense_rank.get(cid), bm25_rank=bm25_rank.get(cid), rrf_score=score,
        ))
    return out


def hybrid_search_pg_ids(query: str, k: int, fanout: int = 30) -> list[str]:
    return [c.chunk_id for c in hybrid_search_pg(query, k, fanout)]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "2026년 상반기 니켈 LME 가격 동향"
    for c in hybrid_search_pg(q, k=8):
        print(f"[{c.rrf_score:.4f}] dense={c.dense_rank} bm25={c.bm25_rank} "
              f"{c.source_path} :: {c.section_heading}")
        print("   ", c.text[:120].replace("\n", " "))
