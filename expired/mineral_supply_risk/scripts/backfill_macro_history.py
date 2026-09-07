# -*- coding: utf-8 -*-
"""거시지표 과거분(2006~2021-06) 백필 — 공개 소스 4종 (2026-07-24, 사용자 승인).

배경: 발주처 제공 거시 CSV가 2021-06부터라 거시(CLN) 피처 그룹이 "커버리지
교란"(데이터 존재 시기=전환 다발기)으로 기각됐음. 과거분을 채워 교란을 해소하고
그룹을 재심하는 것이 목적.

소스 매핑(FRED는 이 네트워크에서 접속 차단(도메인 000) 실측 → 대안 구성):
  DXY_W      ← 동방재부 UDI 일봉(ICE 달러인덱스, 2006~)
  USDEUR_W   ← ECB 기준환율 D.USD.EUR
  USDKRW_W   ← ECB 교차환율 (KRW/EUR ÷ USD/EUR)
  CNYUSD_W   ← ECB 교차환율 (CNY/EUR ÷ USD/EUR)
  UST10Y_W   ← 미 재무부 daily yield curve CSV(10 Yr)
  UST10Y2Y_W ← 〃 (10 Yr − 2 Yr)
  FEDFUNDS_W ← NY연준 EFFR(2000-07~; 원계열 '기준금리'의 실효연방기금리 — 사실상 동일 궤적)
백필 불가(사유 명시): STLFSI_W(FRED 유일 원천·네트워크 차단), BDI_W(무료 히스토리
소스 부재), PRICEIDX_* 3종(가격지수 오염군 — 백필 가치 없음).

방법: 일별 → 주간평균(월요일 앵커, KOMIS '주간평균' 규약과 동일) 변환 후,
**KOMIS 중복 구간(2021-06~2022-12)과 교차검증** — 중앙값 상대오차(환율·지수) 또는
절대오차(금리 %p)가 임계 이내인 계열만 채택. 채택 계열은 KOMIS 시계열 시작일
**이전 주만** src='BACKFILL_PUBLIC'으로 삽입(발주처 원본과 출처 분리, 멱등).

실행: MSR_DB=<warehouse> python -m scripts.backfill_macro_history
"""
from __future__ import annotations
import io, os, sys, time
import datetime as dt

import duckdb
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
START = "2006-01-01"
SRC = "BACKFILL_PUBLIC"
# 교차검증 임계: (mode, threshold) — rel=중앙값 상대오차, abs=중앙값 절대오차
VALIDATE = {
    "DXY_W": ("rel", 0.01), "USDEUR_W": ("rel", 0.01), "USDKRW_W": ("rel", 0.01),
    "CNYUSD_W": ("rel", 0.01), "UST10Y_W": ("abs", 0.10), "UST10Y2Y_W": ("abs", 0.10),
    "FEDFUNDS_W": ("abs", 0.15),
}


def weekly_mean(daily: pd.DataFrame) -> pd.DataFrame:
    """일별(d, v) → 주간평균, 앵커=해당 주 월요일(KOMIS 규약)."""
    d = daily.dropna(subset=["v"]).copy()
    d["wk"] = d["d"] - pd.to_timedelta(d["d"].dt.weekday, unit="D")
    return d.groupby("wk", as_index=False)["v"].mean().rename(columns={"wk": "obs_date"})


def fetch_ecb(cur: str) -> pd.DataFrame:
    url = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"
           f"?format=csvdata&startPeriod={START}")
    r = requests.get(url, headers=UA, timeout=90)
    r.raise_for_status()
    c = pd.read_csv(io.StringIO(r.text))
    out = pd.DataFrame({"d": pd.to_datetime(c["TIME_PERIOD"]),
                        "v": pd.to_numeric(c["OBS_VALUE"], errors="coerce")})
    return out.dropna()


def fetch_udi() -> pd.DataFrame:
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           "?secid=100.UDI&fields1=f1&fields2=f51,f53&klt=101&fqt=0"
           "&beg=20060101&end=20500101")
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    kl = (r.json().get("data") or {}).get("klines") or []
    rows = [(pd.Timestamp(x.split(",")[0]), float(x.split(",")[1])) for x in kl]
    return pd.DataFrame(rows, columns=["d", "v"])


def fetch_treasury() -> pd.DataFrame:
    frames = []
    for yr in range(2006, 2023):
        url = (f"https://home.treasury.gov/resource-center/data-chart-center/"
               f"interest-rates/daily-treasury-rates.csv/{yr}/all"
               f"?type=daily_treasury_yield_curve&_format=csv")
        r = requests.get(url, headers=UA, timeout=90)
        if r.status_code != 200:
            print(f"  [warn] treasury {yr}: HTTP {r.status_code} — 건너뜀")
            continue
        c = pd.read_csv(io.StringIO(r.text))
        frames.append(pd.DataFrame({
            "d": pd.to_datetime(c["Date"], errors="coerce"),
            "y10": pd.to_numeric(c.get("10 Yr"), errors="coerce"),
            "y2": pd.to_numeric(c.get("2 Yr"), errors="coerce")}))
        time.sleep(0.5)
    return pd.concat(frames, ignore_index=True).dropna(subset=["d"])


