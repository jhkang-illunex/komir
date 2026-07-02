# -*- coding: utf-8 -*-
"""USGS 공급집중 참조데이터 자동수집 (ScienceBase REST API).
연도별 MCS 데이터릴리스에서 세계 생산(국가별)을 모아 2016~최근 HHI·점유율 시계열 생성.

  python -m geo.refdata --from 2016 --to 2026

출력(GEO_DATA/config/refdata/):
  concentration.parquet : commodity, country, year, prod_share, weight, source_doi, release
  hhi.parquet           : commodity, year, hhi, hhi_mult, n_countries, source_doi, release
※ 네트워크 필요 → 호스트/도커(오픈망)에서 실행. (Cowork 샌드박스 프록시는 sciencebase 차단)
"""
import argparse, io, os, sys, re
from pathlib import Path
import requests
import pandas as pd
from . import config as C

SB_ITEM = "https://www.sciencebase.gov/catalog/item/{id}?format=json"
SB_SEARCH = "https://www.sciencebase.gov/catalog/items?format=json&max=10&fields=title,dates&q={q}"

# 확인된 릴리스 item (나머지는 discover로 자동탐색)
SEED_ITEMS = {
    2025: "677eaf95d34e760b392c4970",   # DOI 10.5066/P13XCP3R
    2026: "696a75d5d4be0228872d3bf8",   # DOI 10.5066/P1WKQ63T
}
COMMODITY_MAP = {   # MCS Commodity/chapter → 내부 코드
    "copper": "CU", "nickel": "NI", "lithium": "LI", "cobalt": "CO", "rare earths": "REE",
}
REFDIR = C.CONFIG / "refdata"


def discover_item(year: int) -> str | None:
    if year in SEED_ITEMS:
        return SEED_ITEMS[year]
    q = requests.utils.quote(f"Mineral Commodity Summaries {year} Data Release")
    try:
        j = requests.get(SB_SEARCH.format(q=q), timeout=30).json()
        for it in j.get("items", []):
            if str(year) in (it.get("title") or "") and "Data Release" in it.get("title", ""):
                return it["id"]
    except Exception as e:
        print(f"  [discover {year}] {e}")
    return None


def commodities_csv_url(item_id: str) -> tuple[str, str] | None:
    """item의 파일 목록에서 Commodities/World Production CSV의 (downloadUri, doi)."""
    j = requests.get(SB_ITEM.format(id=item_id), timeout=60).json()
    doi = next((i["key"] for i in j.get("identifiers", []) if i.get("type") == "DOI"), "")
    cand = None
    for f in j.get("files", []):
        n = (f.get("name") or "").lower()
        if n.endswith(".csv") and ("commodities_data" in n or "world_production" in n or "world production" in n):
            cand = f["downloadUri"];
            if "commodities_data" in n: break
    return (cand, doi) if cand else None


def parse_world_production(csv_bytes: bytes) -> pd.DataFrame:
    """long CSV → (commodity, country, year, value) 세계 생산 국가별."""
    df = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, encoding="utf-8", on_bad_lines="skip")
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
    """(commodity, country, year, value) → HHI·점유율."""
    prod = prod.copy()
    tot = prod.groupby(["commodity", "year"])["value"].transform("sum")
    prod["prod_share"] = prod["value"] / tot
    prod["weight"] = 1.0 + prod["prod_share"]                 # 국가 가중(점유율 반영)
    hhi = (prod.assign(sq=(prod["prod_share"] * 100) ** 2)
               .groupby(["commodity", "year"])
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
        got = commodities_csv_url(item)
        if not got:
            print(f"[refdata] {mcs_year} CSV 미발견 skip"); continue
        url, doi = got
        try:
            b = requests.get(url, timeout=180).content
            prod = parse_world_production(b)
            prod["release"] = mcs_year; prod["source_doi"] = doi
            all_prod.append(prod); doi_by_rel[mcs_year] = doi
            print(f"[refdata] MCS {mcs_year}: {len(prod)}행 (연도 {sorted(prod['year'].unique())})")
        except Exception as e:
            print(f"[refdata] {mcs_year} 실패: {e}")
    if not all_prod:
        print("[refdata] 수집 없음"); return
    prod = pd.concat(all_prod, ignore_index=True)
    # 같은 (commodity,country,year)는 최신 릴리스값 우선
    prod = prod.sort_values("release").drop_duplicates(["commodity","country","year"], keep="last")
    prod = prod[(prod["year"] >= y_from) & (prod["year"] <= y_to)]
    conc, hhi = compute_hhi(prod)
    conc.to_parquet(REFDIR / "concentration.parquet", index=False)
    hhi.to_parquet(REFDIR / "hhi.parquet", index=False)
    print(f"\n[refdata] 완료 → {REFDIR}")
    print(hhi.pivot_table(index="year", columns="commodity", values="hhi", aggfunc="first").round(0).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="y_from", type=int, default=2016)
    ap.add_argument("--to", dest="y_to", type=int, default=2026)
    a = ap.parse_args()
    run(a.y_from, a.y_to)
