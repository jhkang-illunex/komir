# -*- coding: utf-8 -*-
"""USGS 공급집중 참조데이터 자동수집 (ScienceBase REST API).
연도별 MCS 데이터릴리스에서 세계 생산(국가별)을 모아 2016~최근 HHI·점유율 시계열 생성.

  python -m geo.refdata --from 2016 --to 2026

출력(GEO_DATA/config/refdata/):
  concentration.parquet : commodity, country, year, prod_share, weight, source_doi, release
  hhi.parquet           : commodity, year, hhi, hhi_mult, n_countries, source_doi, release
※ 네트워크 필요 → 호스트/도커(오픈망)에서 실행. (Cowork 샌드박스 프록시는 sciencebase 차단)
"""
import argparse, io, os, sys, re, zipfile
from pathlib import Path
import requests
import pandas as pd
from . import config as C

SB_ITEM = "https://www.sciencebase.gov/catalog/item/{id}?format=json"
# max=10(구버전)은 마스터(전 광종 통합) item이 개별광종 item들에 밀려 검색결과 밖으로
# 빠지는 경우가 있어(예: 2024) max=100으로 확대(2026-07-22, 시점정합성 수정 #8 부속작업).
SB_SEARCH = "https://www.sciencebase.gov/catalog/items?format=json&max=100&fields=title,dates&q={q}"

# 확인된 릴리스 item (나머지는 discover로 자동탐색)
SEED_ITEMS = {
    2025: "677eaf95d34e760b392c4970",   # DOI 10.5066/P13XCP3R
    2026: "696a75d5d4be0228872d3bf8",   # DOI 10.5066/P1WKQ63T
}
COMMODITY_MAP = {   # MCS Commodity/chapter → 내부 코드
    "copper": "CU", "nickel": "NI", "lithium": "LI", "cobalt": "CO", "rare earths": "REE",
}
# world.zip류(2022~2024 릴리스)는 광종별 개별 CSV로 쪼개져 있고 파일명이 5자 약어(예:
# mcs2022-coppe_world.csv) — 대상 5광종만 골라서 읽는다.
ZIP_COMMODITY_PREFIX = {"CU": "coppe", "NI": "nicke", "CO": "cobal", "LI": "lithi", "REE": "raree"}
REFDIR = C.CONFIG / "refdata"


def discover_item(year: int) -> str | None:
    if year in SEED_ITEMS:
        return SEED_ITEMS[year]
    q = requests.utils.quote(f"Mineral Commodity Summaries {year} Data Release")
    try:
        j = requests.get(SB_SEARCH.format(q=q), timeout=30).json()
        cands = [it for it in j.get("items", [])
                 if str(year) in (it.get("title") or "") and "Data Release" in (it.get("title") or "")]
        if not cands:
            return None
        # 마스터(전 광종 통합) item 우선 — "... - LITHIUM Data Release" 같은 개별광종 item은 후순위
        # ("Data Release" 앞부분에 " - "가 없으면 마스터로 간주).
        master = next((it for it in cands if " - " not in it["title"].split("Data Release")[0]), None)
        return (master or cands[0])["id"]
    except Exception as e:
        print(f"  [discover {year}] {e}")
    return None


def _read_csv_bytes(b: bytes, **kw) -> pd.DataFrame:
    """MCS 릴리스마다 CSV 인코딩이 달라(UTF-8 BOM/CP1252 스마트따옴표 등) 순서대로 시도."""
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(b), dtype=str, encoding=enc, on_bad_lines="skip", **kw)
        except UnicodeDecodeError as e:
            last_err = e
    return pd.read_csv(io.BytesIO(b), dtype=str, encoding="latin-1", on_bad_lines="skip", **kw)


_YEAR_RE = re.compile(r"(\d{4})")


def _prod_year_cols(columns) -> dict:
    """와이드 포맷의 생산연도 컬럼(예: 'Prod_kt_2020','Prod_kt_Est_2021','PROD_2023',
    'PROD_EST_ 2024')에서 연도를 추출. CAP_*/RESERVES_*/*_NOTES 등은 'prod'로 시작하지
    않거나 4자리 연도가 없어 자연히 제외됨."""
    out = {}
    for c in columns:
        cl = c.strip().lower()
        if not cl.startswith("prod"):
            continue
        m = _YEAR_RE.search(c)
        if m:
            out[c] = int(m.group(1))
    return out


