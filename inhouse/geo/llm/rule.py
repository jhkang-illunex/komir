# -*- coding: utf-8 -*-
"""규칙기반 추출기 (LLM 없이 폴백). 키워드→event_type/방향/severity 매핑."""
import re
from .base import GEO_KEYWORDS
from ..classify import COMMODITY_KEYWORDS

# (정규식, event_type, direction, target, severity)
RULES = [
    (r"수출\s*(금지|규제|통제|제한)|export\s*(ban|control|restriction)", "수출규제", "supply_down", "supply", 3),
    (r"제재|sanction|embargo|금수", "제재", "supply_down", "supply", 3),
    (r"파업|strike|force majeure|불가항력", "파업", "supply_down", "production", 2),
    # war/coup/quota는 단어 경계 필수 — 실측(2026-07-07): "warehouse"(LME 창고 재고, 비철금속
    # 시황보고서에 극히 흔함)가 "war"에 오매칭되어 CU/China "분쟁" 이벤트 오탐 발생(Argus 보고서
    # 1건에 warehouse 88회 vs 실제 war 3회). "quotations"(가격고시)도 "quota"에 오탐.
    (r"분쟁|전쟁|쿠데타|conflict|\bwar\b|\bcoup\b", "분쟁", "supply_down", "supply", 2),
    (r"감산|폐쇄|shutdown|curtail|생산\s*차질|disruption", "감산", "supply_down", "production", 2),
    (r"국유화|nationaliz", "국유화", "supply_down", "supply", 2),
    (r"관세|tariff|쿼터|\bquota\b|허가제", "정책", "supply_down", "supply", 1),
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
        """다광종 문서 대응(2026-07-07 수정): 매치마다 commodity_hint를 무조건 붙이던 방식은
        조달청·Argus·IEA처럼 한 문서가 5광종을 다 다루는 경우 엉뚱한 광종으로 오염됨(WoodMac
        니켈 보고서가 "LI"로 오분류돼 그 안의 니켈 이벤트가 리튬 이벤트로 저장된 사례 실측 확인).
        이제 사건유형 매치마다 그 국지창(±120자)에 실제로 등장하는 광종 키워드를 찾아 그것으로
        태깅하고, 창 안에 광종 키워드가 없을 때만 commodity_hint(문서 대표 광종)로 폴백한다.
        국지창에 여러 광종이 같이 언급되면 각각에 대해 이벤트를 하나씩 생성한다."""
        low = passages.lower()
        out = []
        for pat, etype, direction, target, sev in RULES:
            for mm in re.finditer(pat, low):
                s = max(0, mm.start()-120); e = min(len(passages), mm.end()+120)
                window_low = low[s:e]
                quote = passages[s:e].replace("\n", " ").strip()
                country = next((v for k, v in _COUNTRY.items() if k in window_low), None)
                local_commodities = [cc for cc, kws in COMMODITY_KEYWORDS.items()
                                      if any(k in window_low for k in kws)]
                commodities = local_commodities or (
                    [commodity_hint] if commodity_hint in ("CU", "NI", "LI", "CO", "REE") else [])
                if not commodities:
                    continue  # 국지창·문서힌트 어디에도 광종을 특정 못하면 스킵(오분류 방지)
                for cc in commodities:
                    out.append(dict(commodity=cc, country=country, event_type=etype,
                                    direction=direction, target=target, severity=sev,
                                    horizon_months=None, obs_date=None, confidence=0.4,
                                    evidence_quote=quote[:300]))
                break                       # 룰당 문서 1건(과다중복 방지) — 광종별로는 이미 분기됨
        return out
