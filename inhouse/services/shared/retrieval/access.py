# -*- coding: utf-8 -*-
"""public/private MCP 프로필의 데이터 접근 경계 — 단일 진리원.

`rag/ragkit/mcp_server_public.py`(물리적으로 분리된 public 전용 모듈)가
hybrid_search·pageindex_lookup 두 도구에서 `PRIVATE_ONLY_SOURCE_GROUPS`를,
`_mcp_tools_common.py`가 등록하는 `komis_raw_lookup`이 `PRIVATE_ONLY_KOMIS_PAGES`를
참조한다 — 짝인 `mcp_server_private.py`는 두 상수 모두 아예 import하지 않는다
(제외 로직 자체가 없음). 라이선스 제한 제3자 문서
(현재는 Argus 비철금속 일일동향 하나)만 private 전용이고 나머지(komir 자체
산출물·USGS·조달청보고서 등)는 public — 값이 하나뿐이라도 여러 곳(dense_pg.py·
bm25_pg.py·pageindex.py)이 같은 문자열을 하드코딩하면 나중에 라이선스 목록이
바뀔 때 한 곳을 빠뜨리는 위험이 있어 이 모듈 하나로 모은다.

`data_lake/semi_structure/{okf_documents,pageindex_trees}/Argus_비철금속_일일/`
가 원천이고, `ingest/vectorize/build_pgvector_okf.py`가 pgvector `doc_chunk.src`
컬럼에, PageIndex 트리 JSON이 `source_group` 필드에 이 값을 그대로 싣는다."""
from __future__ import annotations

PRIVATE_ONLY_SOURCE_GROUPS: frozenset[str] = frozenset({"Argus_비철금속_일일"})

#: `komis_raw.AnalysisPreviewPageId` 중 private 프로필 전용인 page_id — 2026-09-01
#: 사용자 지시(같은 날 `indicator_composite` 추가 정정 포함). `indicator_market`
#: (KO_MRKT_PRSPECT_IDCT, 시장동향지표)·`indicator_supply`(KO_SPDM_STBT_INDX,
#: 수급동향지표)·`indicator_composite`(KO_MNRL_SNTHS_INDX, 광물종합지수) 3개
#: 테이블만 private 전용이고, 나머지 6개 `ko_*`(가격·가격예측·교역 2종·매장량·
#: 생산량)는 public이다. 매핑 메타데이터 테이블(`ai_hs_mnrl_map`·`ai_prc_mnrl_map`)은
#: 특정 page_id로 노출되지 않고 komis_raw.py 내부에서 코드→필터값 번역에만 쓰여
#: 이 제한과 무관하다(두 프로필 모두 공통으로 계속 쓴다).
PRIVATE_ONLY_KOMIS_PAGES: frozenset[str] = frozenset(
    {"indicator_market", "indicator_supply", "indicator_composite"}
)
