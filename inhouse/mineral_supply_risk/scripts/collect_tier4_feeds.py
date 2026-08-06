# -*- coding: utf-8 -*-
"""Tier4 최종 스윕 자체수집 (2026-07-25, "더 수집할 게 없을 때까지" 사용자 지시).

Tier1~3에 이어 접근 가능 잔여 후보 전부. 전 항목 사전 프로브 실측 완료:
  1. Comtrade 흐름 10종(월간 2016~, fact_indicator src='UN_COMTRADE'):
     수요축 — 중국 CU정광 수입(월 ~2.5Mt)·중국 NI 수입(광석+매트+정련 ~1.7Mt)·
              중국 LI 수입(~794kt) [중국 보고 2024-12 컷, 축적 목적] ·
              일본 CU정광 수입(~2026-05)·일본 CO 수입·인도 CU정광 수입(~2026-03)
     공급축 — 캐나다 CO 수출(북미 정제)·노르웨이 NI 정련 수출(유럽 정제
              Nikkelverk)·미국 REE 수출(MP Materials→중국)·브라질 LI 수출(5위,
              월 ~200kt)
  2. EIA 헨리허브 천연가스 월간(제련 에너지비 프록시) → fact_series 'NG_HENRYHUB_M'
     (src='EIA_PUBLIC', DEMO_KEY 실측 200 — 데이터 API는 curl 글로빙 함정 주의)
  3. Eurostat Comext — 독일 수입 월간(니켈 750210·코발트 810520·탄산리튬 283691,
     EU 수요축 대표) → fact_indicator 'DE_{NI,CO,LI}_IMPORT_WGT'
     (src='EUROSTAT_COMEXT'; EU27 집계코드는 이 dataflow에서 미작동 실측 — DE 사용)
  4. akshare — 중국 전력소비(월간)·전국 탄소배출권 가격(주간화)
     → fact_series 'CN_ELEC_CONS_M'·'CN_CARBON_W'
  5. ECOS 출하지수(901Y032 구분3) — 전자부품·자동차 → 'KSH_ELEC_M'·'KSH_AUTO_M'

프로브에서 기각 확정(문서 기록용): 핀란드 CO(2.4t 무의미)·잠비아 CU(미보고)·
러시아 NI(제재 후 미보고)·페루 CU(지연 12개월+, 후순위 보류).

2026-08-06 dmz/inhouse 물리분리: 이 파일의 ECOS 부분(collect_ecos_ship)만 DMZ 라이브 API
의존이었다 — 실제 수집은 `dmz/msr_collectors/scripts/collect_ecos.py
--jobs msr_collectors/data/ecos_jobs_tier4_ship.json --out-subdir tier4_ship`로 이전, 여기서는
그 산출물을 로드만 한다. Comtrade(_comtrade_fetch, scripts.collect_priority_feeds 경유)·EIA·
Eurostat Comext·akshare·ICSG·OECD 등 나머지는 msr.collectors를 쓰지 않는 직접 수집이라
이번 리팩터 범위 밖(그대로 in-house에서 라이브 수집) — DMZ 격리 원칙상으로는 이들도 이전
대상이지만 별도 사이클로 분리.

실행: (사전) cd komir/dmz && ECOS_API_KEY=<키> python -m msr_collectors.scripts.collect_ecos \
        --jobs msr_collectors/data/ecos_jobs_tier4_ship.json --out-subdir tier4_ship
      MSR_DB=<warehouse> ECOS_API_KEY=<키> python -m scripts.collect_tier4_feeds
멱등: indicator 접두어/시리즈 단위 DELETE 후 INSERT(+빈 응답 가드).
"""
from __future__ import annotations
import datetime as dt
import os
import re
import sys
import time

import duckdb
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, MSR_COLLECT_OUT  # noqa: E402
from msr import dmz_ingest  # noqa: E402
from scripts.collect_priority_feeds import (  # noqa: E402
    _comtrade_fetch, _month_batches, _aggregate_rows, upsert_indicator,
)

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 "
                    "Firefox/127.0"}
SLEEP = 1.6