def _parse_wide_prod(df: pd.DataFrame, cty_col: str, type_col: str,
                      com_col: str | None = None, static_commodity: str | None = None) -> pd.DataFrame:
    """와이드(국가×연도컬럼) 포맷 → (commodity, country, year, value) long. 'Mine production'
    행만(정련·비축·매장량 등 제외), 연도컬럼은 _prod_year_cols로 자동 탐지해 melt."""
    d = df[df[type_col].astype(str).str.contains("Mine production", case=False, na=False)].copy()
    prod_cols = _prod_year_cols(d.columns)
    if not prod_cols or len(d) == 0:
        return pd.DataFrame(columns=["commodity", "country", "year", "value"])
    parts = []
    for col, yr in prod_cols.items():
        commodity = (pd.Series([static_commodity] * len(d), index=d.index) if com_col is None
                     else d[com_col].astype(str).str.strip().str.lower().map(COMMODITY_MAP))
        parts.append(pd.DataFrame({
            "commodity": commodity,
            "country": d[cty_col].astype(str).str.strip(),
            "year": yr,
            "value": pd.to_numeric(d[col].astype(str).str.replace(",", "", regex=False), errors="coerce"),
        }))
    out = pd.concat(parts, ignore_index=True)
    out = out.dropna(subset=["value", "commodity"])
    out = out[~out["country"].str.contains("World total|United States and", case=False, na=False)]
    out = out[out["value"] > 0]
    return out.groupby(["commodity", "country", "year"], as_index=False)["value"].sum()


def fetch_release_production(item_id: str) -> tuple[pd.DataFrame, str] | None:
    """릴리스 item에서 대상 5광종 세계생산을 (commodity,country,year,value)로 추출.
    MCS Data Release는 연도마다 파일 포맷이 3종 혼재해 순서대로 시도(2026-07-22,
    시점정합성 수정 #8 부속작업 — 이 스크레이퍼가 이 환경에서 한 번도 끝까지 성공한 적이
    없어 실제 ScienceBase 응답을 보고 재작성함):
      ① 평평한 long CSV 한 장(2026 패턴: *_Commodities_Data.csv)
      ② zip 안에 통합 wide CSV 한 장(2025 패턴: World_Data_Release_MCS_*.zip)
      ③ zip 안에 광종별 wide CSV 여러 장(2022~2024 패턴: world.zip, mcs{yr}-{com5}_world.csv)
    """
    j = requests.get(SB_ITEM.format(id=item_id), timeout=60).json()
    doi = next((i["key"] for i in j.get("identifiers", []) if i.get("type") == "DOI"), "")
    files = j.get("files", [])

    for f in files:                                            # ① 평평한 long CSV
        n = (f.get("name") or "").lower()
        if n.endswith(".csv") and ("commodities_data" in n or "world_production" in n):
            b = requests.get(f["downloadUri"], timeout=180).content
            out = parse_world_production(b)
            if len(out):
                return out, doi

    for f in files:                                            # zip 후보
        n = (f.get("name") or "").lower()
        if not (n.endswith(".zip") and "world" in n and "salient" not in n and "trends" not in n):
            continue
        try:
            b = requests.get(f["downloadUri"], timeout=180).content
            z = zipfile.ZipFile(io.BytesIO(b))
        except (requests.RequestException, zipfile.BadZipFile):
            continue
        csvs = [nm for nm in z.namelist() if nm.lower().endswith(".csv")]
        if len(csvs) == 1:                                     # ② 통합 wide CSV
            df = _read_csv_bytes(z.read(csvs[0]))
            df.columns = [c.strip() for c in df.columns]
            cty = next((c for c in df.columns if c.strip().lower() == "country"), None)
            com = next((c for c in df.columns if c.strip().lower() == "commodity"), None)
            typ = next((c for c in df.columns if c.strip().lower() == "type"), None)
            if cty and com and typ:
                out = _parse_wide_prod(df, cty, typ, com_col=com)
                if len(out):
                    return out, doi
        elif csvs:                                              # ③ 광종별 wide CSV
            parts = []
            for code, prefix in ZIP_COMMODITY_PREFIX.items():
                hit = next((nm for nm in csvs if prefix in nm.lower()), None)
                if not hit:
                    continue
                df = _read_csv_bytes(z.read(hit))
                df.columns = [c.strip() for c in df.columns]
                cty = next((c for c in df.columns if c.strip().lower() == "country"), None)
                typ = next((c for c in df.columns if c.strip().lower() == "type"), None)
                if not (cty and typ):
                    continue
                part = _parse_wide_prod(df, cty, typ, static_commodity=code)
                if len(part):
                    parts.append(part)
            if parts:
                return pd.concat(parts, ignore_index=True), doi
    return None


