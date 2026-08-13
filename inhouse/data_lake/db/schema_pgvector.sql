-- =====================================================================
-- doc_chunk pgvector 확장 (2026-08-11) — komis_demo(PostgreSQL 16) 전용.
--
-- 배경: CONTAINER_ARCHITECTURE.md §4는 "벡터는 Qdrant, doc_chunk엔 두지 않는다"
-- (2026-08-05 결정)였으나, 2026-08-11 사용자가 결정을 바꿨다 — komis_demo에
-- pgvector 0.8.2가 이미 설치돼 있고 접속 계정도 슈퍼유저임이 실측 확인돼
-- (`pg_extension`), 8/5에 pgvector를 폐기한 유일한 사유("확장 설치 권한 보장
-- 없음")가 사라졌다. Qdrant 컨테이너를 새로 띄우지 않고 이미 붙어 있는
-- Postgres에 벡터 컬럼을 얹는다(§0 표 갱신됨).
--
-- 적용 대상 스키마는 mineral_risk 뿐이다. public(ko_*·ai_*)은 타 팀 소유라
-- 이 파일은 절대 건드리지 않는다 — 모든 문장을 mineral_risk.로 명시 한정한다
-- (PG_DSN의 기본 search_path가 "$user",public이라 미한정 DDL은 public에 떨어짐).
-- search_path 자체는 건드리지 않는다 — vector 타입이 public에 설치돼 있어
-- search_path에서 public을 빼면 `vector(384)` 해석이 깨진다.
--
-- 범위(의도적 부분 적용): §4 addendum 중 **dense 벡터 절반만** 여기서 적용한다.
-- `structured_query`·`txt_tsv`(GIN, BM25 절반)는 이번 작업 범위 밖 —
-- BM25는 당분간 rag/index/rag.duckdb의 DuckDB FTS를 그대로 쓴다(§5-4 이관은
-- 후속 사이클). addendum이 통째로 적용된 것으로 오해하지 말 것.
--
-- 원본 DDL(mineral_supply_risk/db/schema_core.sql)은 건드리지 않는다
-- (CLAUDE.md §4 "최소·외과적 변경"). schema_core의 doc_chunk는 이식 대상
-- 포터블 DDL이고 vector 타입은 Postgres 전용이라, 방언 종속 컬럼을 원본에
-- 섞지 않고 이 파일로 분리했다.
--
-- 적용:  cd inhouse && python -m rag.ragkit.build_pgvector_index --schema-only
--   (또는 services/shared/db.apply_schema_pg("data_lake/db/schema_pgvector.sql"))
-- 멱등: 재실행해도 안전(ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
-- ⚠ CREATE EXTENSION vector는 일부러 넣지 않았다 — 이미 설치돼 있고, 확장
--   상태를 마이그레이션이 건드릴 이유가 없다.
-- =====================================================================

CREATE TABLE IF NOT EXISTS mineral_risk.doc_chunk (
  chunk_id VARCHAR(32) NOT NULL,
  doc_id VARCHAR(32),
  commodity_code VARCHAR(8),
  src VARCHAR(40),
  pub_date DATE,
  seq INTEGER,
  txt TEXT
);

-- 검색 결과에 그대로 실어 보낼 인용 메타(rag/ragkit의 DocRecord·ChunkRecord 필드).
-- 별도 doc 테이블을 두지 않고 비정규화한다 — 코퍼스가 작고(문서<100) 조회 경로가
-- "청크 top-k + 출처 표시" 하나뿐이라 조인을 만들 이유가 없다.
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS source_path TEXT;
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS week VARCHAR(80);
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS section_heading TEXT;
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS char_len INTEGER;
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS source_type VARCHAR(16);
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMP;

-- dense 임베딩: intfloat/multilingual-e5-small 384차원, normalize_embeddings=True
-- (rag/ragkit/embed.py) — 정규화 벡터라 코사인이 맞다.
ALTER TABLE mineral_risk.doc_chunk ADD COLUMN IF NOT EXISTS embedding vector(384);

-- PK 대신 UNIQUE INDEX: PostgreSQL엔 ADD CONSTRAINT IF NOT EXISTS가 없어
-- ADD PRIMARY KEY는 재실행 시 실패한다(멱등 불가). UNIQUE 인덱스면
-- ON CONFLICT (chunk_id) 대상으로도 동일하게 쓸 수 있다.
CREATE UNIQUE INDEX IF NOT EXISTS doc_chunk_chunk_id_uq
  ON mineral_risk.doc_chunk (chunk_id);

-- HNSW(코사인). IVFFlat이 아니라 HNSW인 이유: IVFFlat은 리스트 학습에 사전 데이터가
-- 필요해 빈 테이블에 못 걸고 재적재 때마다 재구축이 필요한 반면, HNSW는 증분이고
-- 이 규모(청크 수천)에선 빌드 비용이 무시할 만하다.
CREATE INDEX IF NOT EXISTS idx_doc_chunk_embedding_hnsw
  ON mineral_risk.doc_chunk USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_doc_chunk_doc_id ON mineral_risk.doc_chunk (doc_id);
