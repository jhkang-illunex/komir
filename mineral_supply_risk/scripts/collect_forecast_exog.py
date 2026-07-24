# -*- coding: utf-8 -*-
"""예측모델(2-4) 외생피처 수집기 — CFTC COT 구리 포지셔닝 + WoodMac 연간 수급밸런스
(2026-07-24, 피처 인벤토리 C단계).

1. CFTC COT(구리, COMEX 085692) — 공개 Socrata API(publicreporting.cftc.gov,
   무키·무제한급), 주간(화요일 기준·금요일 발표). 비상업(투기) 순포지션/미결제약정
   비율을 저장 → fact_series 'COT_CU_NETPCT_W'(src='CFTC_SOCRATA').
2. WoodMac 연간 수급밸런스 — 사내 보유 parquet(2026-03 빈티지, CU·NI)에서
   ⚠ **단일 빈티지 한계**: 과거 연도 값도 2026년 시점에 개정된 값이라 엄밀한
   as-of가 불가(전망 개정 이력 미보유). 백테스트 해석 시 "방향 참고" 플래그 필수.
   - NI: GlobalBalance 'Balance'(kt) · '- in days of Consumption'(재고일수)
   - CU: Global 'Change in Metal Stocks'(kt, 밸런스 대용) · 'Metal Stocks-days of
     Consumption'(재고일수)
   → fact_indicator (indicator 'WM_BALANCE_A'/'WM_STOCKDAYS_A', freq='A',
     src='WOODMAC_2026V', obs_date=해당연도 1월 1일)

실행: MSR_DB=<warehouse> python -m scripts.collect_forecast_exog
"""
from __future__ import annotations
import os, sys
import datetime as dt

import duckdb
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

COT_URL = ("https://publicreporting.cftc.gov/resource/6dca-aqww.json"
           "?cftc_contract_market_code=085692"
           "&$select=report_date_as_yyyy_mm_dd,noncomm_positions_long_all,"
           "noncomm_positions_short_all,open_interest_all"
           "&$order=report_date_as_yyyy_mm_dd&$limit=5000")
WM_PARQUET = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..",
    "documents", "산출물", "2026-W28_0706-0712", "reports", "woodmac_series.parquet"))

WM_LINES = {   # (commodity, sheet, line_item) → indicator
    ("NI", "GlobalBalance", "Balance"): "WM_BALANCE_A",
    ("NI", "GlobalBalance", "- in days of Consumption"): "WM_STOCKDAYS_A",
    ("CU", "Global", "Change in Metal Stocks"): "WM_BALANCE_A",
    ("CU", "Global", "Metal Stocks-days of Consumption"): "WM_STOCKDAYS_A",
}


def collect_cot() -> pd.DataFrame:
    r = requests.get(COT_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    d = pd.DataFrame(r.json())
    for c in ["noncomm_positions_long_all", "noncomm_positions_short_all",
              "open_interest_all"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["obs_date"] = pd.to_datetime(d["report_date_as_yyyy_mm_dd"]).dt.date
    d["val"] = ((d["noncomm_positions_long_all"] - d["noncomm_positions_short_all"])
                / d["open_interest_all"].replace(0, pd.NA)) * 100.0
    out = pd.DataFrame({"series_code": "COT_CU_NETPCT_W", "obs_date": d["obs_date"],
                        "val": pd.to_numeric(d["val"], errors="coerce"),
                        "unit": "%OI", "src": "CFTC_SOCRATA"})
    return out.dropna(subset=["val"]).drop_duplicates(subset=["series_code", "obs_date"])


def collect_wm() -> pd.DataFrame:
    w = pd.read_parquet(WM_PARQUET)
    rows = []
    for (cc, sheet, line), ind in WM_LINES.items():
        sub = w[(w["commodity"] == cc) & (w["sheet"] == sheet) & (w["line_item"] == line)]
        for _, r in sub.iterrows():
            y = int(r["year"])
            v = pd.to_numeric(r["value"], errors="coerce")
            if pd.notna(v) and 1990 <= y <= 2040:
                rows.append((cc, ind, "A", dt.date(y, 1, 1), float(v), "WOODMAC_2026V"))
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    return df.drop_duplicates(subset=["commodity_code", "indicator", "obs_date"], keep="last")


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)
    cot = collect_cot()
    con.execute("DELETE FROM fact_series WHERE src='CFTC_SOCRATA'")
    con.register("_c", cot)
    con.execute("INSERT INTO fact_series SELECT * FROM _c")
    con.unregister("_c")
    print(f"COT: {len(cot)}행 ({cot['obs_date'].min()}~{cot['obs_date'].max()})")

    wm = collect_wm()
    con.execute("DELETE FROM fact_indicator WHERE src='WOODMAC_2026V'")
    con.register("_w", wm)
    con.execute("INSERT INTO fact_indicator SELECT * FROM _w")
    con.unregister("_w")
    print(wm.groupby(["commodity_code", "indicator"])
          .agg(n=("val", "size"), y0=("obs_date", "min"), y1=("obs_date", "max"))
          .to_string())
    con.close()


if __name__ == "__main__":
    main()
