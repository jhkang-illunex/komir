# -*- coding: utf-8 -*-
"""DuckDB FTS(영문 위주 whitespace 토크나이저)는 한국어 교착어 특성상 그대로 쓰면
BM25가 사실상 안 걸린다(예: "AUC" 쿼리가 "AUC는"에 매칭 안 됨, 조사가 붙어 토큰이
매번 달라짐). 형태소 분석기(kiwipiepy 등) 신규 설치 없이도 충분히 쓸만한 절충:
- 영문/숫자/식별자(코드명·버전 등)는 그대로 토큰 유지 → 정확 매칭.
- 한글 구간은 글자 단위 바이그램(overlapping 2-gram)으로 풀어써서, 조사가 붙어도
  어간 바이그램 다수가 겹치도록 함(BM25 TF가 그 겹침을 점수로 반영).
색인 시점과 질의 시점에 동일 함수를 적용해야 함.
"""
from __future__ import annotations

import re

_ASCII_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")
_HANGUL_RUN = re.compile(r"[가-힣]+")


def to_fts_text(text: str) -> str:
    tokens: list[str] = []
    tokens.extend(m.group(0) for m in _ASCII_TOKEN.finditer(text))
    for run in _HANGUL_RUN.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return " ".join(tokens)


if __name__ == "__main__":
    print(to_fts_text("핵심광물 수급위기 진단모델의 AUC는 0.977이다"))
    print(to_fts_text("ph_psa 이웃 강건성 QWK CI 하한>0"))
