# -*- coding: utf-8 -*-
"""KOMIS·조달청 주간 광물동향의 게시물 목록 adapter.

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

_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-._/]?(\d{2})[-._/]?(\d{2})(?!\d)")
_SOURCES = ("주간광물동향", "조달청보고서")
_SOURCE_LABELS = {
    "주간광물동향": "KOMIS 주간광물동향",
    "조달청보고서": "조달청 주간시장동향",
}
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
    """기간 내 날짜가 확인된 KOMIS·조달청 주간동향 문서를 최신순으로 반환한다."""
    settings = get_settings()
    schema = getattr(settings, "VECTOR_SCHEMA", settings.PG_SCHEMA)
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (doc_id) doc_id, src, title, source_path, txt
                FROM {schema}.doc_chunk
                WHERE src = ANY(%s)
                ORDER BY doc_id, seq ASC
                """,
                (list(_SOURCES),),
            )
            rows = cur.fetchall()
    finally:
        con.close()
    documents = []
    for _doc_id, source_group, title, source_path, text in rows:
        published = _publication_date(str(source_path or ""))
        if published is None:
            continue
        if start and published < start:
            continue
        if end and published > end:
            continue
        group = str(source_group or "")
        original = _BOARD_URL if group == "조달청보고서" else str(source_path or "원문 경로 미확인")
        documents.append((str(_doc_id), published, _SOURCE_LABELS.get(group, group or "주간동향"), str(title or ""), original, str(text or "")))
    documents.sort(reverse=True)
    selected = documents[:limit]
    if not selected:
        return [], ["weekly_trend_no_dated_document"]
    # 표지/면책 문구인 첫 청크는 시장 이슈를 담지 않는 경우가 많다. 선택된 문서
    # 안에서만 후속 청크를 읽어 ``가격 동향``·``시장 뉴스``가 실제로 있는 발췌를
    # 사용한다. 문서 경계를 넘거나 생성으로 요약하지 않는다.
    summaries: dict[str, str] = {}
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, seq, txt FROM {schema}.doc_chunk WHERE doc_id = ANY(%s) ORDER BY doc_id, seq",
                ([doc_id for doc_id, *_rest in selected],),
            )
            chunks: dict[str, list[str]] = {}
            for doc_id, _seq, text in cur.fetchall():
                cleaned = re.sub(r"\s+", " ", str(text or "")).replace("|", "/").strip()
                if cleaned:
                    chunks.setdefault(str(doc_id), []).append(cleaned)
            for doc_id, *_rest, first_text in selected:
                preferred = [chunk for chunk in chunks.get(doc_id, [])
                             if any(marker in chunk for marker in ("가격 동향", "시장 뉴스", "주간 동향", "재고 동향"))]
                summaries[doc_id] = " ".join((preferred or [first_text])[:2])[:1200]
    finally:
        con.close()
    table = [
        "| 게시일 | 출처 | 보고서 제목 | 원문 | 요약 |",
        "| --- | --- | --- | --- | --- |",
        *[f"| {published.isoformat()} | {source} | {title} | {original} | {summaries.get(doc_id, '')} |"
          for doc_id, published, source, title, original, _first_text in selected],
    ]
    return [Evidence(
        kind="structured", source="KOMIS·조달청 주간 광물동향", section="주간 광물동향 게시물",
        text="\n".join(table), as_of=selected[0][1].isoformat(),
    )], []