SUPPLY_FLOWS = [
    ("CU", 156, "M", "2603", 0, "CN_CU_IMPORT"),
    ("NI", 156, "M", "2604,7501,7502", 0, "CN_NI_IMPORT"),
    ("LI", 156, "M", "283691,253090", 0, "CN_LI_IMPORT"),
    ("CU", 392, "M", "2603", 0, "JP_CU_IMPORT"),
    ("CO", 392, "M", "810520", 0, "JP_CO_IMPORT"),
    ("CU", 699, "M", "2603", 0, "IN_CU_IMPORT"),
    ("CO", 124, "X", "810520", 0, "CA_CO_EXPORT"),
    ("NI", 579, "X", "7502", 0, "NO_NI_EXPORT"),
    ("REE", 842, "X", "253090,2846", 0, "US_REE_EXPORT"),
    ("LI", 76, "X", "253090,283691", 0, "BR_LI_EXPORT"),
]


def collect_supply_flows(con) -> None:
    for cc, rep, flow, cmd, partner, prefix in SUPPLY_FLOWS:
        done = con.execute(
            "SELECT count(DISTINCT obs_date) FROM fact_indicator WHERE indicator=?",
            [f"{prefix}_WGT"]).fetchone()[0]
        if done >= 100:
            print(f"  {prefix}: 기수집 {done}개월 — 스킵(이어받기)")
            continue
        agg = {}
        for period in _month_batches(2016):
            rows = _comtrade_fetch(dict(reporterCode=rep, period=period,
                                        cmdCode=cmd, flowCode=flow,
                                        partnerCode=partner))
            for p, wv in _aggregate_rows(rows).items():
                w0, v0 = agg.get(p, (0.0, 0.0))
                agg[p] = (w0 + wv[0], v0 + wv[1])
            time.sleep(SLEEP)
        if len(agg) < 24:
            print(f"  [warn] {prefix}: {len(agg)}개월 — 비정상, 기존 유지")
            continue
        n = upsert_indicator(con, cc, agg, prefix)
        months = sorted(agg.keys())
        print(f"  {prefix}({cc}): 월 {len(agg)}개({months[0]}~{months[-1]}) → {n}행")


def _upsert_series(con, df: pd.DataFrame, sc: str) -> None:
    if len(df) < 12:
        print(f"  [warn] {sc}: {len(df)}행 — 비정상, 기존 유지")
        return
    con.execute("DELETE FROM fact_series WHERE series_code = ?", [sc])
    con.register("_s", df)
    con.execute("INSERT INTO fact_series SELECT * FROM _s")
    con.unregister("_s")
    print(f"  {sc}: {len(df)}행 ({df['obs_date'].min()}~{df['obs_date'].max()})")


def collect_eia(con) -> None:
    key = os.environ.get("EIA_API_KEY", "DEMO_KEY")
    r = requests.get("https://api.eia.gov/v2/natural-gas/pri/fut/data/",
                     params={"api_key": key, "frequency": "monthly",
                             "data[0]": "value", "facets[series][]": "RNGWHHD",
                             "start": "2006-01", "length": 5000},
                     headers=UA, timeout=60)
    r.raise_for_status()
    rows = r.json().get("response", {}).get("data", [])
    d = pd.DataFrame(rows)
    if len(d) == 0:
        print("  [warn] EIA 빈 응답 — 기존 유지")
        return
    out = pd.DataFrame({
        "series_code": "NG_HENRYHUB_M",
        "obs_date": pd.to_datetime(d["period"] + "-01").dt.date,
        "val": pd.to_numeric(d["value"], errors="coerce"),
        "unit": "USD/MMBtu", "src": "EIA_PUBLIC"}).dropna(subset=["val"])
    out = out.drop_duplicates(subset=["series_code", "obs_date"]) \
             .sort_values("obs_date")
    _upsert_series(con, out, "NG_HENRYHUB_M")


