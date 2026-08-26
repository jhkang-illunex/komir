# -*- coding: utf-8 -*-
"""public/private MCP 프로필의 데이터 접근 경계 — 단일 진리원.

`rag/ragkit/mcp_server_public.py`(물리적으로 분리된 public 전용 모듈)가
hybrid_search·pageindex_lookup 두 도구에서만 이 상수를 참조한다 — 짝인
`mcp_server_private.py`는 이 상수를 아예 import하지 않는다(제외 로직 자체가
없음). 라이선스 제한 제3자 문서
(현재는 Argus 비철금속 일일동향 하나)만 private 전용이고 나머지(komir 자체
산출물·USGS·조달청보고서 등)는 public — 값이 하나뿐이라도 여러 곳(dense_pg.py·
bm25_pg.py·pageindex.py)이 같은 문자열을 하드코딩하면 나중에 라이선스 목록이
바뀔 때 한 곳을 빠뜨리는 위험이 있어 이 모듈 하나로 모은다.

`data_lake/semi_structure/{okf_documents,pageindex_trees}/Argus_비철금속_일일/`
가 원천이고, `services/ingestion/build_pgvector_okf.py`가 pgvector `doc_chunk.src`
컬럼에, PageIndex 트리 JSON이 `source_group` 필드에 이 값을 그대로 싣는다."""
from __future__ import annotations

PRIVATE_ONLY_SOURCE_GROUPS: frozenset[str] = frozenset({"Argus_비철금속_일일"})
