# -*- coding: utf-8 -*-
"""중국 공시 과거 백필 — Wayback Machine 인벤토리 + 라이브/아카이브 본문 수집.

배경(2026-07-12): 상무부 사이트는 목록이 JS 렌더링이라 주기 수집(cn_trade.py)은 최신분만
가능. 과거 10년치는 Wayback CDX로 '공고 본문 URL 인벤토리'를 확보한 뒤, 본문을 라이브
(아직 살아있는 aqygzj art_*.html)에서 우선 수집하고 죽은 구 경로(www.mofcom.gov.cn/article/
zwgk/zcfb/*.shtml — 라이브 404 실측)는 아카이브 스냅샷(web.archive.org/web/<ts>id_/<url>)에서
수집한다. 날짜는 구 경로 URL에 내장(/YYYYMM/YYYYMMDD...), aqygzj는 본문 날짜 정규식.

1회성 백필 도구 — 주기 수집은 cn_trade.py가 담당. 실행:
  COLLECT_OUT=... python -m collector.cn_trade_backfill
"""
from __future__ import annotations
import hashlib, logging, re, time
from datetime import date, datetime

import requests

from . import config as C
from .common import load_seen, save_seen, write_article
from .cn_trade import _SIGNAL, _TAG, _mineral_of, _article_date, _article_text

logger = logging.getLogger("collector.cn_backfill")

CDX = "http://web.archive.org/cdx/search/cdx"
SOURCES = [
    # (CDX url 패턴, 본문 위치: live 우선 여부)
    ("aqygzj.mofcom.gov.cn/*", r"art_[a-f0-9]+\.html$", True),
    ("www.mofcom.gov.cn/article/zwgk/zcfb/*", r"/\d{6}/\d{14,}\.shtml$", False),
]
_URL_OK = re.compile(r"^https?://[^%\s]+$")     # 인코딩 잡음 URL 배제
_OLD_DATE = re.compile(r"/(\d{6})/(\d{8})\d*\.shtml")
_RATE = 1.5


def _cdx_inventory(pattern: str, path_re: str) -> list:
    r = requests.get(CDX, params={"url": pattern, "output": "text",
                                  "fl": "original,timestamp", "collapse": "urlkey"},
                     timeout=60, headers={"User-Agent": C.UA})
    r.raise_for_status()
    out = []
    pre = re.compile(path_re)
    for line in r.text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        url, ts = parts
        if _URL_OK.match(url) and pre.search(url):
            out.append((url, ts))
    return out


def _fetch(url: str, ts: str, live_first: bool) -> str | None:
    tries = ([url, f"http://web.archive.org/web/{ts}id_/{url}"] if live_first
             else [f"http://web.archive.org/web/{ts}id_/{url}"])
    for u in tries:
        try:
            r = requests.get(u, timeout=C.HTTP_TIMEOUT, headers={"User-Agent": C.UA})
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
        except Exception:
            continue
    return None


def _title_of(html: str) -> str:
    m = re.search(r"<title>([^<]{4,120})</title>", html, re.I)
    t = _TAG.sub(" ", m.group(1)) if m else ""
    return re.sub(r"\s+", " ", t).strip()


def _date_of(url: str, html: str) -> date:
    m = _OLD_DATE.search(url)
    if m:
        try:
            return datetime.strptime(m.group(2), "%Y%m%d").date()
        except ValueError:
            pass
    return _article_date(html, url)


def run(year_from: int = 2016) -> int:
    C.ensure_dirs()
    seen = load_seen("cn_trade")
    n_new = n_skip = 0
    for pattern, path_re, live_first in SOURCES:
        try:
            inv = _cdx_inventory(pattern, path_re)
        except Exception as e:
            logger.warning("CDX 실패(%s): %s", pattern, e)
            continue
        print(f"[cn-backfill] {pattern}: 인벤토리 {len(inv)}건")
        for url, ts in inv:
            if hashlib.md5(url.encode()).hexdigest() in seen:
                continue
            time.sleep(_RATE)
            html = _fetch(url, ts, live_first)
            if not html:
                n_skip += 1
                continue
            title = _title_of(html)
            body = _article_text(html)
            if not any(s in title + body[:600] for s in _SIGNAL):
                continue
            d = _date_of(url, html)
            if d.year < year_from:
                continue
            if write_article(source_label="CN_MOFCOM_ExportControl", subdir="cn_trade",
                             mineral=_mineral_of(title + body[:800]), art_date=d,
                             title=f"{title}\n\n{body}", url=url,
                             domain=url.split("/")[2], extra=f"Backfill: wayback {ts}",
                             seen=seen):
                n_new += 1
                if n_new % 20 == 0:
                    print(f"  ... 신규 {n_new}건")
    save_seen(seen, "cn_trade")
    print(f"[cn-backfill] 신규 {n_new}건 (본문 확보실패 {n_skip})")
    return n_new


if __name__ == "__main__":
    run()