def _comext_fetch(product: str) -> dict:
    """JSON-stat 응답 → {date: tonnes}. 독일 수입, 100kg 단위 → 톤."""
    r = requests.get(
        "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/"
        "data/DS-045409",
        params={"format": "JSON", "freq": "M", "reporter": "DE",
                "partner": "WORLD", "product": product, "flow": "1",
                "indicators": "QUANTITY_IN_100KG",
                "sinceTimePeriod": "2016-01"},
        headers=UA, timeout=90)
    r.raise_for_status()
    j = r.json()
    tidx = j["dimension"]["time"]["category"]["index"]
    vals = j.get("value", {})
    n_time = len(tidx)
    out = {}
    for tlabel, ti in tidx.items():
        # 시간이 마지막 차원이라 평탄 인덱스 % n_time == ti (단일 셀 조합 가정 검증)
        for flat, v in vals.items():
            if int(flat) % n_time == ti:
                out[tlabel] = out.get(tlabel, 0.0) + float(v) * 0.1  # 100kg→t
    return out


def collect_comext(con) -> None:
    for cc, product, prefix in [("NI", "750210", "DE_NI_IMPORT"),
                                ("CO", "810520", "DE_CO_IMPORT"),
                                ("LI", "283691", "DE_LI_IMPORT")]:
        try:
            d = _comext_fetch(product)
        except Exception as e:
            print(f"  [warn] Comext {prefix} 실패({type(e).__name__}) — 건너뜀")
            continue
        if len(d) < 24:
            print(f"  [warn] {prefix}: {len(d)}개월 — 비정상, 기존 유지")
            continue
        rows = []
        for t, v in sorted(d.items()):
            y, m = int(t[:4]), int(t[5:7])
            rows.append((cc, f"{prefix}_WGT", "M",
                         dt.date(y, m, 1), v, "EUROSTAT_COMEXT"))
        df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                         "obs_date", "val", "src"])
        con.execute("DELETE FROM fact_indicator WHERE indicator = ?",
                    [f"{prefix}_WGT"])
        con.register("_c", df)
        con.execute("INSERT INTO fact_indicator SELECT * FROM _c")
        con.unregister("_c")
        print(f"  {prefix}_WGT({cc}): {len(df)}행 "
              f"({df['obs_date'].min()}~{df['obs_date'].max()})")
        time.sleep(1.0)


def _call_with_timeout(fn, timeout_s=120):
    """akshare 등 자체 타임아웃 제어가 없는 라이브러리 호출에 하드 타임아웃 강제
    (2026-08-06 — collect_akshare가 응답 없이 6시간 이상 멈춘 사고의 유력 원인으로 지목됨,
    같은 파일 다른 requests.get 호출엔 전부 timeout=60~120이 있었는데 이 함수만 없었음).
    별도 스레드에서 실행해 시간 초과 시 TimeoutError를 던진다 — akshare 내부 호출 자체를
    강제 종료할 방법은 없어 완전한 해결은 아니지만(hang된 스레드는 백그라운드에 남음),
    최소한 호출부(cron 체인 전체)가 더 이상 멈추지 않고 다음 단계로 진행하도록 보장한다."""
    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn)
    try:
        return fut.result(timeout=timeout_s)
    finally:
        ex.shutdown(wait=False)  # wait=True면 hang된 스레드를 다시 기다려 타임아웃 무의미해짐


