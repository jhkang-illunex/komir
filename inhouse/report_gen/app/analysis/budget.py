# -*- coding: utf-8 -*-
"""분석요약 8종의 시간 예산 상수 — 2026-08-27 신설.

`routers/_common.py`(요청당 예산·lock 인수 판단)와 `analysis/summary.py`
(`_refine_with_llm`이 LLM 호출 전 남은 예산 확인, Pass 3 R3-F1)가 같은 값을 써야
하는데, summary.py가 routers를 import하면 계층이 뒤집히므로 analysis 쪽에 둔다.

- `REQUEST_BUDGET_SECONDS`: 클라이언트 계약 "요청당 20초 초과 금지".
- `ANALYSIS_LLM_TIMEOUT_SECONDS`/`ANALYSIS_LLM_RETRIES`: report_gen용 `KomirJsonLLM`
  cfg. 실 vLLM(gemma-4-26b-a4b) 정제 1회 지연 실측 3.6~6.5s, 콜드 호출 12.6s —
  12s는 "호출 1회의 상한"이지 "요청 전체가 20초 안에 끝난다"는 뜻이 아니다.
  요청 전체는 `_refine_with_llm`이 매 호출 전에 `deadline - now < timeout`이면
  LLM을 건너뛰고 규칙기반으로 돌아가는 것으로 예산을 지킨다(R3-F1: 이전엔
  정제 2루프 × repair 2회 = 최대 48s가 lock을 쥘 수 있었다).
"""
from __future__ import annotations

REQUEST_BUDGET_SECONDS = 20
ANALYSIS_LLM_TIMEOUT_SECONDS = 12
ANALYSIS_LLM_RETRIES = 1

__all__ = ["ANALYSIS_LLM_RETRIES", "ANALYSIS_LLM_TIMEOUT_SECONDS", "REQUEST_BUDGET_SECONDS"]
