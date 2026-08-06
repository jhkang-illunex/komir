# -*- coding: utf-8 -*-
"""Tier1 자체수집 확장 (2026-07-24, 자체수집_추가후보_상세_260724.md 승인 실행).

수집 대상(전부 사전 접근성 실측 완료):
  1. Comtrade 공급국 물리 흐름 4종(월간, 2016~, fact_indicator src='UN_COMTRADE'):
     - NI: 인도네시아(360)→세계 수출, HS 2604(니켈광)+7501(매트) → 'ID_NI_EXPORT_*'
     - LI: 호주(36)→세계 수출, HS 253090(스포듀민 등 광물)+283691(탄산리튬) → 'AU_LI_EXPORT_*'
     - CU: 칠레(152)→세계 수출, HS 2603(구리정광) → 'CL_CU_EXPORT_*'
     - REE: 중국(156)←미얀마(104) 수입, HS 253090+2846 → 'CN_REE_IMPORT_MMR_*'
     ※ preview API 제약(period 호출당 1개) 기왕 실측 — 126개월×4흐름=504콜, 1.6초 간격.
  2. CFTC COT 코발트(188691)·리튬수산화물(189691) — disaggregated(72hh-3qpy),
     managed-money 순포지션/OI% → fact_series 'COT_CO_NETPCT_W'/'COT_LI_NETPCT_W'
     (src='CFTC_SOCRATA'). ⚠2022-11 시작 — 부분 커버리지 교란 플래그 필수.
  3. 인니 루피아 환율(생산국 통화) — ECB 교차환율(IDR/EUR ÷ USD/EUR) 주간평균
     → fact_series 'IDRUSD_W'(src='ECB_PUBLIC'). 칠레 페소는 ECB 미제공(실측) —
     칠레 중앙은행 API는 등록키 필요라 후보 보류 문서화.
  4. 중국 선물 OI(포지셔닝 대용) — akshare 신랑 연속선물 일별(NI0·CU0·LC0)의
     持仓量(OI) 주간평균 → fact_series 'SHFE_NI_OI_W'/'SHFE_CU_OI_W'/'GFEX_LC_OI_W'
     (src='SINA_FUTURES').

실행: MSR_DB=<warehouse> python -m scripts.collect_tier1_feeds
멱등: indicator 접두어/src+series 단위 DELETE 후 INSERT.
"""
from __future__ import annotations
import io, os, sys, time

import duckdb
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402
from scripts.collect_priority_feeds import (  # noqa: E402
    _comtrade_fetch, _month_batches, _aggregate_rows, upsert_indicator,
)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
SLEEP = 1.6

SUPPLY_FLOWS = [
    # (commodity, reporter, flow, cmdCodes, partner, indicator_prefix)
    ("NI", 360, "X", "2604,7501", 0, "ID_NI_EXPORT"),
    ("LI", 36, "X", "253090,283691", 0, "AU_LI_EXPORT"),
    ("CU", 152, "X", "2603", 0, "CL_CU_EXPORT"),
    ("REE", 156, "M", "253090,2846", 104, "CN_REE_IMPORT_MMR"),
]

COT_CODES = {"COT_CO_NETPCT_W": "188691", "COT_LI_NETPCT_W": "189691"}
COT_URL = ("https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
           "?cftc_contract_market_code={code}"
           "&$select=report_date_as_yyyy_mm_dd,m_money_positions_long_all,"
           "m_money_positions_short_all,open_interest_all"
           "&$order=report_date_as_yyyy_mm_dd&$limit=5000")


def collect_supply_flows(con):
    for cc, rep, flow, cmd, partner, prefix in SUPPLY_FLOWS:
        agg = {}
        for period in _month_batches(2016):
            rows = _comtrade_fetch(dict(reporterCode=rep, period=period, cmdCode=cmd,
                                        flowCode=flow, partnerCode=partner))
            for p, wv in _aggregate_rows(rows).items():
                w0, v0 = agg.get(p, (0.0, 0.0))
                agg[p] = (w0 + wv[0], v0 + wv[1])
            time.sleep(SLEEP)
        n = upsert_indicator(con, cc, agg, prefix)
        months = sorted(agg.keys())
        print(f"  {prefix}({cc}): 월 {len(agg)}개({months[0] if months else '-'}~"
              f"{months[-1] if months else '-'}) → {n}행")


