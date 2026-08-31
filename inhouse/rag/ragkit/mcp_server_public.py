# -*- coding: utf-8 -*-
"""ragkit MCP 서버 — **public 프로필**. `mcp_server_private.py`와 물리적으로
분리된 별도 모듈이다(2026-08-26, 사용자 요청 — 이전엔 `MCP_PROFILE` 환경변수
하나로 파일 하나에서 분기했으나, 런타임 플래그에 기대는 대신 "어느 파일을
실행했는가"로 신뢰 경계를 옮겼다). `mcp_client.py`가 이 모듈을 stdio
서브프로세스로 띄운다.

**이 파일을 처음부터 끝까지 읽어도 라이선스 제한 소스(Argus 비철금속
일일동향, `shared.retrieval.access.PRIVATE_ONLY_SOURCE_GROUPS`)를 포함시키는
코드 경로가 없다** — `hybrid_search`/`pageindex_lookup` 두 tool이 그 상수를
`exclude_src`/`exclude_source_groups`로 **하드코딩**해서 하위 함수(`hybrid_pg.
hybrid_search_pg`/`pageindex.lookup`)에 넘긴다. 조건문·환경변수 분기가 전혀
없다 — private 쪽으로 값이 새려면 이 파일 자체를 고쳐야 한다.

정형 3종·komis_raw_lookup·komis_resolve_mineral·pageindex_agentic(라이선스
무관, public/private 결과 동일)은 `_mcp_tools_common.py`에 한 번만 구현돼
있고 여기서는 등록만 한다(재구현 금지).

실행(직접 점검용, 실제로는 mcp_client.py가 서브프로세스로 띄운다):
    cd inhouse && python -m rag.ragkit.mcp_server_public
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from shared.retrieval import hybrid_pg, pageindex  # noqa: E402
from shared.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS  # noqa: E402
from shared.retrieval.evidence import from_dense_chunk, from_pageindex_hit  # noqa: E402

from ._mcp_tools_common import register_common_tools  # noqa: E402

mcp = FastMCP("komir-ragkit-public")
register_common_tools(mcp)


@mcp.tool()
def hybrid_search(query: str, k: int = 8, fanout: int = 30) -> dict[str, Any]:
    """dense(pgvector)+BM25 RRF 하이브리드 문서검색 — {"evidence": [...]}.
    라이선스 제한 소스(Argus)를 SQL 단에서 항상 제외한다(하드코딩, 조건 없음)."""

    chunks = hybrid_pg.hybrid_search_pg(query, k, fanout, exclude_src=PRIVATE_ONLY_SOURCE_GROUPS)
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
    라이선스 제한 소스(Argus)를 트리 후보에서 항상 제외한다(하드코딩, 조건 없음)."""

    result = pageindex.lookup(
        query, doc=doc, doc_limit=doc_limit, node_limit=node_limit, with_text=with_text,
        exclude_source_groups=PRIVATE_ONLY_SOURCE_GROUPS,
    )
    return {
        "documents": result["documents"],
        "nodes": [dataclasses.asdict(from_pageindex_hit(hit)) for hit in result["nodes"]],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
