# -*- coding: utf-8 -*-
"""예측·진단 결과를 외부(운영) DB로 발행 — 접속 URL·스키마는 env에서 주입.

  MSR_PUBLISH_DB      대상 DB. '://' 포함=SQLAlchemy URL(Oracle/MariaDB/MSSQL/PG…),
                      아니면 DuckDB 파일 경로.
  MSR_PUBLISH_SCHEMA  (선택) 대상 스키마/데이터베이스명.
  MSR_DB              원천 warehouse(기본 로컬 DuckDB).

발행 테이블(근거 포함 — 2026-07-12 요구 "예측 결과도 DB화, 근거도 같이"):
  out_diagnosis_alert     주간 4단계 경보 + 사유(법정 문안·모델 원천·확률·기여·이벤트 인용)
  mart_diagnosis_nowcast  진단 nowcast + XAI(단계확률·기여도 json)
  out_import_forecast     수입 예측(h=1~12) — 존재 시
  geo_index / geo_prob    지정학 지수·확률 — 존재 시(geo publish와 동일 계약)

실행: MSR_PUBLISH_DB='mariadb+pymysql://u:p@host/db' MSR_PUBLISH_SCHEMA=komis \\
        python -m scripts.publish_results
"""
from __future__ import annotations
import os, sys

import duckdb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db.dbio import write_df                     # noqa: E402
from msr.config import DB_PATH                   # noqa: E402

TABLES = ["out_diagnosis_alert", "mart_diagnosis_nowcast", "out_import_forecast",
          "out_import_forecast_unit", "geo_index", "geo_prob"]


def run(target: str | None = None, schema: str | None = None, source: str | None = None) -> dict:
    target = target or os.environ.get("MSR_PUBLISH_DB")
    schema = schema or os.environ.get("MSR_PUBLISH_SCHEMA") or None
    source = source or DB_PATH
    if not target:
        print("[publish-results] MSR_PUBLISH_DB 미설정 — 발행 생략(로컬 warehouse만 유지)")
        return {}
    con = duckdb.connect(source, read_only=True)
    have = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    out = {}
    for tbl in TABLES:
        if tbl not in have:
            print(f"  [skip] {tbl} — 원천에 없음")
            continue
        df = con.execute(f'SELECT * FROM "{tbl}"').df()
        n = write_df(df, tbl, target, if_exists="replace", schema=schema)
        out[tbl] = n
        print(f"  [publish] {tbl}: {n}행 → {target.split('@')[-1] if '://' in target else target}"
              + (f" (schema={schema})" if schema else ""))
    con.close()
    print(f"[publish-results] 완료: {out}")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="대상(기본 env MSR_PUBLISH_DB)")
    ap.add_argument("--schema", default=None, help="대상 스키마(기본 env MSR_PUBLISH_SCHEMA)")
    ap.add_argument("--source", default=None, help="원천 warehouse(기본 env MSR_DB)")
    a = ap.parse_args()
    run(a.db, a.schema, a.source)
