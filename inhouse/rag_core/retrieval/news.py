"""일일 자원뉴스 원천과 반정형 보고서 근거를 함께 반환한다."""
from __future__ import annotations

from html import unescape
import re

from common.config import get_settings
from common.db import pg_connect
from common.data_catalog import source_table
from .evidence import Evidence, KOMIS_RAW_DUMMY_CAVEAT


# ai_news의 광종 코드는 비어 있을 수 있으므로 제목·헤드라인의 명시 표기도 함께
# 읽는다. 이 목록은 검색어 확장과 출력 메타데이터에만 쓰며, 기사에 없는 광종을
# 추론하지 않는다.
_MINERAL_NAMES = (
    "네오디뮴", "디스프로슘", "텅스텐", "희토류", "리튬", "니켈", "코발트",
    "망간", "흑연", "구리", "아연", "주석", "납", "몰리브덴", "안티몬",
)
_COUNTRY_NAMES = (
    "대한민국", "한국", "중국", "미국", "일본", "호주", "캐나다", "칠레",
    "인도네시아", "콩고", "러시아", "브라질", "아르헨티나", "페루", "필리핀",
)
_COUNTRY_CODES = {
    "대한민국": "KR", "한국": "KR", "중국": "CN", "미국": "US", "일본": "JP",
    "호주": "AU", "캐나다": "CA", "칠레": "CL", "인도네시아": "ID", "콩고": "CD",
    "러시아": "RU", "브라질": "BR", "아르헨티나": "AR", "페루": "PE", "필리핀": "PH",
}
_COUNTRY_LABELS = {code: name for name, code in _COUNTRY_CODES.items() if name != "한국"}


def mentioned_minerals(text: str) -> list[str]:
    """기사 원문에 실제로 등장한 광종만 안정된 순서로 반환한다."""
    compact = str(text or "")
    return [name for name in _MINERAL_NAMES if name in compact]


def mentioned_countries(text: str) -> list[str]:
    """기사 원문에 실제로 등장한 국가명만 반환한다."""
    compact = str(text or "")
    return [name for name in _COUNTRY_NAMES if name in compact]


def _query_terms(topic: str) -> list[str]:
    """자유 질문 전체를 ILIKE 하지 않고, 검증 가능한 핵심 검색어만 고른다."""
    text = str(topic or "")
    terms = mentioned_minerals(text)
    if "수출통제" in text or "수출 규제" in text or "수출제한" in text:
        terms.append("수출통제")
    # 일상적인 "최근 뉴스"는 최신 목록이라는 명확한 의미여서 검색어를 강제하지
    # 않는다. 그 외 미인식 자유문은 기존처럼 그대로 한 번만 검색한다.
    if not terms and text.strip() and not any(token in text for token in ("최근", "이번주", "오늘", "뉴스", "기사")):
        terms.append(text.strip())
    return list(dict.fromkeys(terms))


def _plain_text(value: object) -> str:
    """일일뉴스 본문의 HTML을 검색·표시 가능한 짧은 평문으로 정리한다."""
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _country_codes_for_topic(topic: str) -> list[str]:
    return list(dict.fromkeys(
        code for name, code in _COUNTRY_CODES.items() if name in str(topic or "")
    ))


