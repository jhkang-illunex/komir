# -*- coding: utf-8 -*-
"""KOMIS 주간가격 5개주 반영 (2026-06-08~2026-07-06, 2026-07-31 사용자 요청
"mart 갱신 후 ph_psa 재검정" 수행 중 발견).

배경: fact_price(5광종 전부)가 2026-06-08에서 멈춰 있었다(주간 cron은 거래소
재고·COT 등 자동 수집분만 갱신하고, KOMIS 가격은 msr/collectors/komis_files.py
standalone 수동 로더 대상이라 자동화 밖에 있음). 로컬에 이미 07-13 반입된
6월말 기준 파일이 있었으나 미적재 상태였다. 단, 이 파일은 komis_files.py의
canonical 스키마(raw_name·price_basis·value·source)와 컬럼명이 달라 그 로더를
그대로 쓰면 스키마 불일치로 깨진다(운영 스키마는 price_type·val·src) — 이
스크립트는 운영 스키마에 맞춰 새로 작성한 최소 로더다.

교차검증(2026-07-31, 코드 실행 전 5월 과거값으로 매핑 검증 완료):
  - NI: 열1=LME CASH·열2=LME 3개월 (5/4·5/11·6/1 값 기존 DB와 정확일치 확인)
  - CU: 열3=LME CASH·열4=LME 3개월 (동일 검증)
  - CO: 열23=LME CASH (열22 Rotterdam·열24 15개월물은 기존 DB 미사용, 스킵)
  - LI: 열74=탄산리튬 CIF China (기존 REF 계열과 일치, 열73 LiOH는 스킵)
  - REE: 열63=산화네오디뮴 FOB China (기존 REF 계열과 일치)

발견된 이상치(같은 검증 과정에서 우연히 발견, 이번에 같이 교정):
  06-08 기존 DB의 NI(18340/18540)·CU(13661/13670)가 같은 파일의 인접 주(5월
  전체)·독립 소스(fact_diagnosis_answer의 KOMIS_GRADE_MONITOR 피드, NI=17744로
  이 파일과 일치)와 맞지 않음 — 잘못 적재된 값으로 판단해 xlsx 값으로 교정.
  CO/LI/REE 06-08은 반올림 오차 수준(≤5)이라 원값 유지.

실행: MSR_DB=<warehouse> python -m scripts.load_komis_weekly_202606_07
멱등: (commodity_code,price_type,obs_date) 정확 스코프 DELETE 후 INSERT.
"""
import datetime as dt
import os
import sys

import duckdb
import openpyxl
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH  # noqa: E402

XLSX_PATH = ("/home/nuri/dev/git/ws/mine_ws/komir/documents/2차_데이타/"
            "3. 학습 및 검증용/1. 학습용 참고자료/"
            "3. KOMIS 핵심광물 공급망 통계(가격,수출입)_2026년 6월말 기준(1) (1).xlsx")

# (컬럼 인덱스, 광종, price_type) — 위 docstring 검증표 그대로
COL_MAP = [
    (1, "NI", "LME_CASH"), (2, "NI", "LME_3M"),
    (3, "CU", "LME_CASH"), (4, "CU", "LME_3M"),
    (23, "CO", "LME_CASH"),
    (74, "LI", "REF"),
    (63, "REE", "REF"),
]
TARGET_DATES = ["20260608", "20260615", "20260622", "20260629", "20260706"]


def main():
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb["주간 평균"]
    rows = {r[0]: r for r in ws.iter_rows(values_only=True) if r[0] in TARGET_DATES}
    missing = set(TARGET_DATES) - set(rows)
    if missing:
        raise RuntimeError(f"xlsx에 대상 날짜 누락: {missing}")

    recs = []
    for date_str in TARGET_DATES:
        r = rows[date_str]
        obs_date = dt.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
        for col, cc, pt in COL_MAP:
            val = r[col]
            if val is None:
                continue
            recs.append((cc, pt, "W", obs_date, float(val), "USD/mt" if pt.startswith("LME")
                        else ("KRW/kg" if cc == "LI" else "USD/kg"), "KOMIS"))

    df = pd.DataFrame(recs, columns=["commodity_code", "price_type", "freq",
                                     "obs_date", "val", "unit", "src"])
    if len(df) < 30:  # 5주 × 최소 6계열(REE/LI 결측 없다는 전제, 여유 가드)
        raise RuntimeError(f"추출 {len(df)}행 — 비정상 축소, 적재 중단")

    con = duckdb.connect(DB_PATH)
    con.register("_p", df)
    for _, row in df[["commodity_code", "price_type", "obs_date"]].drop_duplicates().iterrows():
        con.execute("DELETE FROM fact_price WHERE commodity_code=? AND price_type=? "
                    "AND obs_date=? AND freq='W'",
                    [row["commodity_code"], row["price_type"], row["obs_date"]])
    con.execute("INSERT INTO fact_price SELECT * FROM _p")
    con.unregister("_p")
    for (cc, pt), g in df.groupby(["commodity_code", "price_type"]):
        print(f"  {cc}/{pt}: {len(g)}행 ({g['obs_date'].min()}~{g['obs_date'].max()})")
    con.close()
    print(f"완료 — 총 {len(df)}행 반영")


if __name__ == "__main__":
    main()
