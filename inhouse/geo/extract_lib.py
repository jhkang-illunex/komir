# -*- coding: utf-8 -*-
"""[2] 퍼널: 지정학 프리필터 + 관련 단락 추출."""
import re
from .llm.base import GEO_KEYWORDS

_PAT = re.compile("|".join(re.escape(k) for k in GEO_KEYWORDS), re.IGNORECASE)
WINDOW = 400   # 매칭 주변 문자수


def is_relevant(text: str) -> bool:
    return bool(_PAT.search(text or ""))


def passages(text: str, max_chars: int = 6000) -> str:
    """키워드 매칭 주변 단락만 이어붙여 반환(비용 절감). 매칭 없으면 앞부분."""
    if not text:
        return ""
    spans = []
    for m in _PAT.finditer(text):
        s = max(0, m.start() - WINDOW); e = min(len(text), m.end() + WINDOW)
        spans.append((s, e))
    if not spans:
        return text[:1500]
    # 겹치는 구간 병합
    spans.sort(); merged = [spans[0]]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out = "\n...\n".join(text[s:e] for s, e in merged)
    return out[:max_chars]
