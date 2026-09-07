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
from db.dbio import is_url

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
  {PROD_COL},
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
{PROD_JOIN}
"""

# 주의: 이 치환 문자열 뒤에 템플릿의 쉼표가 바로 붙으므로 SQL 인라인 주석(--) 금지
# (주석이 쉼표를 삼켜 ParserException — 실측 2026-07-08).
_GEO_COL_NULL = "CAST(NULL AS DOUBLE) AS geopolitical_risk"
_GEO_COL_JOIN = "CAST(g.idx_value AS DOUBLE) AS geopolitical_risk"
# 변수⑤(2026-07-12): 연간 발행 USGS를 연 단위 적용 — scripts/load_usgs.py 산출 테이블을
# ASOF로 당김(발행 가용일 이전 행은 NULL 유지 = 미래참조 없음. 2016~23 백필은 수집서버
# geo refdata 실행 후 번들 반입).
_PROD_COL_NULL = "CAST(NULL AS DOUBLE) AS production_hhi"
_PROD_COL_JOIN = "CAST(ph.production_hhi AS DOUBLE) AS production_hhi"
_PROD_JOIN = """ASOF LEFT JOIN (
  SELECT commodity_code, production_hhi, CAST(avail_date AS DATE) AS avail_date
  FROM agg_production_hhi
) ph ON v.commodity_code = ph.commodity_code AND v.obs_date >= ph.avail_date"""
_GEO_JOIN = """ASOF LEFT JOIN (
  SELECT commodity_code, CAST(period AS DATE) AS period, idx_value
  FROM geo_index WHERE freq='W'
) g ON v.commodity_code = g.commodity_code AND v.obs_date >= g.period"""

# ── postgres(URL) 대상 — 2026-08-19 postgres cutover ──────────────────────
# ASOF JOIN은 duckdb 전용(표준 SQL도 postgres도 지원 안 함) — LEFT JOIN LATERAL
# (파티션키 일치 + 날짜 이하 중 최신 1행)로 치환. 라이브 duckdb 데이터로 원본
# ASOF 쿼리와 결과가 완전히 일치함을 4621행 전 컬럼 실측 검증했다(스칼라·NULL
# 위치까지 동일) — 이하 템플릿은 그 검증을 통과한 형태 그대로.
_DDL_TMPL_PG = """
CREATE TABLE mart_weekly_diagnosis AS
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
cash AS (SELECT commodity_code,obs_date,val FROM fact_price WHERE price_type='LME_CASH' AND freq='W'),
m3 AS (SELECT commodity_code,obs_date,val FROM fact_price WHERE price_type='LME_3M' AND freq='W'),
spread AS (
  SELECT c.commodity_code, c.obs_date, (c.val - m.val)/NULLIF(m.val,0)*100 AS spread_pct
  FROM cash c
  LEFT JOIN LATERAL (
    SELECT val FROM m3
    WHERE m3.commodity_code = c.commodity_code AND m3.obs_date <= c.obs_date
    ORDER BY m3.obs_date DESC LIMIT 1
  ) m ON true
),
teacher AS (
  SELECT commodity_code, obs_date, val FROM fact_indicator WHERE indicator='SUPPLY_DEMAND'
)
SELECT
  v.commodity_code, v.obs_date, EXTRACT(YEAR FROM v.obs_date)::int AS yr,
  v.ref_price, v.logret, v.volatility_12w,
  s.spread_pct,
  ta.import_hhi, ta.import_yoy, ta.import_cagr3,
  {PROD_COL},
  {GEO_COL},
  CAST(NULL AS DOUBLE PRECISION) AS geo_macro,
  t.val AS teacher_supply_demand
