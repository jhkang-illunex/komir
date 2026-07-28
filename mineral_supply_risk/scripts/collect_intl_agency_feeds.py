# -*- coding: utf-8 -*-
"""해외 정부기관 직접 수집 (2026-07-28, 발주처 수집대상 확장 요청 대응).

발주처 지정 tier1/tier2 국가·기관 중 실호출 검증(2026-07-28, 3개 조사 + 서버
재검증)으로 "무키·무인 수집 가능" 판정을 받은 소스만 구현. 키 발급·유료 절차가
필요한 소스(BPS·Census·Comtrade 정식키·DataWeb·GACC 상세통계 등)는
`documents/산출물/2026-W31_0727-0802/해외관세정책_데이터확장_260728.md` 참조.

구현 소스(전부 무키·이 서버에서 실호출 검증 완료):
  ○ 페루 BCRP — estadisticas.bcrp.gob.pe 시리즈 API(JSON, 무인증). 구리 수출
    금액(백만US$)·물량(천톤)·광산생산(천톤). 원자료 SUNAT/MINEM. 2000-01~.
  ○ 호주 ABS — data.api.abs.gov.au SDMX(키 제도 2024-11 폐지). MERCH_EXP
    SITC 283(동광)·284(니켈광) 월별 수출액(천AUD). 1988~. ⚠SITC 3자리 한계로
    리튬·희토류 분리 불가(REQ xlsx는 이 서버에서 도달 불가 — 문서 참조).
  ○ 필리핀 PSA OpenSTAT — PxWeb API(무키). 니켈 광석·괴(HS 2604*+7502*) 월별
    수출 FOB(USD)·물량(kg), 국가합. 2012~. MGB(WAF 403) 대체 경로.
  ○ 중국 GACC 영문 월보 — 정적 HTML 표13(주요 수출)·표14(주요 수입).
    동정광·정련동·희토류의 월 수량/금액(천US$). 2018-01~(과거 연도
    monthly{YYYY}.html 체인). Comtrade 중국 2024-12 정지의 대체 최신축(래그
    ~3주). 1~2월은 합산 발표 → 누계 차분으로 복원.
  ○ 중국 MOFCOM 정책공고(대외무역관리) — jpaas unit API(GET, 무키). 수출통제·
    쿼터·실체명단 공고 목록+날짜. 최신 ~15건/호출 → url upsert 축적형.
  ○ 미국 Federal Register API — BIS(수출통제)·USTR(301)·CBP 관보 문서(무키).
    2020-01~ 전량 재수집형.
  ○ 미국 USITC HTS reststop — 광물 HS4 관세율 + 챕터99(232/301 추가관세)
    스냅샷(JSON, 무키). 릴리스 단위 보존.

멱등 규칙(2026-07-27 교차 삭제 사고 교훈): DELETE 스코프는 이번에 수집한 계열과
정확히 일치(src+indicator/series 한정). 축소 수집 가드 부착.

실행: MSR_DB=<warehouse> python -m scripts.collect_intl_agency_feeds [all|trade|policy]
  trade  = BCRP+ABS+PSA+GACC 월보 (월간 cron)
  policy = MOFCOM+FedReg+HTS (주간 cron)
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
from msr.config import DB_PATH  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 "
                    "Firefox/127.0"}


def _upsert_indicator(con, df: pd.DataFrame, src: str, guard_min: int) -> None:
    """indicator 단위 멱등 적재. df cols = commodity_code, indicator, freq,
    obs_date, val, src. DELETE는 (src, 이번에 수집한 indicator)로 한정."""
    if len(df) < guard_min:
        raise RuntimeError(f"{src} 수집 {len(df)}행 — 비정상 축소, 기존 데이터 보존")
    df = df.dropna(subset=["val"]).drop_duplicates(
        subset=["indicator", "obs_date"], keep="last")
    inds = sorted(df["indicator"].unique())
    ph = ",".join("?" * len(inds))
    con.execute(f"DELETE FROM fact_indicator WHERE src = ? "
                f"AND indicator IN ({ph})", [src] + inds)
    con.register("_x", df)
    con.execute("INSERT INTO fact_indicator SELECT * FROM _x")
    con.unregister("_x")
    for ind, g in df.groupby("indicator"):
        print(f"  {ind}: {len(g)}행 ({g['obs_date'].min()}~{g['obs_date'].max()})")


# ─────────────── 1. 페루 BCRP (구리) ───────────────
BCRP_URL = ("https://estadisticas.bcrp.gob.pe/estadisticas/series/api/"
            "{code}/json/2000-1/{end}/ing")
BCRP_SERIES = [
    # (BCRP 코드, indicator, 광종) — 단위: VAL 백만US$ / WGT·PROD 천톤
    ("PN38782BM", "PE_CU_EXPORT_VAL", "CU"),
    ("PN38783BM", "PE_CU_EXPORT_WGT", "CU"),
    ("PN01873AM", "PE_CU_PROD_MINE", "CU"),
]
_BCRP_MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
     "Nov", "Dec"])}


def collect_bcrp(con) -> None:
    today = dt.date.today()
    end = f"{today.year}-{today.month}"
    rows = []
    for code, ind, cc in BCRP_SERIES:
        r = requests.get(BCRP_URL.format(code=code, end=end), headers=UA,
                         timeout=60)
        r.raise_for_status()
        for p in r.json().get("periods", []):
            m = re.match(r"^([A-Za-z]{3})\.(\d{4})$", p["name"])
            v = pd.to_numeric(p["values"][0], errors="coerce")
            if m and pd.notna(v):
                rows.append((cc, ind, "M",
                             dt.date(int(m.group(2)), _BCRP_MON[m.group(1)], 1),
                             float(v), "BCRP_API"))
        time.sleep(1)
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    _upsert_indicator(con, df, "BCRP_API", guard_min=300)


# ─────────────── 2. 호주 ABS SDMX (동광·니켈광 수출) ───────────────
ABS_URL = ("https://data.api.abs.gov.au/rest/data/ABS,MERCH_EXP,1.0.0/"
           "{sitc}.TOT.TOT.M?startPeriod=1988-01&format=csvfile")
ABS_SERIES = [("283", "AU_CU_EXPORT_KAUD", "CU"),
              ("284", "AU_NI_EXPORT_KAUD", "NI")]  # 값 단위: 천AUD(UNIT_MULT=3)


def collect_abs(con) -> None:
    rows = []
    for sitc, ind, cc in ABS_SERIES:
        r = requests.get(ABS_URL.format(sitc=sitc), headers=UA, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        # TIME_PERIOD 'YYYY-MM', OBS_VALUE 천AUD
        for _, row in df.iterrows():
            v = pd.to_numeric(row["OBS_VALUE"], errors="coerce")
            m = re.match(r"^(\d{4})-(\d{2})$", str(row["TIME_PERIOD"]))
            if m and pd.notna(v):
                rows.append((cc, ind, "M",
                             dt.date(int(m.group(1)), int(m.group(2)), 1),
                             float(v), "ABS_SDMX"))
        time.sleep(1)
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    _upsert_indicator(con, df, "ABS_SDMX", guard_min=300)


# ─────────────── 3. 필리핀 PSA OpenSTAT (니켈 수출) ───────────────
PSA_BASE = "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/2L/IMT"
# ⚠_PSA 접미 필수: Comtrade 필리핀 보고(tier3)가 PH_NI_EXPORT_VAL/WGT를 선점 —
# indicator 단독 조회 혼입 방지(원천: PSA=관세청 BOC 직접 vs Comtrade=UN 미러)
PSA_GROUPS = [("FOB", "PH_NI_EXPORT_VAL_PSA"),   # USD
              ("QPE", "PH_NI_EXPORT_WGT_PSA")]   # kg(원단위 그대로)
PSA_HS_PREFIX = ("2604", "7502")  # 니켈 광석·정광 + 니켈괴


def _psa_year_tables(group: str) -> dict[int, str]:
    r = requests.get(f"{PSA_BASE}/{group}/", headers=UA, timeout=60)
    r.raise_for_status()
    out = {}
    for t in r.json():
        m = re.search(r"\b(20\d{2})\b", str(t.get("text", "")))
        if m:
            out[int(m.group(1))] = t["id"]
    return out


def _psa_year(group: str, tid: str) -> pd.DataFrame | None:
    # 1단계: 경량 쿼리로 상품코드 키↔HS 라벨 취득(연도별 코드셋 상이)
    q0 = {"query": [
        {"code": "Country", "selection": {"filter": "item", "values": ["156"]}},
        {"code": "Period", "selection": {"filter": "item", "values": ["0"]}}],
        "response": {"format": "json-stat2"}}
    r = requests.post(f"{PSA_BASE}/{group}/{tid}", json=q0, headers=UA,
                      timeout=120)
    if r.status_code != 200:
        return None
    comm = r.json()["dimension"]["Commodity Code"]["category"]
    keys = [k for k in comm["index"]
            if str(comm["label"].get(k, "")).startswith(PSA_HS_PREFIX)]
    if not keys:
        return None
    # 2단계: 대상 코드만 CSV로 (전 국가 × 전 월)
    q = {"query": [{"code": "Commodity Code",
                    "selection": {"filter": "item", "values": keys}}],
         "response": {"format": "csv"}}
    r2 = requests.post(f"{PSA_BASE}/{group}/{tid}", json=q, headers=UA,
                       timeout=120)
    if r2.status_code != 200:
        return None
    try:
        df = pd.read_csv(io.BytesIO(r2.content))
    except UnicodeDecodeError:  # 일부 연도 CSV는 latin-1(국가명 악센트)
        df = pd.read_csv(io.BytesIO(r2.content), encoding="latin-1")
    mon_cols = [c for c in df.columns if c not in ("Commodity Code", "Country")]
    recs = []
    for c in mon_cols:
        m = re.match(r"^(\d{4})\s+(\w+)", re.sub(r"\s+", " ", c).strip())
        if not m:
            continue
        try:
            mon = dt.datetime.strptime(m.group(2)[:3], "%b").month
        except ValueError:
            continue
        v = pd.to_numeric(df[c], errors="coerce").sum()
        if pd.notna(v) and v > 0:
            recs.append((dt.date(int(m.group(1)), mon, 1), float(v)))
    return pd.DataFrame(recs, columns=["obs_date", "val"])


def collect_psa(con) -> None:
    rows = []
    for group, ind in PSA_GROUPS:
        tables = _psa_year_tables(group)
        for year in sorted(tables):
            d = _psa_year(group, tables[year])
            if d is None or d.empty:
                print(f"  [warn] PSA {group} {year} 결과 없음 — 건너뜀")
                continue
            for _, r in d.iterrows():
                rows.append(("NI", ind, "M", r["obs_date"], r["val"],
                             "PSA_OPENSTAT"))
            time.sleep(1)
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    _upsert_indicator(con, df, "PSA_OPENSTAT", guard_min=100)


# ─────────────── 4. 중국 GACC 영문 월보 (표13 수출·표14 수입) ───────────────
GACC_LIST = "http://english.customs.gov.cn/statics/report/monthly{suffix}.html"
GACC_YEARS = list(range(2018, dt.date.today().year + 1))
# (표 방향, 행 라벨 정규식, indicator 접두, 광종) — 값: 수량(원단위), 금액(천US$).
# ⚠_GACC 접미 규칙: Comtrade 중국 보고(CN_REE_EXPORT_VAL 등)와 이름 충돌 방지 —
# 최종 indicator = {접두}_{QTY|VAL}_GACC
GACC_ROWS = [
    ("import", r"^Copper ores and concentrates", "CN_CU_ORE_IMPORT", "CU"),
    ("import", r"^Unwrought copper", "CN_CU_UNWROUGHT_IMPORT", "CU"),
    ("import", r"^Rare[- ]earth", "CN_REE_IMPORT", "REE"),
    ("export", r"^Rare[- ]earth", "CN_REE_EXPORT", "REE"),
]
_GACC_TITLE = {"export": r"Major Export Commodities in Quantity and Value",
               "import": r"Major Import Commodities in Quantity and Value"}
_UNIT_MULT = {"T": 1.0, "10000T": 10000.0, "KG": 0.001}


def _gacc_month_pages(year: int) -> dict[str, dict[int, str]]:
    """연도 목록 페이지 → {방향: {월: 표 URL}}."""
    suffix = "" if year == dt.date.today().year else str(year)
    r = requests.get(GACC_LIST.format(suffix=suffix), headers=UA, timeout=60)
    if r.status_code != 200:
        return {}
    out: dict[str, dict[int, str]] = {"export": {}, "import": {}}
    # 과거 연도 페이지(2018~2024)는 태그 사이 개행·들여쓰기 有 → \s* 허용
    for title, cell in re.findall(
            r"<tr>\s*<td>([^<]+)</td>\s*<td>(.*?)</td>\s*</tr>", r.text, re.S):
        for direction, pat in _GACC_TITLE.items():
            if re.search(pat, title):
                for url, monname in re.findall(
                        r"href=(\S+?\.html)>\s*([A-Za-z.]+)", cell):
                    try:
                        mon = dt.datetime.strptime(
                            monname.strip(".")[:3], "%b").month
                    except ValueError:
                        continue
                    out[direction][mon] = url
    return out


def _gacc_table(url: str) -> pd.DataFrame | None:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            break
        except requests.exceptions.RequestException:
            time.sleep(5 * (attempt + 1))
    else:
        return None
    if r.status_code != 200:
        return None
    try:
        tabs = pd.read_html(io.StringIO(r.text))
    except ValueError:
        return None
    return max(tabs, key=lambda x: x.size)


def collect_gacc(con) -> None:
    # (indicator접두, 광종, 월) → {qty_mo, val_mo, qty_cum, val_cum}
    acc: dict[tuple, dict] = {}
    for year in GACC_YEARS:
        pages = _gacc_month_pages(year)
        if not any(pages.values()):
            print(f"  [warn] GACC {year} 목록 없음 — 건너뜀")
            continue
        n_pages = 0
        for direction, months in pages.items():
            wanted = [(pre, cc, pat) for d, pat, pre, cc in GACC_ROWS
                      if d == direction]
            if not wanted:
                continue
            for mon, url in sorted(months.items()):
                t = _gacc_table(url)
                if t is None or t.shape[1] < 6:
                    continue
                n_pages += 1
                for _, row in t.iterrows():
                    name = str(row.iloc[0]).strip()
                    for pre, cc, pat in wanted:
                        if not re.search(pat, name):
                            continue
                        unit = str(row.iloc[1]).strip().upper().replace(" ", "")
                        mult = _UNIT_MULT.get(unit, 1.0)
                        vals = [pd.to_numeric(row.iloc[k], errors="coerce")
                                for k in (2, 3, 4, 5)]
                        d = acc.setdefault((pre, cc, dt.date(year, mon, 1)), {})
                        if pd.notna(vals[0]):
                            d["qty_mo"] = float(vals[0]) * mult
                        if pd.notna(vals[1]):
                            d["val_mo"] = float(vals[1])
                        if pd.notna(vals[2]):
                            d["qty_cum"] = float(vals[2]) * mult
                        if pd.notna(vals[3]):
                            d["val_cum"] = float(vals[3])
                time.sleep(0.8)
        print(f"  GACC {year}: {n_pages}페이지 파싱")
    # 1~2월 합산 발표 대응: 당월치 없으면 누계 차분으로 복원(차분 불가면 결측)
    rows = []
    for (pre, cc, date), d in sorted(acc.items()):
        prev = acc.get((pre, cc, dt.date(date.year, date.month - 1, 1))
                       if date.month > 1 else None, {})
        for suf, mo_k, cum_k in (("QTY", "qty_mo", "qty_cum"),
                                 ("VAL", "val_mo", "val_cum")):
            v = d.get(mo_k)
            if v is None and cum_k in d:
                if date.month == 1:
                    v = d[cum_k]
                elif cum_k in prev:
                    v = d[cum_k] - prev[cum_k]
            if v is not None and v >= 0:
                rows.append((cc, f"{pre}_{suf}_GACC", "M", date, v,
                             "GACC_EN_MONTHLY"))
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    _upsert_indicator(con, df, "GACC_EN_MONTHLY", guard_min=100)


# ─────────────── 5. 정책 공고 (MOFCOM·Federal Register) ───────────────
POLICY_DDL = """
CREATE TABLE IF NOT EXISTS raw_policy_notice(
  src VARCHAR, notice_date DATE, title VARCHAR, url VARCHAR,
  agency VARCHAR, doc_type VARCHAR, collected_at TIMESTAMP)
