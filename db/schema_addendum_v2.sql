-- =====================================================================
-- 서빙 레이어(services/) 스키마 확장분 — mineral_supply_risk/db/schema_core.sql은
-- 불변, 이 파일을 이어서 적용한다(원본 훼손 없음, CLAUDE.md §4 "최소·외과적 변경").
-- 설계 단계 초안(docs/CONTAINER_ARCHITECTURE.md §4) — 구현 시점에 실제 대상 DB
-- (Postgres 등) 방언에 맞춰 검증 후 적용할 것. 아직 어떤 DB에도 실행되지 않았음.
--
-- 2026-08-05 정정: 벡터 컬럼(doc_chunk.embedding VECTOR)은 폐기 — 벡터DB는 Qdrant로
-- 확정(docs/CONTAINER_ARCHITECTURE.md §4·§7). 이 파일엔 벡터를 두지 않는다.
-- =====================================================================

-- 챗봇 세션·히스토리(신규 — user_id/session_id 요구사항)
CREATE TABLE IF NOT EXISTS chat_session (
  session_id  VARCHAR(36) NOT NULL,
  user_id     VARCHAR(80) NOT NULL,
  title       VARCHAR(200),
  created_at  TIMESTAMP,
  updated_at  TIMESTAMP,
  PRIMARY KEY (session_id)
);

CREATE TABLE IF NOT EXISTS chat_message (
  message_id      VARCHAR(36) NOT NULL,
  session_id      VARCHAR(36) NOT NULL,
  role            VARCHAR(16),          -- user/assistant/system
  content         TEXT,
  citations_json  VARCHAR(4000),        -- 인용 청크 id 등(비정형+정형 출처 둘 다)
  created_at      TIMESTAMP,
  PRIMARY KEY (message_id)
);

-- out_report.body 확장: schema_core.sql 원본은 VARCHAR(8000)이라 실제 보고서 본문엔
-- 부족 — TEXT로 확장(Oracle: CLOB / MSSQL: NVARCHAR(MAX) / DuckDB·Postgres·MariaDB: TEXT)
ALTER TABLE out_report ALTER COLUMN body TYPE TEXT;

-- doc_chunk 확장: 벡터는 여기 없음(Qdrant가 별도 소유) — chunk_id가 Qdrant 포인트 ID와
-- 동일 값을 쓰는 조인 키. 여기선 메타+BM25용 tsvector만 둔다.
ALTER TABLE doc_chunk ADD COLUMN source_type VARCHAR(16);       -- 'unstructured'|'structured'
ALTER TABLE doc_chunk ADD COLUMN structured_query TEXT;         -- source_type='structured'일 때
                                                                  -- 원 SQL/근거 쿼리 보존(감사용)

-- BM25 절반(현재 rag/ragkit이 DuckDB FTS로 하던 것)의 Postgres 대응.
-- 'simple'은 형태소 분석 없는 단순 토큰화 — 한국어 전용 tsvector 설정이 기본 제공되지
-- 않는다. rag/ragkit/tokenize_ko.py의 한글 bigram 전처리를 txt에 미리 적용해 저장할지,
-- pg 한국어 확장(예: mecab 연동) 설치를 요청할지는 구현 단계 결정 필요.
-- ⚠ DuckDB 개발환경에는 GENERATED ALWAYS AS ... STORED 문법이 없어 별도 분기 필요
-- (개발 중엔 이 두 statement를 스킵하고 애플리케이션 레벨에서 BM25 처리하거나,
-- DuckDB FTS 확장을 그대로 유지하는 방안 검토).
ALTER TABLE doc_chunk ADD COLUMN txt_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', txt)) STORED;
CREATE INDEX IF NOT EXISTS idx_doc_chunk_tsv ON doc_chunk USING GIN (txt_tsv);
