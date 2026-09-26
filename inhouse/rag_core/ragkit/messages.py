"""챗봇 사용자 노출 문구 리소스."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_RESOURCE_PATH = Path(__file__).with_name("resources") / "messages.yml"


@lru_cache(maxsize=1)
def _messages() -> dict:
    data = yaml.safe_load(_RESOURCE_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid chat message resource: {_RESOURCE_PATH}")
    return data


def chat_message(key: str) -> str:
    value = _messages().get("chat", {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"missing chat message key: {key}")
    return value


def faq_message(key: str) -> str:
    """수정 가능한 FAQ 원문 resource를 반환한다."""
    value = _messages().get("faq", {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise KeyError(f"missing FAQ message key: {key}")
    return value
