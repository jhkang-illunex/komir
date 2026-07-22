# -*- coding: utf-8 -*-
"""
canonical DuckDB -> 모델별 feature mart 생성
  - agg_trade_annual         : 광종·연도 교역 집계 (수입 HHI, YoY, CAGR3)
  - agg_production_annual     : 광종·연도 생산 HHI (USGS)
  - mart_weekly_diagnosis     : [진단모델] 주간 패널 (6변수+신규지표+교사신호)
  - mart_annual_forecast      : [예측모델] 연간 수입 패널 (월간 타깃 데이터 확보 시 월간 확장)
사용:  python build_feature_marts.py --db minerals.duckdb
"""
import argparse, duckdb

CORE=("CU","NI","LI","CO","REE")

DDL = r"""
-- ========== 1) 연간 교역 집계 (수입편중 HHI ②, 수입 CAGR/YoY ③) ==========
CREATE OR REPLACE TABLE agg_trade_annual AS
WITH base AS (
  SELECT commodity_code, year, country,
         SUM(import_value_usd) imp_usd, SUM(import_weight_kg) imp_kg
  FROM fact_trade
  WHERE commodity_code IS NOT NULL AND import_value_usd IS NOT NULL
  GROUP BY 1,2,3
),
tot AS (
  SELECT commodity_code, year, SUM(imp_usd) tot_usd, SUM(imp_kg) tot_kg
  FROM base GROUP BY 1,2
),
hhi AS (  -- 국가별 수입액 점유율 제곱합 *10000 (0~10000)
  SELECT b.commodity_code, b.year,
         SUM( POWER(b.imp_usd / NULLIF(t.tot_usd,0), 2) ) * 10000 AS import_hhi
  FROM base b JOIN tot t USING(commodity_code, year)
  GROUP BY 1,2
)
SELECT t.commodity_code, t.year, t.tot_usd AS import_value_usd, t.tot_kg AS import_weight_kg,
       h.import_hhi,
       t.tot_usd / NULLIF(LAG(t.tot_usd) OVER (PARTITION BY t.commodity_code ORDER BY t.year),0) - 1 AS import_yoy,
       POWER( t.tot_usd / NULLIF(LAG(t.tot_usd,3) OVER (PARTITION BY t.commodity_code ORDER BY t.year),0), 1.0/3) - 1 AS import_cagr3,
       make_date(t.year+1, 1, 1) AS avail_date   -- 연간데이터는 익년 초부터 가용(누수방지)
FROM tot t JOIN hhi h USING(commodity_code, year);

-- ========== 2) 연간 생산 독점도 HHI (⑤, USGS) ==========
CREATE OR REPLACE TABLE agg_production_annual AS
WITH base AS (
  SELECT commodity_code, year, country, SUM(value) prod
  FROM fact_production_reserve
  WHERE commodity_code IS NOT NULL AND metric_type='PRODUCTION' AND value>0
  GROUP BY 1,2,3
),
tot AS (SELECT commodity_code, year, SUM(prod) tot FROM base GROUP BY 1,2)
SELECT b.commodity_code, b.year,
       SUM( POWER(b.prod/NULLIF(t.tot,0),2) )*10000 AS production_hhi,
       make_date(b.year+1, 1, 1) AS avail_date
FROM base b JOIN tot t USING(commodity_code,year)
GROUP BY 1,2;

-- ========== 3) 광종별 주간 대표가격 (우선순위 coalesce) ==========
CREATE OR REPLACE TABLE _ref_price AS
WITH p AS (
  SELECT commodity_code, obs_date, price_basis, value,
         CASE price_basis
           WHEN 'LME_3M' THEN 1 WHEN 'LME_CASH' THEN 2 WHEN 'REF' THEN 3
           WHEN '99.5%min CIF China' THEN 4 WHEN 'LiOH 56.5%min FOB China' THEN 5
           WHEN '99.8%min In warehouse Rotterdam' THEN 6 ELSE 9 END AS pr
  FROM fact_price
  WHERE commodity_code IN ('CU','NI','LI','CO','REE') AND freq='W' AND value IS NOT NULL
)
SELECT commodity_code, obs_date, value AS ref_price
FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY commodity_code, obs_date ORDER BY pr) rn FROM p)
WHERE rn=1;

-- ========== 4) [진단] 주간 패널 ==========
CREATE OR REPLACE TABLE mart_weekly_diagnosis AS
WITH wk AS (  -- 주간 그리드 + 대표가격 + 수익률/변동성(①)
  SELECT commodity_code, obs_date, ref_price,
         LN(ref_price / NULLIF(LAG(ref_price) OVER w,0)) AS logret
  FROM _ref_price
  WINDOW w AS (PARTITION BY commodity_code ORDER BY obs_date)
),
vol AS (
  SELECT *, STDDEV_SAMP(logret) OVER (PARTITION BY commodity_code ORDER BY obs_date
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) AS volatility_12w
  FROM wk
),
cash3m AS ( -- Cash/3M 스프레드(신규지표)
  SELECT c.commodity_code, c.obs_date,
         c.value AS lme_cash, m.value AS lme_3m,
         (c.value - m.value)/NULLIF(m.value,0)*100 AS spread_pct
  FROM (SELECT commodity_code,obs_date,value FROM fact_price WHERE price_basis='LME_CASH' AND freq='W') c
  LEFT JOIN (SELECT commodity_code,obs_date,value FROM fact_price WHERE price_basis='LME_3M' AND freq='W') m
    USING(commodity_code,obs_date)
)
SELECT
  v.commodity_code, v.obs_date,
  YEAR(v.obs_date) AS yr,
  v.ref_price, v.logret,
  v.volatility_12w,                         -- ① 시장변동성
  c.lme_cash, c.lme_3m, c.spread_pct        -- 신규: Cash-3M 스프레드
FROM vol v
LEFT JOIN cash3m c USING(commodity_code, obs_date);

-- ========== 4b) 연간 교역/생산 변수 ASOF 결합 (직전 가용연도) ==========
CREATE OR REPLACE TABLE mart_weekly_diagnosis AS
SELECT m.*, ta.import_hhi, ta.import_yoy, ta.import_cagr3   -- ②③
FROM mart_weekly_diagnosis m
ASOF LEFT JOIN agg_trade_annual ta
  ON m.commodity_code=ta.commodity_code AND m.obs_date >= ta.avail_date;

CREATE OR REPLACE TABLE mart_weekly_diagnosis AS
SELECT m.*, pa.production_hhi,                              -- ⑤
       CAST(NULL AS DOUBLE) AS supply_shortage,            -- ④ 소비데이터 미보유
       CAST(NULL AS DOUBLE) AS geopolitical_risk           -- ⑥ 발주처 제공예정
FROM mart_weekly_diagnosis m
ASOF LEFT JOIN agg_production_annual pa
  ON m.commodity_code=pa.commodity_code AND m.obs_date >= pa.avail_date;

-- ========== 5) 교사신호(수급동향지표) ASOF 결합 ==========
-- 수급동향지표: 월간 -> 주간 ASOF (week 이하 최신 월값)
CREATE OR REPLACE TABLE mart_weekly_diagnosis AS
SELECT m.*, ind.value AS teacher_supply_demand
FROM mart_weekly_diagnosis m
ASOF LEFT JOIN (
   SELECT commodity_code, obs_date, value
   FROM fact_indicator WHERE indicator_type='SUPPLY_DEMAND'
) ind
  ON m.commodity_code = ind.commodity_code AND m.obs_date >= ind.obs_date;

-- ========== 6) [예측] 연간 수입 패널 (월간 타깃 미보유로 연간 단위) ==========
CREATE OR REPLACE TABLE mart_annual_forecast AS
SELECT a.commodity_code, a.year,
       a.import_value_usd,  -- 타깃 후보 (천$ 환산 전, $ 단위)
       a.import_weight_kg,  -- 타깃 후보 (kg)
       a.import_hhi, a.import_yoy, a.import_cagr3,
       p.production_hhi,
       LEAD(a.import_value_usd) OVER (PARTITION BY a.commodity_code ORDER BY a.year) AS import_value_usd_next  -- 1년 후 타깃
FROM agg_trade_annual a
LEFT JOIN agg_production_annual p USING(commodity_code, year)
WHERE a.commodity_code IN ('CU','NI','LI','CO','REE');
"""

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--db",default="minerals.duckdb"); a=ap.parse_args()
    con=duckdb.connect(a.db)
    con.execute(DDL)
    con.execute("DROP TABLE IF EXISTS _ref_price")
    print("=== feature mart 생성 완료 ===")
    for t in ["agg_trade_annual","agg_production_annual","mart_weekly_diagnosis","mart_annual_forecast"]:
        print(f"  {t:24s}: {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:,}")
    con.close()

if __name__=="__main__":
    main()
