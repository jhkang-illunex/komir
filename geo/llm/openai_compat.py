# -*- coding: utf-8 -*-
"""OpenAI 호환 chat 클라이언트 (OpenAI·vLLM·Ollama·Gemini호환). requests 기반.
- 429/5xx/타임아웃: 지수 백오프 재시도(기본 3회) — 일시 장애로 문서가 조용히 유실되지 않게.
- response_format(json_object) 미지원 서버가 400을 주면: 1회에 한해 제거 후 재요청."""
import json, os, time
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
        self.retries = int(cfg.get("retries", 3))

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResult:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "temperature": self.temperature,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        use_rf = self.json_mode
        last = None
        for a in range(self.retries):
            b = dict(body)
            if use_rf:
                b["response_format"] = {"type": "json_object"}
            try:
                r = requests.post(url, headers=headers, json=b, timeout=self.timeout)
                if r.status_code == 400 and use_rf:
                    # 서버가 response_format 미지원(ollama/구버전 vLLM 등) → 제거 후 즉시 재시도
                    use_rf = False
                    continue
                if r.status_code in (429, 500, 502, 503, 504):
                    last = RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
                    time.sleep(2 * (a + 1)); continue
                r.raise_for_status()
                j = r.json()
                text = j["choices"][0]["message"]["content"]
                return LLMResult(text=text, usage=j.get("usage", {}), model=self.model)
            except requests.RequestException as e:     # 타임아웃/커넥션 오류
                last = e
                time.sleep(2 * (a + 1))
        raise last if last else RuntimeError("LLM 호출 실패(원인 미상)")
