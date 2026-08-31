# -*- coding: utf-8 -*-
"""ragkit MCP 서버 — **private 프로필**. `mcp_server_public.py`와 물리적으로
분리된 별도 모듈이다(2026-08-26, 사용자 요청 — 배경은 `mcp_server_public.py`
모듈독스트링 참고). `mcp_client.py`가 이 모듈을 stdio 서브프로세스로 띄운다.

**이 파일은 라이선스 제한 소스(Argus 비철금속 일일동향)를 걸러내는 코드가
아예 없다** — `hybrid_search`/`pageindex_lookup` 두 tool이 하위 함수
(`hybrid_pg.hybrid_search_pg`/`pageindex.lookup`)를 `exclude_src`/
`exclude_source_groups` 인자 없이(기본값 = 빈 집합 = 무제한) 그대로 부른다.
`shared.retrieval.access.PRIVATE_ONLY_SOURCE_GROUPS`를 이 파일이 import조차
안 한다 — public 쪽 제한 로직을 우회할 조건문이 구조적으로 없다.

정형 3종·komis_raw_lookup·komis_resolve_mineral·pageindex_agentic(라이선스
무관, public/private 결과 동일)은 `_mcp_tools_common.py`에 한 번만 구현돼
있고 여기서는 등록만 한다(재구현 금지).

실행(직접 점검용, 실제로는 mcp_client.py가 서브프로세스로 띄운다):
    cd inhouse && python -m rag.ragkit.mcp_server_private
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from shared.retrieval import hybrid_pg, pageindex  # noqa: E402
from shared.retrieval.evidence import from_dense_chunk, from_pageindex_hit  # noqa: E402

from ._mcp_tools_common import register_common_tools  # noqa: E402

mcp = FastMCP("komir-ragkit-private")
register_common_tools(mcp)


@mcp.tool()
def hybrid_search(query: str, k: int = 8, fanout: int = 30) -> dict[str, Any]:
    """dense(pgvector)+BM25 RRF 하이브리드 문서검색 — {"evidence": [...]}.
    라이선스 제한 소스(Argus) 포함 전체 코퍼스 대상(필터 없음)."""

    chunks = hybrid_pg.hybrid_search_pg(query, k, fanout)
    return {"evidence": [dataclasses.asdict(from_dense_chunk(c)) for c in chunks]}


@mcp.tool()
def pageindex_lookup(
    query: str,
    doc: str | None = None,
    doc_limit: int = 3,
    node_limit: int = 5,
    with_text: bool = True,
) -> dict[str, Any]:
    """PageIndex(OKF 목차 트리) 결정적 단발조회 — {문서 후보, 관련 노드(+원문)}.
    라이선스 제한 소스(Argus) 포함 전체 트리 대상(필터 없음)."""

    result = pageindex.lookup(
        query, doc=doc, doc_limit=doc_limit, node_limit=node_limit, with_text=with_text,
    )
    return {
        "documents": result["documents"],
        "nodes": [dataclasses.asdict(from_pageindex_hit(hit)) for hit in result["nodes"]],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
