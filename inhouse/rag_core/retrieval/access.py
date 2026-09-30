# -*- coding: utf-8 -*-
"""public/private MCP 프로필의 데이터 접근 경계 — 단일 진리원.

`rag_core/ragkit/mcp_server_public.py`(물리적으로 분리된 public 전용 모듈)가
hybrid_search·pageindex_lookup 두 도구에서 `PRIVATE_ONLY_SOURCE_GROUPS`를,
`_mcp_tools_common.py`가 등록하는 `komis_raw_lookup`이 `PRIVATE_ONLY_KOMIS_PAGES`를
참조한다 — 짝인 `mcp_server_private.py`는 두 상수 모두 아예 import하지 않는다
(제외 로직 자체가 없음). 해외 발행처 문서는 출처별 그룹을 private 전용으로 관리하고
나머지(komir 자체 산출물·USGS·조달청보고서 등)는 public — 같은 목록을 여러 곳(dense_pg.py·
bm25_pg.py·pageindex.py)이 같은 문자열을 하드코딩하면 나중에 라이선스 목록이
바뀔 때 한 곳을 빠뜨리는 위험이 있어 이 모듈 하나로 모은다.

`data_lake/semi_structure/{okf_documents,pageindex_trees}/<source_group>/`
가 원천이고, `ingest/vectorize/build_pgvector_okf.py`가 pgvector `doc_chunk.src`
컬럼에, PageIndex 트리 JSON이 `source_group` 필드에 이 값을 그대로 싣는다.
해외 발행처 그룹은 WoodMackenzie·AsianMetal·CRU·IEA 등 실제 발행처명이다."""
from __future__ import annotations

PRIVATE_ONLY_SOURCE_GROUPS: frozenset[str] = frozenset({
    "Argus_비철금속_일일",
    "WoodMackenzie",
    "AsianMetal",
    "CRU",
    "IEA",
})

#: `komis_raw.AnalysisPreviewPageId` 중 public 프로필에서 private 전용인 page_id.
#: 광물종합지수(`indicator_composite`)는 public 허용이다.
PRIVATE_ONLY_KOMIS_PAGES: frozenset[str] = frozenset(
    {"indicator_market", "indicator_supply"}
)

#: 2026-09-30 사용자 요청 — 시장동향지표·수급동향지표 원천 테이블을 RDB 자원
#: 목록에서 제거하고, public/private 어느 프로필에서도 조회하지 않는다. 챗봇은
#: 이 집합을 만나면 검색·fallback 없이 접근 권한 없음으로 종료한다.
RESTRICTED_KOMIS_PAGES: frozenset[str] = frozenset(
    {"indicator_market", "indicator_supply"}
)