def collect_cot2(con):
    for series, code in COT_CODES.items():
        r = requests.get(COT_URL.format(code=code), headers=UA, timeout=60)
        r.raise_for_status()
        d = pd.DataFrame(r.json())
        for c in ["m_money_positions_long_all", "m_money_positions_short_all",
                  "open_interest_all"]:
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d["obs_date"] = pd.to_datetime(d["report_date_as_yyyy_mm_dd"]).dt.date
        d["val"] = ((d["m_money_positions_long_all"] - d["m_money_positions_short_all"])
                    / d["open_interest_all"].replace(0, pd.NA)) * 100.0
        out = pd.DataFrame({"series_code": series, "obs_date": d["obs_date"],
                            "val": pd.to_numeric(d["val"], errors="coerce"),
                            "unit": "%OI", "src": "CFTC_SOCRATA"}).dropna(subset=["val"])
        out = out.drop_duplicates(subset=["series_code", "obs_date"])
        con.execute("DELETE FROM fact_series WHERE series_code = ?", [series])
        con.register("_c", out)
        con.execute("INSERT INTO fact_series SELECT * FROM _c")
        con.unregister("_c")
        print(f"  {series}: {len(out)}주 ({out['obs_date'].min()}~{out['obs_date'].max()})")


def collect_idr(con):
    def ecb(cur):
        url = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"
               f"?format=csvdata&startPeriod=2006-01-01")
        r = requests.get(url, headers=UA, timeout=90)
        r.raise_for_status()
        c = pd.read_csv(io.StringIO(r.text))
        return pd.DataFrame({"d": pd.to_datetime(c["TIME_PERIOD"]),
                             "v": pd.to_numeric(c["OBS_VALUE"], errors="coerce")}).dropna()
    usd, idr = ecb("USD"), ecb("IDR")
    x = usd.merge(idr, on="d", suffixes=("_usd", "_idr"))
    x["v"] = x["v_idr"] / x["v_usd"]
    x["wk"] = x["d"] - pd.to_timedelta(x["d"].dt.weekday, unit="D")
    wk = x.groupby("wk", as_index=False)["v"].mean()
    out = pd.DataFrame({"series_code": "IDRUSD_W", "obs_date": wk["wk"].dt.date,
                        "val": wk["v"].astype(float), "unit": "IDR", "src": "ECB_PUBLIC"})
    con.execute("DELETE FROM fact_series WHERE series_code='IDRUSD_W'")
    con.register("_i", out)
    con.execute("INSERT INTO fact_series SELECT * FROM _i")
    con.unregister("_i")
    print(f"  IDRUSD_W: {len(out)}주 ({out['obs_date'].min()}~{out['obs_date'].max()})")


def collect_cn_oi(con):
    import akshare as ak
    for series, sym in [("SHFE_NI_OI_W", "NI0"), ("SHFE_CU_OI_W", "CU0"),
                        ("GFEX_LC_OI_W", "LC0")]:
        try:
            d = ak.futures_zh_daily_sina(symbol=sym)
        except Exception as e:
            print(f"  {series}: 수집 실패({type(e).__name__}) — 건너뜀")
            continue
        d["date"] = pd.to_datetime(d["date"])
        d["oi"] = pd.to_numeric(d["hold"], errors="coerce")
        d = d.dropna(subset=["oi"])
        d["wk"] = d["date"] - pd.to_timedelta(d["date"].dt.weekday, unit="D")
        wk = d.groupby("wk", as_index=False)["oi"].mean()
        out = pd.DataFrame({"series_code": series, "obs_date": wk["wk"].dt.date,
                            "val": wk["oi"].astype(float), "unit": "lots",
                            "src": "SINA_FUTURES"})
        con.execute("DELETE FROM fact_series WHERE series_code = ?", [series])
        con.register("_o", out)
        con.execute("INSERT INTO fact_series SELECT * FROM _o")
        con.unregister("_o")
        print(f"  {series}: {len(out)}주 ({out['obs_date'].min()}~{out['obs_date'].max()})")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-comtrade", action="store_true",
                    help="주간 cron용 경량 모드(월간 그레인 Comtrade 생략)")
    a = ap.parse_args()
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)
    if a.skip_comtrade:
        print("[1/4] Comtrade 생략(--skip-comtrade)")
    else:
        print("[1/4] Comtrade 공급국 흐름 4종(504콜, ~15분)")
        collect_supply_flows(con)
    print("[2/4] CFTC 코발트·리튬 COT")
    collect_cot2(con)
    print("[3/4] ECB 인니 루피아")
    collect_idr(con)
    print("[4/4] 중국 선물 OI(NI·CU·LC)")
    collect_cn_oi(con)
    con.close()
    print("완료")


if __name__ == "__main__":
    main()
