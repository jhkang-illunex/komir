# -*- coding: utf-8 -*-
"""수집기 공용: inbox 텍스트 투척 + URL 단위 중복수집 방지 (geo/collectors/_common.py에서 이식,
geo 패키지 의존 제거 — 이 패키지는 분석기와 다른 서버에서 단독 실행된다)."""
from __future__ import annotations
import hashlib, json
from datetime import date
from pathlib import Path

from . import config as C


def _seen_path(name: str) -> Path:
    C.ensure_dirs()
    return C.STATE / f"seen_{name}.json"


def load_seen(name: str = "news") -> set:
    p = _seen_path(name)
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(seen: set, name: str = "news") -> None:
    _seen_path(name).write_text(json.dumps(sorted(seen)), encoding="utf-8")


def write_article(*, source_label: str, subdir: str, mineral: str, art_date: date,
                   title: str, url: str, domain: str = "", extra: str = "",
                   seen: set) -> bool:
    """기사/공시 1건 → $COLLECT_OUT/inbox/<subdir>/ 텍스트 파일(geo ingest 호환 형식).
    이미 본 URL(해시)이면 아무것도 쓰지 않고 False 반환(중복 스킵)."""
    if not url or not title:
        return False
    uh = hashlib.md5(url.encode()).hexdigest()
    if uh in seen:
        return False
    body = (
        f"Mineral: {C.MINERAL_EN.get(mineral, mineral)}\n"
        f"Source: {source_label}\n"
        f"Domain: {domain}\n"
        f"Published: {art_date.isoformat()}\n"
        f"URL: {url}\n"
        + (f"{extra}\n" if extra else "")
        + f"\n{title}\n"
    )
    fname = f"{mineral}_{art_date.strftime('%Y%m%d')}_{uh[:8]}.txt"
    dest = C.INBOX / subdir
    dest.mkdir(parents=True, exist_ok=True)
    (dest / fname).write_text(body, encoding="utf-8")
    seen.add(uh)
    return True
