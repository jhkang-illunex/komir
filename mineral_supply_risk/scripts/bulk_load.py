# -*- coding: utf-8 -*-
"""정형 데이터 벌크 입력 인터페이스 (CSV/Excel/Parquet → 임의 테이블).
API 외 수기·외부 제공 데이터를 매핑으로 적재. DuckDB 및 서버DB(SQLAlchemy) 공용.

  python -m scripts.bulk_load --file 수입.xlsx --table fact_trade_monthly \
      --map map.yaml [--db <target>] [--sheet 0] [--if-exists append] [--dry-run]

map.yaml 예:
  columns:            # 원본컬럼 → 대상컬럼
    연도: yr
    월: mon
    HS부호: hs10
    국가: country
    수입금액: imp_usd
  const:              # 고정값 주입
    src: "수기입력"
  keep_unmapped: false
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from msr.config import DB_PATH
from db import dbio

try:
    import yaml
except ImportError:
    yaml = None


def read_any(path, sheet=0):
    low = path.lower()
    if low.endswith((".csv", ".tsv")):
        return pd.read_csv(path, sep=("\t" if low.endswith(".tsv") else ","), dtype=str)
    if low.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, sheet_name=int(sheet) if str(sheet).isdigit() else sheet, dtype=str)
    if low.endswith(".parquet"):
        return pd.read_parquet(path)
    raise ValueError(f"지원 형식 아님: {path}")


def apply_map(df, mp):
    cols = mp.get("columns", {}) if mp else {}
    const = mp.get("const", {}) if mp else {}
    keep = bool(mp.get("keep_unmapped", False)) if mp else True
    out = df.rename(columns=cols)
    if cols and not keep:
        dest = list(cols.values())
        out = out[[c for c in dest if c in out.columns]]
    for k, v in const.items():
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--map", default=None, help="컬럼 매핑 yaml")
    ap.add_argument("--db", default=DB_PATH, help="대상 DB(파일경로 또는 SQLAlchemy URL)")
    ap.add_argument("--sheet", default="0")
    ap.add_argument("--if-exists", default="append", choices=["append", "replace"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    df = read_any(a.file, a.sheet)
    mp = yaml.safe_load(open(a.map, encoding="utf-8")) if (a.map and yaml) else None
    out = apply_map(df, mp)
    print(f"[bulk] {a.file} → {a.table} @ {a.db}")
    print(f"  행 {len(out)} · 컬럼 {list(out.columns)}")
    print(out.head(5).to_string(index=False))
    if a.dry_run:
        print("  (dry-run: 적재 안 함)"); return
    n = dbio.write_df(out, a.table, a.db, if_exists=a.if_exists)
    print(f"  적재 완료: {n}행")


if __name__ == "__main__":
    main()
