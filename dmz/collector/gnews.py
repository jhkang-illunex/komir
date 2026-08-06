# -*- coding: utf-8 -*-
"""[0] Google News RSS 뉴스 수집 → $COLLECT_OUT/inbox 텍스트 투척 (komis/collectors/gnews.py 이식).

API 키 불필요, 레이트리밋 느슨(2초 권장). after:/before: 날짜 연산자로 과거 기사도 수집 가능하나
쿼리당 최대 ~100건 반환 → 분기 단위로 분할 수집한다.

komis 원본과 달리 자체 event_intensity/감성 점수를 산출하지 않는다 — 원문(제목+메타)만 저장해
기존 [1]ingest→[2]extract(LLM/rule)가 severity를 산출하도록 한다(소스 간 점수체계 일원화, §9-1).
실행 후 반드시 `python -m geo ingest && python -m geo extract`로 이어야 실제 GeoEvent가 생긴다.
"""
from __future__ import annotations
import argparse, logging, time
from datetime import date, timedelta, datetime, timezone
from urllib.parse import quote, urlparse

import feedparser

from . import config as C
from .common import load_seen, save_seen, write_article

logger = logging.getLogger("collector.gnews")

_GNEWS_BASE = "https://news.google.com/rss/search"
_RATE_SECS = 2

# 광물별 검색 쿼리 (komis 원본 그대로 — 핵심 공급망 리스크 키워드)
MINERAL_QUERIES: dict[str, str] = {
    "CU":  'copper mine supply "export" OR "tariff" OR "strike" OR "disruption" OR "Chile" OR "Peru"',
    "NI":  'nickel supply mine Indonesia Philippines "export ban" OR "battery" OR disruption',
    "CO":  'cobalt supply DRC Congo mine "export" OR "battery" OR disruption',
    "LI":  'lithium battery supply carbonate hydroxide Chile Argentina Australia China',
    "REE": '"rare earth" neodymium China "export" OR "ban" OR "control" supply',
}


def _url(query: str, after: date, before: date) -> str:
    q = f'{query} after:{after.isoformat()} before:{before.isoformat()}'
    return f"{_GNEWS_BASE}?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"


def fetch_period(mineral: str, after: date, before: date, seen: set) -> int:
    """단일 기간의 특정 광물 기사 수집 → inbox 투척. 반환: 신규 건수."""
    query = MINERAL_QUERIES.get(mineral)
    if not query:
        return 0
    time.sleep(_RATE_SECS)
    try:
        feed = feedparser.parse(_url(query, after, before))
    except Exception as exc:
        logger.warning("Google News 요청 실패(%s %s~%s): %s", mineral, after, before, exc)
        return 0
    n = 0
    for entry in feed.entries:
        url, title = entry.get("link", ""), entry.get("title", "")
        pub = entry.get("published_parsed")
        try:
            art_date = datetime(*pub[:6], tzinfo=timezone.utc).date() if pub else after
        except Exception:
            art_date = after
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = ""
        if write_article(source_label="Google News RSS", subdir="gnews", mineral=mineral,
                          art_date=art_date, title=title, url=url, domain=domain, seen=seen):
            n += 1
    logger.info("Google News %s [%s~%s]: 신규 %d건", mineral, after, before, n)
    return n


def _quarter_ranges(start: date, end: date) -> list[tuple[date, date]]:
    """날짜 범위를 분기(3개월) 단위로 분할(구글 뉴스 쿼리당 반환건수 제한 대응)."""
    ranges: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        if cur.month <= 3: nxt = date(cur.year, 4, 1)
        elif cur.month <= 6: nxt = date(cur.year, 7, 1)
        elif cur.month <= 9: nxt = date(cur.year, 10, 1)
        else: nxt = date(cur.year + 1, 1, 1)
        ranges.append((cur, min(nxt - timedelta(days=1), end)))
        cur = nxt
    return ranges


def run(minerals: list[str] | None = None, days: int = 90) -> int:
    C.ensure_dirs()
    minerals = minerals or list(MINERAL_QUERIES)
    seen = load_seen("news")
    end = date.today()
    start = end - timedelta(days=days)
    total = 0
    for q_start, q_end in _quarter_ranges(start, end):
        for m in minerals:
            total += fetch_period(m, q_start, q_end, seen)
    save_seen(seen, "news")
    print(f"[gnews] inbox 신규 투척 {total}건 → $COLLECT_OUT/inbox/gnews/ "
          f"(분석 서버의 'geo ingest'가 처리)")
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minerals", default=None, help="쉼표구분 CU,NI,CO,LI,REE(기본 전체)")
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    run(a.minerals.split(",") if a.minerals else None, a.days)
