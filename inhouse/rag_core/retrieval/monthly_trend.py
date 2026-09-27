"""월간동향 게시물 구조화 adapter."""
from __future__ import annotations

import re

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence


_MINERALS = ("리튬", "니켈", "코발트", "구리", "동", "아연", "망간", "텅스텐", "몰리브덴", "희토류", "흑연", "알루미늄", "철광석")


def fetch_monthly_trend_evidence(topic: str = "", *, limit_chunks: int = 12) -> tuple[list[Evidence], list[str]]:
    settings = get_settings()
    schema = getattr(settings, "VECTOR_SCHEMA", settings.PG_SCHEMA).replace('"', "")
    con = pg_connect()
    try:
        with con.cursor() as cur:
            # 최신 후보의 일부 청크들을 서로 섞으면 제목·광종·요약의 출처가
            # 달라진다. 먼저 문서 하나를 고르고 그 문서의 청크만 묶는다.
            cur.execute(
                f"""
                WITH selected AS (
                    SELECT doc_id
                    FROM {schema}.doc_chunk
                    WHERE title ILIKE %s OR source_path ILIKE %s OR txt ILIKE %s
                    ORDER BY pub_date DESC NULLS LAST, doc_id DESC, seq ASC
                    LIMIT 1
                )
                SELECT d.doc_id, d.title, d.source_path, d.pub_date, d.txt
                FROM {schema}.doc_chunk d JOIN selected s ON s.doc_id=d.doc_id
                ORDER BY d.seq ASC
                LIMIT %s
                """,
                ("%월간동향%", "%월간동향%", "%월간동향%", int(limit_chunks)),
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"monthly_trend_query_failed:{type(exc).__name__}"]
    finally:
        con.close()
    if not rows:
        return [], ["monthly_trend_not_found"]
    title = str(rows[0][1] or "").strip() or "월간동향"
    source_path = str(rows[0][2] or "").strip()
    published = str(rows[0][3] or "").strip()
    body = "\n".join(str(row[4] or "") for row in rows if row[4])
    minerals = []
    for mineral in _MINERALS:
        if mineral in body and mineral not in minerals:
            minerals.append(mineral)
    summary = re.sub(r"\s+", " ", body).strip()[:1200]
    original = source_path if source_path.startswith(("https://", "http://")) else (source_path or "원문 경로 미확인")
    text = (f"| 월호 | 게시일 | 원문 | 광종목록 | 요약 |\n|---|---|---|---|---|\n"
            f"| {title} | {published or '게시일 미확인'} | {original} | {', '.join(minerals)} | {summary} |")
    return [Evidence(kind="structured", source="월간동향", section=title, text=text,
                     as_of=published or None)], []
