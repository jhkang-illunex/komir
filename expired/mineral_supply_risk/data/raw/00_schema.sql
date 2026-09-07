-- =====================================================================
-- 핵심광물 위기진단·수입예측 프로젝트 : Canonical 스키마 (DuckDB 기준)
-- =====================================================================
-- 설계 원칙
--   1) long/tidy 정규화  : 광종·날짜·변수명·값·단위·출처 키로 통일
--   2) 영문 snake_case 식별자, 보수적 타입 (Postgres/MySQL/Oracle 이식 용이)
--   3) 두 모델(진단=주간, 예측=월간)이 공유하는 단일 원천(canonical) 계층
--   4) 운영 DB 이관 시 타입만 치환:
--        DuckDB        Postgres        MySQL           Oracle
--        VARCHAR    -> VARCHAR         VARCHAR(n)      VARCHAR2(n)
--        DATE       -> DATE            DATE            DATE
--        DOUBLE     -> DOUBLE PRECISION DOUBLE         NUMBER
--        BIGINT     -> BIGINT          BIGINT          NUMBER(19)
--        DECIMAL    -> NUMERIC         DECIMAL         NUMBER
-- =====================================================================

-- ---------- 차원(Dimension) ----------

-- 광종 사전 (5대 핵심광물 + 확장)
CREATE TABLE IF NOT EXISTS dim_commodity (
    commodity_code   VARCHAR PRIMARY KEY,   -- 'CU','NI','LI','CO','REE'
    name_ko          VARCHAR NOT NULL,
    name_en          VARCHAR,
    is_core5         BOOLEAN DEFAULT FALSE,  -- 과업 대상 5종 여부
    category         VARCHAR                 -- 비철금속/배터리/희토류 등
);

-- 원천별 표기명 -> 표준 광종코드 매핑 (소스마다 명칭이 달라 별도 관리)
CREATE TABLE IF NOT EXISTS dim_commodity_map (
    source           VARCHAR NOT NULL,       -- 'KOMIS','CUSTOMS','USGS','SUPPLY'
    raw_name         VARCHAR NOT NULL,       -- 원본 표기 (동, 탄산리튬, Rare earths ...)
    commodity_code   VARCHAR,                -- 매핑된 표준코드 (미매핑이면 NULL)
    PRIMARY KEY (source, raw_name)
);

-- 거시·지수·환율 등 단일 시계열 메타
CREATE TABLE IF NOT EXISTS dim_series (
    series_code      VARCHAR PRIMARY KEY,    -- 'BDI','USDKRW','BLOOMBERG_CMD' ...
    series_name_ko   VARCHAR,
    unit             VARCHAR,
    freq             VARCHAR,                -- 'W','M','D'
    source           VARCHAR
);


-- HS코드 -> 광종 권위 매핑 (HS코드분류__최종.xlsx 종합분류 기반, 검증완료)
CREATE TABLE IF NOT EXISTS dim_hs_commodity (
    hs10             VARCHAR PRIMARY KEY,
    commodity_ko     VARCHAR,
    commodity_code   VARCHAR,
    is_core5         BOOLEAN DEFAULT FALSE
);

-- ---------- 사실(Fact) ----------

-- 1) 가격 (long): LME Cash/3M, 기준가, 연·월 평균 등 모든 가격을 통합
CREATE TABLE IF NOT EXISTS fact_price (
    commodity_code   VARCHAR,        -- 표준코드 (미매핑 시 NULL 가능)
    raw_name         VARCHAR,        -- 원본 광종 표기
    price_basis      VARCHAR,        -- 'LME_CASH','LME_3M','REF','LOW','HIGH','CIF' ...
    unit             VARCHAR,        -- 'USD/mt','USD/kg'
    freq             VARCHAR,        -- 'W','M','Y'
    obs_date         DATE,           -- 주간/월간은 해당 기준일, 연간은 해당연도 1/1
    value            DOUBLE,
    source           VARCHAR
);

-- 2) LME 재고 (주간)
CREATE TABLE IF NOT EXISTS fact_inventory (
    commodity_code   VARCHAR,
    raw_name         VARCHAR,
    obs_date         DATE,
    lme_stock        DOUBLE,         -- LME재고량
    stock_chg        DOUBLE,         -- 전일대비등락가
    stock_chg_pct    DOUBLE,         -- 전일대비등락비율
    unit             VARCHAR,        -- 'mt'
    source           VARCHAR
);

-- 3) 교역 (관세청, 연간·국가별)
CREATE TABLE IF NOT EXISTS fact_trade (
    year             INTEGER,
    commodity_code   VARCHAR,
    raw_name         VARCHAR,        -- 광종명(원본)
    hscode           VARCHAR,
    item_name        VARCHAR,        -- 품목명
    country          VARCHAR,        -- 국가명
    import_value_usd DOUBLE,
    import_weight_kg DOUBLE,
    export_value_usd DOUBLE,
    export_weight_kg DOUBLE,
    flow_lv1         VARCHAR,        -- 물질흐름_Lv1
    flow_lv2         VARCHAR,        -- 물질흐름_Lv2
    classification   VARCHAR,        -- 분류 (핵심/전략광물 등)
    source           VARCHAR
);

-- 4) 생산·매장량 (USGS, 연간·국가별 long)
CREATE TABLE IF NOT EXISTS fact_production_reserve (
    source_tag       VARCHAR,        -- 'MCS2026' 등
    commodity_code   VARCHAR,
    raw_name         VARCHAR,        -- COMMODITY 원본
    country          VARCHAR,
    metric_type      VARCHAR,        -- 'PRODUCTION','RESERVE'
    year             INTEGER,
    value            DOUBLE,
    unit             VARCHAR,        -- 'ton'
    source           VARCHAR
);

-- 5) KOMIS 지표 (월간, long): 수급동향/시장동향/광물종합 + 지표용 가격
CREATE TABLE IF NOT EXISTS fact_indicator (
    commodity_code   VARCHAR,
    raw_name         VARCHAR,
    obs_date         DATE,           -- 월초 기준일
    indicator_type   VARCHAR,        -- 'SUPPLY_DEMAND','MARKET','COMPOSITE','PRICE'
    value            DOUBLE,
    source           VARCHAR
);

-- 6) 거시·지수·환율 (long): BDI, 원자재지수, 환율, 美금융, 中수요 등
CREATE TABLE IF NOT EXISTS fact_series (
    series_code      VARCHAR,
    obs_date         DATE,
    value            DOUBLE,
    unit             VARCHAR,
    source           VARCHAR
);

-- ---------- 권장 인덱스 (운영 DB 이관 시) ----------
-- CREATE INDEX ix_price_cd_date  ON fact_price(commodity_code, obs_date);
-- CREATE INDEX ix_trade_cd_year  ON fact_trade(commodity_code, year);
-- CREATE INDEX ix_ind_cd_date    ON fact_indicator(commodity_code, obs_date);
-- CREATE INDEX ix_series_cd_date ON fact_series(series_code, obs_date);
