# -*- coding: utf-8 -*-
"""LLM 출력 JSON 복구·검증 (로컬모델 방어)."""
import json, re


def repair_json(text: str):
    """텍스트에서 JSON 배열/객체를 최대한 복구."""
    if not text:
        return None
    # 코드펜스 제거
    text = re.sub(r"```(json)?", "", text).strip()
    # 첫 배열/객체 스팬 추출
    for op, cl in (("[", "]"), ("{", "}")):
        i, j = text.find(op), text.rfind(cl)
        if i != -1 and j != -1 and j > i:
            frag = text[i:j+1]
            try:
                return json.loads(frag)
            except Exception:
                pass
    try:
        return json.loads(text)
    except Exception:
        return None


def as_event_list(parsed):
    """dict/list 어떤 형태로 오든 이벤트 dict 리스트로 정규화."""
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        for k in ("events", "results", "data", "items"):
            if isinstance(parsed.get(k), list):
                return parsed[k]
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    return []
