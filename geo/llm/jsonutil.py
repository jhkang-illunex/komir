# -*- coding: utf-8 -*-
"""LLM 출력 JSON 복구·검증 (로컬모델 방어)."""
import json, re


_TRAILING_COMMA = re.compile(r",\s*([\]}])")


def _try_loads(frag: str):
    """순정 → 트레일링콤마 제거 → (배열 한정) 절단 복구 순으로 시도."""
    for cand in (frag, _TRAILING_COMMA.sub(r"\1", frag)):
        try:
            return json.loads(cand)
        except Exception:
            pass
    # max_tokens 절단 복구: 마지막 완결 객체까지 자르고 배열 닫기
    if frag.lstrip().startswith("["):
        k = frag.rfind("}")
        if k != -1:
            cand = _TRAILING_COMMA.sub(r"\1", frag[:k + 1]) + "]"
            try:
                return json.loads(cand)
            except Exception:
                pass
    return None


def repair_json(text: str):
    """텍스트에서 JSON 배열/객체를 최대한 복구(펜스·군더더기·절단 방어)."""
    if not text:
        return None
    # 코드펜스 제거(```json / ```JSON / ``` 모두)
    text = re.sub(r"```\s*(json)?", "", text, flags=re.IGNORECASE).strip()
    # 첫 배열/객체 스팬 추출
    for op, cl in (("[", "]"), ("{", "}")):
        i, j = text.find(op), text.rfind(cl)
        if i != -1 and j != -1 and j > i:
            r = _try_loads(text[i:j + 1])
            if r is not None:
                return r
        elif i != -1:                       # 여는 괄호만 있음(닫힘 절단)
            r = _try_loads(text[i:])
            if r is not None:
                return r
    return _try_loads(text)


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