"""


def _policy_upsert(con, df: pd.DataFrame, src: str) -> None:
    """url 기준 upsert(축적형) — 목록이 최신 N건만 반환해도 과거분 보존."""
    if df.empty:
        print(f"  [warn] {src} 0건 — 건너뜀")
        return
    df = df.drop_duplicates(subset="url", keep="first")
    con.execute(POLICY_DDL)
    con.register("_p", df)
    con.execute("DELETE FROM raw_policy_notice WHERE src = ? "
                "AND url IN (SELECT url FROM _p)", [src])
    con.execute("INSERT INTO raw_policy_notice SELECT * FROM _p")
    con.unregister("_p")
    n = con.execute("SELECT COUNT(*), MAX(notice_date) FROM raw_policy_notice "
                    "WHERE src = ?", [src]).fetchone()
    print(f"  {src}: 이번 {len(df)}건 upsert → 누적 {n[0]}건(최신 {n[1]})")


MOFCOM_PAGE = "https://www.mofcom.gov.cn/zcfb/dwmygl/index.html"
MOFCOM_UNIT = ("https://www.mofcom.gov.cn/api-gateway/jpaas-publish-server/"
               "front/page/build/unit?parseType=bulidstatic&pageType=column"
               "&webId={webId}&tplSetId={tplSetId}&pageId={pageId}"
               "&unitId={unitId}"
               "&tagId=%E5%88%86%E9%A1%B5%E5%88%97%E8%A1%A8&editType=null")


def collect_mofcom(con) -> None:
    page = requests.get(MOFCOM_PAGE, headers=UA, timeout=60)
    page.raise_for_status()
    ids = {}
    for k, pat in [("webId", r"webId['\"]?\s*[=:]\s*['\"]([0-9a-f]{32})"),
                   ("tplSetId",
                    r"tplSetId['\"]?\s*[=:]\s*['\"]([0-9a-zA-Z]+)['\"]"),
                   ("unitId",
                    r"authorizedReadUnitId['\"]?\s*[=:]\s*['\"]([0-9a-f]{32})"),
                   ("pageId", r'ColId"?\s+content="([0-9a-f]{32})')]:
        m = re.search(pat, page.text)
        if not m:
            print(f"  [warn] MOFCOM {k} 추출 실패 — 페이지 구조 변경 의심, 건너뜀")
            return
        ids[k] = m.group(1)
    r = requests.get(MOFCOM_UNIT.format(**ids), headers=UA, timeout=60)
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        print(f"  [warn] MOFCOM unit API 실패: {str(j)[:120]}")
        return
    html = j.get("data", {}).get("html", "")
    items = re.findall(r'<a href="([^"]+)"[^>]*title="([^"]+)"[^>]*>.*?'
                       r"<span>\[(\d{4}-\d{2}-\d{2})\]</span>", html, re.S)
    now = dt.datetime.now()
    df = pd.DataFrame(
        [("MOFCOM_ZCFB", dt.date.fromisoformat(d), title,
          "https://www.mofcom.gov.cn" + url, "MOFCOM 대외무역관리",
          "notice", now) for url, title, d in items],
        columns=["src", "notice_date", "title", "url", "agency", "doc_type",
                 "collected_at"])
    _policy_upsert(con, df, "MOFCOM_ZCFB")


FEDREG_URL = ("https://www.federalregister.gov/api/v1/documents.json"
              "?conditions[agencies][]={agency}"
              "&conditions[publication_date][gte]=2020-01-01"
              "&conditions[type][]=RULE&conditions[type][]=PRORULE"
              "&conditions[type][]=NOTICE&conditions[type][]=PRESDOCU"
              "&per_page=1000&order=newest"
              "&fields[]=title&fields[]=publication_date&fields[]=type"
              "&fields[]=html_url")
FEDREG_AGENCIES = ["industry-and-security-bureau",
                   "trade-representative-office-of-united-states"]


def collect_fedreg(con) -> None:
    rows, now = [], dt.datetime.now()
    for ag in FEDREG_AGENCIES:
        url = FEDREG_URL.format(agency=ag)
        while url:
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            j = r.json()
            for d in j.get("results", []):
                rows.append(("FEDREG_API",
                             dt.date.fromisoformat(d["publication_date"]),
                             d["title"], d["html_url"], ag, d["type"], now))
            url = j.get("next_page_url")
            time.sleep(1)
    df = pd.DataFrame(rows, columns=["src", "notice_date", "title", "url",
                                     "agency", "doc_type", "collected_at"])
    if len(df) < 100:
        print(f"  [warn] FedReg {len(df)}건 — 비정상 축소, 기존 데이터 보존")
        return
    _policy_upsert(con, df, "FEDREG_API")


# ─────────────── 6. USITC HTS 관세율 스냅샷 ───────────────
HTS_DDL = """
CREATE TABLE IF NOT EXISTS raw_hts_rates(
  release VARCHAR, htsno VARCHAR, description VARCHAR, units VARCHAR,
  general VARCHAR, special VARCHAR, col2 VARCHAR, chapter99 VARCHAR,
  collected_at TIMESTAMP)
