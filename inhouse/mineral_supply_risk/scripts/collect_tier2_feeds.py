# -*- coding: utf-8 -*-
"""Tier2 자체수집 (2026-07-25, 자체수집_추가후보_상세_260724.md Tier2 실측 후속).

접근성 실측 결과(2026-07-25, 전부 실제 호출로 확인):
  ○ Cochilco 칠레 구리 생산 — 구 URL 404였으나 boletin.cochilco.cl/productos/
    boletin.asp?anio&mes&tabla=tabla21 생존. 각 호가 직전 2년+당해 월간치를 담아
    12월호 체인으로 2015-01~ 복원 가능. 최신 2026-05호 = 2026-04월까지(지연 ~80일).
  ○ USGS MIS 코발트 — mis-YYYYMM-cobal.xlsx (2019~2021 atoms/files·2021-12부터
    media/files, S3 직링크, www.usgs.gov는 브라우저 UA 필요). T1 = LME 코발트 금속
    재고(월말, 톤) — CO 최초의 재고축. ⚠값이 거의 상수(2025년 123~140t) + 최신호
    2025-12(지연 ~7개월) — 검정에서 정직 평가. LI·REE 월간 MIS는 부재 실측.
  ○ WSTS Historical Billings — wsts.org/67/Historical-Billings-Report 페이지에서
    최신 XLSX 링크 동적 추출. 1986-01~2026-05 월간, 지역별(1000US$).
    반도체 수요축(REE Nd·CU 전방산업). SIA 보도자료의 원천 데이터.
  ○ ECOS 901Y032 산업별 생산/출하/재고 지수(월간, 1975~) — 기존 ecos_api 재사용.
    전자부품(I11ACQ)·자동차(I11ACU)·전기장비(I11ACS)·1차금속(I11ACO), 구분 1=생산
    원지수·5=재고 원지수. 한국 수입수요 직접 축.
  ✗ 중국 국가통계국(data.stats.gov.cn) — 해외 IP 403 실측, akshare 대응 함수 부재
    → 수집 불가 확정(문서화만).

2026-08-06 dmz/inhouse 물리분리: 이 파일의 ECOS 부분(collect_ecos)만 DMZ 라이브 API 의존
이었다 — 실제 수집은 `dmz/msr_collectors/scripts/collect_ecos.py
--jobs msr_collectors/data/ecos_jobs_tier2.json --out-subdir tier2`로 이전, 여기서는 그
산출물을 로드만 한다. Cochilco·USGS MIS·WSTS 등 나머지 함수는 msr.collectors를 쓰지 않는
직접 requests 수집이라 이번 리팩터 범위 밖(그대로 in-house에서 라이브 수집) — DMZ 격리
원칙상으로는 이들도 이전 대상이지만 별도 사이클로 분리.

실행: (사전) cd komir/dmz && ECOS_API_KEY=<키> python -m msr_collectors.scripts.collect_ecos \
        --jobs msr_collectors/data/ecos_jobs_tier2.json --out-subdir tier2
      MSR_DB=<warehouse> python -m scripts.collect_tier2_feeds
멱등: indicator/series 단위 DELETE 후 INSERT.
"""
from __future__ import annotations
import datetime as dt
import io
import re
import sys
import time

import duckdb
import pandas as pd
import requests

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, MSR_COLLECT_OUT  # noqa: E402
from msr import dmz_ingest  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 "
                    "Firefox/127.0"}

# ─────────────── 1. Cochilco 칠레 구리 생산 (tabla21) ───────────────
COCHILCO_URL = ("https://boletin.cochilco.cl/productos/boletin.asp"
                "?anio={anio}&mes={mes:02d}&tabla=tabla21")
# 12월호 체인: 각 호가 (호년-2)-01부터 월간치 포함 → 2018/2021/2024 12월호 + 최신호
COCHILCO_ISSUES = [(2018, 12), (2021, 12), (2024, 12)]
_MON = {"ENE/JAN": 1, "FEB": 2, "MAR": 3, "ABR/APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AGO/AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC/DEC": 12}


