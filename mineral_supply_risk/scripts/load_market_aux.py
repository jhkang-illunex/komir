# -*- coding: utf-8 -*-
"""발주처 원본(documents/2차_데이타)의 미활용 시장·거시 데이터를 warehouse DB에 적재
(2026-07-24, /goal "현재 데이터 외 필요한 정보 확보→모델링 반영" 1단계).

적재 대상(y_lag1 심층검토가 지목한 '외부 직교 정보원' 후보 — 전부 발주처가 이미 준
파일인데 진단모델 피처로 한 번도 쓰인 적 없음):
  1. fact_inventory ← `1. 주간가격및재고량_{동,니켈}.xlsx`의 LME재고량
     (주간, 2007-01-08~, CU·NI만 — 발주처 원본에 CO/LI/REE 재고는 없음)
  2. fact_series ← 거시 CSV 12종(주간 2021-06~ / 월간 2016-01~):
     BDI·달러인덱스·환율3종·미국금리/스트레스4종·중국 경기선행/산업생산 +
     원자재지수 3종(가격지수 — 라벨 오염 경계, series_code에 PRICEIDX_ 접두어로 격리)

시점 규약: 파일의 날짜를 그대로 obs_date로 저장(값이 무엇의 시점인지 원본 보존).
누수 방지 시프트(주간 +1주, 월간 +45일 등)는 적재가 아니라 **피처 생성 단계**에서 적용.

실행: MSR_DB=<warehouse> python -m scripts.load_market_aux
멱등: src/series_code 단위 DELETE 후 INSERT.
"""
from __future__ import annotations
import os, sys, glob

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

ROOT = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "documents", "2차_데이타", "1. 정형데이터",
    "1. 광물가격, 재고량, 지수, 거시경제 데이터 등"))

INV_FILES = {"CU": "1. 주간가격및재고량_동.xlsx", "NI": "1. 주간가격및재고량_니켈.xlsx"}

# (파일명, series_code, 단위) — PRICEIDX_ 접두어 = 가격지수(라벨 오염 경계, 주모델 금지)
SERIES_FILES = [
    ("2. Baltic Dry Index.csv",        "BDI_W",             "Index"),
    ("2. Bloomberg 원자재지수.csv",      "PRICEIDX_BBG_W",    "Index"),
    ("2. Reuters 원자재지수.csv",        "PRICEIDX_RTR_W",    "Index"),
    ("2. S&P 원자재지수.csv",           "PRICEIDX_SP_W",     "Index"),
    ("3. 달러인덱스.csv",               "DXY_W",             "Index"),
    ("3. 미달러 유로화 환율.csv",         "USDEUR_W",          "Rate"),
    ("3. 원달러 환율.csv",              "USDKRW_W",          "KRW"),
    ("3. 위안화 달러 환율.csv",          "CNYUSD_W",          "Rate"),
    ("4. 미국 10년만기 국채수익률.csv",    "UST10Y_W",          "%"),
    ("4. 미국 금융스트레스 지수.csv",      "STLFSI_W",          "Index"),
    ("4. 미국 기준금리.csv",            "FEDFUNDS_W",        "%"),
    ("4. 미국 장단기 국채 스프레드.csv",   "UST10Y2Y_W",        "%p"),
    ("5. 중국 경기선행지수.csv",         "CN_LEADING_M",      "Index"),
    ("5. 중국 산업생산 증가율.csv",       "CN_INDPROD_M",      "%"),
]


def load_inventory(con: duckdb.DuckDBPyConnection) -> int:
    rows = []
    for cc, fname in INV_FILES.items():
        x = pd.read_excel(os.path.join(ROOT, fname), header=2)
        x["기준일"] = pd.to_datetime(x["기준일"], format="%Y%m%d", errors="coerce")
        x["LME재고량"] = pd.to_numeric(x["LME재고량"], errors="coerce")
        x = x.dropna(subset=["기준일", "LME재고량"])
        for _, r in x.iterrows():
            rows.append((cc, r["기준일"].date(), float(r["LME재고량"]), "ton", "KOMIS_WEEKLY_LME"))
    df = pd.DataFrame(rows, columns=["commodity_code", "obs_date", "val", "unit", "src"])
    con.execute("DELETE FROM fact_inventory WHERE src = 'KOMIS_WEEKLY_LME'")
    con.register("_inv", df)
    con.execute("INSERT INTO fact_inventory SELECT * FROM _inv")
    con.unregister("_inv")
    return len(df)


def load_series(con: duckdb.DuckDBPyConnection) -> int:
    total = 0
    for fname, code, unit in SERIES_FILES:
        path = os.path.join(ROOT, fname)
        try:
            c = pd.read_csv(path, skiprows=1)
        except UnicodeDecodeError:
            c = pd.read_csv(path, skiprows=1, encoding="cp949")
        d = pd.to_datetime(c.iloc[:, 0], errors="coerce")
        v = pd.to_numeric(c.iloc[:, 1], errors="coerce")
        ok = d.notna() & v.notna()
        df = pd.DataFrame({"series_code": code, "obs_date": d[ok].dt.date,
                           "val": v[ok].astype(float), "unit": unit,
                           "src": "KOMIS_MARKET_AUX"})
        df = df.drop_duplicates(subset=["series_code", "obs_date"])
        con.execute("DELETE FROM fact_series WHERE series_code = ?", [code])
        con.register("_ser", df)
        con.execute("INSERT INTO fact_series SELECT * FROM _ser")
        con.unregister("_ser")
        print(f"  {code}: {len(df)}행 ({df['obs_date'].min()}~{df['obs_date'].max()})")
        total += len(df)
    return total


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)
    n_inv = load_inventory(con)
    print(f"fact_inventory: {n_inv}행 적재(CU·NI LME재고)")
    n_ser = load_series(con)
    print(f"fact_series: 총 {n_ser}행 적재")
    con.close()


if __name__ == "__main__":
    main()