def parse_world_production(csv_bytes: bytes) -> pd.DataFrame:
    """long CSV → (commodity, country, year, value) 세계 생산 국가별."""
    df = _read_csv_bytes(csv_bytes)
    df.columns = [c.strip() for c in df.columns]
    def col(*names):
        for n in names:
            for c in df.columns:
                if c.lower() == n: return c
        return None
    c_com, c_cty, c_sec = col("commodity"), col("country"), col("section")
    c_stat, c_yr, c_val = col("statistics"), col("year"), col("value")
    c_det = col("statistics_detail")
    if not all([c_com, c_cty, c_stat, c_yr, c_val]):
        raise ValueError(f"예상 컬럼 없음: {df.columns.tolist()[:12]}")
    d = df.copy()
    d["_com"] = d[c_com].str.strip().str.lower().map(COMMODITY_MAP)
    d = d[d["_com"].notna()]
    d = d[d[c_stat].str.contains("Production", case=False, na=False)]
    if c_sec:                                   # 세계 생산 표만(미국 salient 제외)
        d = d[d[c_sec].str.contains("World", case=False, na=False)]
    d = d[~d[c_cty].str.contains("World total|United States and", case=False, na=False)]
    d["_val"] = pd.to_numeric(d[c_val].str.replace(",", "", regex=False), errors="coerce")
    d["_yr"] = pd.to_numeric(d[c_yr], errors="coerce")
    d = d.dropna(subset=["_val", "_yr"])
    d = d[d["_val"] > 0]
    # mine production 우선(있으면), 아니면 그대로
    if c_det:
        mask_mine = d[c_det].str.contains("[Mm]ine", na=False)
        if mask_mine.any():
            d = d[mask_mine | ~d.groupby(["_com","_yr"])[c_det].transform(lambda s: s.str.contains("[Mm]ine", na=False).any())]
    d["_cty"] = d[c_cty].str.strip()
    out = d.groupby(["_com", "_cty", "_yr"], as_index=False)["_val"].sum()
    out.columns = ["commodity", "country", "year", "value"]
    out["year"] = out["year"].astype(int)
    return out


def compute_hhi(prod: pd.DataFrame):
    """(commodity, country, year, value, release) → HHI·점유율.
    release까지 묶어서 집계 — 같은 생산연도라도 릴리스마다(추후 개정 포함) 그 시점에
    '실제로 발표됐던' 국가별 구성으로 독립 계산해야 시점 정합성이 성립함(2026-07-22,
    시점정합성 수정 #8). release 컬럼이 없으면(구버전 호출) 과거 방식(연도만)으로 폴백."""
    prod = prod.copy()
    keys = ["commodity", "year", "release"] if "release" in prod.columns else ["commodity", "year"]
    tot = prod.groupby(keys)["value"].transform("sum")
    prod["prod_share"] = prod["value"] / tot
    prod["weight"] = 1.0 + prod["prod_share"]                 # 국가 가중(점유율 반영)
    hhi = (prod.assign(sq=(prod["prod_share"] * 100) ** 2)
               .groupby(keys)
               .agg(hhi=("sq", "sum"), n_countries=("country", "nunique")).reset_index())
    hhi["hhi_mult"] = 1.0 + hhi["hhi"] / 10000.0              # HHI 배수(1~2)
    return prod, hhi


def run(y_from=2016, y_to=2026):
    REFDIR.mkdir(parents=True, exist_ok=True)
    all_prod, doi_by_rel = [], {}
    for mcs_year in range(y_from + 1, y_to + 1):   # MCS N → 생산연도 N-1(및 그 전년)
        item = discover_item(mcs_year)
        if not item:
            print(f"[refdata] {mcs_year} 릴리스 미발견 skip"); continue
        try:
            got = fetch_release_production(item)
            if not got:
                print(f"[refdata] {mcs_year} 생산데이터 미발견 skip"); continue
            prod, doi = got
            prod["release"] = mcs_year; prod["source_doi"] = doi
            all_prod.append(prod); doi_by_rel[mcs_year] = doi
            print(f"[refdata] MCS {mcs_year}: {len(prod)}행 (연도 {sorted(prod['year'].unique())})")
        except Exception as e:
            print(f"[refdata] {mcs_year} 실패: {e}")
    if not all_prod:
        print("[refdata] 수집 없음"); return
    prod = pd.concat(all_prod, ignore_index=True)
    # 시점정합성 수정(2026-07-22, #8): 과거에는 같은 (commodity,country,year)를 최신
    # 릴리스값으로 collapse했음 — 이는 훗날 개정된 수치를 과거 시점 지수계산에 역주입하는
    # lookahead bias였음(예: 2020년 이벤트를 2026년에 개정된 2020년 생산치로 채점).
    # 이제는 릴리스별 원본을 모두 보존하고(같은 (commodity,country,year,release) 조합 내
    # 완전 중복행만 제거), indexer.py에서 이벤트 시점 기준 "release <= 이벤트연도"로
    # as-of 조인하도록 넘긴다.
    prod = prod.drop_duplicates(["commodity", "country", "year", "release"])
    prod = prod[(prod["year"] >= y_from) & (prod["year"] <= y_to)]
    conc, hhi = compute_hhi(prod)
    conc.to_parquet(REFDIR / "concentration.parquet", index=False)
    hhi.to_parquet(REFDIR / "hhi.parquet", index=False)
    print(f"\n[refdata] 완료 → {REFDIR} (릴리스별 원본 {conc['release'].nunique()}개 보존, "
          f"{len(conc)}행 — 이전에는 연도당 1행으로 collapse했음)")
    latest = hhi.sort_values("release").drop_duplicates(["commodity", "year"], keep="last")
    print(latest.pivot_table(index="year", columns="commodity", values="hhi", aggfunc="first").round(0).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="y_from", type=int, default=2016)
    ap.add_argument("--to", dest="y_to", type=int, default=2026)
    a = ap.parse_args()
    run(a.y_from, a.y_to)
