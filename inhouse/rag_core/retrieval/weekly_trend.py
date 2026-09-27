# -*- coding: utf-8 -*-
"""조달청 주간 비철금속 동향의 게시물 목록 adapter.

문서 청크를 의미검색 결과 순위로 섞지 않고, `doc_chunk`의 원문 파일명에 있는
YYYYMMDD만 발행일로 인정한다. `pub_date`가 비어 있는 현재 조달청 코퍼스에서
"최근"을 추정하지 않기 위한 좁은 읽기 전용 adapter다.
"""
from __future__ import annotations

import re
from datetime import date

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence

_DATE_RE = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_SOURCE = "조달청 주간시장동향"
_BOARD_URL = "https://www.pps.go.kr/bichuk/bbs/list.do?key=00826"


def _publication_date(source_path: str) -> date | None:
    match = _DATE_RE.search(source_path)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def fetch_weekly_trend_evidence(
    *, start: date | None = None, end: date | None = None, limit: int = 5,
) -> tuple[list[Evidence], list[str]]:
    """기간 내 날짜가 확인된 조달청 주간동향 문서만 최신순으로 반환한다."""
    settings = get_settings()
    schema = getattr(settings, "VECTOR_SCHEMA", settings.PG_SCHEMA)
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (doc_id) doc_id, title, source_path
                FROM {schema}.doc_chunk
                WHERE src = %s
                ORDER BY doc_id, seq ASC
                """,
                ("조달청보고서",),
            )
            rows = cur.fetchall()
    finally:
        con.close()
    documents = []
    for _doc_id, title, source_path in rows:
        published = _publication_date(str(source_path or ""))
        if published is None:
            continue
        if start and published < start:
            continue
        if end and published > end:
            continue
        documents.append((published, str(title or "")))
    documents.sort(reverse=True)
    selected = documents[:limit]
    if not selected:
        return [], ["weekly_trend_no_dated_document"]
    table = [
        "| 게시일 | 보고서 제목 | 원문 |",
        "| --- | --- | --- |",
        *[f"| {published.isoformat()} | {title} | {_BOARD_URL} |" for published, title in selected],
    ]
    return [Evidence(
        kind="structured", source=_SOURCE, section="조달청 주간 비철금속 시장 동향 게시물",
        text="\n".join(table), as_of=selected[0][0].isoformat(),
    )], []
