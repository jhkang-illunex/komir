# -*- coding: utf-8 -*-
"""[0] GDELT DOC API 뉴스 수집 → geo_data/inbox 텍스트 투척 (komis/collectors/gdelt.py 이식).

GDELT Article List API(무료, 키 불필요)로 광물별 뉴스 제목을 수집한다. 이 API는 원시 GDELT
Event DB(CAMEO 코드·Goldstein scale)가 아니라 기사 목록만 반환하므로, gnews.py와 마찬가지로
구조화 severity를 직접 매핑하지 않는다 — 원문만 저장해 기존 [1]ingest→[2]extract(LLM/rule)가
severity를 산출하도록 한다(소스 간 점수체계 일원화, §9-1/§9-2 정정).

Rate limit: 공식 권고 5초/요청 → 여유 있게 15초 대기 + 429 지수 백오프.
실행 후 반드시 `python -m geo ingest && python -m geo extract`로 이어야 실제 GeoEvent가 생긴다.
"""
from __future__ import annotations
import argparse, logging, time
from datetime import date, timedelta, datetime, timezone

import requests

from .. import config as C
from ._common import load_seen, save_seen, write_article

logger = logging.getLogger("geo.collectors.gdelt")

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_RATE_SECS = 15  # 보수적 대기 — IP 차단 방지(공식 권고 5초 대비 여유)

# 광물별 검색 쿼리 (komis 원본 그대로, GDELT Boolean 문법)
MINERAL_QUERIES: dict[str, str] = {
    "CU":  'copper mine supply "export control" OR "supply disruption" OR "tariff" OR strike',
    "NI":  "nickel mine Indonesia Philippines supply disruption export ban",
    "CO":  "cobalt DRC Congo mine supply disruption export",
    "LI":  "lithium battery supply carbonate hydroxide China Australia Chile Argentina",
    "REE": '"rare earth" neodymium dysprosium China "export control" OR "export ban" supply',
}


def _params(query: str, start: date, end: date, maxrecords: int = 250) -> dict:
    return {"query": query, "mode": "artlist", "maxrecords": str(maxrecords),
            "startdatetime": start.strftime("%Y%m%d000000"),
            "enddatetime": end.strftime("%Y%m%d235959"), "format": "json"}


def _fetch(params: dict, retries: int = 3) -> list[dict]:
    """단일 GDELT API 호출. rate limit 준수 + 지수 백오프."""
    for attempt in range(retries):
        time.sleep(_RATE_SECS * (2 ** attempt) if attempt else _RATE_SECS)
        try:
            r = requests.get(GDELT_API, params=params, timeout=30)
            if r.status_code == 200:
                return r.json().get("articles") or []
            if r.status_code == 429:
                logger.warning("GDELT rate limit (attempt %d/%d)", attempt + 1, retries)
                continue
            logger.warning("GDELT HTTP %s", r.status_code)
        except Exception as exc:
            logger.warning("GDELT 요청 실패: %s", exc)
    return []


def fetch_week(mineral: str, week_start: date, seen: set) -> int:
    """특정 광물의 1주치 뉴스 수집 → inbox 투척. 반환: 신규 건수."""
    query = MINERAL_QUERIES.get(mineral)
    if not query:
        return 0
    week_end = week_start + timedelta(days=6)
    articles = _fetch(_params(query, week_start, week_end))
    n = 0
    for a in articles:
        try:
            art_date = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ") \
                .replace(tzinfo=timezone.utc).date()
        except Exception:
            art_date = week_start
        ok = write_article(source_label="GDELT", subdir="gdelt", mineral=mineral, art_date=art_date,
                            title=a.get("title", ""), url=a.get("url", ""), domain=a.get("domain", ""),
                            extra=f"SourceCountry: {a.get('sourcecountry', '')}", seen=seen)
        if ok: n += 1
    logger.info("GDELT %s [%s~%s]: 신규 %d건", mineral, week_start, week_end, n)
    return n


def _week_start(d: date) -> date:
    """ISO 주의 월요일 반환."""
    return d - timedelta(days=d.weekday())


def run(minerals: list[str] | None = None, days: int = 90) -> int:
    C.ensure_dirs()
    minerals = minerals or list(MINERAL_QUERIES)
    seen = load_seen()
    end = date.today()
    w = _week_start(end - timedelta(days=days))
    limit = _week_start(end)
    total = 0
    while w <= limit:
        for m in minerals:
            total += fetch_week(m, w, seen)
        w += timedelta(weeks=1)
    save_seen(seen)
    print(f"[gdelt] inbox 신규 투척 {total}건 → geo_data/inbox/gdelt/ "
          f"(다음 'python -m geo ingest && python -m geo extract'로 처리)")
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minerals", default=None, help="쉼표구분 CU,NI,CO,LI,REE(기본 전체)")
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    run(a.minerals.split(",") if a.minerals else None, a.days)
