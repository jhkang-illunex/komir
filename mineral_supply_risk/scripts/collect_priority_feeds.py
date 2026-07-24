# -*- coding: utf-8 -*-
"""피처 인벤토리 1~4순위 수집기 (2026-07-24, 사용자 승인 "1~4순위 수집해서 검정까지").

수집 대상(피처_데이터_인벤토리_260724.md 셔틀리스트):
  1. SHFE 구리 재고(99期货, akshare) → fact_inventory_exch (CU, src='SHFE_99QH_W')
     — 2005-01~현재 주간. NI에서 유의 실증된 2축 패턴의 CU 이식용.
  2. COMEX 구리 재고: **수집 불가로 판정** — akshare `futures_comex_inventory`는
     금·은만 지원(실측), CME 공식 페이지는 별도 스크레이퍼 개발 필요 → 후순위 이관.
  3. UN Comtrade 월간 무역흐름(공개 preview API, 무키·레이트리밋 있음):
     - REE: 중국(156) 희토류화합물(HS 2846) 세계(0) 수출 월간 → fact_indicator
       (REE, 'CN_REE_EXPORT_WGT' 톤 / 'CN_REE_EXPORT_VAL' USD)
     - CO: 중국(156)이 DRC(180)에서 수입한 코발트 원료(HS 2605 광석+2822 산화물·
       수산화물+810520 매트) 월간 합산 → fact_indicator(CO, 'CN_CO_IMPORT_COD_WGT'/'_VAL')
     ※ DRC 자체 신고는 결측이 많아 중국측 수입(mirror flow)을 쓴다. 기간 배치
       (12개월/호출)+1.5초 간격+429 재시도(공개 API 예의).
  4. 중국 PMI(akshare): 공식 제조업(2008-01~)·차이신 제조업(2014-04~) 월간
     → fact_series ('CN_PMI_OFF_M'/'CN_PMI_CX_M', src='AKSHARE_MACRO')

전부 멱등(대상 src/indicator 단위 DELETE 후 INSERT).
실행: MSR_DB=<warehouse> python -m scripts.collect_priority_feeds
"""
from __future__ import annotations
import os, sys, time
import datetime as dt

import duckdb
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

COMTRADE_BASE = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
COMTRADE_SLEEP = 1.6
COMTRADE_START = 2016


# ─────────────────────── 1. SHFE 구리 재고 ───────────────────────
def collect_shfe_cu() -> pd.DataFrame:
    import akshare as ak
    raw = ak.futures_inventory_99(symbol="铜")
    return pd.DataFrame({
        "commodity_code": "CU",
        "obs_date": pd.to_datetime(raw["日期"]).dt.date,
        "val": pd.to_numeric(raw["库存"], errors="coerce"),
        "unit": "ton",
        "src": "SHFE_99QH_W",
    }).dropna(subset=["val"]).drop_duplicates(subset=["obs_date"], keep="last")


