"""허용된 public.ai_news 원천에서 자원뉴스를 반환한다."""
from __future__ import annotations

from common.db import pg_connect
from .evidence import Evidence, KOMIS_RAW_DUMMY_CAVEAT


_MINERAL_NAMES = ("리튬", "니켈", "코발트", "구리", "동", "망간", "흑연", "텅스텐", "희토류", "네오디뮴")


def _query_term(topic: str) -> str:
    """전체 질문이 아닌 확인 가능한 광종명만 뉴스 검색어로 사용한다."""
    compact = "".join((topic or "").split())
    mineral = next((name for name in _MINERAL_NAMES if name in compact), None)
    return "구리" if mineral == "동" else (mineral or "")


def fetch_news_evidence(topic: str = "", *, limit: int = 5) -> tuple[list[Evidence], list[str]]:
    """ai_news 제목·헤드라인만 조회한다.

    mineral_risk.doc_chunk의 반정형 보고서는 사용자 제약상 이 adapter에서
    사용하지 않는다. 허용 원천에 같은 보고서가 제공되기 전에는 기사 목록만
    반환하며, 보고서 요약을 추정하지 않는다.
    """
    source_schema = "public"
    con = None
    try:
        con = pg_connect()
        with con.cursor() as cur:
            term = _query_term(topic)
            if term:
                like = f"%{term.replace('%', '')}%"
                cur.execute(
                    f"SELECT n.base_ymd, m.mnrl_nm_ko, n.title, n.headline, n.sort_ordr "
                    f"FROM {source_schema}.ai_news n LEFT JOIN {source_schema}.ai_mnrl_mst m "
                    "ON m.mnrknd_unq_cd=n.mnrknd_unq_cd "
                    "WHERE m.mnrl_nm_ko=%s OR n.title ILIKE %s OR n.headline ILIKE %s "
                    "ORDER BY n.base_ymd DESC, n.sort_ordr ASC LIMIT %s", (term, like, like, int(limit)))
            else:
                cur.execute(
                    f"SELECT n.base_ymd, m.mnrl_nm_ko, n.title, n.headline, n.sort_ordr "
                    f"FROM {source_schema}.ai_news n LEFT JOIN {source_schema}.ai_mnrl_mst m "
                    "ON m.mnrknd_unq_cd=n.mnrknd_unq_cd "
                    "ORDER BY n.base_ymd DESC, n.sort_ordr ASC LIMIT %s", (int(limit),))
            news = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"news_query_failed:{type(exc).__name__}"]
    finally:
        if con is not None:
            con.close()
    if not news:
        return [], ["news_not_found"]
    lines = ["| 날짜 | 광종 | 제목 | 요약 |", "|---|---|---|---|"]
    dummy = False
    for day, mineral, title, headline, _order in news:
        title, headline = str(title or ''), str(headline or '')
        dummy = dummy or '[DEV_DUMMY]' in title or '[DEV_DUMMY]' in headline
        lines.append(f"| {day or ''} | {mineral or ''} | {title} | {headline} |")
    return [Evidence(kind="structured", source="public.ai_news", section="자원뉴스",
                     text='\n'.join(lines), caveat=KOMIS_RAW_DUMMY_CAVEAT if dummy else None)], []