def collect_akshare(con) -> None:
    import akshare as ak
    # 중국 전월 누계 전력소비(월간) — 산업활동 프록시
    try:
        e = _call_with_timeout(ak.macro_china_society_electricity)
        col_t = next(c for c in e.columns if "累计" in c or "总量" in c or "用电量" in c)
        col_d = next(c for c in e.columns if "月" in c or "日期" in c or "统计" in c)
        rows = []
        for _, r in e.iterrows():
            s = str(r[col_d])
            m = pd.to_datetime(s.replace("年", "-").replace("月份", "")
                               .replace("月", ""), errors="coerce")
            v = pd.to_numeric(r[col_t], errors="coerce")
            if pd.notna(m) and pd.notna(v):
                rows.append(("CN_ELEC_CONS_M", m.date().replace(day=1), float(v),
                             "GWh", "AKSHARE_MACRO"))
        df = pd.DataFrame(rows, columns=["series_code", "obs_date", "val",
                                         "unit", "src"]) \
            .drop_duplicates(subset=["series_code", "obs_date"]) \
            .sort_values("obs_date")
        _upsert_series(con, df, "CN_ELEC_CONS_M")
    except Exception as e:
        print(f"  [warn] 중국 전력소비 실패({type(e).__name__}: {e})")
    # 전국 탄소배출권 가격(일간→주간 평균)
    try:
        c = _call_with_timeout(ak.energy_carbon_domestic)
        col_d = next(cc_ for cc_ in c.columns if "日期" in cc_ or "date" in cc_.lower())
        col_p = next(cc_ for cc_ in c.columns if "价" in cc_ or "price" in cc_.lower())
        c["d"] = pd.to_datetime(c[col_d], errors="coerce")
        c["v"] = pd.to_numeric(c[col_p], errors="coerce")
        c = c.dropna(subset=["d", "v"])
        c["wk"] = c["d"] - pd.to_timedelta(c["d"].dt.weekday, unit="D")
        wk = c.groupby("wk", as_index=False)["v"].mean()
        df = pd.DataFrame({"series_code": "CN_CARBON_W",
                           "obs_date": wk["wk"].dt.date, "val": wk["v"],
                           "unit": "CNY/t", "src": "AKSHARE_MACRO"}) \
            .sort_values("obs_date")
        _upsert_series(con, df, "CN_CARBON_W")
    except Exception as e:
        print(f"  [warn] 탄소가격 실패({type(e).__name__}: {e})")


def collect_icsg(con) -> None:
    """ICSG Table1(세계 정련구리 생산·사용 월간, PDF) — 국제기구 축(2026-07-25 실측).
    최근 4개월치가 표에 노출(지연 ~2개월) — 멱등 병합으로 히스토리 축적."""
    import pypdf
    r = requests.get("https://icsg.org/wp-content/uploads/Table1.pdf",
                     headers=UA, timeout=60)
    r.raise_for_status()
    import io as _io
    txt = pypdf.PdfReader(_io.BytesIO(r.content)).pages[0].extract_text()
    lines = txt.splitlines()
    # 헤더에서 월 라벨(Feb Mar Apr May)과 연도(2026 p/) 파싱
    mon_map = {m: i + 1 for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
         "Nov", "Dec"])}
    hdr_months, hdr_year = [], None
    for ln in lines[:8]:
        ms = [w for w in ln.split() if w in mon_map]
        ys = re.findall(r"\b(20\d{2})\b", ln)
        if len(ms) >= 2:
            hdr_months = ms
        if ys and hdr_year is None:
            hdr_year = int(ys[-1])
    if not hdr_months or hdr_year is None:
        print("  [warn] ICSG 헤더 파싱 실패 — 건너뜀")
        return
    targets = {
        "World Copper Mine Production": ("CU_WORLD_MINE_PROD", "kt"),
        "Primary Refined Copper Production": ("CU_WORLD_REF_PRIMARY", "kt"),
        "World Refined Copper Usage": ("CU_WORLD_USAGE", "kt"),
    }
    rows = []
    joined = " ".join(lines)
    for label, (ind, unit) in targets.items():
        m = re.search(re.escape(label) + r"[^\d\-]*((?:[\d,\.]+%?\s+|-?[\d\.]+%\s+){4,})",
                      joined)
        if not m:
            continue
        nums = [w for w in m.group(1).split() if "%" not in w]
        nums = [float(w.replace(",", "")) for w in nums if
                re.fullmatch(r"-?[\d,]+(\.\d+)?", w)]
        # 마지막 len(hdr_months)개 = 최근 월값
        tail = nums[-len(hdr_months):]
        for mo, v in zip(hdr_months, tail):
            rows.append(("CU", ind, "M", dt.date(hdr_year, mon_map[mo], 1), v,
                         "ICSG_PUBLIC"))
    if len(rows) < 3:
        print(f"  [warn] ICSG 값 파싱 {len(rows)}행 — 건너뜀")
        return
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    # 멱등 병합: 같은 (indicator, obs_date)만 대체 — 축적형(과거 호 값 보존)
    for _, rr in df.iterrows():
        con.execute("DELETE FROM fact_indicator WHERE indicator=? AND obs_date=?",
                    [rr["indicator"], rr["obs_date"]])
    con.register("_i", df)
    con.execute("INSERT INTO fact_indicator SELECT * FROM _i")
    con.unregister("_i")
    print(f"  ICSG: {len(df)}행({df['obs_date'].min()}~{df['obs_date'].max()}) — "
          f"축적형(월간 재실행으로 히스토리 확장)")


