# -*- coding: utf-8 -*-
"""한국 수입의존 비중(kr_import_share) 생성 — 이중 노출 가중의 s_imp 항 (2026-07-15).

raw_customs_annual_bycountry(국가별 연간, collect_annual_bycountry.py 산출) →
(commodity, country[영문 별칭 확장], year, imp_share). 지정학 이벤트의 country(영문
자유텍스트)와 매칭되도록 관세청 한글 국가명을 영문 별칭들로 확장해 방출한다.

산출: $GEO_DATA/config/refdata/kr_import_share.parquet (+ 수입국 HHI 참고 출력)
실행: MSR_DB=<warehouse> GEO_DATA=<geo_data> python -m scripts.build_kr_import_share
"""
from __future__ import annotations
import os, sys

import duckdb
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH                                   # noqa: E402

# 관세청 한글 국가명 → 이벤트/USGS 체계(영문) 별칭들. 첫 별칭이 대표명.
ALIAS = {
    "중국": ["China"], "칠레": ["Chile"], "페루": ["Peru"], "호주": ["Australia"],
    "일본": ["Japan"], "미국": ["United States", "USA", "U.S.", "US"],
    "캐나다": ["Canada"], "인도네시아": ["Indonesia"], "필리핀": ["Philippines"],
    "러시아 연방": ["Russia", "Russian Federation"], "러시아": ["Russia"],
    "콩고민주공화국": ["DR Congo", "Democratic Republic of the Congo",
                 "Democratic Republic of Congo", "DRC", "Congo"],
    "브라질": ["Brazil"], "멕시코": ["Mexico"], "남아프리카공화국": ["South Africa"],
    "마다가스카르": ["Madagascar"], "뉴칼레도니아": ["New Caledonia"], "핀란드": ["Finland"],
    "노르웨이": ["Norway"], "독일": ["Germany"], "대만": ["Taiwan"], "베트남": ["Vietnam"],
    "태국": ["Thailand"], "말레이시아": ["Malaysia"], "아르헨티나": ["Argentina"],
    "볼리비아": ["Bolivia"], "잠비아": ["Zambia"], "카자흐스탄": ["Kazakhstan"],
    "몽골": ["Mongolia"], "튀르키예": ["Turkey", "Turkiye"], "터키": ["Turkey"],
    "스페인": ["Spain"], "네덜란드": ["Netherlands"], "벨기에": ["Belgium"],
    "영국": ["United Kingdom", "Britain", "UK"], "프랑스": ["France"],
    "이탈리아": ["Italy"], "스위스": ["Switzerland"], "폴란드": ["Poland"],
    "인도": ["India"], "싱가포르": ["Singapore"], "홍콩": ["Hong Kong"],
    "아랍에미리트 연합": ["United Arab Emirates", "UAE"], "사우디아라비아": ["Saudi Arabia"],
    "오만": ["Oman"], "미얀마": ["Myanmar"], "라오스": ["Laos"], "파나마": ["Panama"],
    "에콰도르": ["Ecuador"], "조지아": ["Georgia"], "우즈베키스탄": ["Uzbekistan"],
    "모로코": ["Morocco"], "짐바브웨": ["Zimbabwe"], "나미비아": ["Namibia"],
    "탄자니아": ["Tanzania"], "쿠바": ["Cuba"], "파푸아뉴기니": ["Papua New Guinea"],
    "뉴질랜드": ["New Zealand"], "오스트리아": ["Austria"], "스웨덴": ["Sweden"],
    "체코": ["Czech Republic", "Czechia"], "에리트레아": ["Eritrea"],
}


def run(db=None, geo_data=None):
    db = db or DB_PATH
    geo_data = geo_data or os.environ.get("GEO_DATA", "./geo_data")
    con = duckdb.connect(db, read_only=True)
    d = con.execute("""
        SELECT commodity_code AS commodity, country, CAST(year AS INT) AS year,
               sum(CAST(imp_usd AS DOUBLE)) AS imp_usd
        FROM raw_customs_annual_bycountry
        WHERE commodity_code IS NOT NULL GROUP BY 1,2,3""").df()
    con.close()
    tot = d.groupby(["commodity", "year"])["imp_usd"].transform("sum")
    d["imp_share"] = (d["imp_usd"] / tot.replace(0, pd.NA)).fillna(0.0)

    # 참고: 진짜 '수입국 HHI'(종전 품목 HHI 결함의 교정판) 출력
    d["_sq"] = d["imp_share"] ** 2
    hhi = d.groupby(["commodity", "year"])["_sq"].sum().rename("import_hhi_country")
    print("=== 수입국 HHI(국가 기준, 최근 3년) ===")
    print(hhi.unstack(0).tail(3).round(3).to_string())

    # 한글 국가명 → 영문 별칭 확장
    rows = []
    n_unmapped = {}
    for r in d.itertuples():
        aliases = ALIAS.get(str(r.country).strip())
        if not aliases:
            n_unmapped[r.country] = n_unmapped.get(r.country, 0) + 1
            continue
        for a in aliases:
            rows.append(dict(commodity=r.commodity, country=a, year=r.year,
                             imp_share=float(r.imp_share)))
    out = pd.DataFrame(rows)
    top_un = sorted(n_unmapped.items(), key=lambda x: -x[1])[:8]
    print(f"\n별칭 미매핑 국가(비중 소국 위주, 상위): {top_un}")

    rd = os.path.join(geo_data, "config", "refdata")
    os.makedirs(rd, exist_ok=True)
    f = os.path.join(rd, "kr_import_share.parquet")
    out.to_parquet(f, index=False)
    cov = d.merge(pd.DataFrame({"country": list(ALIAS)}), on="country")["imp_share"]
    print(f"\n[kr-share] {len(out)}행 → {f} | 매핑 커버리지(수입액 가중): "
          f"{cov.sum() / max(d['imp_share'].sum(), 1e-9):.1%}")
    return out


if __name__ == "__main__":
    run()
