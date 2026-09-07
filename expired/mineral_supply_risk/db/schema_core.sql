-- =====================================================================
-- 핵심광물 수급위기 시스템 · 코어 스키마 (portable DDL)
-- 대상: DuckDB(개발) → Oracle / MariaDB / MS-SQL(운영) 이관용.
-- 타입은 ANSI 근사. 이관 시 방언 치환:
--   VARCHAR(n)  → Oracle: VARCHAR2(n) / MSSQL: NVARCHAR(n)
--   TIMESTAMP   → MSSQL: DATETIME2 / (Oracle·MariaDB: 그대로)
--   BOOLEAN     → Oracle: NUMBER(1) / MSSQL: BIT / MariaDB: TINYINT(1)
--   DECIMAL(p,s)→ Oracle: NUMBER(p,s) (그 외 그대로)
--   "IF NOT EXISTS"는 DuckDB/MariaDB 전용. Oracle/MSSQL은 제거 후 존재검사로 감쌀 것.
-- 예약어 회피 위해 컬럼명은 yr, mon, val, src, period 등 사용.
-- =====================================================================

-- ---------- 차원 ----------
CREATE TABLE IF NOT EXISTS dim_hs_commodity (
  hs10            VARCHAR(10)  NOT NULL,
  commodity_code  VARCHAR(8),         -- CU/NI/LI/CO/REE
  commodity_ko    VARCHAR(40),
  is_core5        BOOLEAN,
  PRIMARY KEY (hs10)
);

-- ---------- 정형 팩트 ----------
-- 관세청 연간(품목·국가) : getNitemtradeList 연 집계
CREATE TABLE IF NOT EXISTS fact_trade_annual (
  yr    INTEGER NOT NULL, hs10 VARCHAR(10) NOT NULL, commodity_code VARCHAR(8),
  country VARCHAR(80) NOT NULL,
  imp_usd DECIMAL(20,3), imp_wgt DECIMAL(20,3), exp_usd DECIMAL(20,3), exp_wgt DECIMAL(20,3),
  src VARCHAR(40), loaded_at TIMESTAMP,
  PRIMARY KEY (yr, hs10, country)
);
-- 관세청 월간(품목·국가) : strtYymm=endYymm 월별 콜
CREATE TABLE IF NOT EXISTS fact_trade_monthly (
  yr INTEGER NOT NULL, mon INTEGER NOT NULL, hs10 VARCHAR(10) NOT NULL,
  commodity_code VARCHAR(8), country VARCHAR(80) NOT NULL,
  imp_usd DECIMAL(20,3), imp_wgt DECIMAL(20,3), exp_usd DECIMAL(20,3), exp_wgt DECIMAL(20,3),
  src VARCHAR(40), loaded_at TIMESTAMP,
  PRIMARY KEY (yr, mon, hs10, country)
);
-- 가격(LME 등, 주간/월간)
CREATE TABLE IF NOT EXISTS fact_price (
  commodity_code VARCHAR(8) NOT NULL, price_type VARCHAR(30) NOT NULL,  -- cash/3m/기준가 등
  freq VARCHAR(1) NOT NULL,           -- D/W/M
  obs_date DATE NOT NULL, val DECIMAL(20,4), unit VARCHAR(20), src VARCHAR(40),
  PRIMARY KEY (commodity_code, price_type, obs_date)
);
-- 재고(LME 주간)
CREATE TABLE IF NOT EXISTS fact_inventory (
  commodity_code VARCHAR(8) NOT NULL, obs_date DATE NOT NULL,
  val DECIMAL(20,3), unit VARCHAR(20), src VARCHAR(40),
  PRIMARY KEY (commodity_code, obs_date)
);
-- KOMIS 수급/시장 지표(월)
CREATE TABLE IF NOT EXISTS fact_indicator (
  commodity_code VARCHAR(8) NOT NULL, indicator VARCHAR(60) NOT NULL,
  freq VARCHAR(1), obs_date DATE NOT NULL, val DECIMAL(20,4), src VARCHAR(40),
  PRIMARY KEY (commodity_code, indicator, obs_date)
);
-- 거시/원자재 시계열(환율·BDI·美금융·中수요 등)
CREATE TABLE IF NOT EXISTS fact_series (
  series_code VARCHAR(40) NOT NULL, obs_date DATE NOT NULL,
  val DECIMAL(24,6), unit VARCHAR(20), src VARCHAR(40),
  PRIMARY KEY (series_code, obs_date)
);
-- USGS 생산·매장(연)
CREATE TABLE IF NOT EXISTS fact_production_reserve (
  commodity_code VARCHAR(8) NOT NULL, country VARCHAR(80) NOT NULL, yr INTEGER NOT NULL,
  production DECIMAL(20,3), reserve DECIMAL(20,3), unit VARCHAR(20), src VARCHAR(60),
  PRIMARY KEY (commodity_code, country, yr)
);
-- ECOS 원자료(산업생산·GDP)
CREATE TABLE IF NOT EXISTS raw_ecos (
  series_name VARCHAR(40) NOT NULL, period VARCHAR(8) NOT NULL, val DECIMAL(20,4),
  PRIMARY KEY (series_name, period)
);

