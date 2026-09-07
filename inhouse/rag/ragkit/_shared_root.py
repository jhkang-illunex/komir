# -*- coding: utf-8 -*-
"""`common.llm_client`/`rag.retrieval.*`를 최상위 패키지로 import하기 위한
sys.path 부트스트랩 — `chatbot_graph.py`·`mcp_server_public.py`·
`mcp_server_private.py`·`mcp_client.py`가 공유(2026-08-26 신설, TWIN 방지).

2026-09-07 services/ 해체 재구성 이후로는 소스트리(inhouse/)와 컨테이너
배포본(/app)의 레이아웃이 동일해져서(`common/`·`rag/`가 둘 다 루트 직속)
과거의 소스트리/컨테이너 이중 분기 없이 마커 하나로 루트를 찾는다."""
from __future__ import annotations

import sys
from pathlib import Path


def find_shared_root(start: Path) -> Path:
    """`common/llm_client.py`를 담은 루트(inhouse/ 또는 컨테이너 /app)를 찾는다."""

    for candidate in (start, *start.parents):
        if (candidate / "common" / "llm_client.py").is_file():
            return candidate
    raise ImportError(f"common/llm_client.py를 {start} 상위에서 찾지 못함")


def ensure_shared_on_path(start: Path) -> Path:
    """`find_shared_root()` 결과를 `sys.path`에 없으면 넣고 그 경로를 돌려준다."""

    root = find_shared_root(start)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root
