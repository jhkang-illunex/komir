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

# HHI 원천 교정(2026-07-15): fact_trade_annual.country는 구수집분의 품목명 오염(수집기
# country←statKor 오매핑 — 당일 교정)이라 종전 import_hhi는 '수입국 집중'이 아닌 '품목
# 구성 HHI'였음. HHI만 국가별 재수집 정본({HHI_SRC})에서 계산하고, 총액·YoY·CAGR은 합계
# 기반이라 종전 경로 유지(오염 무영향). bycountry 미존재 환경은 구식으로 폴백(run()).
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
bc AS (
  SELECT commodity_code, year, country, SUM(imp_usd) imp_usd
  FROM {HHI_SRC} src
  WHERE commodity_code IS NOT NULL
  GROUP BY 1,2,3
),
bt AS (SELECT commodity_code, year, SUM(imp_usd) tot FROM bc GROUP BY 1,2),
hhi AS (
  SELECT b.commodity_code, b.year,
         SUM(POWER(b.imp_usd / NULLIF(t.tot,0), 2)) * 10000 AS import_hhi
  FROM bc b JOIN bt t USING(commodity_code, year) GROUP BY 1,2
)
SELECT t.commodity_code, t.year,
       t.tot_usd AS import_value_usd, t.tot_kg AS import_weight_kg, h.import_hhi,
       t.tot_usd / NULLIF(LAG(t.tot_usd)   OVER (PARTITION BY t.commodity_code ORDER BY t.year),0) - 1        AS import_yoy,
       POWER(t.tot_usd / NULLIF(LAG(t.tot_usd,3) OVER (PARTITION BY t.commodity_code ORDER BY t.year),0), 1.0/3) - 1 AS import_cagr3,
       make_date(t.year+1, 1, 1) AS avail_date
FROM tot t LEFT JOIN hhi h USING(commodity_code, year)
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
    has_bc = con.execute("SELECT count(*) FROM information_schema.tables "
                         "WHERE table_name='raw_customs_annual_bycountry'").fetchone()[0] > 0
    hhi_src = ("(SELECT commodity_code, CAST(year AS INT) AS year, country, "
               "CAST(imp_usd AS DOUBLE) AS imp_usd FROM raw_customs_annual_bycountry)"
               if has_bc else
               "(SELECT commodity_code, yr AS year, country, imp_usd FROM fact_trade_annual)")
    if not has_bc:
        print("  [warn] raw_customs_annual_bycountry 없음 — import_hhi가 구식(품목 HHI)으로 폴백")
    con.execute(_AGG_TRADE_ANNUAL_SQL.replace("{HHI_SRC}", hhi_src))   # 팩트 기반 재생성(멱등)
    n = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
         for t in ("fact_trade_monthly", "fact_trade_annual", "agg_trade_annual")}
    con.execute("CHECKPOINT"); con.close()
    print(f"[normalize] fact_trade_monthly={n['fact_trade_monthly']} · "
          f"fact_trade_annual={n['fact_trade_annual']} · agg_trade_annual={n['agg_trade_annual']}")
    return n


if __name__ == "__main__":
    run()