def _cochilco_issue(anio: int, mes: int) -> pd.DataFrame | None:
    r = requests.get(COCHILCO_URL.format(anio=anio, mes=mes), headers=UA, timeout=60)
    if r.status_code != 200:
        return None
    raw = r.content.decode("latin-1")
    try:
        tabs = pd.read_html(io.StringIO(raw), thousands=".", decimal=",")
    except ValueError:
        return None
    t = max(tabs, key=lambda x: x.size)
    if t.shape[1] < 8 or "MINA" not in str(t.iloc[0, 1]):
        return None
    rows, year = [], None
    for _, row in t.iterrows():
        lab = str(row[0]).strip()
        # 당해 연도는 'ENE/JAN 2026 (P)'처럼 잠정치 표기가 붙음 — 접미 허용
        m = re.match(r"^ENE/JAN (\d{4})\b", lab)
        if m:
            year, mon = int(m.group(1)), 1
        elif lab in _MON and year is not None:
            mon = _MON[lab]
        else:
            continue  # 연간 합계·누계·변화율 행 제외
        mine = pd.to_numeric(row[3], errors="coerce")
        ref = pd.to_numeric(row[7], errors="coerce")
        if pd.notna(mine):
            rows.append((dt.date(year, mon, 1), float(mine),
                         float(ref) if pd.notna(ref) else None))
    return pd.DataFrame(rows, columns=["obs_date", "mine_kt", "ref_kt"])


def collect_cochilco(con) -> None:
    frames = []
    for anio, mes in COCHILCO_ISSUES:
        d = _cochilco_issue(anio, mes)
        if d is None or d.empty:
            print(f"  [warn] Cochilco {anio}-{mes:02d}호 파싱 실패 — 건너뜀")
            continue
        frames.append(d)
        print(f"  Cochilco {anio}-{mes:02d}호: {len(d)}개월 "
              f"({d['obs_date'].min()}~{d['obs_date'].max()})")
    # 최신호 탐색: 이번 달부터 12개월 역순
    today = dt.date.today()
    for k in range(12):
        y, m = (today.year * 12 + today.month - 1 - k) // 12, \
               (today.year * 12 + today.month - 1 - k) % 12 + 1
        d = _cochilco_issue(y, m)
        if d is not None and not d.empty:
            frames.append(d)
            print(f"  Cochilco 최신호 {y}-{m:02d}: {len(d)}개월 "
                  f"(~{d['obs_date'].max()})")
            break
    if not frames:
        print("  [warn] Cochilco 수집 실패 — 기존 데이터 유지")
        return
    merged = (pd.concat(frames).sort_values("obs_date")
            .drop_duplicates(subset="obs_date", keep="last"))
    rows = []
    for _, r in merged.iterrows():
        rows.append(("CU", "CL_CU_PROD_MINE", "M", r["obs_date"], r["mine_kt"],
                     "COCHILCO"))
        if pd.notna(r["ref_kt"]):
            rows.append(("CU", "CL_CU_PROD_REF", "M", r["obs_date"], r["ref_kt"],
                         "COCHILCO"))
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    con.execute("DELETE FROM fact_indicator WHERE indicator LIKE 'CL_CU_PROD_%'")
    con.register("_c", df)
    con.execute("INSERT INTO fact_indicator SELECT * FROM _c")
    con.unregister("_c")
    print(f"  CL_CU_PROD_*: {len(df)}행 ({merged['obs_date'].min()}~"
          f"{merged['obs_date'].max()})")


# ─────────────── 2. USGS MIS 코발트 LME 재고 (T1) ───────────────
USGS_BASE = ("https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/"
             "production/s3fs-public/{path}/mis-{ym}-cobal.xlsx")
_USGS_MON = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"])}