# ─────────────────────── 3. UN Comtrade ───────────────────────
def _comtrade_fetch(params: dict) -> list[dict]:
    for attempt in range(4):
        r = requests.get(COMTRADE_BASE, params=params,
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        if r.status_code == 429:
            time.sleep(3.0 + attempt * 2)
            continue
        r.raise_for_status()
        return r.json().get("data") or []
    raise RuntimeError("Comtrade 429 지속(레이트리밋)")


def _month_batches(y0: int) -> list[str]:
    """preview API는 period를 호출당 1개만 허용(콤마 배치는 400 — 실측). cmdCode
    콤마는 허용되므로 월 단위로만 순회한다(126개월 × 2계열 ≈ 252콜, 1.6초 간격)."""
    today = dt.date.today()
    months = []
    y, m = y0, 1
    while (y, m) <= (today.year, today.month):
        months.append(f"{y}{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


def _aggregate_rows(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """period → (netWgt 합, primaryValue 합). 최광의 집계행만 사용 —
    motCode/customsCode/partner2Code 세분행이 섞이면 합산 중복이 나므로 필터."""
    out: dict[str, tuple[float, float]] = {}
    for r in rows:
        if r.get("partner2Code") not in (None, 0):
            continue
        if str(r.get("motCode", 0)) not in ("0", "None"):
            continue
        cc = str(r.get("customsCode", "C00"))
        if cc not in ("C00", "None"):
            continue
        p = str(r["period"])
        w = float(r.get("netWgt") or 0.0)
        v = float(r.get("primaryValue") or 0.0)
        w0, v0 = out.get(p, (0.0, 0.0))
        out[p] = (w0 + w, v0 + v)
    return out


def collect_comtrade(flow: str, cmd: str, partner: int) -> dict[str, tuple[float, float]]:
    agg: dict[str, tuple[float, float]] = {}
    for batch in _month_batches(COMTRADE_START):
        rows = _comtrade_fetch(dict(reporterCode=156, period=batch, cmdCode=cmd,
                                    flowCode=flow, partnerCode=partner))
        for p, wv in _aggregate_rows(rows).items():
            w0, v0 = agg.get(p, (0.0, 0.0))
            agg[p] = (w0 + wv[0], v0 + wv[1])
        time.sleep(COMTRADE_SLEEP)
    return agg


def upsert_indicator(con, commodity: str, agg: dict, name_prefix: str):
    rows = []
    for p, (w, v) in sorted(agg.items()):
        d = dt.date(int(p[:4]), int(p[4:6]), 1)
        rows.append((commodity, f"{name_prefix}_WGT", "M", d, w / 1000.0, "UN_COMTRADE"))
        rows.append((commodity, f"{name_prefix}_VAL", "M", d, v, "UN_COMTRADE"))
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    con.execute("DELETE FROM fact_indicator WHERE indicator LIKE ?", [name_prefix + "%"])
    con.register("_ind", df)
    con.execute("INSERT INTO fact_indicator SELECT * FROM _ind")
    con.unregister("_ind")
    return len(df)


# ─────────────────────── 4. 중국 PMI ───────────────────────
def collect_pmi() -> pd.DataFrame:
    import akshare as ak
    rows = []
    off = ak.macro_china_pmi()
    for _, r in off.iterrows():
        s = str(r["月份"])          # '2026年06月份'
        y, m = int(s[:4]), int(s[5:7])
        v = pd.to_numeric(r["制造业-指数"], errors="coerce")
        if pd.notna(v):
            rows.append(("CN_PMI_OFF_M", dt.date(y, m, 1), float(v), "Index", "AKSHARE_MACRO"))
    cx = ak.index_pmi_man_cx()
    for _, r in cx.iterrows():
        d = pd.to_datetime(r["日期"])
        v = pd.to_numeric(r["制造业PMI"], errors="coerce")
        if pd.notna(v):
            rows.append(("CN_PMI_CX_M", dt.date(d.year, d.month, 1), float(v), "Index", "AKSHARE_MACRO"))
    df = pd.DataFrame(rows, columns=["series_code", "obs_date", "val", "unit", "src"])
    return df.drop_duplicates(subset=["series_code", "obs_date"])


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)

    # 1. SHFE 구리
    try:
        cu = collect_shfe_cu()
        # 2026-07-25 무결성 가드: 원천이 빈/부분 응답을 주면 DELETE가 기존 전량을
        # 날린다(실제 발생 — CU 1,165행 소실 후 복구). 정상 히스토리(1,100행+)의
        # 절반 미만이면 기존 데이터 보존이 우선.
        if len(cu) < 500:
            raise RuntimeError(f"수집 {len(cu)}행 — 비정상 축소, 기존 데이터 보존")
        con.execute("DELETE FROM fact_inventory_exch WHERE src='SHFE_99QH_W' AND commodity_code='CU'")
        con.register("_cu", cu)
        con.execute("INSERT OR REPLACE INTO fact_inventory_exch SELECT * FROM _cu")
        con.unregister("_cu")
        print(f"1. SHFE CU 재고: {len(cu)}행 ({cu['obs_date'].min()}~{cu['obs_date'].max()})")
    except Exception as e:
        print(f"1. SHFE CU 실패: {type(e).__name__}: {e}")

    # 3. Comtrade
    try:
        ree = collect_comtrade(flow="X", cmd="2846", partner=0)
        n = upsert_indicator(con, "REE", ree, "CN_REE_EXPORT")
        print(f"3a. REE 중국 수출(2846): 월 {len(ree)}개 → fact_indicator {n}행")
    except Exception as e:
        print(f"3a. REE Comtrade 실패: {type(e).__name__}: {e}")
    try:
        co = collect_comtrade(flow="M", cmd="2605,2822,810520", partner=180)
        n = upsert_indicator(con, "CO", co, "CN_CO_IMPORT_COD")
        print(f"3b. CO 중국←DRC 수입(2605+2822+810520): 월 {len(co)}개 → fact_indicator {n}행")
    except Exception as e:
        print(f"3b. CO Comtrade 실패: {type(e).__name__}: {e}")

    # 4. PMI
    try:
        pmi = collect_pmi()
        con.execute("DELETE FROM fact_series WHERE src='AKSHARE_MACRO'")
        con.register("_pmi", pmi)
        con.execute("INSERT INTO fact_series SELECT * FROM _pmi")
        con.unregister("_pmi")
        for code, g in pmi.groupby("series_code"):
            print(f"4. {code}: {len(g)}행 ({g['obs_date'].min()}~{g['obs_date'].max()})")
    except Exception as e:
        print(f"4. PMI 실패: {type(e).__name__}: {e}")

    print(con.execute("""SELECT 'fact_inventory_exch' t, src, commodity_code, COUNT(*) n
                          FROM fact_inventory_exch GROUP BY 2,3
                          UNION ALL
                          SELECT 'fact_indicator', src, commodity_code||'/'||indicator, COUNT(*)
                          FROM fact_indicator WHERE src='UN_COMTRADE' GROUP BY 2,3
                          ORDER BY 1,2,3""").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
