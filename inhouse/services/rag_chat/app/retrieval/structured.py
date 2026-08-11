# -*- coding: utf-8 -*-
"""정형(RDB) 검색 — 템플릿 질의만 지원(docs/CONTAINER_ARCHITECTURE.md §5-4 권고안
그대로): LLM은 "어떤 템플릿+어떤 광종"만 고르고, SQL 자체는 파라미터화된 하드코딩
쿼리만 실행한다. 자유형 NL→SQL은 구현하지 않는다(운영 DB 직접 노출 위험 —
인젝션·환각 둘 다).

2026-08-11(2차): 실제 SQL은 전부 `services/shared/retrieval/structured.py`(정본)로
옮겼다 — 같은 날 report_gen이 따로 만든 사본과의 중복 제거(§6 "중복 구현 금지").
이 파일에는 **LLM 도구호출 계약**(`TEMPLATES`/`run_template`)과, 챗봇이 쓰기 좋은
형태(최신 1건)로 얇게 감싸는 어댑터만 남는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICES_ROOT = Path(__file__).resolve().parents[3]
if str(_SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICES_ROOT))

from shared.retrieval.structured import (  # noqa: E402,F401
    VALID_COMMODITIES,
    StructuredQueryError,
    import_forecast,
    latest_diagnosis,
)
from shared.retrieval.structured import geo_index_trend as _geo_index_trend  # noqa: E402


def latest_geo_index(commodity_code: str, freq: str = "W") -> dict | None:
    """"{cc} 최근 위기지수?" — freq: 'W'(주간)|'M'(월간). 가장 최근 1건."""

    rows = _geo_index_trend(commodity_code, freq, limit=1)
    return rows[-1] if rows else None


TEMPLATES = {
    "latest_diagnosis": latest_diagnosis,
    "import_forecast": import_forecast,
    "latest_geo_index": latest_geo_index,
}


def run_template(name: str, **kwargs):
    """LLM이 고른 템플릿 이름 + 파라미터로 실행(라우터/도구 호출 진입점)."""

    fn = TEMPLATES.get(name)
    if fn is None:
        raise StructuredQueryError(f"알 수 없는 템플릿: {name!r} (지원: {sorted(TEMPLATES)})")
    return fn(**kwargs)
