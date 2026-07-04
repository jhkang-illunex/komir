# -*- coding: utf-8 -*-
"""raw→fact 정규화: 랜딩 테이블(raw_customs_*)을 운영 정본 팩트(fact_trade_*)로 통합.
- raw_customs_monthly → fact_trade_monthly  (yr·mon·hs10·country 그레인, 측정치 SUM)
- raw_customs_annual  → fact_trade_annual   (yr·hs10·country 그레인; raw가 월행이어도 연도로 집계)
- agg_trade_annual: 광종·연도 수입 집계(HHI/YoY/CAGR3) — 정본 팩트 기반 분석 마트
멱등: src='CUSTOMS' 기존행 삭제 후 재적재. 단일 트랜잭션.
가격/생산/교사신호(fact_price·fact_production_reserve·fact_indicator)는 별도 수집 필요(미구현).
"""
import duckdb
from ..config import DB_PATH

# 스테이지(temp) → src 리프레시 삭제 + PK 그레인 삭제(타 src와의 PK 충돌 방지) → INSERT
_MONTHLY_STAGE = """
CREATE OR REPLACE TEMP TABLE _stg_m AS
SELECT year AS yr, month AS mon, hscode AS hs10, any_value(commodity_code) AS commodity_code,
       country, SUM(imp_usd) AS imp_usd, SUM(imp_wgt) AS imp_wgt,
       SUM(exp_usd) AS exp_usd, SUM(exp_wgt) AS exp_wgt, 'CUSTOMS' AS src, now() AS loaded_at
FROM raw_customs_monthly
WHERE month IS NOT NULL AND hscode IS NOT NULL AND country IS NOT NULL
GROUP BY year, month, hscode, country
"""
_MONTHLY_MERGE = """
DELETE FROM fact_trade_monthly WHERE src='CUSTOMS';
DELETE FROM fact_trade_monthly t
 WHERE EXISTS (SELECT 1 FROM _stg_m s
               WHERE s.yr=t.yr AND s.mon=t.mon AND s.hs10=t.hs10 AND s.country=t.country);
INSERT INTO fact_trade_monthly SELECT * FROM _stg_m;
"""

_ANNUAL_STAGE = """
CREATE OR REPLACE TEMP TABLE _stg_a AS
SELECT year AS yr, hscode AS hs10, any_value(commodity_code) AS commodity_code,
       country, SUM(imp_usd) AS imp_usd, SUM(imp_wgt) AS imp_wgt,
       SUM(exp_usd) AS exp_usd, SUM(exp_wgt) AS exp_wgt, 'CUSTOMS' AS src, now() AS loaded_at
FROM raw_customs_annual
WHERE hscode IS NOT NULL AND country IS NOT NULL
GROUP BY year, hscode, country
"""
_ANNUAL_MERGE = """
DELETE FROM fact_trade_annual WHERE src='CUSTOMS';
DELETE FROM fact_trade_annual t
 WHERE EXISTS (SELECT 1 FROM _stg_a s
               WHERE s.yr=t.yr AND s.hs10=t.hs10 AND s.country=t.country);
INSERT INTO fact_trade_annual SELECT * FROM _stg_a;
"""

_AGG_TRADE_ANNUAL_SQL = """
CREATE OR REPLACE TABLE agg_trade_annual AS
WITH base AS (
  SELECT commodity_code, yr AS year, country,
         SUM(imp_usd) imp_usd, SUM(imp_wgt) imp_kg
  FROM fact_trade_annual
  WHERE commodity_code IS NOT NULL AND imp_usd IS NOT NULL
  GROUP BY 1,2,3
),
tot AS (SELECT commodity_code, year, SUM(imp_usd) tot_usd, SUM(imp_kg) tot_kg FROM base GROUP BY 1,2),
hhi AS (
  SELECT b.commodity_code, b.year,
         SUM(POWER(b.imp_usd / NULLIF(t.tot_usd,0), 2)) * 10000 AS import_hhi
  FROM base b JOIN tot t USING(commodity_code, year) GROUP BY 1,2
)
SELECT t.commodity_code, t.year,
       t.tot_usd AS import_value_usd, t.tot_kg AS import_weight_kg, h.import_hhi,
       t.tot_usd / NULLIF(LAG(t.tot_usd)   OVER (PARTITION BY t.commodity_code ORDER BY t.year),0) - 1        AS import_yoy,
       POWER(t.tot_usd / NULLIF(LAG(t.tot_usd,3) OVER (PARTITION BY t.commodity_code ORDER BY t.year),0), 1.0/3) - 1 AS import_cagr3,
       make_date(t.year+1, 1, 1) AS avail_date
FROM tot t JOIN hhi h USING(commodity_code, year)
"""


def run(db=None):
    """raw_customs_* → fact_trade_* + agg_trade_annual. 반환: 적재 행수 요약."""
    db = db or DB_PATH
    con = duckdb.connect(db)
    try:
        con.execute(_MONTHLY_STAGE)
        con.execute(_ANNUAL_STAGE)
        con.execute("BEGIN")
        con.execute(_MONTHLY_MERGE)
        con.execute(_ANNUAL_MERGE)
        con.execute("COMMIT")
    except Exception:
        try: con.execute("ROLLBACK")
        except Exception: pass
        con.close(); raise
    con.execute(_AGG_TRADE_ANNUAL_SQL)   # 팩트 기반 재생성(멱등)
    n = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
         for t in ("fact_trade_monthly", "fact_trade_annual", "agg_trade_annual")}
    con.execute("CHECKPOINT"); con.close()
    print(f"[normalize] fact_trade_monthly={n['fact_trade_monthly']} · "
          f"fact_trade_annual={n['fact_trade_annual']} · agg_trade_annual={n['agg_trade_annual']}")
    return n


if __name__ == "__main__":
    run()
