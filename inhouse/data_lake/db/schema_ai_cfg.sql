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
-- AnalysisSummaryRequest.page_id 값 — 2026-09-02 기준 seed_prompts.py가
-- `prompts.py::PROMPTS`의 13개 키(summary_common + indicator_market/
-- indicator_supply/indicator_composite/map_mineral/forecast_price/
-- price_base_metals/price_minor_metals/price_iron_energy/price_other/
-- price_group/map_korea/map_global)를 전부 심는다 — LLM 정제를 안 쓰던
-- price/map_korea/map_global 제외는 260827 이후 없어졌다(옛 주석은
-- 5개 page_id 시절 기준이라 갱신, 실제 시딩 대상은 `python -m app.analysis.
-- seed_prompts` 실행 로그 또는 `prompts.py::PROMPTS`가 정본).
CREATE TABLE IF NOT EXISTS ai_cfg.cfg_prompt (
  prompt_key  VARCHAR(40) NOT NULL,
  content     TEXT NOT NULL,
  description VARCHAR(200),
  updated_at  TIMESTAMP,
  PRIMARY KEY (prompt_key)
);

-- 2026-08-27 프롬프트 DB화 2단계: 지시문 본문(content) 외에 페이지 정책
-- (이름·정의·작성 제약·정책버전)과 출력 계약(섹션별 문장수 범위)도 DB에서
-- 통제한다 — 이전엔 YAML(indicator_market/supply)·Python dataclass(나머지 7종)·
-- prompts.py 상수(문장수 범위)에 흩어져 있던 ~15%. 컬럼은 ADD COLUMN IF NOT
-- EXISTS라 재실행 안전하고, report_gen의 prompt_store.reload()가 기동·리로드
-- 시 information_schema로 누락 컬럼을 감지하면 이 파일을 자동 적용한다.
-- summary_common 행(공통 서두)은 페이지가 아니라 아래 컬럼이 전부 NULL이다.
-- NULL인 컬럼은 "코드 기본값을 쓴다"는 뜻이다(값 단위 폴백).
ALTER TABLE ai_cfg.cfg_prompt ADD COLUMN IF NOT EXISTS page_name            VARCHAR(80);
ALTER TABLE ai_cfg.cfg_prompt ADD COLUMN IF NOT EXISTS page_definition      TEXT;
ALTER TABLE ai_cfg.cfg_prompt ADD COLUMN IF NOT EXISTS analysis_constraints JSONB;
ALTER TABLE ai_cfg.cfg_prompt ADD COLUMN IF NOT EXISTS policy_version       VARCHAR(60);
ALTER TABLE ai_cfg.cfg_prompt ADD COLUMN IF NOT EXISTS output_contract      JSONB;

-- 2026-09-02 skeptic 2차 감사 PA-002: `ON CONFLICT DO UPDATE`(위 upsert)는
-- 전 컬럼을 코드 기본값으로 무조건 덮어써서, 운영자가 prompt_admin UI로
-- 편집해 둔 행도 재시드 한 번이면 조용히 사라진다 — 배포 절차가 재시드를
-- 의무화하고 있어(2회 실사고로 규칙화) 실제 위험이 크다. 최소 대응으로
-- `seed_prompts.py`가 upsert 직전 현재 cfg_prompt 전체를 여기 백업한다
-- (append-only, id 자동증가라 실행마다 새 스냅샷이 쌓임 — 필요시 UI 경고·
-- 복원 기능은 후속 과제).
CREATE TABLE IF NOT EXISTS ai_cfg.cfg_prompt_backup (
  id                    BIGSERIAL PRIMARY KEY,
  backup_at             TIMESTAMP NOT NULL,
  prompt_key            VARCHAR(40) NOT NULL,
  content               TEXT NOT NULL,
  description           VARCHAR(200),
  updated_at            TIMESTAMP,
  page_name             VARCHAR(80),
  page_definition       TEXT,
  analysis_constraints  JSONB,
  policy_version        VARCHAR(60),
  output_contract       JSONB
);
