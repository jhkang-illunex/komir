# -*- coding: utf-8 -*-
"""서빙 레이어 공통 LLM 클라이언트.

TODO(구현 단계): geo/llm/openai_compat.py(provider 무관 어댑터, rag/ragkit/generate.py가
이미 재사용 중)를 그대로 재노출한다 — 신규 LLM 클라이언트 재구현 금지.
임베딩은 별도(EMBEDDING_* env, 로컬 e5-small 기본) — LLM 서버와 분리된 축.
"""
raise NotImplementedError("설계 단계 스켈레톤 — 구현은 다음 세션(docs/CONTAINER_ARCHITECTURE.md §8)")