def _usgs_issue(ym: str) -> pd.DataFrame | None:
    r = None
    for path in ("media/files", "atoms/files"):
        for attempt in range(3):
            try:
                r = requests.get(USGS_BASE.format(path=path, ym=ym), headers=UA,
                                 timeout=60)
                break
            except requests.exceptions.RequestException:
                time.sleep(5 * (attempt + 1))
        else:
            continue
        if r.status_code == 200:
            break
    if r is None or r.status_code != 200:
        return None
    try:
        t = pd.ExcelFile(io.BytesIO(r.content)).parse("T1", header=None)
    except Exception:
        return None
    # 헤더에서 창고 컬럼 위치 탐색 — 구 포맷(~2023)은 Total에 미 정부 비축분이
    # 포함되므로 Total 대신 U.S.+Non-U.S. warehouse 합 = LME 총재고로 일관 계산.
    # 헤더가 두 행에 걸치는 구 포맷 대응: 상단 12행을 컬럼별로 이어붙여 분류.
    us_col = nonus_col = None
    head = t.head(12).astype(str)
    for j in range(t.shape[1]):
        s = " ".join(head[j].tolist())
        if "warehouse" in s:
            if "Non" in s:
                nonus_col = j
            else:
                us_col = j
    if us_col is None or nonus_col is None:
        return None
    rows, year = [], None
    for _, row in t.iterrows():
        lab = str(row[0]).strip()
        ym_m = re.match(r"^((?:19|20)\d{2})[:,]?\s*(\w*)$", lab)
        if ym_m and (not ym_m.group(2) or ym_m.group(2) in _USGS_MON):
            year = int(ym_m.group(1))
            mon = _USGS_MON.get(ym_m.group(2))  # '2021, December' 형태
        elif lab in _USGS_MON and year is not None:
            mon = _USGS_MON[lab]
        else:
            continue
        if mon is None:
            continue
        us = pd.to_numeric(row[us_col], errors="coerce")
        nonus = pd.to_numeric(row[nonus_col], errors="coerce")
        if pd.notna(us) and pd.notna(nonus):
            rows.append((dt.date(year, mon, 1), float(us) + float(nonus)))
    return pd.DataFrame(rows, columns=["obs_date", "val"])


def collect_usgs_co(con) -> None:
    frames = []
    yms = [f"{y}12" for y in range(2019, 2026)]
    # 2026년 호 존재 시 추가(현재 403 실측 — 발행되면 자동 포섭)
    today = dt.date.today()
    yms += [f"2026{m:02d}" for m in range(1, today.month + 1)]
    for ym in yms:
        d = _usgs_issue(ym)
        if d is not None and not d.empty:
            frames.append(d)
            print(f"  USGS MIS {ym}: {len(d)}개월")
    if not frames:
        print("  [warn] USGS MIS 수집 실패 — 기존 데이터 유지")
        return
    merged = (pd.concat(frames).sort_values("obs_date")
            .drop_duplicates(subset="obs_date", keep="last"))
    df = pd.DataFrame({"commodity_code": "CO", "indicator": "CO_LME_STOCK_T",
                       "freq": "M", "obs_date": merged["obs_date"],
                       "val": merged["val"], "src": "USGS_MIS"})
    con.execute("DELETE FROM fact_indicator WHERE indicator='CO_LME_STOCK_T'")
    con.register("_u", df)
    con.execute("INSERT INTO fact_indicator SELECT * FROM _u")
    con.unregister("_u")
    print(f"  CO_LME_STOCK_T: {len(df)}행 ({merged['obs_date'].min()}~"
          f"{merged['obs_date'].max()})")


# ─────────────── 3. WSTS 반도체 월간 빌링 ───────────────
WSTS_PAGE = "https://www.wsts.org/67/Historical-Billings-Report"
_REGIONS = {"Worldwide": "WSTS_BILL_WW_M", "Asia Pacific": "WSTS_BILL_AP_M",
            "Americas": "WSTS_BILL_AM_M", "Europe": "WSTS_BILL_EU_M",
            "Japan": "WSTS_BILL_JP_M"}   # 2026-07-25 최종 스윕: 전 지역 확장


def collect_wsts(con) -> None:
    pg = requests.get(WSTS_PAGE, headers=UA, timeout=60)
    pg.raise_for_status()
    m = re.search(r'href="(https?://[^"]+\.xlsx)"', pg.text)
    if not m:
        print("  [warn] WSTS XLSX 링크 미발견 — 기존 데이터 유지")
        return
    r = requests.get(m.group(1), headers=UA, timeout=120)
    r.raise_for_status()
    t = pd.ExcelFile(io.BytesIO(r.content)).parse("Monthly Data", header=None)
    rows, year = [], None
    for _, row in t.iterrows():
        lab = str(row[0]).strip()
        if re.match(r"^(19|20)\d{2}$", lab):
            year = int(lab)
        elif lab in _REGIONS and year is not None:
            for mon in range(1, 13):
                v = pd.to_numeric(row[mon], errors="coerce")
                if pd.notna(v):
                    rows.append((_REGIONS[lab], dt.date(year, mon, 1),
                                 float(v) / 1000.0))  # 1000US$ → 백만US$
    df = pd.DataFrame(rows, columns=["series_code", "obs_date", "val"])
    df["unit"] = "MUSD"
    df["src"] = "WSTS_PUBLIC"
    df = df.drop_duplicates(subset=["series_code", "obs_date"])
    for sc in _REGIONS.values():
        con.execute("DELETE FROM fact_series WHERE series_code = ?", [sc])
    con.register("_w", df)
    con.execute("INSERT INTO fact_series SELECT * FROM _w")
    con.unregister("_w")
    for sc, g in df.groupby("series_code"):
        print(f"  {sc}: {len(g)}개월 ({g['obs_date'].min()}~{g['obs_date'].max()})")