"""
# 5광종 HS4 + 챕터99(232/301/IEEPA 추가관세 전체).
# ⚠reststop exportList의 to는 상한 배타적(9903-9903=0행 실측) → +1 범위로 지정
HTS_RANGES = [("2530", "2531"), ("2603", "2607"), ("2805", "2806"),
              ("2836", "2847"), ("7401", "7404"), ("7501", "7503"),
              ("8105", "8106"), ("9903", "9904")]


def collect_hts(con) -> None:
    rel = requests.get("https://hts.usitc.gov/reststop/currentRelease",
                       headers=UA, timeout=60).json()
    release = rel.get("name", "unknown")
    rows, now = [], dt.datetime.now()
    for lo, hi in HTS_RANGES:
        r = requests.get(f"https://hts.usitc.gov/reststop/exportList"
                         f"?from={lo}&to={hi}&format=JSON&styles=false",
                         headers=UA, timeout=120)
        if r.status_code != 200:
            print(f"  [warn] HTS {lo}-{hi} HTTP {r.status_code} — 건너뜀")
            continue
        for d in (r.json() or []):
            foot = "; ".join(f.get("value", "")
                             for f in (d.get("footnotes") or []))
            rows.append((release, d.get("htsno"), d.get("description"),
                         ",".join(d.get("units") or []), d.get("general"),
                         d.get("special"), d.get("other"), foot, now))
        time.sleep(1)
    df = pd.DataFrame(rows, columns=["release", "htsno", "description", "units",
                                     "general", "special", "col2", "chapter99",
                                     "collected_at"])
    if len(df) < 100:
        print(f"  [warn] HTS {len(df)}행 — 비정상 축소, 기존 데이터 보존")
        return
    con.execute(HTS_DDL)
    con.register("_h", df)
    con.execute("DELETE FROM raw_hts_rates WHERE release = ?", [release])
    con.execute("INSERT INTO raw_hts_rates SELECT * FROM _h")
    con.unregister("_h")
    print(f"  HTS {release}: {len(df)}행(광물 HS4 + 챕터99)")


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"[collect_intl_agency_feeds] DB={DB_PATH} what={what}")
    con = duckdb.connect(DB_PATH)
    steps = []
    if what in ("all", "trade"):
        steps += [("1) 페루 BCRP 구리(수출·생산)", collect_bcrp),
                  ("2) 호주 ABS 동광·니켈광 수출", collect_abs),
                  ("3) 필리핀 PSA 니켈 수출", collect_psa),
                  ("4) 중국 GACC 영문 월보(CU·REE)", collect_gacc)]
    if what in ("all", "policy"):
        steps += [("5) 중국 MOFCOM 정책공고", collect_mofcom),
                  ("6) 미국 Federal Register(BIS·USTR)", collect_fedreg),
                  ("7) 미국 HTS 관세율 스냅샷", collect_hts)]
    for title, fn in steps:
        print(title)
        try:
            fn(con)
        except Exception as e:
            print(f"  [error] {type(e).__name__}: {e} — 기존 데이터 보존")
    con.close()
    print("완료")


if __name__ == "__main__":
    main()
