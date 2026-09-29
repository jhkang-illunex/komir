# -*- coding: utf-8 -*-
"""PageIndex ``*.facts.json`` 파생 사실의 결정적 조회 adapter."""
from __future__ import annotations

import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from .evidence import Evidence


def _default_root() -> Path:
    try:
        from common.config import get_settings
        value = (get_settings().INGEST_DATA_LAKE_DIR or "").strip()
        if value:
            return Path(value).expanduser().resolve() / "pageindex_trees"
    except Exception:  # noqa: BLE001
        pass
    return Path(__file__).resolve().parents[2] / "data_lake/semi_structure/pageindex_trees"


FACTS_ROOT = Path(os.environ.get("PAGEINDEX_TREES_DIR", _default_root()))
_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})[-._/](0?[1-9]|1[0-2])(?!\d)")
_KOREAN_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})년\s*(0?[1-9]|1[0-2])월")


def _month(value: Any) -> str | None:
    text = str(value or "")
    match = _MONTH_RE.search(text) or _KOREAN_MONTH_RE.search(text)
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}" if match else None


@lru_cache(maxsize=4)
def load_facts(root_str: str = str(FACTS_ROOT)) -> tuple[dict[str, Any], ...]:
    root = Path(root_str)
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return ()
    for path in sorted(root.rglob("*.facts.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            continue
        payload = dict(payload)
        payload["_facts_path"] = str(path)
        rows.append(payload)
    return tuple(rows)


def reload_facts() -> None:
    load_facts.cache_clear()


def _topic_groups(topic: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", topic or "")
    if "희소금속" in compact or "희소" in compact:
        return ("희소금속 월간동향",)
    if "전략광종" in compact:
        return ("전략광종 월간동향",)
    if "월간동향" in compact:
        return ("희소금속 월간동향", "전략광종 월간동향")
    return ()


def _topic_period(topic: str) -> tuple[str, str] | None:
    compact = re.sub(r"\s+", "", topic or "")
    match = re.search(r"(20\d{2})년(\d{1,2})월", compact)
    if match and 1 <= int(match.group(2)) <= 12:
        value = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
        return value, value
    if "이번달" in compact:
        value = date.today().strftime("%Y-%m")
        return value, value
    return None


def _render(payload: dict[str, Any]) -> str:
    minerals = payload.get("mineral_list") or []
    summary = str(payload.get("summary") or "").strip()
    title = str(payload.get("title") or payload.get("okf_path") or "월간동향")
    month = str(payload.get("document_month") or "게시월 미확인")
    lines = [
        "| 문서 | 게시월 | 광종 목록 | 문서 요약 |",
        "|---|---|---|---|",
        f"| {title} | {month} | {', '.join(map(str, minerals)) or '확인되지 않음'} | {summary or '요약 없음'} |",
    ]
    return "\n".join(lines)


def fetch_document_facts_evidence(
    topic: str = "", *, root: Path | str = FACTS_ROOT, limit: int = 1,
) -> tuple[list[Evidence], list[str]]:
    """월간동향 파생 사실을 기간·문서군으로 좁혀 최신 1건 반환."""

    rows = list(load_facts(str(root)))
    groups = _topic_groups(topic)
    if groups:
        rows = [row for row in rows if row.get("source_group") in groups]
    period = _topic_period(topic)
    if period:
        start, end = period
        rows = [row for row in rows if start <= str(row.get("document_month") or "") <= end]
    if not rows:
        return [], ["document_facts_not_found"]
    rows.sort(key=lambda row: (str(row.get("document_month") or ""), str(row.get("okf_path") or "")), reverse=True)
    selected = rows[: max(1, limit)]
    evidence = [Evidence(
        kind="pageindex", source=f"PageIndex 파생 사실 · {row.get('source_group') or '문서'}",
        section=str(row.get("title") or row.get("okf_path") or "문서 파생 사실"),
        text=_render(row), as_of=str(row.get("document_month") or "") or None,
    ) for row in selected]
    return evidence, []
