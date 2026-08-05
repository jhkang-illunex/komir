# -*- coding: utf-8 -*-
"""테스트용 결정론 mock 추출기 (키 없이 [1]→[2]→[3] E2E 확인)."""
import hashlib
from .base import GEO_KEYWORDS


class MockExtractor:
    name = "mock"; provider = "mock"; model = "mock-v1"

    def extract(self, passages: str, commodity_hint):
        low = passages.lower()
        hit = next((k for k in GEO_KEYWORDS if k.lower() in low), None)
        if not hit or not commodity_hint:
            return []
        sev = 3 if any(k in low for k in ["수출규제","수출금지","제재","sanction","export ban"]) else 1
        seed = int(hashlib.md5((passages[:200]).encode()).hexdigest(), 16) % 3
        return [dict(commodity=commodity_hint, country=None, event_type=f"mock:{hit}",
                     direction="supply_down", target="supply", severity=sev,
                     horizon_months=[3,6,12][seed], obs_date=None, confidence=0.5,
                     evidence_quote=f"[MOCK] keyword '{hit}' near: " + passages[:120].replace("\n"," "))]
