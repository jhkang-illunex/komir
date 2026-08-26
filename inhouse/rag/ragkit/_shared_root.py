# -*- coding: utf-8 -*-
"""`shared.llm_client`/`shared.retrieval.*`를 최상위 패키지로 import하기 위한
sys.path 부트스트랩 — `chatbot_graph.py`·`mcp_server_public.py`·
`mcp_server_private.py`·`mcp_client.py`가 공유(2026-08-26, MCP 서버 신설 때
`chatbot_graph.py`에서 뽑아냄, TWIN 방지)."""
from __future__ import annotations

import sys
from pathlib import Path


def find_shared_root(start: Path) -> Path:
    """`shared.llm_client`/`shared.retrieval.*`를 최상위 패키지로 import할 수
    있는 sys.path 루트를 찾는다.

    `services/rag_chat/app/routers/chat.py`의 `_find_root`(조상 방향 탐색)와
    달리 이 파일들(`rag/ragkit/*.py`)에선 그 패턴이 안 통한다 — `rag/ragkit`과
    `services/shared`는 **형제** 디렉토리라, `rag/ragkit`에서 조상 쪽으로
    아무리 올라가도 `services/shared`를 절대 지나치지 않는다(`dense_pg.py`의
    `_find_rag_parent`가 반대 방향으로 이 문제를 풀 때는 컨테이너가
    `rag/ragkit` 상대경로를 그대로 보존해줘서 마커 하나로 됐지만, 이쪽 방향은
    소스트리(`services/shared/llm_client.py`)와 컨테이너(services→./shared로
    평평화된 `shared/llm_client.py`)의 마커 경로 자체가 다르다 — 마커 하나로는
    못 풀어 두 경우를 각각 확인한다)."""

    for candidate in (start, *start.parents):
        if (candidate / "shared" / "llm_client.py").is_file():
            return candidate  # 컨테이너 배포본: services/shared→./shared로 평평화됨
        if (candidate / "services" / "shared" / "llm_client.py").is_file():
            return candidate / "services"  # 소스트리: inhouse/services/shared/...
    raise ImportError(f"shared/llm_client.py를 {start} 상위에서 찾지 못함(소스트리·컨테이너 배포본 둘 다 확인함)")


def ensure_shared_on_path(start: Path) -> Path:
    """`find_shared_root()` 결과를 `sys.path`에 없으면 넣고 그 경로를 돌려준다."""

    root = find_shared_root(start)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root
