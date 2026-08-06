# -*- coding: utf-8 -*-
"""비정형 검색 래퍼 — 설계 단계 스켈레톤. rag/ragkit/retrieve.py(하이브리드 BM25+dense,
RRF)의 융합 로직을 그대로 호출한다(재구현 금지) — 단 2026-08-05 결정으로 조회 대상이
둘로 나뉜다: dense 벡터는 Qdrant(qdrant-client, QDRANT_COLLECTION), BM25는 Postgres
doc_chunk.txt_tsv(§4). 대상 인덱스를 기존 rag/index/rag.duckdb 단일 파일에서 이 두
저장소로 옮기는 게 이 모듈의 실질 구현 작업 — 융합(RRF) 단계는 무변경."""
raise NotImplementedError("설계 단계 스켈레톤 — 구현은 다음 세션(docs/CONTAINER_ARCHITECTURE.md §8)")
