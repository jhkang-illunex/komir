# -*- coding: utf-8 -*-
"""관세청 수집분 검증 — 로컬에서 실행: python -m scripts.verify_customs
   행수·기간·HS 커버리지·cnt(=1000) 절단위험·광종 매핑 결측을 점검."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import duckdb
from msr.config import DB_PATH, HS_MAP_CSV
from msr.preprocess.hs_mapping import core_hs_list

CNT = 1000  # customs_api.fetch_one 의 cnt 상한
c = duckdb.connect(DB_PATH, read_only=True)

n = c.execute("select count(*) from raw_customs_monthly").fetchone()[0]
print(f"총 행수: {n:,}")
print("기간(year):", c.execute("select min(year), max(year) from raw_customs_monthly").fetchone())
print("distinct hs_query:", c.execute("select count(distinct hs_query) from raw_customs_monthly").fetchone()[0],
      "/ 목표 core5:", len(core_hs_list()))
print("distinct 국가:", c.execute("select count(distinct country) from raw_customs_monthly").fetchone()[0])

print("\n-- 연도별 행수 --")
print(c.execute("select year, count(*) n from raw_customs_monthly group by 1 order by 1").df().to_string(index=False))

# cnt 절단위험: (hs_query, year) 그룹이 상한에 근접
print(f"\n-- cnt(={CNT}) 절단위험: (hs_query,year) 행수 상위 --")
print(c.execute(f"""
  select hs_query, year, count(*) as n_rows
  from raw_customs_monthly group by 1,2
  having count(*) >= {int(CNT*0.98)} order by n_rows desc limit 20
""").df().to_string(index=False))

# 수집됐어야 하나 0행인 HS(무교역 or 누락)
got = set(r[0] for r in c.execute("select distinct hs_query from raw_customs_monthly").fetchall())
missing = [h for h in core_hs_list() if h not in got]
print(f"\n-- 수집 0행 HS: {len(missing)}개 --")
print(missing[:30])

# 광종 매핑 결측: hscode가 매핑표에 없는 비율 (타입 안전하게 파이썬 비교)
m = duckdb.sql(f"select cast(hs10 as varchar) hs10 from read_csv_auto('{HS_MAP_CSV}', header=true, all_varchar=true)").df()
mapset = set(str(x).strip() for x in m['hs10'])
cnts = c.execute("select cast(hscode as varchar) h, count(*) c from raw_customs_monthly group by 1").fetchall()
miss_map = sum(cc for h, cc in cnts if str(h).strip() not in mapset)
print(f"\n광종 매핑 미일치 행수: {miss_map:,} / {n:,}  ({miss_map/max(n,1)*100:.1f}%)")
c.close()
