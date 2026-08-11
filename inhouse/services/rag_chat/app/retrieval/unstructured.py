# -*- coding: utf-8 -*-
"""비정형 검색 래퍼 — rag/ragkit/retrieve.py(하이브리드 BM25+dense, RRF)의 융합
로직을 그대로 호출한다(재구현 금지).

2026-08-11 범위 결정(실측 근거): docs/CONTAINER_ARCHITECTURE.md §5-4 설계는 dense
벡터를 Qdrant로, BM25를 Postgres doc_chunk.txt_tsv로 이관하는 게 목표지만, 지금
시점에 (1) `rag/index/rag.duckdb` 자체가 아직 빌드된 적이 없고(build_index.py
미실행 — 이관할 데이터가 없음), (2) qdrant-client가 설치돼 있지 않고 Qdrant
서버도 기동돼 있지 않다(둘 다 실측 확인, curl 연결 실패) — 이 상태에서 Qdrant
배선을 만들어봐야 테스트할 방법이 없다. 그래서 이번엔 **이미 검증된 ragkit의
duckdb 하이브리드 검색을 그대로 호출**하는 걸 실제 구현으로 삼는다(§5-4가 원래
"미확정으로 남긴" 것도 세부 구현 백킹 스토어뿐, 하이브리드 검색 자체의 채택은
확정이었음). Qdrant+Postgres tsvector 이관은 그 인프라가 실제로 준비된 다음
별도 사이클로 진행할 것 — 이 파일이 그 이관 지점(hybrid_search 호출부)이다."""
from __future__ import annotations

import sys
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[4]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from rag.ragkit.retrieve import RetrievedChunk, hybrid_search  # noqa: E402,F401


def search_documents(query: str, k: int = 6) -> list[RetrievedChunk]:
    """rag/ragkit의 하이브리드(BM25+dense RRF) 검색을 그대로 호출한다.

    rag/index/rag.duckdb가 아직 없으면(build_index.py 미실행) FileNotFoundError류
    예외가 그대로 올라간다 — 호출자가 "색인 미구축" 상태를 구분해 처리할 것."""

    return hybrid_search(query, k=k)
