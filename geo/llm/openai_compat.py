# -*- coding: utf-8 -*-
"""OpenAI 호환 chat 클라이언트 (OpenAI·vLLM·Ollama·Gemini호환). requests 기반."""
import json, os
import requests
from .base import LLMResult


class OpenAICompatChat:
    def __init__(self, cfg: dict):
        self.base_url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.model = cfg.get("model", "gpt-4o-mini")
        self.api_key = cfg.get("api_key", "") or os.environ.get("LLM_API_KEY", "")
        self.temperature = float(cfg.get("temperature", 0))
        self.timeout = int(cfg.get("timeout", 120))
        self.json_mode = bool(cfg.get("json_mode", True))

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResult:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "temperature": self.temperature,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        r.raise_for_status()
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        return LLMResult(text=text, usage=j.get("usage", {}), model=self.model)
