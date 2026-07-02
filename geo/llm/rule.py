# -*- coding: utf-8 -*-
"""규칙기반 추출기 (LLM 없이 폴백). 키워드→event_type/방향/severity 매핑."""
import re
from .base import GEO_KEYWORDS

# (정규식, event_type, direction, target, severity)
RULES = [
    (r"수출\s*(금지|규제|통제|제한)|export\s*(ban|control|restriction)", "수출규제", "supply_down", "supply", 3),
    (r"제재|sanction|embargo|금수", "제재", "supply_down", "supply", 3),
    (r"파업|strike|force majeure|불가항력", "파업", "supply_down", "production", 2),
    (r"분쟁|전쟁|쿠데타|conflict|war|coup", "분쟁", "supply_down", "supply", 2),
    (r"감산|폐쇄|shutdown|curtail|생산\s*차질|disruption", "감산", "supply_down", "production", 2),
    (r"국유화|nationaliz", "국유화", "supply_down", "supply", 2),
    (r"관세|tariff|쿼터|quota|허가제", "정책", "supply_down", "supply", 1),
    (r"증설|확장|expansion|ramp[- ]?up|신규\s*생산", "증설", "supply_up", "production", 1),
]

_COUNTRY = {
    "인도네시아": "Indonesia", "indonesia": "Indonesia", "중국": "China", "china": "China",
    "콩고": "DR Congo", "drc": "DR Congo", "congo": "DR Congo", "칠레": "Chile", "chile": "Chile",
    "러시아": "Russia", "russia": "Russia", "호주": "Australia", "australia": "Australia",
}


class RuleExtractor:
    name = "rule"; provider = "rule"; model = "keyword-v1"

    def extract(self, passages: str, commodity_hint):
        if not commodity_hint or commodity_hint not in ("CU","NI","LI","CO","REE"):
            return []                       # 광종 미상은 룰로는 스킵
        low = passages.lower()
        out = []
        for pat, etype, direction, target, sev in RULES:
            for mm in re.finditer(pat, low):
                s = max(0, mm.start()-120); e = min(len(passages), mm.end()+120)
                quote = passages[s:e].replace("\n", " ").strip()
                country = next((v for k, v in _COUNTRY.items() if k in low[s:e]), None)
                out.append(dict(commodity=commodity_hint, country=country, event_type=etype,
                                direction=direction, target=target, severity=sev,
                                horizon_months=None, obs_date=None, confidence=0.4,
                                evidence_quote=quote[:300]))
                break                       # 룰당 문서 1건(과다중복 방지)
        return out
