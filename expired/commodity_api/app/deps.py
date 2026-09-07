# -*- coding: utf-8 -*-
"""FastAPI 의존성 — 광종 코드 검증 + 모델 재적합 결과 캐시.

DB 접근은 `services/shared/db.py`(→ `mineral_supply_risk/db/dbio.py`)를 통해서만
한다. 이 모듈은 그 위에 두 가지를 얹는다:
  1) 경로 URL의 `cc`가 5광종(CU/NI/CO/LI/REE) 중 하나인지 검증(아니면 404).
  2) `dashboards/streamlit_app.py`가 `st.cache_data`로 하던 "DB mtime 기준 캐시"를
     API 서버 프로세스 메모리에 그대로 재현(in-memory, TTL 없음 — DB 파일이
     바뀌지 않는 한 계속 유효, mtime이 바뀌면 자동 무효화). ExtraTrees 예측
     재적합은 conformal 보정까지 포함하면 수 분 걸리므로(원본 docstring 참고)
     이 캐시가 없으면 매 요청마다 그 비용을 치른다.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Callable

from fastapi import HTTPException, Path

from . import _bootstrap  # noqa: F401 — import 시점에 sys.path 부트스트랩

from msr.config import CORE_COMMODITIES, DB_PATH  # noqa: E402

# streamlit_app.py와 동일한 표시 순서(CORE_COMMODITIES dict 삽입순은 CU/NI/LI/CO/REE라
# 화면 순서와 다름 — 기존 데모가 써온 CCS 순서를 그대로 따른다).
CCS = ["CU", "NI", "CO", "LI", "REE"]
CC_KO = {cc: f"{CORE_COMMODITIES[cc]['ko']}({cc})" for cc in CCS}


def cc_path(cc: str = Path(..., description="광종 코드: CU|NI|CO|LI|REE")) -> str:
    """경로 파라미터 `cc`를 검증하고 대문자로 정규화한다."""

    up = cc.upper()
    if up not in CCS:
        raise HTTPException(status_code=404, detail=f"지원하지 않는 광종 코드: {cc} (허용: {', '.join(CCS)})")
    return up


# ─────────────────────────── 모델 재적합 결과 캐시 ───────────────────────────
_cache: dict[tuple[str, float], Any] = {}
_cache_lock = threading.Lock()


def db_mtime() -> float:
    """streamlit_app.py의 `_db_key()`와 동일 — DB 파일이 갱신되면 캐시가
    자동 무효화되도록 하는 캐시 키."""

    try:
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0.0


def cached(name: str, loader: Callable[[], Any]) -> Any:
    """`loader()`의 결과를 (name, db_mtime) 키로 프로세스 메모리에 캐시한다.

    동시 요청이 같은 키를 중복 계산하지 않도록 락으로 보호(ExtraTrees 재적합처럼
    비용이 큰 로더가 동시에 여러 번 도는 것을 막기 위함)."""

    key = (name, db_mtime())
    if key in _cache:
        return _cache[key]
    with _cache_lock:
        if key not in _cache:  # 락 대기 중 다른 스레드가 이미 채웠을 수 있음
            try:
                _cache[key] = loader()
            except Exception as exc:  # noqa: BLE001 — 원인을 500 detail로 노출
                raise HTTPException(
                    status_code=500, detail=f"'{name}' 모델 재적합 실패: {exc}"
                ) from exc
        return _cache[key]


def clear_cache() -> int:
    """캐시 전체를 비운다(streamlit 데모의 "모델 다시 적합" 버튼과 동일 기능).
    돌려주는 값은 비워진 엔트리 수."""

    with _cache_lock:
        n = len(_cache)
        _cache.clear()
        return n
