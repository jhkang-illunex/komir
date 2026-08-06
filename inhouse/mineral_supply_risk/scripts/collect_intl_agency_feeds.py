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
  ○ 아르헨티나 ARCA(구 AFIP, 관세청) — informacionAgregada 월간 zip(무키,
    URL 완전 예측). "Total Exportación" 파일만 파싱(같은 zip의 수입 파일은
    월 6GB급이라 제외). NCM '2836.91'(탄산리튬) 수출 물량·금액 — 발주처
    "아르헨티나 리튬" 요청의 관세청 직접 소스(기존 UN Comtrade 산발 보고의
    보완/교차검증축). 2026-07-29 구현, 컬럼 구조는 공식 안내 PDF로 확인.
    ⚠백필은 2019-01부터(그 이전은 이 NCM코드 자체가 존재하지 않음 — 코드
    부재≠수출 부재, 실측 확인).

키 필요 소스(2026-07-29 사용자 발급, .env에 저장):
  ○ 미국 Census Bureau 무역통계 API(CENSUS_API_KEY) — HS4×월 미국 수입
    금액·관세부담액(DUT_VAL_MO, CBP 대체). 5광종 HS4 9종, 2013-01~ 단일
    콜로 전체 이력 확보(range 쿼리 `time=from ... to ...` 지원 확인).
  ○ UN Comtrade 정식 키(COMTRADE_API_KEY) — 기존 preview 무키 호출을
    대체해 429 완화 + DRC 미러 등 최신 프론티어 확인용. 이 스크립트에는
    아직 미편입(기존 collect_tier*.py의 UN_COMTRADE 호출부가 대상 —
    별도 작업).
  ○ 인도네시아 BPS(BPS_API_KEY) — 2026-07-29 재발급 키("Indonesia Critical
    Minerals Trade Monitor")로 정상 작동 확인, 구현 완료. 니켈은 jenishs=1
    (2자리 챕터 "75")로 타 금속 혼입 없이 수집(2014-01~). 코발트·리튬은
    jenishs=2(전체자리)가 BPS 자체 8자리 코드북과 정확히 일치해야만 응답
    (임의 4자리는 unavailable) — 실측으로 유효 코드 확정(81052010/81052090/
    81059000=코발트, 28369100/28252000=리튬; 25301000은 응답은 되나
    "Vermiculite/perlite"로 리튬 무관이라 제외). ⚠_BPS 접미 필수 —
    ID_NI_EXPORT_VAL/WGT는 기존 UN_COMTRADE(tier1) 계열과 이름 충돌 실측.

멱등 규칙(2026-07-27 교차 삭제 사고 교훈): DELETE 스코프는 이번에 수집한 계열과
정확히 일치(src+indicator/series 한정). 축소 수집 가드 부착.

실행: MSR_DB=<warehouse> python -m scripts.collect_intl_agency_feeds [all|trade|policy|arca_backfill]
  trade  = BCRP+ABS+PSA+GACC 월보+ARCA(최근 4개월만, 증분)+Census+BPS(전체
    재수집, 가벼움 — 키 필요) (월간 cron)
  policy = MOFCOM+FedReg+HTS (주간 cron)
  arca_backfill = ARCA 전체 이력(2019-01~) 1회성 백필 — 월 100~200MB×~96개월
    다운로드라 수 시간 소요. cron 미편입, 최초 1회 수동 실행 전용.
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


# ─────────────── 5. 아르헨티나 ARCA(관세청) 리튬 수출 ───────────────
# 2026-07-29 구현. 컬럼 구조는 공식 안내 PDF로 확인(추측 아님):
#   https://www.afip.gob.ar/operadoresComercioExterior/documentos/
#   Procedimiento-descarga-y-lectura-archivos-de-ComExAFIP-2018.pdf
# "Total Exportación"(국가 미분리, 9컬럼: FECHA·POS_NCM·UN·PESO_NETO_KILOS·
# MONTO_FOB_DOLAR·CANT_DECLARACIONES·CANT_UNIDAD_ESTADISTICA·PRECIO_MAX·
# PRECIO_MIN) 파일만 사용 — 같은 zip의 impo_YYYYMM.lst(수입, 월 6GB급)는
# 파싱 대상에서 제외(다운로드는 서버가 Range 미지원이라 불가피하게 전체
# 수신하지만, 압축 상태로는 월 100~200MB 수준으로 확인).
# 실측(202506=2025년6월): NCM '2836.91.00'(탄산리튬)=4,459톤·USD 3,524만.
# '2530.90.90'·'2836.50.00'(탄산칼슘 — 리튬 아님, prefix grep 오탐 확인 후 제외)
# 등은 리튬과 무관해 채택하지 않음 — 유일하게 명확한 리튬 코드는 2836.91뿐.
ARCA_LIST_URL = ("https://www.afip.gob.ar/operadoresComercioExterior/"
                 "informacionAgregada/informacion-agregada.asp")
ARCA_ZIP_URL = ("https://www.afip.gob.ar/operadoresComercioExterior/"
                "informacionAgregada/download.aspx?filename={ym}.zip")
ARCA_LI_NCM_PREFIX = "2836.91"  # 탄산리튬(carbonato de litio) — 유일 확정 코드
# ⚠2026-07-29 실측: 이 NCM코드로 리튬 수출이 잡히는 시점은 2019-01부터
# (2017-02·2018-01 total_expo_agregado 직접 파싱 — 해당 코드 행 자체가 없음.
# 2019-01=3,364t·2025-06=4,459t로 이후는 일관 존재). 노멘클라토르 개정으로
# 그 이전엔 다른 코드였을 가능성 — 확인 전까지 2019-01 이전은 절대 포함 금지
# (포함 시 "그 시기엔 수출 0"이라는 잘못된 인상을 준다 — 코드 부재≠수출 부재).
ARCA_LI_SAFE_START = "201901"


def _arca_month_list() -> list[str]:
    """ARCA_LI_SAFE_START(2019-01) 이전은 제외 — 코드 부재 확인 구간(§주석)."""
    r = requests.get(ARCA_LIST_URL, headers=UA, timeout=60)
    r.raise_for_status()
    months = sorted(set(re.findall(r"download\.aspx\?filename=(\d{6})\.zip",
                                   r.text)))
    return [m for m in months if m >= ARCA_LI_SAFE_START]


def _arca_fetch_month(ym: str) -> tuple[float, float] | None:
    """해당 월 zip에서 total_expo_agregado 파일만 파싱 — (수출 kg, 수출 USD)."""
    import zipfile
    r = requests.get(ARCA_ZIP_URL.format(ym=ym), headers=UA, timeout=600,
                     stream=True)
    if r.status_code != 200 or "zip" not in (r.headers.get("Content-Type") or ""):
        return None  # 미래월 플레이스홀더(Content-Length 극소) 등
    buf = io.BytesIO()
    for chunk in r.iter_content(chunk_size=1 << 20):
        buf.write(chunk)
    buf.seek(0)
    try:
        zf = zipfile.ZipFile(buf)
        name = next(n for n in zf.namelist()
                   if n.startswith("total_expo_agregado"))
        text = zf.read(name).decode("ascii", errors="replace")
    except (zipfile.BadZipFile, StopIteration):
        return None
    kg = usd = 0.0
    for line in text.splitlines():
        if not line[:6].isdigit():
            continue  # 헤더·구분선 skip
        f = [x.strip() for x in line.split("'")]
        if len(f) < 5 or not f[1].startswith(ARCA_LI_NCM_PREFIX):
            continue
        kg += float(f[3] or 0)
        usd += float(f[4] or 0)
    return (kg, usd) if (kg or usd) else None


def collect_arca_li(con, months: list[str] | None = None) -> None:
    """months 미지정 시 목록 페이지의 전체 이력을 병렬 백필(무키, 서버 부하
    고려해 동시 6개로 제한). 월 1건이라도 신규 코드 배포 초기 실행은 몇 시간
    걸릴 수 있음 — cron 편입 후에는 최근 3개월만 넘기면 수 분 내 종료."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if months is None:
        months = _arca_month_list()
    guard = max(2, len(months) // 2)  # 절반 이상 월이 실패하면 보존
    rows = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_arca_fetch_month, ym): ym for ym in months}
        done = 0
        for fut in as_completed(futs):
            ym = futs[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as e:
                print(f"  [warn] ARCA {ym} 실패({type(e).__name__}) — 건너뜀")
                continue
            if res is None:
                continue
            kg, usd = res
            d = dt.date(int(ym[:4]), int(ym[4:]), 1)
            rows.append(("LI", "AR_LI_EXPORT_WGT_ARCA", "M", d, kg,
                        "ARCA_MONTHLY"))
            rows.append(("LI", "AR_LI_EXPORT_VAL_ARCA", "M", d, usd,
                        "ARCA_MONTHLY"))
            if done % 20 == 0 or done == len(months):
                print(f"  ARCA 진행 {done}/{len(months)}월 처리")
    df = pd.DataFrame(rows, columns=["commodity_code", "indicator", "freq",
                                     "obs_date", "val", "src"])
    # ⚠증분 실행(cron)은 최근 수개월만 재수집 — 다른 소스처럼 indicator
    # 전체를 DELETE하면 이전에 백필한 과거 이력이 매달 날아간다(2026-07-27
    # 교차 삭제 사고와 같은 부류의 함정). obs_date까지 일치하는 행만 스코프.
    if df.empty:
        raise RuntimeError("ARCA_MONTHLY 수집 0행 — 비정상, 기존 데이터 보존")
    if len(df) < guard:
        raise RuntimeError(f"ARCA_MONTHLY 수집 {len(df)}행 — 비정상 축소, 기존 데이터 보존")
    df = df.dropna(subset=["val"]).drop_duplicates(
        subset=["indicator", "obs_date"], keep="last")
    con.register("_a", df)
    con.execute("""DELETE FROM fact_indicator WHERE src = 'ARCA_MONTHLY'
        AND indicator IN ('AR_LI_EXPORT_WGT_ARCA','AR_LI_EXPORT_VAL_ARCA')
        AND obs_date IN (SELECT obs_date FROM _a)""")
    con.execute("INSERT INTO fact_indicator SELECT * FROM _a")
    con.unregister("_a")
    for ind, g in df.groupby("indicator"):
        print(f"  {ind}: {len(g)}행 ({g['obs_date'].min()}~{g['obs_date'].max()})")


# ─────────────── 6. 미국 Census Bureau 무역통계(CBP 대체, 키 필요) ───────────────
# 2026-07-29 구현. CENSUS_API_KEY 실호출 검증 완료 — HS4 단일 콜로 range 쿼리
# (`time=from YYYY-MM to YYYY-MM`)가 전체 이력을 한번에 반환(2013-01~).
# DUT_VAL_MO(관세부담액, 원단위 USD) = CBP 직접 수집 불가(403)의 대체 신호 —
# 실측(2024-01~03): 8105(코발트) 관세비중 ~15%·2846(희토류 화합물) ~60%대로
# 301조 추가관세 효과가 값에 그대로 드러남(정성 검증됨).
CENSUS_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
CENSUS_HS4 = [
    ("CU", "2603", "US_CU_ORE_IMPORT"), ("CU", "7403", "US_CU_REFINED_IMPORT"),
    ("NI", "2604", "US_NI_ORE_IMPORT"), ("NI", "7502", "US_NI_UNWROUGHT_IMPORT"),
    ("CO", "8105", "US_CO_IMPORT"),
    ("LI", "2836", "US_LI_CARBONATE_IMPORT"),  # 2836류 전체(탄산리튬 283691 포함)
    ("LI", "2530", "US_LI_ORE_IMPORT"),         # 기타 광물(리튬광 일부 혼재)
    ("REE", "2805", "US_REE_METAL_IMPORT"), ("REE", "2846", "US_REE_COMPOUND_IMPORT"),
]
CENSUS_START = "2013-01"


def collect_census_us(con) -> None:
    """2026-08-06 물리분리 리팩터 — 실호출은 dmz/msr_collectors/scripts/
    collect_keyed_agency_feeds.py(census)로 이동. 여기서는 그 결과 parquet만 읽는다.
    CENSUS_API_KEY는 더 이상 in-house에 필요 없음(원칙상 dmz/.env 전용)."""
    from msr import dmz_ingest
    from msr.config import MSR_COLLECT_OUT
    pending = dmz_ingest.list_pending(MSR_COLLECT_OUT, prefix="intl_agency__census")
    if not pending:
        print("  [warn] DMZ census parquet 없음 — 건너뜀"
              "(dmz/msr_collectors/scripts/collect_keyed_agency_feeds.py census 선행 필요)")
        return
    dfs = [dmz_ingest.read_df(p) for p in pending]
    df = pd.concat(dfs, ignore_index=True)
    _upsert_indicator(con, df, "CENSUS_API", guard_min=500)
    for p in pending:
        dmz_ingest.mark_loaded(p)


# ─────────────── 7. 인도네시아 BPS 수출통계(니켈·코발트·리튬, 키 필요) ───────────────
# 2026-07-29 구현. 첫 키는 앱 미승인으로 전량 거부됐으나 사용자가 재발급한
# 키("Indonesia Critical Minerals Trade Monitor")로 실호출 검증 완료.
# jenishs=1(2자리 챕터)은 니켈(75류="Nickel and articles thereof")이
# 타 금속과 섞이지 않는 청정 코드라 그대로 사용. jenishs=2(전체자리)는
# BPS 자체 8자리 코드북과 정확히 일치해야만 응답하며(4자리 등 임의 코드는
# unavailable), 실측으로 코발트·리튬 유효 코드를 확정했다(품목명 응답으로
# 교차검증 — 예: 25301000은 "Vermiculite, perlite..."로 리튬 무관이라 제외).
BPS_URL = ("https://webapi.bps.go.id/v1/api/dataexim/sumber/1/periode/1/"
          "kodehs/{hs}/jenishs/{jenishs}/tahun/{tahun}/key/{key}")
# ⚠_BPS 접미 필수: ID_NI_EXPORT_VAL/WGT는 기존 UN_COMTRADE(tier1) 계열과
# 이름이 겹침(실측 확인 — fact_indicator PK에 src가 없어 충돌). PSA·GACC와
# 동일 규칙 적용.
BPS_ITEMS = [
    ("NI", "75", 1, "ID_NI_EXPORT_BPS"),  # 니켈류 전체(2자리) — 타 금속 혼입 없음
    ("CO", "81052010", 2, "ID_CO_UNWROUGHT_EXPORT_BPS"),  # Unwrought cobalt
    ("CO", "81052090", 2, "ID_CO_POWDER_EXPORT_BPS"),      # Powders of cobalt
    ("CO", "81059000", 2, "ID_CO_MATTE_EXPORT_BPS"),  # Cobalt mattes(중간재)
    ("LI", "28369100", 2, "ID_LI_CARBONATE_EXPORT_BPS"),   # Lithium carbonates
    ("LI", "28252000", 2, "ID_LI_OXIDE_EXPORT_BPS"),   # Lithium oxide and hydroxide
]
BPS_START_YEAR = 2014  # 실측: 2013 이전 unavailable


def collect_bps_id(con) -> None:
    """2026-08-06 물리분리 리팩터 — 실호출은 dmz/msr_collectors/scripts/
    collect_keyed_agency_feeds.py(bps)로 이동. 여기서는 그 결과 parquet만 읽는다.
    BPS_API_KEY는 더 이상 in-house에 필요 없음(원칙상 dmz/.env 전용)."""
    from msr import dmz_ingest
    from msr.config import MSR_COLLECT_OUT
    pending = dmz_ingest.list_pending(MSR_COLLECT_OUT, prefix="intl_agency__bps")
    if not pending:
        print("  [warn] DMZ bps parquet 없음 — 건너뜀"
              "(dmz/msr_collectors/scripts/collect_keyed_agency_feeds.py bps 선행 필요)")
        return
    dfs = [dmz_ingest.read_df(p) for p in pending]
    df = pd.concat(dfs, ignore_index=True)
    _upsert_indicator(con, df, "BPS_API", guard_min=100)
    for p in pending:
        dmz_ingest.mark_loaded(p)


# ─────────────── 8. 정책 공고 (MOFCOM·Federal Register) ───────────────
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


# ─────────────── 9. USITC HTS 관세율 스냅샷 ───────────────
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


def _arca_recent_months(n: int = 4) -> list[str]:
    """cron 증분용 — 최근 n개월만(래그 대비 여유분 포함, 멱등이라 겹쳐도 무해)."""
    today = dt.date.today()
    out = []
    for k in range(n):
        idx = today.year * 12 + today.month - 1 - k
        out.append(f"{idx // 12}{idx % 12 + 1:02d}")
    return out


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"[collect_intl_agency_feeds] DB={DB_PATH} what={what}")
    con = duckdb.connect(DB_PATH)
    steps = []
    if what in ("all", "trade"):
        steps += [("1) 페루 BCRP 구리(수출·생산)", collect_bcrp),
                  ("2) 호주 ABS 동광·니켈광 수출", collect_abs),
                  ("3) 필리핀 PSA 니켈 수출", collect_psa),
                  ("4) 중국 GACC 영문 월보(CU·REE)", collect_gacc),
                  ("5) 아르헨 ARCA 리튬 수출(최근 4개월 증분)",
                   lambda c: collect_arca_li(c, months=_arca_recent_months())),
                  ("6) 미국 Census 무역통계(CBP 대체, 키필요)", collect_census_us),
                  ("7) 인니 BPS 니켈·코발트·리튬 수출(키필요)", collect_bps_id)]
    if what == "arca_backfill":
        steps += [("아르헨 ARCA 리튬 수출(전체 이력 백필, 시간 소요)",
                  lambda c: collect_arca_li(c, months=None))]
    if what in ("all", "policy"):
        steps += [("8) 중국 MOFCOM 정책공고", collect_mofcom),
                  ("9) 미국 Federal Register(BIS·USTR)", collect_fedreg),
                  ("10) 미국 HTS 관세율 스냅샷", collect_hts)]
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
