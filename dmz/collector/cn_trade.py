# -*- coding: utf-8 -*-
"""중국 수출입 공시 수집 — 상무부 안전관제국(수출통제 주관국) 직접 스크레이프.

실측(2026-07-12): 메인 www.mofcom.gov.cn 은 JS 렌더링(jpaas API)이라 파싱이 불안정하지만,
수출통제 주관국인 안전관제국(aqygzj.mofcom.gov.cn)은 순수 HTML이고 내용이 정확히 표적이다 —
"商务部公告 第N号"(실체명단·战略矿产 两用물项 수출통제), 대변인 문답, 대외 수출통제 대화 동향.

실측(2026-07-12) 주의: 하위 목록 페이지(/flzc/gzjgfxwj/ 등)도 JS 렌더링(jpaas)이라 빈 목록이
온다 — **메인 페이지("/")만 서버 렌더링**이며 공고·대변인 문답·동향의 최신 항목이 모두 실려
있으므로 주기 수집은 메인 페이지를 긁는다(주기 실행 전제라 최신분이면 충분. 과거 백필은 불가 —
필요 시 GKG/GNews가 보완). 키워드 필터 통과 항목만 본문 페이지를 열어 텍스트를 저장.
접속 불가(중국 사이트 특성상 간헐 차단) 시엔 다음 주기에 자연 재시도 — 상태는 seen으로 유지.
"""
from __future__ import annotations
import logging, re, time
from datetime import date, datetime

import requests

from . import config as C
from .common import load_seen, save_seen, write_article

logger = logging.getLogger("collector.cn_trade")

BASE = "https://aqygzj.mofcom.gov.cn"
SECTIONS = ["/"]     # 메인만 서버 렌더링(하위 목록은 jpaas JS) — 최신 공고·문답·동향이 모두 포함
# 수집 대상 판별(제목 기준): 수출통제/무역조치 신호어 — 광물 무관 실체명단도 포함(공급망 신호)
_SIGNAL = ("出口管制", "管控名单", "关注名单", "两用物项", "出口", "关税", "禁运", "制裁", "矿产")
_RATE_SECS = 3
_LINK = re.compile(r'href="([^"]+?/art/\d{4}/art_[a-f0-9]+\.html)"[^>]*>([^<]{6,120})<')
_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_TAG = re.compile(r"<[^>]+>")


def _get(url: str) -> str:
    r = requests.get(url, timeout=C.HTTP_TIMEOUT, headers={"User-Agent": C.UA})
    r.raise_for_status()
    # apparent_encoding(chardet 계열)은 환경(라이브러리 버전)에 따라 중국어 페이지를 오판해
    # 제목이 모지바케 → 키워드 필터 전멸하는 사례 실측(2026-07-12, slim 컨테이너에서 0건).
    # mofcom은 UTF-8 고정이므로 명시한다.
    r.encoding = "utf-8"
    return r.text


def _mineral_of(text: str) -> str:
    for cc, kws in C.MINERAL_ZH.items():
        if any(k in text for k in kws):
            return cc
    return "ALL"


def _article_date(html: str, url: str) -> date:
    m = _DATE.search(html)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    m = re.search(r"/art/(\d{4})/", url)          # 최후: URL의 연도, 1/1로 근사
    return date(int(m.group(1)), 1, 1) if m else date.today()


def _article_text(html: str, limit: int = 3000) -> str:
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    txt = _TAG.sub(" ", body)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:limit]


def run(minerals: list | None = None) -> int:   # minerals 인자는 CLI 일관성용(중국어 필터가 대신함)
    C.ensure_dirs()
    seen = load_seen("cn_trade")
    n_new = 0
    for sec in SECTIONS:
        time.sleep(_RATE_SECS)
        try:
            html = _get(BASE + sec)
        except Exception as e:
            logger.warning("cn_trade 목록 실패(%s): %s", sec, e)
            continue
        for path, title in _LINK.findall(html):
            title = title.strip()
            if not any(s in title for s in _SIGNAL):
                continue
            url = path if path.startswith("http") else BASE + path
            import hashlib
            if hashlib.md5(url.encode()).hexdigest() in seen:
                continue
            time.sleep(_RATE_SECS)
            try:
                art = _get(url)
            except Exception as e:
                logger.warning("cn_trade 본문 실패(%s): %s", url, e)
                continue
            body = _article_text(art)
            if write_article(source_label="CN_MOFCOM_ExportControl", subdir="cn_trade",
                             mineral=_mineral_of(title + body[:500]), art_date=_article_date(art, url),
                             title=f"{title}\n\n{body}", url=url, domain="aqygzj.mofcom.gov.cn",
                             extra=f"Section: {sec}", seen=seen):
                n_new += 1
    save_seen(seen, "cn_trade")
    logger.info("cn_trade: 신규 %d건", n_new)
    print(f"[cn_trade] 신규 {n_new}건")
    return n_new