def collect_oecd_cli(con) -> None:
    """OECD 경기선행지수(CLI, 월간) — 중국·한국. SDMX CSV 직접(실측 200)."""
    for area, sc in [("CHN", "OECD_CLI_CN_M"), ("KOR", "OECD_CLI_KR_M")]:
        url = (f"https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,"
               f"DSD_STES@DF_CLI,4.1/{area}.M.LI...AA...H"
               f"?startPeriod=2006-01&format=csvfile")
        r = requests.get(url, headers=UA, timeout=90)
        if r.status_code != 200:
            print(f"  [warn] OECD CLI {area}: HTTP {r.status_code}")
            continue
        import io as _io
        d = pd.read_csv(_io.StringIO(r.text))
        d = d[["TIME_PERIOD", "OBS_VALUE"]].dropna()
        out = pd.DataFrame({
            "series_code": sc,
            "obs_date": pd.to_datetime(d["TIME_PERIOD"]).dt.date,
            "val": pd.to_numeric(d["OBS_VALUE"], errors="coerce"),
            "unit": "Index", "src": "OECD_SDMX"}).dropna(subset=["val"]) \
            .drop_duplicates(subset=["series_code", "obs_date"]) \
            .sort_values("obs_date")
        _upsert_series(con, out, sc)
        time.sleep(1.0)


def collect_ecos_ship(con) -> None:
    """DMZ가 만든 parquet(ecos_jobs_tier4_ship.json 기준, name==series_code)을 로드해
    원본과 동일하게 fact_series에 적재 — 더 이상 라이브 ECOS 호출 없음."""
    out_dir = os.path.join(MSR_COLLECT_OUT, "ecos", "tier4_ship")
    files = dmz_ingest.list_pending(out_dir, prefix="ecos__")
    if not files:
        print(f"  [warn] ECOS DMZ 산출물 없음({out_dir}) — 먼저 dmz 쪽 collect_ecos 실행할 것")
        return
    for path in files:
        sc = os.path.basename(path).split("__")[1]
        d = dmz_ingest.read_df(path)
        if d.empty:
            print(f"  [warn] ECOS {sc} 빈 결과")
            dmz_ingest.mark_loaded(path)
            continue
        out = pd.DataFrame({
            "series_code": sc,
            "obs_date": pd.to_datetime(d["TIME"], format="%Y%m").dt.date,
            "val": pd.to_numeric(d["DATA_VALUE"], errors="coerce"),
            "unit": "Index2020", "src": "ECOS_API"}).dropna(subset=["val"]) \
            .drop_duplicates(subset=["series_code", "obs_date"]) \
            .sort_values("obs_date")
        _upsert_series(con, out, sc)
        dmz_ingest.mark_loaded(path)


def main() -> None:
    db = os.environ.get("MSR_DB", DB_PATH)
    print(f"[collect_tier4_feeds] DB={db}")
    con = duckdb.connect(db)
    print("1) Comtrade 흐름 10종(수요축 6·공급축 4)")
    collect_supply_flows(con)
    print("2) EIA 헨리허브 천연가스")
    collect_eia(con)
    print("3) Eurostat Comext 독일 수입 3종")
    collect_comext(con)
    print("4) akshare 중국 전력소비·탄소가격")
    collect_akshare(con)
    print("5) ECOS 출하지수 2종")
    collect_ecos_ship(con)
    print("6) ICSG 세계 구리 수급(월간, 축적형)")
    collect_icsg(con)
    print("7) OECD 경기선행지수(중국·한국)")
    collect_oecd_cli(con)
    con.close()
    print("완료")


if __name__ == "__main__":
    main()
