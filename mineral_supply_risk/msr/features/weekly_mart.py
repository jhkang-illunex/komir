# -*- coding: utf-8 -*-
"""[진단] 주간 마트 빌더 — 정본 팩트에서 mart_weekly_diagnosis 생성(warehouse 스키마).
소스 무관: fact_price(주간 가격)·fact_indicator(교사=수급동향지표)·agg_trade_annual(교역)·
geo_index(지정학 지수, `geo publish` 산출)에서 읽어 진단모델 FEATS 컬럼을 구성한다.
실 KOMIS든 합성이든 이 팩트 테이블에 들어오면 흐른다. 가격 데이터 없으면 빈 마트(진단은 자동 스킵).

geopolitical_risk 배선(2026-07-08, v1 문서 §11-3): geo_index(freq='W', 주말 라벨)를 ASOF로
당겨 붙인다 — 마트 관측일 이전의 가장 최근 주간 지수(pandas resample 'W'가 주 종료일을 라벨로
쓰므로 사실상 직전 완결 주의 지수 = 미래참조 없음). geo_index 테이블이 없거나 비어 있으면
기존처럼 NULL(하위호환 — geo publish 전 환경에서도 마트 빌드는 성공해야 함).
"""
import duckdb
from ..config import DB_PATH

# price_type 우선순위(대표가격): LME_3M > LME_CASH > REF > 기타
# {GEO_JOIN}/{GEO_COL}은 run()에서 geo_index 존재 여부에 따라 치환된다.
_DDL_TMPL = """
CREATE OR REPLACE TABLE mart_weekly_diagnosis AS
WITH refp AS (
  SELECT commodity_code, obs_date, val AS ref_price,
         ROW_NUMBER() OVER (PARTITION BY commodity_code, obs_date ORDER BY
           CASE price_type WHEN 'LME_3M' THEN 1 WHEN 'LME_CASH' THEN 2 WHEN 'REF' THEN 3 ELSE 9 END) rn
  FROM fact_price WHERE freq='W' AND val IS NOT NULL
),
rp AS (SELECT commodity_code, obs_date, ref_price FROM refp WHERE rn=1),
wk AS (
  SELECT commodity_code, obs_date, ref_price,
         LN(ref_price / NULLIF(LAG(ref_price) OVER (PARTITION BY commodity_code ORDER BY obs_date),0)) AS logret
  FROM rp
),
vol AS (
  SELECT *, STDDEV_SAMP(logret) OVER (
             PARTITION BY commodity_code ORDER BY obs_date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
           ) AS volatility_12w
  FROM wk
),
spread AS (
  -- ASOF: 실제 LME는 CASH/3M 관측일이 어긋나는 경우가 흔함 → 정확일치 대신
  -- 각 CASH 관측 이전의 가장 최근 3M 값과 매칭(동일 일자면 그 값).
  SELECT c.commodity_code, c.obs_date, (c.val - m.val)/NULLIF(m.val,0)*100 AS spread_pct
  FROM (SELECT commodity_code,obs_date,val FROM fact_price WHERE price_type='LME_CASH' AND freq='W') c
  ASOF LEFT JOIN (SELECT commodity_code,obs_date,val FROM fact_price WHERE price_type='LME_3M' AND freq='W') m
    ON c.commodity_code = m.commodity_code AND c.obs_date >= m.obs_date
),
teacher AS (
  SELECT commodity_code, obs_date, val FROM fact_indicator WHERE indicator='SUPPLY_DEMAND'
)
SELECT
  v.commodity_code, v.obs_date, YEAR(v.obs_date) AS yr,
  v.ref_price, v.logret, v.volatility_12w,
  s.spread_pct,
  ta.import_hhi, ta.import_yoy, ta.import_cagr3,
  CAST(NULL AS DOUBLE) AS production_hhi,       -- USGS 미보유
  {GEO_COL},
  CAST(NULL AS DOUBLE) AS geo_macro,            -- 거시 지정학
  t.val AS teacher_supply_demand                -- 교사신호(수급동향지표)
FROM vol v
LEFT JOIN spread s USING(commodity_code, obs_date)
ASOF LEFT JOIN agg_trade_annual ta
  ON v.commodity_code = ta.commodity_code AND v.obs_date >= ta.avail_date
ASOF LEFT JOIN teacher t
  ON v.commodity_code = t.commodity_code AND v.obs_date >= t.obs_date
{GEO_JOIN}
"""

# 주의: 이 치환 문자열 뒤에 템플릿의 쉼표가 바로 붙으므로 SQL 인라인 주석(--) 금지
# (주석이 쉼표를 삼켜 ParserException — 실측 2026-07-08).
_GEO_COL_NULL = "CAST(NULL AS DOUBLE) AS geopolitical_risk"
_GEO_COL_JOIN = "CAST(g.idx_value AS DOUBLE) AS geopolitical_risk"
_GEO_JOIN = """ASOF LEFT JOIN (
  SELECT commodity_code, CAST(period AS DATE) AS period, idx_value
  FROM geo_index WHERE freq='W'
) g ON v.commodity_code = g.commodity_code AND v.obs_date >= g.period"""


def _has_geo_index(con) -> bool:
    n = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='geo_index'").fetchone()[0]
    if not n:
        return False
    return con.execute("SELECT count(*) FROM geo_index WHERE freq='W'").fetchone()[0] > 0


def run(db=None):
    db = db or DB_PATH
    con = duckdb.connect(db)
    # 가격 데이터 유무 확인(없으면 빈 마트 생성)
    npx = con.execute("SELECT count(*) FROM fact_price WHERE freq='W'").fetchone()[0]
    use_geo = _has_geo_index(con)
    ddl = _DDL_TMPL.format(
        GEO_COL=_GEO_COL_JOIN if use_geo else _GEO_COL_NULL,
        GEO_JOIN=_GEO_JOIN if use_geo else "",
    )
    con.execute(ddl)
    n = con.execute("SELECT count(*) FROM mart_weekly_diagnosis").fetchone()[0]
    nt = con.execute("SELECT count(*) FROM mart_weekly_diagnosis WHERE teacher_supply_demand IS NOT NULL").fetchone()[0]
    ng = con.execute("SELECT count(*) FROM mart_weekly_diagnosis WHERE geopolitical_risk IS NOT NULL").fetchone()[0]
    con.execute("CHECKPOINT"); con.close()
    print(f"[weekly-mart] fact_price(W)={npx} → mart_weekly_diagnosis={n}행 "
          f"(교사신호 {nt}행, 지정학지수 {ng}행{'—geo_index 미발행' if not use_geo else ''})")
    return {"rows": n, "with_teacher": nt, "with_geo": ng}


if __name__ == "__main__":
    run()
