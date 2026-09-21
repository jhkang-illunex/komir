# -*- coding: utf-8 -*-
"""Anthropic 네이티브 messages 클라이언트. requests 기반(SDK 불필요)."""
import os
import requests
from .base import LLMResult


class AnthropicChat:
    def __init__(self, cfg: dict):
        self.base_url = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        self.model = cfg.get("model", "claude-haiku-4-5-20251001")
        self.api_key = cfg.get("api_key", "") or os.environ.get("LLM_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.temperature = float(cfg.get("temperature", 0))
        self.timeout = int(cfg.get("timeout", 120))

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResult:
        url = f"{self.base_url}/v1/messages"
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": self.temperature,
                "system": system, "messages": [{"role": "user", "content": user}]}
        r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        r.raise_for_status()
        j = r.json()
        text = "".join(b.get("text", "") for b in j.get("content", []))
        return LLMResult(text=text, usage=j.get("usage", {}), model=self.model)
