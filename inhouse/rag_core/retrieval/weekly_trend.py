# -*- coding: utf-8 -*-
"""KOMIS·조달청 주간 광물동향의 게시물 목록 adapter.

문서 청크를 의미검색 결과 순위로 섞지 않고, 원문 파일명·제목에서 확인한
YYYYMMDD 또는 YYYY-MM 발행 정보를 사용한다. `pub_date`가 비어 있는 현재
조달청 코퍼스에서 "최근"을 추정하지 않기 위한 좁은 읽기 전용 adapter다.
"""
from __future__ import annotations

import re
import calendar
from datetime import date

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence

_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-._/]?(\d{2})[-._/]?(\d{2})(?!\d)")
_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})[-._/](0?[1-9]|1[0-2])(?![-._/]?\d)")
_COMPACT_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)")
_KOREAN_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})년\s*(0?[1-9]|1[0-2])월")
_SOURCES = ("주간광물동향", "조달청보고서")
_SOURCE_LABELS = {
    "주간광물동향": "KOMIS 주간광물동향",
    "조달청보고서": "조달청 주간시장동향",
}
_BOARD_URL = "https://www.pps.go.kr/bichuk/bbs/list.do?key=00826"
_MINERAL_ALIASES = (
    ("희토류", ("희토류", "rare earth")),
    ("네오디뮴", ("네오디뮴", "neodymium")),
    ("코발트", ("코발트", "cobalt")),
    ("리튬", ("리튬", "lithium")),
    ("니켈", ("니켈", "nickel")),
    ("구리", ("구리", "동", "copper")),
    ("망간", ("망간", "manganese")),
    ("흑연", ("흑연", "graphite")),
    ("텅스텐", ("텅스텐", "tungsten")),
    ("몰리브덴", ("몰리브덴", "molybdenum")),
    ("안티모니", ("안티모니", "antimony")),
    ("인듐", ("인듐", "indium")),
    ("갈륨", ("갈륨", "gallium")),
    ("티타늄", ("티타늄", "titanium")),
)


def _mentioned_minerals(text: str) -> list[str]:
    """Return only canonical minerals explicitly present in the source text."""
    folded = re.sub(r"\s+", " ", str(text or "")).casefold()
    return [canonical for canonical, aliases in _MINERAL_ALIASES if any(alias in folded for alias in aliases)]


def _publication_date(source_path: str) -> date | None:
    match = _DATE_RE.search(source_path)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _publication_period(source_path: str) -> tuple[date, date, str] | None:
    """파일명·제목에서 발행일 또는 발행월을 읽고 비교 구간과 표기값을 돌려준다."""
    exact = _publication_date(source_path)
    if exact:
        return exact, exact, exact.isoformat()
    match = (_MONTH_RE.search(source_path) or _COMPACT_MONTH_RE.search(source_path)
             or _KOREAN_MONTH_RE.search(source_path))
    if not match:
        return None
    try:
        year, month = int(match.group(1)), int(match.group(2))
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return start, end, f"{year:04d}-{month:02d}"
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
        publication = _publication_period(f"{source_path or ''} {title or ''}")
        if publication is None:
            continue
        published_start, published_end, published_label = publication
        # 월까지만 확인되는 문서는 그 달 전체로 비교한다. 해당 월과 검색 기간이
        # 겹치면 포함하고, 앞선 월의 보고서는 주간 결과에서 제외한다.
        if start and published_end < start:
            continue
        if end and published_start > end:
            continue
        group = str(source_group or "")
        original = _BOARD_URL if group == "조달청보고서" else str(source_path or "원문 경로 미확인")
        documents.append((str(_doc_id), published_start, published_label,
                          _SOURCE_LABELS.get(group, group or "주간동향"), str(title or ""), original, str(text or "")))
    documents.sort(reverse=True)
    selected = documents[:limit]
    if not selected:
        return [], ["weekly_trend_no_dated_document"]
    # 표지/면책 문구인 첫 청크는 시장 이슈를 담지 않는 경우가 많다. 선택된 문서
    # 안에서만 후속 청크를 읽어 ``가격 동향``·``시장 뉴스``가 실제로 있는 발췌를
    # 사용한다. 문서 경계를 넘거나 생성으로 요약하지 않는다.
    summaries: dict[str, str] = {}
    minerals: dict[str, list[str]] = {}
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
                minerals[doc_id] = _mentioned_minerals(" ".join(chunks.get(doc_id, [])))
    finally:
        con.close()
    table = [
        "| 게시일 | 출처 | 보고서 제목 | 원문 | 광종목록 | 요약 |",
        "| --- | --- | --- | --- | --- | --- |",
        *[f"| {published_label} | {source} | {title} | {original} | {', '.join(minerals.get(doc_id, []))} | {summaries.get(doc_id, '')} |"
          for doc_id, _sort_date, published_label, source, title, original, _first_text in selected],
    ]
    return [Evidence(
        kind="structured", source="KOMIS·조달청 주간 광물동향", section="주간 광물동향 게시물",
        text="\n".join(table), as_of=selected[0][2],
    )], []
