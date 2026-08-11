# -*- coding: utf-8 -*-
"""서빙 레이어 공통 설정 로더 — deploy/.env.example 계약(§3) 그대로 읽는다.

기존 geo/mineral_supply_risk .env 컨벤션과 이름을 그대로 쓴다(docs/
CONTAINER_ARCHITECTURE.md §3, 새 접두사 만들지 않는다는 원칙). `PG_*`는
2026-08-10 postgres 이관 작업에서 이미 `inhouse/.env`에 실존 — 이 Settings가
그 값을 읽는 첫 소비자다(주의: `PG_DSN`이 가리키는 `public` 스키마는 타 팀 소유,
komir 쪽 코드는 `PG_SCHEMA`(mineral_risk)로만 스키마를 한정해 조회할 것 —
services/shared/db.py 참고).

2026-08-11: 병합계획(documents/산출물/2026-W33_0810-0816/
병합계획_komis-report-generator_260811.md) 결정②에 따라 search/config.py·
vector_index/config.py(외부 repo, `LLM_TIMEOUT_SECONDS`/`KOMIS_EMBEDDING_*` 등
별도 이름 체계)를 그대로 들여오지 않고, 이 파일 하나로 흡수했다 — 두 개의 설정
로더가 같은 프로젝트에 공존하는 걸 피하기 위함(TWIN 방지)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """서비스 3종(commodity_api·rag_chat·report_gen) 공통 설정."""

    model_config = SettingsConfigDict(
        env_file=str(_INHOUSE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 정형 DB(현재 DuckDB, PG_* 이관 진행 중 — MSR_DB가 정본, cutover 전) ──
    MSR_DB: str = str(_INHOUSE_ROOT / "data_lake/db/minerals.duckdb")
    MSR_PUBLISH_SCHEMA: str = ""

    # ── PostgreSQL(komis_demo, 2026-08-10) — mineral_risk 스키마만 사용,
    #    public(ko_*·ai_*)은 타 팀 소유라 이 프로젝트 코드가 건드리지 않는다 ──
    PG_DSN: str = ""
    PG_SCHEMA: str = "mineral_risk"

    # ── LLM(chat, geo/llm/openai_compat.py가 이미 쓰는 규약 그대로) ──
    LLM_PROVIDER: str = "openai_compat"
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "qwen2.5:32b"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.0
    LLM_CONCURRENCY: int = 8
    LLM_TIMEOUT_SECONDS: float = 120.0

    # ── 임베딩(dense, rag/ragkit/embed.py가 실제로 쓰는 값 — 로컬 sentence-
    #    transformers 직접 로드라 EMBEDDING_BASE_URL은 현재 코드 경로에서는 안
    #    쓰이지만(§5 실사 기록), Settings 계약 자체는 유지) ──
    EMBEDDING_BASE_URL: str = ""
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"

    # ── 벡터DB(Qdrant, komir 직접 소유·기동) ──
    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_COLLECTION: str = "doc_chunks"

    # ── 챗봇 서비스 ──
    CHAT_SESSION_TTL_DAYS: int = 90
    CHAT_STREAM_CHUNK_MS: int = 50

    # 페이지추천(rag_chat/app/page_recommend, 2026-08-11 이식) — 상대기간("최근 5년")을
    # 해석할 기준 현재시각의 지역. 외부 repo의 KOMIS_TIMEZONE을 이름 그대로 흡수했다.
    # 같은 파일의 KOMIS_SEARCH_STATE_DB는 흡수하지 않았다 — 대화상태를 SQLite가 아니라
    # 기존 chat_session/chat_message에 두므로 가리킬 파일 자체가 없다.
    KOMIS_TIMEZONE: str = "Asia/Seoul"

    # ── 리포트 스케줄러 ──
    REPORT_SCHEDULE_CRON: str = "0 6 * * MON"
    REPORT_TEMPLATE_DIR: str = str(_INHOUSE_ROOT / "services/report_gen/app/templates")

    def llm_cfg(self) -> dict:
        """geo/llm/openai_compat.OpenAICompatChat이 받는 cfg dict로 변환."""

        return {
            "provider": self.LLM_PROVIDER,
            "base_url": self.LLM_BASE_URL,
            "model": self.LLM_MODEL,
            "api_key": self.LLM_API_KEY,
            "temperature": self.LLM_TEMPERATURE,
            "timeout": int(self.LLM_TIMEOUT_SECONDS),
            "concurrency": self.LLM_CONCURRENCY,
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    """프로세스당 1회만 로드(캐시) — env 변경은 재시작으로 반영."""

    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
