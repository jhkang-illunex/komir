# -*- coding: utf-8 -*-
"""수요측 확장 피처 수집기 — 미국 ISM·유로존 PMI·중국 부동산 (2026-07-24).

배경: 중국 PMI(수요측·전기간 커버)가 풀링 보조신호를 유의 개선(3번째 실증)한 데 따른
성공 패턴 연장. akshare(동방재부 매크로 피드) 경유.

⚠ 신선도 한계(수집 시점 실측): ISM·유로 PMI는 2025-09, 부동산은 2025-12까지만 제공
(동방재부 피드 갱신 지연) — 2025-10 이후 전환 다발기에 값이 없어 진단 검정에서는
신선도 마스크에 걸려 불리함. 이 한계를 알고 적재하며, 검정 결과 해석 시 명시할 것.

REE 채굴쿼터는 **피처 부적합 판정으로 미수집**: 2025년부터 중국이 쿼터 비공개 전환
(mining-technology.com 확인), 웹 검증 가능한 연도가 2021~2024 4개뿐(168k/210k/255k/
270k톤) — 연 1값×4개는 주간 전환탐지 피처로 정보량이 없고 커버리지 교란만 추가.
REE 공급신호는 기수집한 Comtrade 수출(CN_REE_EXPORT_WGT)로 갈음.

적재: fact_series, src='AKSHARE_MACRO2'(중국 PMI의 'AKSHARE_MACRO'와 분리 — 수집기별
멱등 DELETE가 서로를 지우지 않도록). obs_date=발표일(announcement date) 그대로 저장 —
피처 빌더가 as-of(발표일+2일)로 조인하면 누수 없음(참조월 역산보다 정확).
  - US_ISM_PMI_M : 미국 ISM 제조업 PMI 今值(발표일 기준)
  - EU_PMI_M     : 유로존 제조업 PMI 초치 今值
  - CN_REALEST_M : 중국 국방경기지수(부동산 경기, 최신값)

실행: MSR_DB=<warehouse> python -m scripts.collect_demand_feeds
"""
from __future__ import annotations
import os, sys

import duckdb
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

SRC = "AKSHARE_MACRO2"


def collect() -> pd.DataFrame:
    import akshare as ak
    rows = []
    ism = ak.macro_usa_ism_pmi()
    for _, r in ism.iterrows():
        d = pd.to_datetime(r["日期"], errors="coerce")
        v = pd.to_numeric(r["今值"], errors="coerce")
        if pd.notna(d) and pd.notna(v):
            rows.append(("US_ISM_PMI_M", d.date(), float(v), "Index", SRC))
    eu = ak.macro_euro_manufacturing_pmi()
    for _, r in eu.iterrows():
        d = pd.to_datetime(r["日期"], errors="coerce")
        v = pd.to_numeric(r["今值"], errors="coerce")
        if pd.notna(d) and pd.notna(v):
            rows.append(("EU_PMI_M", d.date(), float(v), "Index", SRC))
    re_ = ak.macro_china_real_estate()
    for _, r in re_.iterrows():
        d = pd.to_datetime(r["日期"], errors="coerce")
        v = pd.to_numeric(r["最新值"], errors="coerce")
        if pd.notna(d) and pd.notna(v):
            rows.append(("CN_REALEST_M", d.date(), float(v), "Index", SRC))
    df = pd.DataFrame(rows, columns=["series_code", "obs_date", "val", "unit", "src"])
    return df.drop_duplicates(subset=["series_code", "obs_date"], keep="last")


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    con = duckdb.connect(db)
    df = collect()
    con.execute("DELETE FROM fact_series WHERE src = ?", [SRC])
    con.register("_d", df)
    con.execute("INSERT INTO fact_series SELECT * FROM _d")
    con.unregister("_d")
    for code, g in df.groupby("series_code"):
        print(f"{code}: {len(g)}행 ({g['obs_date'].min()}~{g['obs_date'].max()})")
    con.close()


if __name__ == "__main__":
    main()
