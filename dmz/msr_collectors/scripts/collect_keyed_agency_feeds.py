# -*- coding: utf-8 -*-
"""DMZ 측 — 키가 필요한 해외기관 무역통계 수집(Census·BPS), 2026-08-06 물리분리 리팩터.

원본은 `inhouse/mineral_supply_risk/scripts/collect_intl_agency_feeds.py`의
`collect_census_us`/`collect_bps_id`(CENSUS_API_KEY·BPS_API_KEY 필요) — 그 외 8개 소스
(BCRP·ABS·PSA·GACC·MOFCOM·FedReg·HTS·ARCA)는 전부 무키라 이번 리팩터 대상 아님
(in-house에 그대로 남음, 별도 사이클에서 처리).

fetch 로직은 원본과 동일(HTTP 호출 부분 그대로 복사) — 차이는 `_upsert_indicator(con, ...)`
직접 호출 대신 `_file_sink.save_parquet`로 로컬 parquet에 떨어뜨리는 것뿐. in-house 쪽은
`inhouse/mineral_supply_risk/scripts/collect_intl_agency_feeds.py`가 이 parquet을 읽어
그대로 `_upsert_indicator`를 호출한다(로직 무변경).

실행: cd komir/dmz && python -m msr_collectors.scripts.collect_keyed_agency_feeds [census|bps|all]
"""
from __future__ import annotations
import datetime as dt
import re
import sys
import time

import pandas as pd
import requests

from .._file_sink import save_parquet
from ..config import COLLECT_OUT

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 "
                    "Firefox/127.0"}

# ─────────────── 미국 Census 무역통계(CBP 대체, 키필요) — 원본과 동일 상수 ───────────────
CENSUS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
CENSUS_HS4 = [
    ("CU", "2603", "US_CU_ORE_IMPORT"), ("CU", "7403", "US_CU_REFINED_IMPORT"),
    ("NI", "2604", "US_NI_ORE_IMPORT"), ("NI", "7502", "US_NI_UNWROUGHT_IMPORT"),
    ("CO", "8105", "US_CO_IMPORT"),
    ("LI", "2836", "US_LI_CARBONATE_IMPORT"),
    ("LI", "2530", "US_LI_ORE_IMPORT"),
    ("REE", "2805", "US_REE_METAL_IMPORT"), ("REE", "2846", "US_REE_COMPOUND_IMPORT"),
]
CENSUS_START = "2013-01"


def fetch_census(key: str) -> pd.DataFrame:
    today = dt.date.today()
    end = f"{today.year}-{today.month:02d}"
    rows = []
    for cc, hs4, pre in CENSUS_HS4:
        r = requests.get(CENSUS_URL, params={
            "get": "GEN_VAL_MO,DUT_VAL_MO", "COMM_LVL": "HS4",
            "I_COMMODITY": hs4, "time": f"from {CENSUS_START} to {end}",
            "key": key}, headers=UA, timeout=90)
        if r.status_code != 200:
            print(f"  [warn] Census HS4={hs4} HTTP {r.status_code} — 건너뜀")
            continue
        data = r.json()
        for val, dut, _lvl, _code, tm in data[1:]:
            m = re.match(r"^(\d{4})-(\d{2})$", tm)
            if not m:
                continue
            d = dt.date(int(m.group(1)), int(m.group(2)), 1)
            if val not in (None, ""):
                rows.append((cc, f"{pre}_VAL", "M", d, float(val), "CENSUS_API"))
            if dut not in (None, ""):
                rows.append((cc, f"{pre}_DUT", "M", d, float(dut), "CENSUS_API"))
        time.sleep(0.5)
    return pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                        "obs_date", "val", "src"])


# ─────────────── 인도네시아 BPS(니켈·코발트·리튬, 키필요) — 원본과 동일 상수 ───────────────
BPS_URL = ("https://webapi.bps.go.id/v1/api/dataexim/sumber/1/periode/1/"
          "kodehs/{hs}/jenishs/{jenishs}/tahun/{tahun}/key/{key}")
BPS_ITEMS = [
    ("NI", "75", 1, "ID_NI_EXPORT_BPS"),
    ("CO", "81052010", 2, "ID_CO_UNWROUGHT_EXPORT_BPS"),
    ("CO", "81052090", 2, "ID_CO_POWDER_EXPORT_BPS"),
    ("CO", "81059000", 2, "ID_CO_MATTE_EXPORT_BPS"),
    ("LI", "28369100", 2, "ID_LI_CARBONATE_EXPORT_BPS"),
    ("LI", "28252000", 2, "ID_LI_OXIDE_EXPORT_BPS"),
]
BPS_START_YEAR = 2014


def fetch_bps(key: str) -> pd.DataFrame:
    today = dt.date.today()
    rows = []
    for cc, hs, jenishs, pre in BPS_ITEMS:
        for yr in range(BPS_START_YEAR, today.year + 1):
            r = requests.get(BPS_URL.format(hs=hs, jenishs=jenishs, tahun=yr,
                                            key=key), headers=UA, timeout=30)
            if r.status_code != 200:
                continue
            j = r.json()
            if j.get("data-availability") != "available":
                continue
            df_y = pd.DataFrame(j["data"])
            m = df_y["bulan"].str.extract(r"^\[(\d{2})\]")
            df_y["month"] = pd.to_numeric(m[0], errors="coerce")
            df_y = df_y.dropna(subset=["month"])
            agg = df_y.groupby("month")[["value", "netweight"]].sum()
            for mon, r2 in agg.iterrows():
                d = dt.date(yr, int(mon), 1)
                rows.append((cc, f"{pre}_VAL", "M", d, float(r2["value"]),
                            "BPS_API"))
                rows.append((cc, f"{pre}_WGT", "M", d, float(r2["netweight"]),
                            "BPS_API"))
            time.sleep(0.3)
    return pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                        "obs_date", "val", "src"])


def main() -> None:
    import os
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "census"):
        key = os.environ.get("CENSUS_API_KEY")
        if not key:
            print("  [warn] CENSUS_API_KEY 미설정 — census 건너뜀")
        else:
            df = fetch_census(key)
            if len(df) >= 500:  # in-house _upsert_indicator의 guard_min과 동일 기준 선검증
                path = save_parquet(df, COLLECT_OUT, prefix="intl_agency", key="census")
                print(f"  census: {len(df)}행 → {path}")
            else:
                print(f"  [warn] census 수집 {len(df)}행 — guard_min(500) 미달, 저장 안 함")
    if what in ("all", "bps"):
        key = os.environ.get("BPS_API_KEY")
        if not key:
            print("  [warn] BPS_API_KEY 미설정 — bps 건너뜀")
        else:
            df = fetch_bps(key)
            if len(df) >= 100:
                path = save_parquet(df, COLLECT_OUT, prefix="intl_agency", key="bps")
                print(f"  bps: {len(df)}행 → {path}")
            else:
                print(f"  [warn] bps 수집 {len(df)}행 — guard_min(100) 미달, 저장 안 함")


if __name__ == "__main__":
    main()
