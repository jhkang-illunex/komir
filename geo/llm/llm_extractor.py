# -*- coding: utf-8 -*-
"""chat 클라이언트를 감싸 GeoEvent를 추출하는 provider 무관 추출기."""
from .base import SYSTEM_PROMPT, LLMResult
from .jsonutil import repair_json, as_event_list


class LLMExtractor:
    name = "llm"

    def __init__(self, chat, provider: str):
        self.chat = chat
        self.provider = provider
        self.model = getattr(chat, "model", "")

    def extract(self, passages: str, commodity_hint):
        hint = f"\n(문서 광종 힌트: {commodity_hint})" if commodity_hint else ""
        user = f"다음 발췌에서 이벤트를 JSON 배열로 추출:{hint}\n\n{passages[:12000]}"
        res: LLMResult = self.chat.complete(SYSTEM_PROMPT, user)
        events = as_event_list(repair_json(res.text))
        # 광종 미기재 시 힌트로 보정
        for e in events:
            if not e.get("commodity") and commodity_hint:
                e["commodity"] = commodity_hint
        return events
