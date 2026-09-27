"""자원뉴스의 RDB 목록과 반정형 보고서 근거를 함께 반환한다."""
from __future__ import annotations

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence, KOMIS_RAW_DUMMY_CAVEAT


def fetch_news_evidence(topic: str = "", *, limit: int = 5) -> tuple[list[Evidence], list[str]]:
    """ai_news 제목·헤드라인과 doc_chunk의 검증 가능한 관련 발췌를 함께 조회한다."""
    schema = get_settings().PG_SCHEMA.replace('"', '')
    con = None
    try:
        con = pg_connect()
        with con.cursor() as cur:
            cur.execute(
                f"SELECT n.base_ymd, m.mnrl_nm_ko, n.title, n.headline, n.sort_ordr "
                f"FROM {schema}.ai_news n LEFT JOIN {schema}.ai_mnrl_mst m "
                "ON m.mnrknd_unq_cd=n.mnrknd_unq_cd "
                "ORDER BY n.base_ymd DESC, n.sort_ordr ASC LIMIT %s", (int(limit),))
            news = cur.fetchall()
            pattern = '%' + topic.replace('%', '') + '%'
            cur.execute(
                f"SELECT title, txt FROM {schema}.doc_chunk WHERE txt ILIKE %s "
                "ORDER BY pub_date DESC NULLS LAST, doc_id DESC, seq ASC LIMIT %s", (pattern, int(limit)))
            reports = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"news_query_failed:{type(exc).__name__}"]
    finally:
        if con is not None:
            con.close()
    if not news and not reports:
        return [], ["news_not_found"]
    lines = ["| 날짜 | 광종 | 제목 | 요약 |", "|---|---|---|---|"]
    dummy = False
    for day, mineral, title, headline, _order in news:
        title, headline = str(title or ''), str(headline or '')
        dummy = dummy or '[DEV_DUMMY]' in title or '[DEV_DUMMY]' in headline
        lines.append(f"| {day or ''} | {mineral or ''} | {title} | {headline} |")
    for title, text in reports:
        excerpt = ' '.join(str(text or '').split())[:300]
        if excerpt:
            lines.append(f"| 반정형 보고서 |  | {str(title or '')} | {excerpt} |")
    return [Evidence(kind="structured", source="public.ai_news + 반정형 보고서", section="자원뉴스",
                     text='\n'.join(lines), caveat=KOMIS_RAW_DUMMY_CAVEAT if dummy else None)], []
