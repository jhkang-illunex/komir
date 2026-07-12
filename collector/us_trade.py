# -*- coding: utf-8 -*-
"""미국 수출입 공시 수집 — Federal Register 공식 JSON API (키 불필요).

대상 기관(실측 확인된 슬러그):
  - industry-and-security-bureau (상무부 BIS — 수출통제·Entity List)
  - trade-representative-office-of-united-states (USTR — 관세·301조)
  - international-trade-administration (ITA — 반덤핑·상계관세)
검색: 광물 키워드 × 무역조치 키워드. 문서 제목+초록(abstract)을 inbox 텍스트로 투척.

Federal Register API는 관보(공식 공시) 그 자체라 보도자료보다 법적 확정력이 높다 —
Section 232/301, Entity List 추가, 수출통제 규칙 개정이 전부 여기 실린다.
"""
from __future__ import annotations
import logging, time
from datetime import date, datetime

import requests

from . import config as C
from .common import load_seen, save_seen, write_article

logger = logging.getLogger("collector.us_trade")

API = "https://www.federalregister.gov/api/v1/documents.json"
AGENCIES = [
    "industry-and-security-bureau",
    "trade-representative-office-of-united-states",
    "international-trade-administration",
]
# 광물 키워드(검색어) — "ALL"은 광종 불특정 공시(예: critical minerals 일반)
TERMS = {
    "ALL": '"critical minerals" OR "rare earth" OR lithium OR cobalt OR nickel OR copper',
    "REE": '"rare earth" OR neodymium',
    "LI": "lithium",
    "CO": "cobalt",
    "NI": "nickel",
    "CU": "copper",
}
_RATE_SECS = 2


def _fetch(term: str, agency: str, since: str, page: int = 1) -> dict:
    params = {
        "conditions[term]": term,
        "conditions[agencies][]": agency,
        "conditions[publication_date][gte]": since,
        "per_page": "100", "page": str(page), "order": "newest",
        "fields[]": ["title", "abstract", "publication_date", "html_url", "type", "agencies"],
    }
    r = requests.get(API, params=params, timeout=C.HTTP_TIMEOUT,
                     headers={"User-Agent": C.UA})
    r.raise_for_status()
    return r.json()


def run(since: str | None = None, minerals: list | None = None) -> int:
    """since: YYYY-MM-DD(기본: 상태파일의 마지막 수집일−7일, 최초엔 2016-01-01)."""
    C.ensure_dirs()
    seen = load_seen("us_trade")
    state_f = C.STATE / "us_trade_since.txt"
    if since is None:
        since = state_f.read_text().strip() if state_f.exists() else "2016-01-01"
    n_new = 0
    for m in (minerals or list(TERMS)):
        term = TERMS.get(m)
        if not term:
            continue
        for agency in AGENCIES:
            page = 1
            while True:
                time.sleep(_RATE_SECS)
                try:
                    d = _fetch(term, agency, since, page)
                except Exception as e:
                    logger.warning("federalregister 실패(%s/%s p%s): %s", m, agency, page, e)
                    break
                for doc in d.get("results", []):
                    try:
                        pd_ = datetime.strptime(doc["publication_date"], "%Y-%m-%d").date()
                    except (KeyError, ValueError):
                        continue
                    extra = f"Type: {doc.get('type','')}\nAgency: {agency}"
                    abstract = (doc.get("abstract") or "").strip()
                    title = doc.get("title", "").strip()
                    if abstract:
                        title = f"{title}\n\n{abstract}"
                    if write_article(source_label="US_FederalRegister", subdir="us_trade",
                                     mineral=m, art_date=pd_, title=title,
                                     url=doc.get("html_url", ""), domain="federalregister.gov",
                                     extra=extra, seen=seen):
                        n_new += 1
                if not d.get("next_page_url"):
                    break
                page += 1
                if page > 10:      # 폭주 방지(초기 백필은 since를 나눠서)
                    break
    save_seen(seen, "us_trade")
    state_f.write_text(date.today().isoformat())
    logger.info("us_trade: 신규 %d건 (since %s)", n_new, since)
    print(f"[us_trade] 신규 {n_new}건 (since {since})")
    return n_new
