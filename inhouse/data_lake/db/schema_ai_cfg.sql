-- =====================================================================
-- ai_cfg 스키마 — komir가 관리하는 AI 설정성 테이블 전용(2026-08-26,
-- PostgreSQL 전용, PG_DSN 대상 — services/shared/db.apply_schema_pg로 적용).
--
-- public(ko_*·ai_mnrl_mst 등)은 타 팀 소유라 건드리지 않는다(data_lake/db/
-- schema_pgvector.sql·services/shared/komis_raw.py와 동일 원칙 — 사용자가
-- 처음 "public 밑에 ai_cfg_prompt로"라고 요청했다가, 이 원칙을 확인시켜주자
-- "ai_cfg 스키마를 새로 만들고 그 안에 cfg_prompt를 두자"로 정정했다,
-- 2026-08-26). mineral_risk는 이미 두 용도(MSR_DB의 fact_*/out_*/mart_*,
-- PG_DSN의 doc_chunk/pgvector)로 쓰이고 있어 프롬프트 같은 설정성 테이블까지
-- 섞지 않고 전용 스키마를 새로 둔다.
--
-- 적용: cd inhouse/services/report_gen && python -m app.analysis.seed_prompts
--   (내부적으로 apply_schema_pg("data_lake/db/schema_ai_cfg.sql") 호출)
-- 멱등: 재실행해도 안전(CREATE ... IF NOT EXISTS).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS ai_cfg;

-- 분석요약 LLM 프롬프트(report_gen/app/analysis/prompt_store.py가 런타임에
-- 읽는 테이블). prompt_key: 'summary_common'(공통 서두) 또는
-- AnalysisSummaryRequest.page_id 값(indicator_market/indicator_supply/
-- indicator_composite/map_mineral/forecast_price) — LLM 정제를 쓰지 않는
-- price/map_korea/map_global은 대상이 아니다(§report_gen/app/analysis/
-- summary.py).
CREATE TABLE IF NOT EXISTS ai_cfg.cfg_prompt (
  prompt_key  VARCHAR(40) NOT NULL,
  content     TEXT NOT NULL,
  description VARCHAR(200),
  updated_at  TIMESTAMP,
  PRIMARY KEY (prompt_key)
);