def fetch_effr() -> pd.DataFrame:
    url = ("https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
           "?startDate=2006-01-01&endDate=2022-12-31")
    r = requests.get(url, headers=UA, timeout=90)
    r.raise_for_status()
    rows = [(pd.Timestamp(x["effectiveDate"]), float(x["percentRate"]))
            for x in r.json().get("refRates", [])]
    return pd.DataFrame(rows, columns=["d", "v"])


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)
    komis = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date, val
        FROM fact_series WHERE src='KOMIS_MARKET_AUX'""").df()
    komis["obs_date"] = pd.to_datetime(komis["obs_date"])

    # ── 원천별 일별 수집 → 주간평균 ──
    print("수집 중: ECB(USD/KRW/CNY)·UDI·재무부·EFFR ...")
    usd = fetch_ecb("USD"); time.sleep(0.5)
    krw = fetch_ecb("KRW"); time.sleep(0.5)
    cny = fetch_ecb("CNY"); time.sleep(0.5)
    xk = usd.merge(krw, on="d", suffixes=("_usd", "_krw"))
    xk["v"] = xk["v_krw"] / xk["v_usd"]               # KRW per USD
    xc = usd.merge(cny, on="d", suffixes=("_usd", "_cny"))
    xc["v"] = xc["v_cny"] / xc["v_usd"]               # CNY per USD
    udi = fetch_udi()
    tsy = fetch_treasury()
    effr = fetch_effr()

    series = {
        "USDEUR_W": weekly_mean(usd),
        "USDKRW_W": weekly_mean(xk[["d", "v"]]),
        "CNYUSD_W": weekly_mean(xc[["d", "v"]]),
        "DXY_W": weekly_mean(udi),
        "UST10Y_W": weekly_mean(tsy.rename(columns={"y10": "v"})[["d", "v"]]),
        "UST10Y2Y_W": weekly_mean(
            tsy.assign(v=tsy["y10"] - tsy["y2"])[["d", "v"]]),
        "FEDFUNDS_W": weekly_mean(effr),
    }

    # ── 교차검증 + 삽입 ──
    inserted = {}
    for code, wk in series.items():
        ref = komis[komis["series_code"] == code].rename(columns={"val": "ref"})
        if len(ref) == 0:
            print(f"{code}: KOMIS 원본 없음 — 건너뜀")
            continue
        ov = wk.merge(ref[["obs_date", "ref"]], on="obs_date", how="inner")
        ov["ref"] = pd.to_numeric(ov["ref"], errors="coerce")
        ov = ov.dropna()
        mode, thr = VALIDATE[code]
        if mode == "rel":
            err = float((abs(ov["v"] - ov["ref"]) / abs(ov["ref"])).median())
            ok = err <= thr
            err_s = f"중앙값 상대오차 {err:.4%}"
        else:
            err = float(abs(ov["v"] - ov["ref"]).median())
            ok = err <= thr
            err_s = f"중앙값 절대오차 {err:.3f}"
        start_komis = ref["obs_date"].min()
        pre = wk[wk["obs_date"] < start_komis].copy()
        print(f"{code}: 중복 {len(ov)}주 교차검증 → {err_s} "
              f"(임계 {thr}) → {'채택' if ok else '기각'} | 백필 대상 {len(pre)}주")
        if not ok or len(pre) == 0:
            continue
        unit = con.execute("SELECT unit FROM fact_series WHERE series_code=? LIMIT 1",
                           [code]).fetchone()[0]
        ins = pd.DataFrame({"series_code": code, "obs_date": pre["obs_date"].dt.date,
                            "val": pre["v"].astype(float), "unit": unit, "src": SRC})
        con.execute("DELETE FROM fact_series WHERE series_code=? AND src=?", [code, SRC])
        con.register("_b", ins)
        con.execute("INSERT INTO fact_series SELECT * FROM _b")
        con.unregister("_b")
        inserted[code] = (len(ins), str(ins["obs_date"].min()), str(ins["obs_date"].max()))

    print("\n=== 백필 적재 결과 ===")
    for code, (n, d0, d1) in inserted.items():
        print(f"  {code}: {n}주 ({d0}~{d1})")
    print("백필 불가(문서화): STLFSI_W(FRED 차단)·BDI_W(무료 소스 부재)·PRICEIDX_*(오염군 제외)")
    con.close()


if __name__ == "__main__":
    main()
