# -*- coding: utf-8 -*-
"""provider 무관 추출기 인터페이스 + 팩토리 + 공용 프롬프트/키워드."""
from __future__ import annotations
from typing import Protocol
from dataclasses import dataclass, field

PROMPT_VERSION = "geo-extract-v1"

# 지정학 관련 프리필터/룰 키워드 (KO+EN)
GEO_KEYWORDS = [
    "제재","금수","수출규제","수출통제","수출제한","파업","분쟁","전쟁","쿠데타","봉쇄",
    "국유화","감산","폐쇄","공급차질","지정학","관세","허가제","쿼터",
    "sanction","export ban","export control","export restriction","strike","conflict",
    "embargo","nationaliz","disruption","shutdown","curtail","force majeure","tariff","quota",
]

SYSTEM_PROMPT = (
    "당신은 광물 공급망 애널리스트입니다. 주어진 문서 발췌에서 5대 핵심광물"
    "(CU=동, NI=니켈, LI=리튬, CO=코발트, REE=네오디뮴)의 수급·가격·생산에 영향을 주는"
    " 지정학/정책/공급 이벤트만 추출합니다. 추정·전망도 포함하되 근거 문장을 인용하세요.\n"
    "반드시 JSON 배열만 출력. 각 원소 필드:\n"
    "commodity(CU|NI|LI|CO|REE), country, event_type, "
    "direction(supply_down|supply_up|price_up|price_down|neutral), "
    "target(supply|price|production|demand|mixed), severity(0~3 정수), "
    "horizon_months(정수|null), obs_date(YYYY-MM-DD|null), confidence(0~1), evidence_quote."
)


@dataclass
class LLMResult:
    text: str = ""
    parsed: object = None
    usage: dict = field(default_factory=dict)
    model: str = ""


class Extractor(Protocol):
    name: str
    provider: str
    model: str
    def extract(self, passages: str, commodity_hint: str | None) -> list[dict]: ...


def get_extractor(cfg: dict) -> "Extractor":
    """cfg['provider']: rule | mock | openai_compat | anthropic."""
    p = (cfg.get("provider") or "rule").lower()
    if p == "rule":
        from .rule import RuleExtractor; return RuleExtractor()
    if p == "mock":
        from .mock import MockExtractor; return MockExtractor()
    if p in ("openai_compat", "openai", "ollama", "vllm", "gemini"):
        from .openai_compat import OpenAICompatChat
        from .llm_extractor import LLMExtractor
        return LLMExtractor(OpenAICompatChat(cfg), provider=p)
    if p == "anthropic":
        from .anthropic_native import AnthropicChat
        from .llm_extractor import LLMExtractor
        return LLMExtractor(AnthropicChat(cfg), provider="anthropic")
    raise ValueError(f"알 수 없는 provider: {p}")