-- ---------- 피처 마트 (계층3 산출, 모델 입력) ----------
CREATE TABLE IF NOT EXISTS mart_weekly_diagnosis (
  commodity_code VARCHAR(8) NOT NULL, obs_date DATE NOT NULL,
  feat_json VARCHAR(4000),            -- 피처 dict(JSON 직렬화) 또는 개별 컬럼으로 확장
  target_label VARCHAR(8),            -- 위기/정상 등
  PRIMARY KEY (commodity_code, obs_date)
);
CREATE TABLE IF NOT EXISTS mart_monthly_forecast_input (
  commodity_code VARCHAR(8) NOT NULL, target VARCHAR(10) NOT NULL,  -- volume/price
  obs_date DATE NOT NULL, y_val DECIMAL(20,4), feat_json VARCHAR(4000),
  PRIMARY KEY (commodity_code, target, obs_date)
);

-- ---------- 지정학 지수 (geo 최종 결과만 저장) ----------
CREATE TABLE IF NOT EXISTS geo_index (
  commodity_code VARCHAR(8) NOT NULL, freq VARCHAR(1) NOT NULL,   -- W/M
  period DATE NOT NULL, raw_score DECIMAL(20,6), n_events INTEGER,
  idx_value DECIMAL(9,3),             -- 0~100
  index_config_version VARCHAR(20), generated_at TIMESTAMP,
  PRIMARY KEY (commodity_code, freq, period)
);

-- 지정학 이벤트 상세 (geo publish → 경보 오버라이드·사유 인용용)
CREATE TABLE IF NOT EXISTS geo_event (
  event_id VARCHAR(32) NOT NULL, doc_id VARCHAR(32),
  commodity_code VARCHAR(8) NOT NULL, obs_date DATE,
  country VARCHAR(80), event_type VARCHAR(160),
  direction VARCHAR(16), target VARCHAR(16),
  severity DECIMAL(6,3),              -- 0~3 (geo GeoEvent 스케일)
  confidence DECIMAL(6,3), evidence_quote VARCHAR(600),
  source VARCHAR(40), published_at TIMESTAMP,
  PRIMARY KEY (event_id)
);

-- ---------- 모델 결과 / 산출물 6종 (계층4~5, DB화) ----------
-- ① 진단·경보 4단계
CREATE TABLE IF NOT EXISTS out_diagnosis_alert (
  commodity_code VARCHAR(8) NOT NULL, obs_date DATE NOT NULL,
  risk_score DECIMAL(9,4), risk_proba DECIMAL(9,6),
  alert_level VARCHAR(8),             -- 관심/주의/경계/심각
  reason VARCHAR(2000),
  evidence_json VARCHAR(4000),        -- 운영판정 로그(D-6): 기여도breakdown·근거이벤트top3·오버라이드/히스테리시스 여부(JSON)
  model_version VARCHAR(30), generated_at TIMESTAMP,
  PRIMARY KEY (commodity_code, obs_date)
);
-- ② 수입 예측(물량·가격, h=12)
CREATE TABLE IF NOT EXISTS out_import_forecast (
  commodity_code VARCHAR(8) NOT NULL, target VARCHAR(10) NOT NULL,   -- volume/price
  base_date DATE NOT NULL, horizon INTEGER NOT NULL,                 -- 1..12
  yhat DECIMAL(20,4), yhat_lo DECIMAL(20,4), yhat_hi DECIMAL(20,4),
  model_version VARCHAR(30), generated_at TIMESTAMP,
  PRIMARY KEY (commodity_code, target, base_date, horizon)
);
-- E-1(피드백기반_수정플랜 P3): 재귀 vs Direct MASE 비교 이력(매 재학습마다 append) — 격차
-- 추세 모니터링 + 자동전환 임계값 판단 근거. 삭제 없이 계속 쌓임(base_month가 자연 유일키).
CREATE TABLE IF NOT EXISTS mart_forecast_method_log (
  base_month DATE NOT NULL, mase_recursive DECIMAL(9,4), mase_direct DECIMAL(9,4),
  gap DECIMAL(9,4),                  -- mase_recursive - mase_direct(양수=Direct가 더 우수)
  method_selected VARCHAR(10),       -- 실제 채택된 방식(마진 임계 적용 후)
  method_naive VARCHAR(10),          -- 마진 없이 단순 최소값 기준 방식(참고용)
  margin_threshold DECIMAL(9,4), generated_at TIMESTAMP,
  PRIMARY KEY (base_month)
);
-- ④ 자동 보고서 로그  ⑤ 시계열 요약
CREATE TABLE IF NOT EXISTS out_report (
  report_id VARCHAR(32) NOT NULL, commodity_code VARCHAR(8), period VARCHAR(8),
  kind VARCHAR(20),                  -- report/summary
  title VARCHAR(200), body VARCHAR(8000), generated_at TIMESTAMP,
  PRIMARY KEY (report_id)
);
-- ⑥ 챗봇(RAG) 문서 청크 (벡터는 별도 벡터스토어; 여기엔 원문·메타)
CREATE TABLE IF NOT EXISTS doc_chunk (
  chunk_id VARCHAR(32) NOT NULL, doc_id VARCHAR(32), commodity_code VARCHAR(8),
  src VARCHAR(40), pub_date DATE, seq INTEGER, txt VARCHAR(8000),
  PRIMARY KEY (chunk_id)
);
-- ③ 모니터링 대시보드는 위 결과 테이블 위의 뷰로 구성(별도 테이블 불필요).

