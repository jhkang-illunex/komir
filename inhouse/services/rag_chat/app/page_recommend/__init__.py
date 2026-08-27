# -*- coding: utf-8 -*-
"""KOMIS 페이지·필터 추천(komis-report-generator-main `search/` 이식본).

이 패키지만 `__init__.py`를 두는 이유: 하위 모듈(graph.py·service.py)이
`services/shared/llm_client.py`를 `shared.llm_client`라는 짧은 이름으로 임포트하는데
(rag_chat Containerfile이 services/shared→./shared로 평평하게 COPY하는 기존 관례,
session_store.py 주석 참고), 소스트리와 컨테이너 배포본의 상대 깊이가 달라 고정
depth로는 두 경우를 다 맞출 수 없다. 패키지 임포트 시점에 한 번 위로 훑어 찾는다
(services/shared/db.py·ingest/parsers/pdf.py가 쓰는 것과 같은 패턴)."""
from __future__ import annotations

import sys
from pathlib import Path


def _find_shared_parent(start: Path) -> Path:
    """`shared/llm_client.py`를 담은 디렉토리를 위로 훑어 찾는다."""

    for candidate in (start, *start.parents):
        if (candidate / "shared" / "llm_client.py").is_file():
            return candidate
    raise ImportError(f"shared/llm_client.py를 {start} 상위에서 찾지 못함")


_SHARED_PARENT = _find_shared_parent(Path(__file__).resolve())
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))
