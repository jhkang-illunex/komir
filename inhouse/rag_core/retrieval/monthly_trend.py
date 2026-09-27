"""월간동향 게시물 구조화 adapter."""
from __future__ import annotations

from datetime import date
import re

from common.config import get_settings
from common.db import pg_connect
from .evidence import Evidence


_MINERALS = ("리튬", "니켈", "코발트", "구리", "동", "아연", "망간", "텅스텐", "몰리브덴", "희토류", "흑연", "알루미늄", "철광석")


def fetch_monthly_trend_evidence(topic: str = "", *, limit_chunks: int = 12) -> tuple[list[Evidence], list[str]]:
    schema = get_settings().PG_SCHEMA.replace('"', "")
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, title, source_path, txt FROM {schema}.doc_chunk "
                "WHERE (title ILIKE %s OR source_path ILIKE %s OR txt ILIKE %s) "
                "ORDER BY pub_date DESC NULLS LAST, doc_id DESC, seq ASC LIMIT %s",
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
    source_path = str(rows[0][2] or "")
    body = "\n".join(str(row[3] or "") for row in rows if row[3])
    minerals = []
    for mineral in _MINERALS:
        if mineral in body and mineral not in minerals:
            minerals.append(mineral)
    summary = re.sub(r"\s+", " ", body).strip()[:1200]
    text = (f"| 월호 | 광종목록 | 요약 |\n|---|---|---|\n"
            f"| {title} | {', '.join(minerals)} | {summary} |")
    return [Evidence(kind="structured", source="월간동향", section=title, text=text,
                     as_of=date.today().isoformat())], []