-- ⑦ 화면기획안 ver.1.3 "텍스트 보고서" 화면 2종 공용(2026-08-19 신설) —
-- A화면(종합 모니터링) §13 "AI 종합분석 및 관련뉴스"·§6 "AI 보고서 다운로드"와
-- B화면(광종별 모니터링) Step6 §21 "AI 종합판단"이 요구하는 필드를 원본 PDF
-- 슬라이드(p.11·p.24) 문구 그대로 스키마화했다 — out_report(범용 렌더 문서,
-- body 단일 블롭)와 별도로 둔 이유는 프런트가 태그 칩·뉴스 카드처럼 구조를
-- 유지한 채 렌더링해야 해서(사전 렌더링된 텍스트 블롭 하나로는 부족).
-- crisis_index/alert_level/key_factor_contrib_json 등 수치성 필드는 반드시
-- out_diagnosis_alert·geo_index·out_import_forecast_unit 등 이미 검증된 원천에서
-- 그대로 가져오고(LLM이 숫자를 지어내지 않음), diagnosis_text/ai_comment/
-- weekly_news_json/supply_chain_summary/event_news_summary만 그 숫자를 근거로
-- LLM이 서술한다(report_gen/app/analysis/summary.py의 "LLM 정제+규칙기반 폴백"
-- 패턴과 동일 원칙).
CREATE TABLE IF NOT EXISTS out_ai_dashboard_summary (
  summary_id VARCHAR(32) NOT NULL,
  scope VARCHAR(12) NOT NULL,                -- 'overall'(A화면 종합) | 'commodity'(B화면 Step6)
  commodity_code VARCHAR(8),                 -- scope='commodity'일 때만 값, overall은 NULL
  period_week DATE NOT NULL,                 -- 기준 주(원천 out_diagnosis_alert.obs_date와 매칭)
  alert_level VARCHAR(8),                    -- 정상/관심/주의/경계/심각 — out_diagnosis_alert 스냅샷
  crisis_index DECIMAL(6,2),                 -- overall=5광종 평균, commodity=해당 광종 값
  wow_delta DECIMAL(6,2),                    -- 전주 대비 변화량(crisis_index 기준)
  diagnosis_text VARCHAR(2000),              -- 종합진단(현황) 서술 — overall 전용(p.11 "①종합 진단")
  ai_comment VARCHAR(2000),                  -- AI 종합분석 코멘트(자유서술) — commodity 전용(p.24 "①종합 분석")
  risk_tags_json VARCHAR(2000),              -- [{"tag":"지정학적","evidence":"..."}] 양쪽 공용
  response_strategies_json VARCHAR(1000),    -- ["해외수입선의 다변화", ...] — overall 전용(p.11 "대응전략")
  key_factor_contrib_json VARCHAR(1000),      -- commodity 전용: out_diagnosis_alert.evidence_json의
                                              -- contrib를 6개 변수 %분해로 재표기(p.18 "③핵심 변수 기여도")
  weekly_news_json VARCHAR(4000),            -- overall 전용: [{"commodity_code","headline","driver_up",
                                              -- "driver_down"}] 5건(p.11 "②주간별 뉴스")
  supply_chain_summary VARCHAR(1500),        -- commodity 전용: 공급망 분석 결과 서술(p.24 "제공 데이터")
  event_news_summary VARCHAR(1500),          -- commodity 전용: 이벤트·뉴스 분석 결과 서술(p.24 상동)
  llm_refined BOOLEAN,                       -- true=LLM 서술 성공, false=규칙기반 폴백만 사용
  model_version VARCHAR(60),
  generated_at TIMESTAMP,
  PRIMARY KEY (summary_id)
);