def fetch_news_evidence(topic: str = "", *, start: str | None = None, end: str | None = None,
                        limit: int = 5) -> tuple[list[Evidence], list[str]]:
    """ai_daynews_raw와 doc_chunk의 검증 가능한 관련 발췌를 함께 조회한다."""
    # 일일 뉴스 원천의 schema/table은 공용 정형 원천 카탈로그에서 읽는다. 이 프로젝트가
    # 적재한 반정형 문서 청크는 VECTOR_SCHEMA(현재 mineral_risk)에 있다. 둘을 같은
    # 스키마로 조회하면 한쪽은 반드시 UndefinedTable이 된다. 조회 전용 adapter
    # 에서 실제 소유 스키마를 명시하되, public에 DDL/DML을 수행하지 않는다.
    news_table = source_table("daily_news")
    settings = get_settings()
    document_schema = getattr(settings, "VECTOR_SCHEMA", settings.PG_SCHEMA).replace('"', '')
    con = None
    try:
        con = pg_connect()
        with con.cursor() as cur:
            terms = _query_terms(topic)
            date_sql = ""
            date_params: list[str] = []
            if start and end:
                # regDate는 YYYYMMDDHHMMSS 문자열이다. 기사 발행일(앞 8자리)만
                # 닫힌 범위로 비교해 시각에 따른 누락을 막는다.
                date_sql = " AND LEFT(COALESCE(n.\"regDate\", ''), 8) BETWEEN %s AND %s"
                date_params = [start.replace("-", ""), end.replace("-", "")]
            country_codes = _country_codes_for_topic(topic)
            country_sql = ""
            country_params: list[object] = []
            if country_codes:
                # countryCodes는 수집 단계가 채운 ISO 3166-1 alpha-2 배열이다.
                # 2026-09-28 실측 적재본은 전부 NULL이므로, NULL 행만 제목·본문
                # 명시 언급으로 보완한다. 코드가 채워진 행은 반드시 코드로 필터한다.
                country_terms = [f"%{name}%" for name in mentioned_countries(topic)]
                country_sql = (
                    " AND ((n.\"countryCodes\" && %s::varchar[]) OR "
                    "(n.\"countryCodes\" IS NULL AND "
                    "(COALESCE(n.ttl, '') ILIKE ANY(%s) OR COALESCE(n.cnts, '') ILIKE ANY(%s))))"
                )
                country_params = [country_codes, country_terms, country_terms]
            select_sql = (
                "SELECT LEFT(COALESCE(n.\"regDate\", ''), 8), n.\"typeCdNm\", n.ttl, n.cnts, "
                f"n.\"countryCodes\", n.seq FROM {news_table} n "
                "WHERE n.\"pubStatusNm\" = '발행'"
            )
            if terms:
                patterns = [f"%{term.replace('%', '')}%" for term in terms]
                cur.execute(
                    select_sql +
                    " AND (COALESCE(n.ttl, '') ILIKE ANY(%s) OR COALESCE(n.cnts, '') ILIKE ANY(%s))" +
                    date_sql + country_sql + " ORDER BY n.\"regDate\" DESC, n.seq DESC LIMIT %s",
                    (patterns, patterns, *date_params, *country_params, int(limit)),
                )
            else:
                cur.execute(
                    select_sql + date_sql + country_sql + " ORDER BY n.\"regDate\" DESC, n.seq DESC LIMIT %s",
                    (*date_params, *country_params, int(limit)))
            news = cur.fetchall()
            patterns = [f"%{term.replace('%', '')}%" for term in terms] or ["%자원뉴스%"]
            report_date_sql = ""
            report_date_params: list[str] = []
            if start and end:
                # 보조 반정형 문서도 일일뉴스와 같은 질문 기간 안에서만 쓴다.
                # 게시일이 없는 문서를 최근 기사인 것처럼 섞지 않는다.
                report_date_sql = " AND pub_date::date BETWEEN %s::date AND %s::date"
                report_date_params = [start, end]
            cur.execute(
                f"SELECT title, source_path, pub_date, txt FROM {document_schema}.doc_chunk WHERE txt ILIKE ANY(%s) "
                + report_date_sql + " ORDER BY pub_date DESC NULLS LAST, doc_id DESC, seq ASC LIMIT %s",
                (patterns, *report_date_params, int(limit)))
            reports = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"news_query_failed:{type(exc).__name__}"]
    finally:
        if con is not None:
            con.close()
    if not news and not reports:
        return [], ["news_not_found"]
    lines = ["| 날짜 | 광종 | 제목 | 요약 | 원문 |", "|---|---|---|---|---|"]
    dummy = False
    for day, mineral, title, body, country_codes, _seq in news:
        title, headline = _plain_text(title), _plain_text(body)
        dummy = dummy or '[DEV_DUMMY]' in title or '[DEV_DUMMY]' in headline
        text = f"{title} {headline}"
        article_minerals = mentioned_minerals(text)
        article_countries = mentioned_countries(text)
        label = str(mineral or '').strip() or ', '.join(article_minerals)
        metadata = []
        if article_minerals and str(mineral or '').strip():
            metadata.append(f"언급 광종: {', '.join(article_minerals)}")
        if article_countries:
            metadata.append(f"언급 국가: {', '.join(article_countries)}")
        structured_countries = [
            _COUNTRY_LABELS.get(str(code).upper(), str(code).upper())
            for code in (country_codes or [])
        ]
        if structured_countries:
            metadata.append(f"국가 코드: {', '.join(structured_countries)}")
        summary = headline[:600] + (f" ({'; '.join(metadata)})" if metadata else "")
        day_text = str(day or "")
        if len(day_text) == 8 and day_text.isdigit():
            day_text = f"{day_text[:4]}-{day_text[4:6]}-{day_text[6:]}"
        lines.append(f"| {day_text} | {label} | {title} | {summary} | 원문 링크 미확인 |")
    for title, source_path, published, text in reports:
        excerpt = ' '.join(str(text or '').split())[:300]
        if excerpt:
            original = str(source_path or '').strip()
            original = original if original.startswith(("https://", "http://")) else (original or "원문 경로 미확인")
            lines.append(f"| {published or '게시일 미확인'} |  | {str(title or '')} | {excerpt} | {original} |")
    # 기사 SQL에는 이미 질문 기간과 ``발행`` 상태가 적용됐다. 그 실제 기사
    # 기간을 Evidence 계약에 남겨야, 뒤의 공통 문서 기간 필터가 뉴스 근거를
    # 날짜 미상으로 잘못 제거하지 않는다.
    article_days = sorted({str(day or "") for day, *_rest in news if re.fullmatch(r"\d{8}", str(day or ""))})
    observed_period = None
    if article_days:
        normalized_days = [f"{day[:4]}-{day[4:6]}-{day[6:]}" for day in article_days]
        observed_period = (normalized_days[0] if len(normalized_days) == 1
                           else f"{normalized_days[0]}~{normalized_days[-1]}")
    sources = " + ".join(part for part, present in (
        (news_table, bool(news)), ("반정형 보고서", bool(reports)),
    ) if present)
    return [Evidence(kind="structured", source=sources, section="일일 자원뉴스",
                     text='\n'.join(lines), as_of=observed_period,
                     caveat=KOMIS_RAW_DUMMY_CAVEAT if dummy else None)], []
