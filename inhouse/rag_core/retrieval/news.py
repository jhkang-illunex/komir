"""자원뉴스의 RDB 목록과 반정형 보고서 근거를 함께 반환한다."""
from __future__ import annotations

from common.config import get_settings
from common.db import pg_connect
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


def fetch_news_evidence(topic: str = "", *, start: str | None = None, end: str | None = None,
                        limit: int = 5) -> tuple[list[Evidence], list[str]]:
    """ai_news 제목·헤드라인과 doc_chunk의 검증 가능한 관련 발췌를 함께 조회한다."""
    # KOMIS 원천 테이블(ai_news·ai_mnrl_mst)은 public 소유이고, 이 프로젝트가
    # 적재한 반정형 문서 청크는 VECTOR_SCHEMA(현재 mineral_risk)에 있다. 둘을 같은
    # 스키마로 조회하면 한쪽은 반드시 UndefinedTable이 된다. 조회 전용 adapter
    # 에서 실제 소유 스키마를 명시하되, public에 DDL/DML을 수행하지 않는다.
    komis_schema = "public"
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
                # base_ymd는 YYYYMMDD 문자열/숫자 어느 쪽이어도 비교할 수 있게
                # 문자화한 뒤 닫힌 범위로 제한한다.
                date_sql = " AND CAST(n.base_ymd AS TEXT) BETWEEN %s AND %s"
                date_params = [start.replace("-", ""), end.replace("-", "")]
            if terms:
                patterns = [f"%{term.replace('%', '')}%" for term in terms]
                cur.execute(
                    f"SELECT n.base_ymd, m.mnrl_nm_ko, n.title, n.headline, n.sort_ordr "
                    f"FROM {komis_schema}.ai_news n LEFT JOIN {komis_schema}.ai_mnrl_mst m "
                    "ON m.mnrknd_unq_cd=n.mnrknd_unq_cd "
                    "WHERE (COALESCE(n.title, '') ILIKE ANY(%s) "
                    "OR COALESCE(n.headline, '') ILIKE ANY(%s))" + date_sql +
                    " ORDER BY n.base_ymd DESC, n.sort_ordr ASC LIMIT %s",
                    (patterns, patterns, *date_params, int(limit)),
                )
            else:
                cur.execute(
                    f"SELECT n.base_ymd, m.mnrl_nm_ko, n.title, n.headline, n.sort_ordr "
                    f"FROM {komis_schema}.ai_news n LEFT JOIN {komis_schema}.ai_mnrl_mst m "
                    "ON m.mnrknd_unq_cd=n.mnrknd_unq_cd "
                    "WHERE 1=1" + date_sql + " ORDER BY n.base_ymd DESC, n.sort_ordr ASC LIMIT %s",
                    (*date_params, int(limit)))
            news = cur.fetchall()
            patterns = [f"%{term.replace('%', '')}%" for term in terms] or ["%자원뉴스%"]
            cur.execute(
                f"SELECT title, source_path, pub_date, txt FROM {document_schema}.doc_chunk WHERE txt ILIKE ANY(%s) "
                "ORDER BY pub_date DESC NULLS LAST, doc_id DESC, seq ASC LIMIT %s", (patterns, int(limit)))
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
    for day, mineral, title, headline, _order in news:
        title, headline = str(title or ''), str(headline or '')
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
        summary = headline + (f" ({'; '.join(metadata)})" if metadata else "")
        lines.append(f"| {day or ''} | {label} | {title} | {summary} | 원문 링크 미확인 |")
    for title, source_path, published, text in reports:
        excerpt = ' '.join(str(text or '').split())[:300]
        if excerpt:
            original = str(source_path or '').strip()
            original = original if original.startswith(("https://", "http://")) else (original or "원문 경로 미확인")
            lines.append(f"| {published or '게시일 미확인'} |  | {str(title or '')} | {excerpt} | {original} |")
    return [Evidence(kind="structured", source="public.ai_news + 반정형 보고서", section="자원뉴스",
                     text='\n'.join(lines), caveat=KOMIS_RAW_DUMMY_CAVEAT if dummy else None)], []
