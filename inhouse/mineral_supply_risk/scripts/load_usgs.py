# -*- coding: utf-8 -*-
"""USGS 엑셀정리본(MCS) → warehouse 적재: fact_production_reserve + agg_production_hhi(⑤).

연간 발행 보고서를 연 단위 변수로 적용(2026-07-12 사용자 방침 — v1 문서 §3 변수⑤).
입력: documents/3. 생산매장량(USGS)/0. USGS_엑셀정리본_*.xlsx (피벗전용데이터 시트)
산출:
  fact_production_reserve  — 광종×국가×연도 생산·매장량(정리본이 담은 연도만; 과거 연도는
                             수집서버에서 `geo refdata`(ScienceBase) 실행 후 번들 반입으로 백필)
  agg_production_hhi       — 광종×연도 HHI(생산/매장) — weekly_mart가 ASOF로 당겨 씀

실행: MSR_DB=<warehouse> python -m scripts.load_usgs [--file <xlsx>]
"""
from __future__ import annotations
import argparse, glob, re

import duckdb
import pandas as pd

from msr.config import DB_PATH

CC_MAP = {"Copper": "CU", "Nickel": "NI", "Cobalt": "CO", "Lithium": "LI", "Rare earths": "REE"}
DEFAULT_GLOB = "/home/nuri/dev/git/ws/mine_ws/komir/documents/3. 생산매장량(USGS)/0. USGS_엑셀정리본_*.xlsx"


def _hhi(shares: pd.Series) -> float:
    s = shares.dropna().astype(float)
    s = s[s > 0]
    if s.sum() <= 0:
        return None
    p = s / s.sum()
    return float((p ** 2).sum())


def run(file: str | None = None, db: str | None = None) -> dict:
    file = file or sorted(glob.glob(DEFAULT_GLOB))[-1]
    df = pd.ExcelFile(file).parse("피벗전용데이터")
    df["COMMODITY"] = df["COMMODITY"].astype(str).str.strip()
    df = df[df["COMMODITY"].isin(CC_MAP)]
    df["commodity_code"] = df["COMMODITY"].map(CC_MAP)
    # Mine production만(정련/플랜트 제외 — 원산지 집중이 ⑤의 정의)
    df = df[df["TYPE"].astype(str).str.startswith("Mine production")]

    # 연도 컬럼 자동 탐지: "YYYY 생산", "YYYY ... 가채매장량" (개행·EST 표기 관대)
    prod_cols, rsv_cols = {}, {}
    for c in df.columns:
        s = re.sub(r"\s+", " ", str(c))
        m = re.match(r"^(20\d{2}) 생산", s)
        if m and "점유율" not in s and "순위" not in s and "계(" not in s:
            prod_cols[int(m.group(1))] = c
        m2 = re.match(r"^(20\d{2}).*가채매장량\s*$", s)
        if m2:
            rsv_cols[int(m2.group(1))] = c
    print(f"[usgs] 파일 {file.split('/')[-1]} | 생산연도 {sorted(prod_cols)} 매장연도 {sorted(rsv_cols)}")

    fact_rows, hhi_rows = [], []
    src = str(df["SOURCE"].iloc[0]) if "SOURCE" in df else "MCS"
    for cc, g in df.groupby("commodity_code"):
        for yr, col in prod_cols.items():
            vals = pd.to_numeric(g[col], errors="coerce")
            for country, v in zip(g["COUNTRY"], vals):
                if pd.notna(v):
                    fact_rows.append((cc, str(country), yr, "production", float(v), src))
            h = _hhi(vals)
            rsv_col = rsv_cols.get(yr)
            hr = _hhi(pd.to_numeric(g[rsv_col], errors="coerce")) if rsv_col else None
            if h is not None:
                # avail_date: MCS는 통상 이듬해 1~2월 발행 — 미래참조 방지 기준일
                hhi_rows.append((cc, yr, h, hr, f"{yr+1}-02-01"))
        for yr, col in rsv_cols.items():
            vals = pd.to_numeric(g[col], errors="coerce")
            for country, v in zip(g["COUNTRY"], vals):
                if pd.notna(v):
                    fact_rows.append((cc, str(country), yr, "reserves", float(v), src))

    con = duckdb.connect(db or DB_PATH)
    fact = pd.DataFrame(fact_rows, columns=["commodity_code", "country", "year", "metric", "val", "src"])
    con.register("_f", fact)
    con.execute("CREATE OR REPLACE TABLE fact_production_reserve AS SELECT * FROM _f")
    hhi = pd.DataFrame(hhi_rows, columns=["commodity_code", "year", "production_hhi",
                                           "reserve_hhi", "avail_date"])
    hhi["avail_date"] = pd.to_datetime(hhi["avail_date"]).dt.date
    con.register("_h", hhi)
    con.execute("CREATE OR REPLACE TABLE agg_production_hhi AS SELECT * FROM _h")
    con.execute("CHECKPOINT"); con.close()
    print(f"[usgs] fact_production_reserve {len(fact)}행, agg_production_hhi {len(hhi)}행")
    print(hhi.to_string(index=False))
    return {"fact": len(fact), "hhi": len(hhi)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    run(a.file, a.db)
