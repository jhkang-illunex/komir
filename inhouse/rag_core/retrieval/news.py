"""자원뉴스의 RDB 목록과 반정형 보고서 근거를 함께 반환한다."""
from __future__ import annotations

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence, KOMIS_RAW_DUMMY_CAVEAT


_MINERAL_NAMES = ("리튬", "니켈", "코발트", "구리", "동", "망간", "흑연", "텅스텐", "희토류", "네오디뮴")


def mentioned_minerals(text: str) -> list[str]:
    """기사 제목·요약에 실제 표기된 광종만 원문 순서대로 반환한다."""
    normalized = text or ""
    result = []
    for mineral in _MINERAL_NAMES:
        label = "구리" if mineral == "동" else mineral
        if mineral in normalized and label not in result:
            result.append(label)
    return result


def _query_term(topic: str) -> str:
    """전체 질문이 아닌 확인 가능한 광종명만 뉴스 검색어로 사용한다."""
    compact = "".join((topic or "").split())
    mineral = next((name for name in _MINERAL_NAMES if name in compact), None)
    return "구리" if mineral == "동" else (mineral or "")


def fetch_news_evidence(topic: str = "", *, limit: int = 5) -> tuple[list[Evidence], list[str]]:
    """ai_news 제목·헤드라인과 doc_chunk의 검증 가능한 관련 발췌를 함께 조회한다."""
    # 자원뉴스와 광종 마스터는 타 팀 소유 public 원천이고, 반정형 보고서만
    # KOMIR 소유 PG_SCHEMA(mineral_risk)에 있다. 채팅 세션 스키마(ai_chatbot)
    # 변경과 혼동해 한 스키마로 묶으면 ai_news가 없어 조회 전체가 실패한다.
    document_schema = get_settings().PG_SCHEMA.replace('"', '')
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
            if term:
                pattern = '%' + term.replace('%', '') + '%'
                cur.execute(
                    f"SELECT title, txt, pub_date FROM {document_schema}.doc_chunk "
                    "WHERE txt ILIKE %s OR title ILIKE %s "
                    "ORDER BY pub_date DESC NULLS LAST, doc_id DESC, seq ASC LIMIT %s", (pattern, pattern, int(limit)))
            else:
                reports = []
                # 광종 없는 주간 종합 질의는 ai_news의 실제 기사 목록만 사용한다.
                # 무관한 반정형 보고서를 최신순으로 섞어 넣지 않는다.
            if term:
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
        mentioned = ", ".join(mentioned_minerals(f"{title} {headline}"))
        lines.append(f"| {day or ''} | {mineral or mentioned} | {title} | {headline} |")
    for title, text, published_at in reports:
        excerpt = ' '.join(str(text or '').split())[:300]
        if excerpt:
            lines.append(f"| {published_at or '반정형 보고서'} |  | {str(title or '')} | {excerpt} |")
    return [Evidence(kind="structured", source="public.ai_news + 반정형 보고서", section="자원뉴스",
                     text='\n'.join(lines), caveat=KOMIS_RAW_DUMMY_CAVEAT if dummy else None)], []
