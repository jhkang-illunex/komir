# -*- coding: utf-8 -*-
"""비정형 dense 검색 — pgvector(komis_demo `mineral_risk.doc_chunk`) 버전.

`rag/ragkit/retrieve.py`의 `dense_search()`(DuckDB `list_cosine_similarity`)와
**같은 역할·같은 반환 계약**을 갖는 교체 가능한 구현이다. RRF 융합 로직은
여기 재구현하지 않는다(재구현 금지) — 이 모듈은 하이브리드의 dense 절반만
담당하고, BM25 절반은 당분간 rag/index/rag.duckdb의 DuckDB FTS 그대로다
(2026-08-11 작업 범위: dense 벡터 저장소 전환만).

질의 임베딩은 `rag/ragkit/embed.encode_query()`를 그대로 쓴다 — 적재
(build_pgvector_index.py)와 같은 모델·같은 접두어("query: "/"passage: ")를
써야 벡터 공간이 일치한다. 로컬 sentence-transformers라 외부 API 호출 없음
(airgap 전제).

⚠ 스키마는 항상 `get_settings().PG_SCHEMA`(mineral_risk)로만 한정한다 —
   "public"을 하드코딩하지 않는다(services/shared/db.py 규약, public은 타 팀 소유).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from ..db import pg_connect


def _find_rag_parent(start: Path) -> Path:
    """`rag/ragkit/embed.py`를 담은 디렉토리를 위로 훑어 찾는다(소스트리는
    inhouse/, 컨테이너 배포본은 COPY 깊이가 달라 고정 depth를 못 쓴다 —
    services/shared/db.py `_find_msr_root`와 같은 이유·같은 패턴)."""

    for candidate in (start, *start.parents):
        if (candidate / "rag" / "ragkit" / "embed.py").is_file():
            return candidate
    raise ImportError(f"rag/ragkit/embed.py를 {start} 상위에서 찾지 못함")


_RAG_PARENT = _find_rag_parent(Path(__file__).resolve())
if str(_RAG_PARENT) not in sys.path:
    sys.path.insert(0, str(_RAG_PARENT))

from rag.ragkit.embed import encode_query  # noqa: E402


@dataclass
class PgRetrievedChunk:
    """`rag/ragkit/retrieve.RetrievedChunk`와 필드명을 맞춘 결과 레코드.

    dense 전용이라 bm25_rank/rrf_score는 없고, 대신 코사인 유사도(score)를
    싣는다 — RRF 융합 쪽에 넘길 땐 chunk_id/dense_rank만 있으면 된다."""

    chunk_id: str
    doc_id: str
    source_path: str
    week: str
    title: str
    section_heading: str
    text: str
    dense_rank: int
    score: float


def _vector_literal(vec) -> str:
    """pgvector 텍스트 리터럴(build_pgvector_index._vector_literal과 동일 규약)."""

    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def dense_search_pg(query: str, k: int = 8) -> list[PgRetrievedChunk]:
    """pgvector 코사인 유사도 상위 k개 청크.

    `<=>`(vector_cosine_ops)는 코사인 **거리**라 오름차순 정렬이고, 적재 벡터가
    정규화돼 있으므로 유사도 = 1 - 거리다. 인덱스(idx_doc_chunk_embedding_hnsw)와
    같은 연산자를 써야 인덱스를 탄다.

    참고(2026-08-11 실측): 현재 코퍼스(1,206행)에선 플래너가 HNSW 인덱스 스캔
    대신 Seq Scan을 고른다 — 테이블이 작아 그게 실제로 더 싸고, 부수적으로
    근사(ANN)가 아니라 **정확한** top-k가 나온다(그래서 DuckDB dense와 결과가
    완전히 일치했다). enable_seqscan=off로 확인한 결과 인덱스 자체는 정상
    동작한다(Index Scan using idx_doc_chunk_embedding_hnsw). 코퍼스가 커지면
    자연히 인덱스 경로로 전환된다."""

    schema = get_settings().PG_SCHEMA
    qvec = _vector_literal(encode_query(query))

    con = pg_connect()
    try:
        with con.cursor() as cur:
            # HNSW 탐색 폭 — 기본 40. k가 크면 재현율 확보를 위해 넉넉히 잡는다.
            cur.execute("SET hnsw.ef_search = %s", (max(40, k * 4),))
            cur.execute(
                f"""
                SELECT chunk_id, doc_id, source_path, week, title, section_heading, txt,
                       embedding <=> %s::vector AS dist
                FROM {schema}.doc_chunk
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (qvec, qvec, k),
            )
            rows = cur.fetchall()
    finally:
        con.close()

    return [
        PgRetrievedChunk(
            chunk_id=r[0], doc_id=r[1], source_path=r[2] or "", week=r[3] or "",
            title=r[4] or "", section_heading=r[5] or "", text=r[6] or "",
            dense_rank=i + 1, score=1.0 - float(r[7]),
        )
        for i, r in enumerate(rows)
    ]


def dense_search_pg_ids(query: str, k: int) -> list[str]:
    """`rag/ragkit/retrieve.dense_search()`의 드롭인 대체(chunk_id 리스트만).

    hybrid_search의 RRF 융합부에 그대로 꽂을 수 있는 형태 — 융합 로직 자체는
    건드리지 않는다."""

    return [c.chunk_id for c in dense_search_pg(query, k)]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "핵심광물 진단모델 QWK 성능은 얼마인가"
    for c in dense_search_pg(q, k=5):
        print(f"[{c.score:.4f}] #{c.dense_rank} {c.source_path} :: {c.section_heading}")
        print("   ", c.text[:120].replace("\n", " "))
