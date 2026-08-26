# -*- coding: utf-8 -*-
"""비정형 sparse(어휘) 검색 — Postgres 전문검색(FTS) 버전, `dense_pg.py`의 짝.

`rag/ragkit/retrieve.py`의 `bm25_search()`(DuckDB `fts_main_chunk.match_bm25`)와
같은 역할이지만, 그 인덱스는 구 코퍼스(<100건)용이라 지금 코퍼스(pgvector
`mineral_risk.doc_chunk`, 140,031행)엔 안 맞는다(같은 데이터를 DuckDB FTS에도
중복 색인하면 두 저장소를 계속 동기화해야 함 — 유지보수 부담). 대신 dense와
**같은 테이블**에 Postgres 내장 전문검색(`to_tsvector`/`ts_rank_cd`)을 얹는다.

`'simple'` config를 쓴다(`'english'`/한국어 전용 config 아님) — 형태소 분석 없이
공백/구두점 기준 토큰화만 한다. 이 프로젝트 코퍼스의 절반 이상(Argus, 영문)엔
문제 없고, 한국어 문서(조달청·KOMIS 등)는 어간 활용형까지는 못 잡지만 **숫자·
연도·영문 고유명사**(이 하이브리드를 도입한 원래 동기 — "2026", "DRC", "LME" 같은
dense 임베딩이 놓치기 쉬운 정확 토큰) 매칭엔 그걸로 충분하다. 한국어 형태소
분석기(`rag/ragkit/tokenize_ko.py`)를 여기 붙이는 건 별도 과업(제목에 없는 범위
확장이라 지금은 안 함) — 필요해지면 `to_tsvector('simple', tokenize_ko.to_fts_text(txt))`
GENERATED 컬럼으로 교체 검토.

인덱스: `idx_doc_chunk_txt_fts`(GIN, `to_tsvector('simple', txt)`) — 2026-08-19 신설,
순수 추가 DDL(기존 컬럼/데이터 변경 없음).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from ..config import get_settings
from ..db import pg_connect


@dataclass
class PgBm25Chunk:
    chunk_id: str
    doc_id: str
    source_path: str
    week: str
    title: str
    section_heading: str
    text: str
    bm25_rank: int
    score: float


def bm25_search_pg(
    query: str, k: int = 8, *, exclude_src: frozenset[str] = frozenset()
) -> list[PgBm25Chunk]:
    """Postgres 전문검색 상위 k개 청크(`ts_rank_cd` 내림차순).

    `plainto_tsquery`는 질의를 AND로 묶는다(OR 아님) — 짧은 키워드 질의엔 맞지만
    자연어 문장 전체를 그대로 넣으면 한 단어라도 코퍼스에 없으면 매치가 0이 될
    수 있다. 그래서 질의를 공백 기준으로 토큰화해 `to_tsquery`에 `|`(OR)로
    묶는다 — dense(의미)가 이미 전체 문장 관련성을 보므로, sparse 쪽은 "이
    토큰들 중 뭐라도 정확히 들어있는 문서"를 넓게 잡아오는 역할로 충분하다
    (RRF 융합이 순위로 재조정하지, 여기서 정밀도를 낼 필요 없음).

    `exclude_src`: `dense_search_pg`와 동일 규약 — `doc_chunk.src`가 이 집합에
    있으면 SQL 단에서 제외(기본값 빈 집합이면 기존 동작과 동일)."""

    schema = get_settings().PG_SCHEMA
    # to_tsquery는 &/|/!/():()가 연산자라 원문 토큰에 구두점("LME," "(2026)")이
    # 섞이면 구문에러가 난다 — 영숫자·한글만 남기고 나머지는 제거(의미상 손실은
    # 없다, 어차피 'simple' config가 구두점을 토큰 경계로 봐서 색인 시에도
    # 떨어져 나감).
    tokens = [re.sub(r"[^\w가-힣]+", "", t) for t in query.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return []
    tsquery = " | ".join(tokens)
    exclude_clause = " AND src <> ALL(%s)" if exclude_src else ""
    exclude_param = (list(exclude_src),) if exclude_src else ()

    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"""
                SELECT chunk_id, doc_id, source_path, week, title, section_heading, txt,
                       ts_rank_cd(to_tsvector('simple', txt), query) AS rank
                FROM {schema}.doc_chunk, to_tsquery('simple', %s) query
                WHERE to_tsvector('simple', txt) @@ query{exclude_clause}
                ORDER BY rank DESC
                LIMIT %s
                """,
                (tsquery, *exclude_param, k),
            )
            rows = cur.fetchall()
    finally:
        con.close()

    return [
        PgBm25Chunk(
            chunk_id=r[0], doc_id=r[1], source_path=r[2] or "", week=r[3] or "",
            title=r[4] or "", section_heading=r[5] or "", text=r[6] or "",
            bm25_rank=i + 1, score=float(r[7]),
        )
        for i, r in enumerate(rows)
    ]


def bm25_search_pg_ids(query: str, k: int) -> list[str]:
    return [c.chunk_id for c in bm25_search_pg(query, k)]


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "DRC 코발트 수출 2025"
    for c in bm25_search_pg(q, k=5):
        print(f"[{c.score:.4f}] #{c.bm25_rank} {c.source_path} :: {c.section_heading}")
        print("   ", c.text[:120].replace("\n", " "))
