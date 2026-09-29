"""공용 정형 원천 카탈로그의 검증된 테이블 경로 조회기."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

import yaml

_CATALOG_PATH = Path(__file__).with_name("resources") / "komis_data_schema.yml"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@lru_cache(maxsize=1)
def _source_tables() -> dict[str, str]:
    raw = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError(f"invalid data source catalog: {_CATALOG_PATH}")
    sources = raw.get("sources")
    if not isinstance(sources, dict):
        raise ValueError(f"data source catalog has no sources map: {_CATALOG_PATH}")
    result: dict[str, str] = {}
    for source_id, entry in sources.items():
        if not isinstance(entry, dict):
            raise ValueError(f"invalid data source definition: {source_id}")
        schema, table = entry.get("schema"), entry.get("table")
        if not isinstance(schema, str) or not _IDENTIFIER.fullmatch(schema):
            raise ValueError(f"invalid schema identifier in source: {source_id}")
        if not isinstance(table, str) or not _IDENTIFIER.fullmatch(table):
            raise ValueError(f"invalid table identifier in source: {source_id}")
        result[str(source_id)] = f"{schema}.{table}"
    return result


def source_table(source_id: str) -> str:
    """카탈로그에 등록된 `schema.table`만 반환한다."""
    try:
        return _source_tables()[source_id]
    except KeyError as exc:
        raise KeyError(f"unknown structured data source: {source_id}") from exc
