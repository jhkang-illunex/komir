# -*- coding: utf-8 -*-
"""`services/shared/*`를 import할 수 있게 sys.path를 잡아준다.

소스트리(`inhouse/services/report_gen/app/...` — shared는 4단 위의
`services/shared`)와 컨테이너 배포본(Containerfile이 `services/shared`→`/app/shared`,
`services/report_gen/app`→`/app/app`으로 평평하게 COPY — shared는 2단 위)의 상대
깊이가 달라 고정 depth 대신 위로 훑어 찾는다(`services/shared/db.py`의
`_find_msr_root`, `ingest/parsers/pdf.py`의 geo 탐색과 같은 패턴).
"""
from __future__ import annotations

import sys
from pathlib import Path


def ensure_shared_on_path() -> Path:
    """`shared/db.py`를 담은 디렉토리를 sys.path에 넣고 그 경로를 돌려준다."""

    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "shared" / "db.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate
    raise ImportError(f"shared/db.py를 {here} 상위에서 찾지 못함")


SHARED_PARENT = ensure_shared_on_path()
