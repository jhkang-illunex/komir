-- =====================================================================
-- ingest 스키마 — 파이프라인 실행상태·파일별 처리현황 (2026-08-27, komis_demo 전용).
--
-- 배경: `inhouse/ingest/`(파일 기반 보고서 정제→OKF→PageIndex→pgvector) 파이프라인이
-- 지금까지 상태를 어디에도 남기지 않아, 언제 뭐가 얼마나 처리됐는지 알 방법이 없었다.
-- streamlit 쪽(별도 세션)이 이 스키마를 직접 읽어 상태탭을 그릴 예정이라, 이 파일이
-- 그 화면의 데이터 계약이다.
--
-- `public`(타 팀 소유)·`mineral_risk`(진단/예측/RAG 정형)·`ai_cfg`(AI 설정값) 3스키마와
-- 별개인 4번째 스키마다 — 파이프라인 운영 로그는 "설정값"도 "모델 결과"도 아니라
-- 성격이 달라 별도로 분리했다(ai_cfg에 섞지 않음, 사용자 확인 완료).
--
-- 적용: `ingest.status.ensure_schema()`가 프로세스당 1회 자동 호출(모든 문장이
-- IF NOT EXISTS라 재실행 안전) — 별도 마이그레이션 스텝 불필요.
--   (또는 수동: services/shared/db.apply_schema_pg("ingest/db/schema_ingest.sql"))
--
-- 대상 스키마는 ingest 뿐이다. public·mineral_risk·ai_cfg는 이 파일이 절대 건드리지
-- 않는다 — 모든 문장을 ingest.으로 명시 한정한다(PG_DSN의 기본 search_path가
-- "$user",public이라 미한정 DDL은 public에 떨어진다 — schema_pgvector.sql의 같은 함정).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS ingest;

-- 잡 실행 1건 = 1행. job_name은 "<stage>.<module>"(예: 'okf.build_okf_documents').
CREATE TABLE IF NOT EXISTS ingest.pipeline_run (
  run_id       BIGSERIAL PRIMARY KEY,
  -- 'okf.build_okf_documents' 같은 모듈 경로
  job_name     VARCHAR(80)  NOT NULL,
  -- 'extract'|'okf'|'pageindex'|'vectorize'
  stage        VARCHAR(20)  NOT NULL,
  -- 'cron'|'manual'
  trigger      VARCHAR(10)  NOT NULL,
  -- 'running'|'success'|'failed'
  status       VARCHAR(10)  NOT NULL DEFAULT 'running',
  started_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  -- 주기 갱신 — 값이 오래됐는데 status='running'이면 hung으로 간주(자가치유 대상)
  heartbeat_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  -- CLI 인자(예: {"what": "usgs", "force": true})
  args         JSONB,
  -- 잡별 자유 카운터(예: {"written": 42, "skipped": 3})
  metrics      JSONB,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS ix_pipeline_run_job_started
  ON ingest.pipeline_run (job_name, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_pipeline_run_status
  ON ingest.pipeline_run (status) WHERE status = 'running';

-- 상태 탭이 바로 긁을 "잡별 최근 실행" 뷰.
CREATE OR REPLACE VIEW ingest.pipeline_run_latest AS
SELECT DISTINCT ON (job_name) *
FROM ingest.pipeline_run
ORDER BY job_name, started_at DESC;

-- 원본 파일 1건 = 1행. file_id는 코드 전반이 이미 doc_id로 쓰는 값(대개
-- md5 hex 16자 절단) 그대로 재사용 — okf/pageindex/vectorize 3단계는 같은 계보라
-- 자연스럽게 조인되고, extract 단계(콘텐츠 md5)는 별도 원장이다.
CREATE TABLE IF NOT EXISTS ingest.source_file (
  file_id        VARCHAR(32)  PRIMARY KEY,
  file_name      VARCHAR(255) NOT NULL,
  -- 'pdf'|'hwp'|'xlsx'|'docx'|'md'|'xls'
  file_ext       VARCHAR(10)  NOT NULL,
  -- 저장소 기준 상대경로
  source_path    TEXT         NOT NULL,
  -- 발행처/보고서종류: '조달청보고서'|'생산매장량_USGS'|'Argus_비철금속_일일'
  --   |'산출물'|'외부자료' 등
  source_group   VARCHAR(80),
  -- CU|NI|CO|LI|REE
  commodity_hint VARCHAR(4),
  -- 발행일(파싱 가능한 것만)
  doc_date       DATE,
  first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_source_file_group
  ON ingest.source_file (source_group, file_ext);

-- (파일, 단계) 조합 1건 = 1행 — 재처리 시 upsert만 하면 파일당 최대 4행으로 항상
-- 최신 단계별 현황을 유지한다.
CREATE TABLE IF NOT EXISTS ingest.file_stage_status (
  file_id       VARCHAR(32)  NOT NULL REFERENCES ingest.source_file(file_id),
  -- 'extract'|'okf'|'pageindex'|'vectorize'
  stage         VARCHAR(20)  NOT NULL,
  -- 단계별 자체 값: extract='extracted'|'ocr_required'|'parse_failed',
  --   okf/pageindex='success'|'skipped'|'failed', vectorize='success'|'failed'
  status        VARCHAR(20)  NOT NULL,
  run_id        BIGINT REFERENCES ingest.pipeline_run(run_id),
  -- 추출 텍스트 길이(품질 신호)
  n_chars       INTEGER,
  -- vectorize 단계 전용 — 이 파일이 쪼개진 청크 수
  chunk_count   INTEGER,
  error_message TEXT,
  processed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (file_id, stage)
);

CREATE INDEX IF NOT EXISTS ix_file_stage_status_stage
  ON ingest.file_stage_status (stage, status);
