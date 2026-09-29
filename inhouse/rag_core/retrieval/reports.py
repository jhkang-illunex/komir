"""기간으로 KOMIS·조달청 동향 보고서를 찾아 제목과 본문 발췌를 반환한다."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import re

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence
from .monthly_trend import _MONTHLY_SOURCES, _publication_month
from .weekly_trend import _BOARD_URL, _SOURCE_LABELS as _WEEKLY_LABELS, _SOURCES as _WEEKLY_SOURCES, _publication_period


_SOURCES = (*_WEEKLY_SOURCES, *_MONTHLY_SOURCES)
_LABELS = {
    **_WEEKLY_LABELS,
    "전략광종 월간동향": "전략광종 월간동향",
    "희소금속 월간동향": "희소금속 월간동향",
}


def _document_period(source: str, title: str, source_path: str, pub_date: object):
    """DB 게시일 또는 제목·파일명에서 확인 가능한 발행 범위를 구한다."""
    if source in _MONTHLY_SOURCES:
        month = _publication_month(pub_date, source_path, title)
        if month is None:
            return None
        next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        return month, next_month - timedelta(days=1), month.isoformat()
    published = _publication_period(f"{source_path} {title}")
    if published:
        return published
    if isinstance(pub_date, (date, datetime)):
        day = date(pub_date.year, pub_date.month, pub_date.day)
        return day, day, day.isoformat()
    return None


def _sources_for_topic(topic: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", topic or "")
    if "조달청" in compact:
        return ("조달청보고서",)
    if "희소금속" in compact and "월간" in compact:
        return ("희소금속 월간동향",)
    if "전략광종" in compact and "월간" in compact:
        return ("전략광종 월간동향",)
    if "주간" in compact:
        return _WEEKLY_SOURCES
    if "월간" in compact:
        return _MONTHLY_SOURCES
    return _SOURCES


def fetch_report_evidence(
    topic: str, *, start: date, end: date, limit: int = 10, chunks_per_report: int = 4,
) -> tuple[list[Evidence], list[str]]:
    """기간 안의 날짜 확인된 보고서를 최신순으로 골라 본문 발췌와 함께 반환한다."""
    if end < start:
        return [], ["report_search_invalid_period"]
    settings = get_settings()
    schema = getattr(settings, "VECTOR_SCHEMA", settings.PG_SCHEMA).replace('"', "")
    connection = None
    try:
        connection = pg_connect()
        with connection.cursor() as cur:
            cur.execute(
                f"""SELECT doc_id, src, MAX(title), MAX(source_path), MAX(pub_date)
                    FROM {schema}.doc_chunk
                    WHERE src = ANY(%s)
                    GROUP BY doc_id, src""",
                (list(_sources_for_topic(topic)),),
            )
            documents = []
            for doc_id, source, title, source_path, pub_date in cur.fetchall():
                title, source_path = str(title or ""), str(source_path or "")
                published = _document_period(str(source or ""), title, source_path, pub_date)
                if published is None:
                    continue
                published_start, published_end, published_label = published
                if published_start <= end and start <= published_end:
                    documents.append((str(doc_id), str(source or ""), title, source_path,
                                      published_start, published_end, published_label))
            documents.sort(key=lambda item: (item[4], item[0]), reverse=True)
            documents = documents[:max(1, int(limit))]
            if not documents:
                return [], ["report_search_no_dated_document"]
            cur.execute(
                f"""SELECT doc_id, seq, txt FROM {schema}.doc_chunk
                    WHERE doc_id = ANY(%s) ORDER BY doc_id, seq""",
                ([item[0] for item in documents],),
            )
            chunk_rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"report_search_query_failed:{type(exc).__name__}"]
    finally:
        if connection is not None:
            connection.close()

    chunks: dict[str, list[str]] = {}
    selected_ids = {item[0] for item in documents}
    for doc_id, _seq, value in chunk_rows:
        key = str(doc_id)
        if key not in selected_ids:
            continue
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text:
            chunks.setdefault(key, []).append(text)

    rows = []
    observed = []
    for doc_id, source, title, source_path, pub_start, pub_end, published_label in documents:
        content_chunks = chunks.get(doc_id, [])[:max(1, int(chunks_per_report))]
        excerpt = " ".join(content_chunks).replace("|", "/")[:1400]
        if not excerpt:
            continue
        source_label = _LABELS.get(source, source or "보고서")
        origin = _BOARD_URL if source == "조달청보고서" else (
            source_path if source_path.startswith(("https://", "http://")) else "원문 링크 미확인"
        )
        rows.append(f"| {published_label} | {source_label} | {title or '제목 미확인'} | {origin} | {excerpt} |")
        observed.extend((pub_start, pub_end))
    if not rows:
        return [], ["report_search_no_content"]
    observed_period = f"{min(observed).isoformat()}~{max(observed).isoformat()}"
    text = "\n".join([
        "| 게시일 | 보고서 | 제목 | 원문 | 내용 발췌 |",
        "|---|---|---|---|---|",
        *rows,
    ])
    return [Evidence(
        kind="structured", source="KOMIS·조달청 보고서", section="기간별 보고서 검색",
        text=text, as_of=observed_period,
    )], []
