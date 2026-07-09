# -*- coding: utf-8 -*-
"""gnews.py/gdelt.py 공용: inbox 텍스트 투척 + URL 단위 중복수집 방지.
GDELT·Google News가 같은 기사를 각자 찾아도 URL 해시 하나로 묶어 inbox에 중복 투척하지 않는다
(같은 사건이 보도량만큼 severity를 부풀리는 것을 방지 — §9-5)."""
from __future__ import annotations
import hashlib, json
from datetime import date
from pathlib import Path

from .. import config as C

MINERAL_EN = {"CU": "copper", "NI": "nickel", "CO": "cobalt", "LI": "lithium", "REE": "rare earth"}


def _seen_path() -> Path:
    p = C.GEO_DATA / "collectors" / "news_seen.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_seen() -> set:
    p = _seen_path()
    if p.exists():
        try:
            return set(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(seen: set) -> None:
    _seen_path().write_text(json.dumps(sorted(seen)), encoding="utf-8")


def write_article(*, source_label: str, subdir: str, mineral: str, art_date: date,
                   title: str, url: str, domain: str = "", extra: str = "",
                   seen: set) -> bool:
    """기사 1건 → geo_data/inbox/<subdir>/ 텍스트 파일.
    이미 본 URL(해시)이면 아무것도 쓰지 않고 False 반환(중복 스킵)."""
    if not url or not title:
        return False
    uh = hashlib.md5(url.encode()).hexdigest()
    if uh in seen:
        return False
    body = (
        f"Mineral: {MINERAL_EN.get(mineral, mineral)}\n"
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
