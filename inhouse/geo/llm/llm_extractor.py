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
        # 2026-07-20 /goal 수정: 기존 "(문서 광종 힌트: X)" 문구는 X를 그대로 확인해달라는 뉘앙스로
        # 읽혀 LLM이 무관한 문서도 힌트 상품으로 확인해버리는 확인편향을 유발했다(상품 오태깅 33건
        # 조사, WORKLOG 2026-07-20의 근본원인 1/2 — commodity_hint가 프롬프트 주입처럼 작용). 힌트가
        # 잠정 후보일 뿐이며 무관하면 반려·다른 상품이면 정정하라고 명시해 편향을 줄인다.
        hint = (f"\n(1차 후보 광종 힌트: {commodity_hint} — 확정이 아니니 본문이 실제로 이 광종과"
                f" 무관하면 이 광종에 대한 이벤트를 반환하지 말고, 다른 광종이 맞다면 그 광종으로"
                f" 정정해 반환하세요.)") if commodity_hint else ""
        user = f"다음 발췌에서 이벤트를 JSON 배열로 추출:{hint}\n\n{passages[:12000]}"
        res: LLMResult = self.chat.complete(SYSTEM_PROMPT, user)
        events = as_event_list(repair_json(res.text))
        # 광종 미기재 시 힌트로 보정
        for e in events:
            if not e.get("commodity") and commodity_hint:
                e["commodity"] = commodity_hint
        return events
