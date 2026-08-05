# -*- coding: utf-8 -*-
"""서빙 레이어 공통 설정 로더 — deploy/.env.example 계약(§3) 그대로 읽는다.

TODO(구현 단계): pydantic-settings BaseSettings로 아래 필드를 읽는 Settings 클래스 구현.
    MSR_DB, MSR_PUBLISH_SCHEMA
    LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY, LLM_TEMPERATURE
    EMBEDDING_BASE_URL, EMBEDDING_MODEL
    CHAT_SESSION_TTL_DAYS, CHAT_STREAM_CHUNK_MS
    REPORT_SCHEDULE_CRON, REPORT_TEMPLATE_DIR
새 접두사 만들지 말 것 — 기존 geo/mineral_supply_risk .env 컨벤션과 이름 일치시킬 것
(docs/CONTAINER_ARCHITECTURE.md §3).
"""
raise NotImplementedError("설계 단계 스켈레톤 — 구현은 다음 세션(docs/CONTAINER_ARCHITECTURE.md §8)")
