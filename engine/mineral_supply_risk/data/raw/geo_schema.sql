-- =====================================================================
-- 지정학 리스크 파이프라인 스키마 (변수⑥ 소스)
--   doc_raw     : 보고서 원본(문건별 발행일+원문+섹션) — 수집 계층
--   geo_event   : LLM/규칙 추출 이벤트(국가·광종·위험도) — 분석 계층
--   fact_geopolitical_weekly : 주간 집계 뷰 -> mart_weekly_diagnosis 변수⑥
-- 타입은 보수적(이식 용이). DuckDB: JSON 네이티브, BLOB는 원본 아카이브용.
-- =====================================================================

-- ---------- 원본(수집) ----------
CREATE TABLE IF NOT EXISTS doc_raw (
    doc_id        VARCHAR PRIMARY KEY,   -- file_hash 기반
    source        VARCHAR,               -- 'AsianMetal','Argus','IEA','WoodMac','KOMIS'
    commodity_hint VARCHAR,              -- 문서 단위 광종 힌트(LI 등), 다광종이면 NULL
    pub_date      DATE,                  -- 발행일(시계열 앵커, 누수방지)
    received_at   TIMESTAMP,             -- 수집 시각
    fmt           VARCHAR,               -- 'pdf','hwp(->pdf)'
    file_name     VARCHAR,
    file_path     VARCHAR,
    file_hash     VARCHAR UNIQUE,        -- 중복 적재 방지
    raw_text      VARCHAR,               -- 추출 원문(컬럼 인식)
    sections      JSON,                  -- [{seq,type,text}] 섹션 태깅 결과
    n_sections    INTEGER,
    status        VARCHAR,               -- received|parsed|analyzed|failed
    error_msg     VARCHAR
    -- raw_blob   BLOB                   -- (선택) 원본 바이트 아카이브
);

-- ---------- 분석(이벤트) ----------
CREATE TABLE IF NOT EXISTS geo_event (
    event_id      VARCHAR PRIMARY KEY,
    doc_id        VARCHAR,               -- FK -> doc_raw
    section_seq   INTEGER,
    obs_date      DATE,                  -- 보고서 발행일 기준
    country       VARCHAR,               -- 지정학 대상국
    commodity_code VARCHAR,              -- 광종(CU/NI/LI/CO/REE)
    event_type    VARCHAR,               -- export_restriction|tariff|sanction|...
    severity      DOUBLE,                -- 0~1 위험 정도
    direction     VARCHAR,               -- negative|positive|neutral
    confidence    DOUBLE,                -- 0~1 추출 신뢰도
    evidence_quote VARCHAR,              -- 근거 인용문(추적성)
    extractor     VARCHAR,               -- 'baseline'|'llm'
    model_version VARCHAR,               -- 모델/프롬프트 버전(재현성)
    analyzed_at   TIMESTAMP
);

-- ---------- 주간 집계(뷰) : 광종×주 지정학 인덱스 ----------
CREATE OR REPLACE VIEW fact_geopolitical_weekly AS
SELECT
    commodity_code,
    date_trunc('week', obs_date) AS week,
    COUNT(*)                       AS n_events,
    SUM(severity*confidence)       AS geo_pressure,   -- 가중 위험합
    MAX(severity)                  AS geo_max_severity,
    AVG(severity)                  AS geo_avg_severity
FROM geo_event
WHERE commodity_code IS NOT NULL AND extractor='llm'  -- 운영: LLM 추출 기준(baseline은 비교보존)
GROUP BY 1,2;