# ─────────────── 4. ECOS 산업별 생산/재고 지수 ───────────────
# ⚠️ 2026-08-06: 아래 목록은 이제 dmz/msr_collectors/data/ecos_jobs_tier2.json에
# 미러링돼 DMZ 쪽에서 실제 수집에 쓰인다 — 이 상수 자체는 코드 어디서도 안 읽힌다(진짜
# 수집 대상은 json이 정본). 참고·문서용으로만 유지 — **계열을 추가/변경할 땐 반드시
# ecos_jobs_tier2.json도 같이 고칠 것, 여기만 고치면 조용히 무시된다(DRY 위반이라
# 두 소스가 갈릴 위험이 실재함 — 2026-08-06 skeptic-code 감사에서 지적됨).**
ECOS_ITEMS = [
    # (item1, 구분 item2, series_code)  — 구분 1=생산 원지수, 5=재고 원지수
    ("I11ACQ", "1", "KIP_ELEC_M"),    # 전자부품·컴퓨터·영상음향통신
    ("I11ACU", "1", "KIP_AUTO_M"),    # 자동차·트레일러
    ("I11ACS", "1", "KIP_ELEQ_M"),    # 전기장비(이차전지 포함)
    ("I11ACO", "1", "KIP_METAL_M"),   # 1차 금속
    ("I11ACO", "5", "KINV_METAL_M"),  # 1차 금속 재고
]


def collect_ecos(con) -> None:
    """DMZ가 만든 parquet(ecos_jobs_tier2.json 기준, name==series_code)을 로드해 원본과
    동일하게 fact_series에 계열 단위 DELETE+INSERT — 더 이상 라이브 ECOS 호출 없음."""
    out_dir = os.path.join(MSR_COLLECT_OUT, "ecos", "tier2")
    files = dmz_ingest.list_pending(out_dir, prefix="ecos__")
    if not files:
        print(f"  [warn] ECOS DMZ 산출물 없음({out_dir}) — 먼저 dmz 쪽 collect_ecos 실행할 것")
        return
    for path in files:
        sc = os.path.basename(path).split("__")[1]
        d = dmz_ingest.read_df(path)
        if d.empty:
            print(f"  [warn] ECOS {sc} 빈 결과 — 건너뜀")
            dmz_ingest.mark_loaded(path)
            continue
        out = pd.DataFrame({
            "series_code": sc,
            "obs_date": pd.to_datetime(d["TIME"], format="%Y%m").dt.date,
            "val": pd.to_numeric(d["DATA_VALUE"], errors="coerce"),
            "unit": "Index2020", "src": "ECOS_API"}).dropna(subset=["val"])
        out = out.drop_duplicates(subset=["series_code", "obs_date"])
        con.execute("DELETE FROM fact_series WHERE series_code = ?", [sc])
        con.register("_e", out)
        con.execute("INSERT INTO fact_series SELECT * FROM _e")
        con.unregister("_e")
        print(f"  {sc}: {len(out)}개월 ({out['obs_date'].min()}~"
              f"{out['obs_date'].max()})")
        dmz_ingest.mark_loaded(path)


def main() -> None:
    print(f"[collect_tier2_feeds] DB={DB_PATH}")
    con = duckdb.connect(DB_PATH)
    print("1) Cochilco 칠레 구리 생산")
    collect_cochilco(con)
    print("2) USGS MIS 코발트 LME 재고")
    collect_usgs_co(con)
    print("3) WSTS 반도체 월간 빌링")
    collect_wsts(con)
    print("4) ECOS 산업별 생산/재고 지수")
    collect_ecos(con)
    con.close()
    print("완료")


if __name__ == "__main__":
    main()
