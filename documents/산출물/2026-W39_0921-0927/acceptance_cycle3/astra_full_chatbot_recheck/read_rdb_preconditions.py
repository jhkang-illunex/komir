"""고정 라이브 사례용 독립 SQL 사전조건/정답 값. SELECT 전용 트랜잭션."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / "inhouse"))
from common.db import pg_connect

conn = pg_connect()
conn.set_session(readonly=True)
checks = {}


def query(label, sql, params=()):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        keys = [column[0] for column in cursor.description]
        rows = [dict(zip(keys, row)) for row in cursor.fetchall()]
    checks[label] = {"sql": sql, "params": params, "rows": rows}
    return rows


try:
    minerals = query("mineral_master", "SELECT mnrknd_unq_cd,mnrl_nm_ko FROM public.ai_mnrl_mst "
                     "WHERE mnrl_nm_ko IN ('동','구리','니켈','코발트','리튬','희토류','네오디뮴') ORDER BY 1")
    for mineral in minerals:
        code, name = mineral["mnrknd_unq_cd"], mineral["mnrl_nm_ko"]
        query("price_" + name + "_" + code,
              "SELECT m.mnrl_prc_crtr_sn,c.prc_crtr,c.prc_unit_cd,c.weig_unit_cd," 
              "count(p.*) AS rows,min(p.crtr_ymd) AS first,max(p.crtr_ymd) AS last "
              "FROM public.ai_prc_mnrl_map m JOIN public.ko_mnrl_prc_crtr c USING(mnrl_prc_crtr_sn) "
              "LEFT JOIN public.ko_mnrl_prc p USING(mnrl_prc_crtr_sn) "
              "WHERE m.mnrknd_unq_cd=%s AND m.use_yn='Y' GROUP BY 1,2,3,4 ORDER BY 1", (code,))
        hs = query("hs_" + name + "_" + code, "SELECT hs_cd FROM public.ai_hs_mnrl_map WHERE mnrknd_unq_cd=%s "
                   "AND use_yn='Y' ORDER BY hs_cd", (code,))
        values = [row["hs_cd"] for row in hs]
        if values:
            query("trade_2025_" + name + "_" + code,
                  "SELECT count(*) AS rows,min(crtr_ymd) AS first,max(crtr_ymd) AS last,"
                  "sum(incm_amt) AS imports,sum(exp_amt) AS exports FROM public.ko_cstm_cmmrc "
                  "WHERE hs_cd=ANY(%s) AND crtr_ymd BETWEEN '20250101' AND '20251231'", (values,))
            if name == "리튬":
                query("lithium_yearly_trade", "SELECT substring(crtr_ymd,1,4) AS year,sum(incm_amt) AS imports,"
                      "sum(exp_amt) AS exports FROM public.ko_cstm_cmmrc WHERE hs_cd=ANY(%s) "
                      "AND crtr_ymd BETWEEN '20240101' AND '20251231' GROUP BY 1 ORDER BY 1", (values,))
                query("lithium_china_2025", "SELECT trgt_ntn,trgt_ntn_cd,sum(incm_amt) AS imports "
                      "FROM public.ko_cstm_cmmrc WHERE hs_cd=ANY(%s) AND crtr_ymd BETWEEN '20250101' AND '20251231' "
                      "GROUP BY 1,2 ORDER BY imports DESC", (values,))
                query("lithium_rank_default", "SELECT trgt_ntn,sum(incm_amt) AS imports FROM public.ko_cstm_cmmrc "
                      "WHERE hs_cd=ANY(%s) AND crtr_ymd BETWEEN '20250701' AND '20260909' GROUP BY 1 ORDER BY 2 DESC", (values,))
        for label, table, metric in [("reserves", "ko_rsrc_burudg_quty", "burudg_quty_ton"),
                                      ("production", "ko_rsrc_prdctn_quty", "prdctn_quty_ton")]:
            query(label + "_" + name + "_" + code,
                  f"SELECT crtr_yr,ntn_eng_cd,sum({metric}) AS amount FROM public.{table} "
                  f"WHERE mnrknd_unq_cd=%s AND crtr_yr=(SELECT max(crtr_yr) FROM public.{table} WHERE mnrknd_unq_cd=%s) "
                  "GROUP BY 1,2 ORDER BY 3 DESC NULLS LAST LIMIT 6", (code, code))
    query("hs2603000000", "SELECT min(crtr_ymd) AS first,max(crtr_ymd) AS last,sum(incm_amt) AS imports,"
          "sum(incm_weig) AS import_weight FROM public.ko_cstm_cmmrc WHERE hs_cd='2603000000'")
    query("future_prices", "SELECT count(*) AS rows FROM public.ko_mnrl_prc WHERE crtr_ymd>='20300101'")
finally:
    conn.close()
    (HERE / "rdb_preconditions.json").write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(), "read_only_transaction": True, "checks": checks,
    }, ensure_ascii=False, indent=2, default=str))
print("independent SQL checks", len(checks))