FROM vol v
LEFT JOIN spread s USING(commodity_code, obs_date)
LEFT JOIN LATERAL (
  SELECT import_hhi, import_yoy, import_cagr3
  FROM agg_trade_annual ta2
  WHERE ta2.commodity_code = v.commodity_code AND ta2.avail_date <= v.obs_date
  ORDER BY ta2.avail_date DESC LIMIT 1
) ta ON true
LEFT JOIN LATERAL (
  SELECT val FROM teacher t2
  WHERE t2.commodity_code = v.commodity_code AND t2.obs_date <= v.obs_date
  ORDER BY t2.obs_date DESC LIMIT 1
) t ON true
{GEO_JOIN}
{PROD_JOIN}
"""
_GEO_COL_JOIN_PG = "CAST(g.idx_value AS DOUBLE PRECISION) AS geopolitical_risk"
_PROD_COL_JOIN_PG = "CAST(ph.production_hhi AS DOUBLE PRECISION) AS production_hhi"
# postgres는 duckdb의 CAST(... AS DOUBLE)을 모른다("type "double" does not exist") — 위
# _GEO_COL_NULL/_PROD_COL_NULL(duckdb용)과 별도로 PG 폴백 상수를 둔다.
_GEO_COL_NULL_PG = "CAST(NULL AS DOUBLE PRECISION) AS geopolitical_risk"
_PROD_COL_NULL_PG = "CAST(NULL AS DOUBLE PRECISION) AS production_hhi"
_GEO_JOIN_PG = """LEFT JOIN LATERAL (
  SELECT idx_value FROM (
    SELECT commodity_code, CAST(period AS DATE) AS period, idx_value
    FROM geo_index WHERE freq='W'
  ) gg
  WHERE gg.commodity_code = v.commodity_code AND gg.period <= v.obs_date
  ORDER BY gg.period DESC LIMIT 1
) g ON true"""
_PROD_JOIN_PG = """LEFT JOIN LATERAL (
  SELECT production_hhi FROM (
    SELECT commodity_code, production_hhi, CAST(avail_date AS DATE) AS avail_date
    FROM agg_production_hhi
  ) ph2
  WHERE ph2.commodity_code = v.commodity_code AND ph2.avail_date <= v.obs_date
  ORDER BY ph2.avail_date DESC LIMIT 1
) ph ON true"""


def _has_table(con, name: str) -> bool:
    return con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [name]).fetchone()[0] > 0


def _has_geo_index(con) -> bool:
    n = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name='geo_index'").fetchone()[0]
    if not n:
        return False
    return con.execute("SELECT count(*) FROM geo_index WHERE freq='W'").fetchone()[0] > 0


def run(db=None):
    db = db or DB_PATH
    if is_url(db):
        return _run_pg(db)
    con = duckdb.connect(db)
    # 가격 데이터 유무 확인(없으면 빈 마트 생성)
    npx = con.execute("SELECT count(*) FROM fact_price WHERE freq='W'").fetchone()[0]
    use_geo = _has_geo_index(con)
    use_prod = _has_table(con, "agg_production_hhi")
    ddl = _DDL_TMPL.format(
        GEO_COL=_GEO_COL_JOIN if use_geo else _GEO_COL_NULL,
        GEO_JOIN=_GEO_JOIN if use_geo else "",
        PROD_COL=_PROD_COL_JOIN if use_prod else _PROD_COL_NULL,
        PROD_JOIN=_PROD_JOIN if use_prod else "",
    )
    con.execute(ddl)
    n = con.execute("SELECT count(*) FROM mart_weekly_diagnosis").fetchone()[0]
    nt = con.execute("SELECT count(*) FROM mart_weekly_diagnosis WHERE teacher_supply_demand IS NOT NULL").fetchone()[0]
    ng = con.execute("SELECT count(*) FROM mart_weekly_diagnosis WHERE geopolitical_risk IS NOT NULL").fetchone()[0]
    np_ = con.execute("SELECT count(*) FROM mart_weekly_diagnosis WHERE production_hhi IS NOT NULL").fetchone()[0]
    con.execute("CHECKPOINT"); con.close()
    print(f"[weekly-mart] fact_price(W)={npx} → mart_weekly_diagnosis={n}행 "
          f"(교사신호 {nt}, 지정학지수 {ng}{'—geo_index 미발행' if not use_geo else ''}, "
          f"생산HHI {np_}{'—usgs 미적재' if not use_prod else ''})")
    return {"rows": n, "with_teacher": nt, "with_geo": ng, "with_prod_hhi": np_}


def _run_pg(db):
    """postgres(URL) 대상 — LATERAL 치환판 DDL(_DDL_TMPL_PG) 사용. duckdb 분기와 동일한
    use_geo/use_prod 존재확인 로직이되, `information_schema.tables WHERE table_name=X`가
    스키마 무관 매칭이라(postgres는 여러 스키마가 보일 수 있음) `to_regclass()`(search_path
    인지)로 바꿨다."""
    import sqlalchemy as sa
    eng = sa.create_engine(db)
    with eng.begin() as conn:
        npx = conn.execute(sa.text("SELECT count(*) FROM fact_price WHERE freq='W'")).scalar()
        has_geo_idx = bool(conn.execute(sa.text("SELECT to_regclass('geo_index') IS NOT NULL")).scalar())
        use_geo = has_geo_idx and bool(conn.execute(
            sa.text("SELECT count(*) FROM geo_index WHERE freq='W'")).scalar())
        use_prod = bool(conn.execute(sa.text("SELECT to_regclass('agg_production_hhi') IS NOT NULL")).scalar())
        ddl = _DDL_TMPL_PG.format(
            GEO_COL=_GEO_COL_JOIN_PG if use_geo else _GEO_COL_NULL_PG,
            GEO_JOIN=_GEO_JOIN_PG if use_geo else "",
            PROD_COL=_PROD_COL_JOIN_PG if use_prod else _PROD_COL_NULL_PG,
            PROD_JOIN=_PROD_JOIN_PG if use_prod else "",
        )
        conn.execute(sa.text("DROP TABLE IF EXISTS mart_weekly_diagnosis"))
        conn.execute(sa.text(ddl))
        n = conn.execute(sa.text("SELECT count(*) FROM mart_weekly_diagnosis")).scalar()
        nt = conn.execute(sa.text(
            "SELECT count(*) FROM mart_weekly_diagnosis WHERE teacher_supply_demand IS NOT NULL")).scalar()
        ng = conn.execute(sa.text(
            "SELECT count(*) FROM mart_weekly_diagnosis WHERE geopolitical_risk IS NOT NULL")).scalar()
        np_ = conn.execute(sa.text(
            "SELECT count(*) FROM mart_weekly_diagnosis WHERE production_hhi IS NOT NULL")).scalar()
    print(f"[weekly-mart] fact_price(W)={npx} → mart_weekly_diagnosis={n}행 "
          f"(교사신호 {nt}, 지정학지수 {ng}{'—geo_index 미발행' if not use_geo else ''}, "
          f"생산HHI {np_}{'—usgs 미적재' if not use_prod else ''})")
    return {"rows": n, "with_teacher": nt, "with_geo": ng, "with_prod_hhi": np_}


if __name__ == "__main__":
    run()
