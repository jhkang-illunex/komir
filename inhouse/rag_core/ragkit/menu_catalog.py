"""메뉴 기준 출처 카탈로그 조회.

문서 검색 근거에는 적용하지 않고, ``Evidence.menu_page_id``가 있는 KOMIS RDB
근거에만 메뉴 경로와 원천 메타데이터를 붙인다.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_PATH = Path(__file__).with_name("resources") / "menu_data_catelog.yml"


@lru_cache(maxsize=1)
def menu_catalog() -> dict[str, dict]:
    raw = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError(f"invalid menu data catalog: {_PATH}")
    items = [item for menu in raw.get("menus", []) for item in menu.get("items", [])]
    catalog = {item["page_id"]: item for item in items if isinstance(item, dict) and item.get("page_id")}
    if len(catalog) != len(items):
        raise ValueError(f"duplicate or invalid page_id in menu data catalog: {_PATH}")
    return catalog


def menu_source(page_id: str | None) -> dict | None:
    if not page_id:
        return None
    entry = menu_catalog().get(page_id)
    if entry is None:
        return None
    return {
        "page_id": entry["page_id"], "label": entry["label"],
        "source_label": entry["source_label"], "source_tables": list(entry["source_tables"]),
        "period_frequency": entry["period_frequency"], "access": entry.get("access", "public"),
    }
