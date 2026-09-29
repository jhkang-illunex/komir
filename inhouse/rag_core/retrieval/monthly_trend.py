"""월간동향 게시물 구조화 adapter."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence


_MINERALS = ("리튬", "니켈", "코발트", "구리", "동", "아연", "망간", "텅스텐", "몰리브덴", "희토류", "흑연", "알루미늄", "철광석")
_MONTHLY_SOURCES = ("전략광종 월간동향", "희소금속 월간동향")
_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})[-._/](0[1-9]|1[0-2])(?!\d)")
_COMPACT_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)")
_KOREAN_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})년\s*(0?[1-9]|1[0-2])월")
_DAY_RE = re.compile(r"(?<!\d)(20\d{2})[-._/]?(0[1-9]|1[0-2])[-._/]?(0[1-9]|[12]\d|3[01])(?!\d)")
_MINERAL_NOT_MENTIONED_WARNING = "monthly_trend_mineral_not_mentioned:"


@dataclass(frozen=True)
class _MonthlyDocument:
    doc_id: str
    source_group: str
    title: str
    source_path: str
    publication_month: date | None


def _month_start(value: date, offset: int = 0) -> date:
    """월 단위 offset을 적용한 월초. ``dateutil`` 의존성을 추가하지 않는다."""

    month = value.month - 1 + offset
    return date(value.year + month // 12, month % 12 + 1, 1)


def _publication_month(pub_date: object, source_path: str, title: str) -> date | None:
    """DB 게시일 우선, 없으면 파일명/제목의 YYYY-MM을 월호 발행월로 사용한다."""

    if isinstance(pub_date, date):
        return date(pub_date.year, pub_date.month, 1)
    for value in (source_path, title):
        day_match = _DAY_RE.search(value or "")
        if day_match:
            try:
                return date(int(day_match.group(1)), int(day_match.group(2)), 1)
            except ValueError:
                pass
        match = (_MONTH_RE.search(value or "") or _COMPACT_MONTH_RE.search(value or "")
                 or _KOREAN_MONTH_RE.search(value or ""))
        if match:
            return date(int(match.group(1)), int(match.group(2)), 1)
    return None


def _source_groups_for_topic(topic: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", topic)
    if "희소금속" in compact:
        return ("희소금속 월간동향",)
    if "전략광종" in compact:
        return ("전략광종 월간동향",)
    return _MONTHLY_SOURCES


def _period_bounds_for_topic(topic: str, *, today: date | None = None) -> tuple[date, date] | None:
    """질문의 명시 기간만 문서 월호에 적용한다. ``최근`` 단독은 최신 보유월을 뜻한다."""

    today = today or date.today()
    compact = re.sub(r"\s+", "", topic)
    year_month = re.search(r"(20\d{2})년(\d{1,2})월", compact)
    if year_month:
        year, month = int(year_month.group(1)), int(year_month.group(2))
        if 1 <= month <= 12:
            start = date(year, month, 1)
            return start, _month_start(start, 1) - timedelta(days=1)
    if "이번달" in compact:
        return _month_start(today), today
    recent = re.search(r"최근(\d+)(개월|년)", compact)
    if recent:
        months = int(recent.group(1)) * (12 if recent.group(2) == "년" else 1)
        return _month_start(today, -(months - 1)), today
    year = re.search(r"(20\d{2})년", compact)
    if year:
        return date(int(year.group(1)), 1, 1), date(int(year.group(1)), 12, 31)
    return None


def _mentioned_minerals(topic: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", topic)
    # "월간동향"의 마지막 글자 동을 구리(동)로 오인하면, 니켈만 지정한
    # 질문도 두 광종 질문처럼 변한다. 광종 약칭 동은 동향이라는 보고서 유형
    # 표지에서만 제외하고 실제 "동 가격" 등은 그대로 인식한다.
    return tuple(
        mineral for mineral in _MINERALS
        if mineral in (compact.replace("동향", "") if mineral == "동" else compact)
    )


def _select_document(
    documents: list[_MonthlyDocument], topic: str, *, matching_mineral_doc_ids: set[str] | None = None,
    today: date | None = None,
) -> _MonthlyDocument | None:
    """문서군·명시 기간·광종 본문 일치 순으로 좁힌 뒤 가장 최신 월호 하나를 고른다."""

    period = _period_bounds_for_topic(topic, today=today)
    filtered = documents
    if period:
        start, end = period
        filtered = [doc for doc in filtered if doc.publication_month and start <= doc.publication_month <= end]
    if matching_mineral_doc_ids:
        mineral_filtered = [doc for doc in filtered if doc.doc_id in matching_mineral_doc_ids]
        if mineral_filtered:
            filtered = mineral_filtered
    if not filtered:
        return None
    return max(filtered, key=lambda doc: (doc.publication_month or date.min, doc.doc_id))


def fetch_monthly_trend_evidence(topic: str = "", *, limit_chunks: int = 12) -> tuple[list[Evidence], list[str]]:
    """질문에 맞는 월간동향 한 월호를 선택해, 그 문서의 청크만 근거로 반환한다."""

    settings = get_settings()
    schema = getattr(settings, "VECTOR_SCHEMA", settings.PG_SCHEMA).replace('"', "")
    source_groups = _source_groups_for_topic(topic)
    minerals = _mentioned_minerals(topic)
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"""
                SELECT doc_id, src, MAX(title), MAX(source_path), MAX(pub_date)
                FROM {schema}.doc_chunk
                WHERE src = ANY(%s)
                GROUP BY doc_id, src
                """,
                (list(source_groups),),
            )
            documents = [
                _MonthlyDocument(
                    doc_id=str(doc_id), source_group=str(source_group or ""), title=str(title or ""),
                    source_path=str(source_path or ""),
                    publication_month=_publication_month(pub_date, str(source_path or ""), str(title or "")),
                )
                for doc_id, source_group, title, source_path, pub_date in cur.fetchall()
            ]
            matching_mineral_doc_ids: set[str] | None = None
            if minerals and documents:
                cur.execute(
                    f"""
                    SELECT DISTINCT doc_id FROM {schema}.doc_chunk
                    WHERE doc_id = ANY(%s) AND txt ILIKE ANY(%s)
                    """,
                    ([doc.doc_id for doc in documents], [f"%{mineral}%" for mineral in minerals]),
                )
                matching_mineral_doc_ids = {str(row[0]) for row in cur.fetchall()}
            selected = _select_document(documents, topic, matching_mineral_doc_ids=matching_mineral_doc_ids)
            if selected is None:
                return [], ["monthly_trend_not_found"]
            cur.execute(
                f"""
                SELECT title, source_path, pub_date, txt
                FROM {schema}.doc_chunk
                WHERE doc_id = %s
                ORDER BY seq ASC
                LIMIT %s
                """,
                (selected.doc_id, int(limit_chunks)),
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"monthly_trend_query_failed:{type(exc).__name__}"]
    finally:
        con.close()
    if not rows:
        return [], ["monthly_trend_not_found"]
    title = str(rows[0][0] or selected.title).strip() or "월간동향"
    source_path = str(rows[0][1] or selected.source_path).strip()
    published = selected.publication_month.isoformat() if selected.publication_month else ""
    body = "\n".join(str(row[3] or "") for row in rows if row[3])
    minerals_in_body = []
    for mineral in _MINERALS:
        if mineral in body and mineral not in minerals_in_body:
            minerals_in_body.append(mineral)
    summary = re.sub(r"\s+", " ", body).strip()[:1200]
    original = source_path if source_path.startswith(("https://", "http://")) else (source_path or "원문 경로 미확인")
    text = (f"| 월호 | 게시월 | 원문 | 광종목록 | 요약 |\n|---|---|---|---|---|\n"
            f"| {title} | {published or '게시월 미확인'} | {original} | {', '.join(minerals_in_body)} | {summary} |")
    warnings = []
    # 선택된 월호는 정상적으로 존재하지만, 질문에서 지정한 광종이 이 문서군의
    # 본문에 한 번도 나타나지 않은 경우다. 이를 "문서를 찾지 못함"과 구별해
    # 상위 응답이 정확한 부재 안내를 만들 수 있게 한다.
    # 같은 문서군의 다른 월호에 광종명이 있어도, 실제 선택된 월호 본문에
    # 없으면 사용자에게는 "이 문서에 언급 없음"이 맞다.
    # ``body``는 답변 요약용 앞쪽 청크에 한정될 수 있다. 언급 여부만큼은
    # 선택된 문서 전체 청크를 대상으로 조회한 결과를 사용해야, 뒤쪽에 있는
    # 광종을 잘못 "언급 없음"으로 안내하지 않는다.
    if minerals and selected.doc_id not in (matching_mineral_doc_ids or set()):
        warnings.append(_MINERAL_NOT_MENTIONED_WARNING + ",".join(minerals))
    return [Evidence(kind="structured", source=selected.source_group, section=title, text=text,
                     as_of=published or None)], warnings
