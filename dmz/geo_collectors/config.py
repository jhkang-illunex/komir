# -*- coding: utf-8 -*-
"""경로 설정(DMZ geo_collectors 전용). 원래 engine/geo/collectors/였을 때는 부모 geo 패키지의
config.py(GEO_DATA 등)를 `from .. import config`로 공유했으나, 2026-08-06 DMZ/in-house 물리
분리로 geo_collectors가 dmz/ 아래 독립 패키지가 되며 그 상대 임포트가 끊겼다(부모에 config가
없음 — 실측: `ImportError: attempted relative import beyond top-level package`).
DMZ는 in-house 코드에 의존하면 안 되므로(격리 원칙) gnews.py/gdelt.py/_common.py가 쓰는
최소 부분집합(GEO_DATA/INBOX/ensure_dirs)만 여기서 자체 정의한다 — 나머지(LLM·STORE 등
in-house 전용 설정)는 없다."""
import os
from pathlib import Path

GEO_DATA = Path(os.environ.get("GEO_DATA", "./geo_data")).resolve()
INBOX = GEO_DATA / "inbox"


def ensure_dirs():
    INBOX.mkdir(parents=True, exist_ok=True)
