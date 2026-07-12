# -*- coding: utf-8 -*-
"""KOMIS 제공 xlsx(실데이터) → warehouse 적재: fact_price(주간, 5광종) + fact_indicator(교사).

목적(2026-07-12): 진단모델이 지금까지 합성(SYNTH) 가격·교사신호로 돌던 것을 실데이터로 교체.
- 가격: 「0. KOMIS 핵심광물 공급망 통계(가격,수출입)」 '주간 평균' 시트 — 1987~2026 주간.
    CU/NI: LME CASH→LME_CASH, LME 3개월→LME_3M(스프레드 계산용)
    CO: LME CASH→LME_CASH / LI: 탄산리튬 CIF China→REF / REE: 산화네오디뮴 FOB China→REF
- 교사: 「수급동향지표.xlsx」 — 월별 2020-01~, 광종 컬럼(리튬/니켈/코발트/동/네오디뮴) →
    indicator='SUPPLY_DEMAND', freq='M' (v1 §7-3 라벨 2·3순위 원천)
- SYNTH 처리: 삭제 전 fact_*_synth_backup 테이블로 백업(보존 정책) 후 제거.

실행: MSR_DB=<warehouse> python -m scripts.load_komis_xlsx
"""
from __future__ import annotations
import argparse, warnings

import duckdb
import pandas as pd

from msr.config import DB_PATH

warnings.filterwarnings("ignore")

DOCS = "/home/nuri/dev/git/ws/mine_ws/documents"
PRICE_XLSX = f"{DOCS}/1. 광물가격, 재고량, 지수 등 (1)/0. KOMIS 핵심광물 공급망 통계(가격,수출입)_2026년 5월말 기준.xlsx"
TEACHER_XLSX = f"{DOCS}/4. KOMIS지표(광물지수, 시장동향지표, 수급동향지표) (2)/수급동향지표.xlsx"

# (광종명, 가격기준 접두) → (commodity_code, price_type)
PRICE_COLS = [
    ("동", "LME CASH", "CU", "LME_CASH"), ("동", "LME 3개월", "CU", "LME_3M"),
    ("니켈", "LME CASH", "NI", "LME_CASH"), ("니켈", "LME 3개월", "NI", "LME_3M"),
    ("코발트", "LME CASH", "CO", "LME_CASH"),
    ("탄산리튬", "99.5%min", "LI", "REF"),
    ("산화네오디뮴", "99.5%min", "REE", "REF"),
]
TEACHER_MAP = {"리튬": "LI", "니켈": "NI", "코발트": "CO", "동": "CU", "네오디뮴": "REE"}


def load_prices() -> pd.DataFrame:
    d = pd.ExcelFile(PRICE_XLSX).parse("주간 평균", header=None)
    names, basis, units = d.iloc[1].astype(str), d.iloc[3].astype(str), d.iloc[4].astype(str)
    rows = []
    for kname, kbasis, cc, ptype in PRICE_COLS:
        cols = [i for i in names.index
                if names[i].strip() == kname and str(basis[i]).startswith(kbasis)]
        if not cols:
            print(f"  [warn] 가격 컬럼 미발견: {kname}/{kbasis}")
            continue
        c = cols[0]
        sub = d.iloc[5:, [0, c]].copy()
        sub.columns = ["ymd", "val"]
        sub["obs_date"] = pd.to_datetime(sub["ymd"].astype(str), format="%Y%m%d", errors="coerce")
        sub["val"] = pd.to_numeric(sub["val"], errors="coerce")
        sub = sub.dropna(subset=["obs_date", "val"])
        rows.append(pd.DataFrame({
            "commodity_code": cc, "price_type": ptype, "freq": "W",
            "obs_date": sub["obs_date"].dt.date, "val": sub["val"],
            "unit": units[c], "src": "KOMIS"}))
    out = pd.concat(rows, ignore_index=True)
    out = out.drop_duplicates(["commodity_code", "price_type", "obs_date"], keep="last")
    return out


def load_teacher() -> pd.DataFrame:
    d = pd.ExcelFile(TEACHER_XLSX).parse("수급동향지표", header=None)
    names = d.iloc[1].astype(str)
    rows = []
    for kname, cc in TEACHER_MAP.items():
        cols = [i for i in names.index if names[i].strip() == kname]
        if not cols:
            print(f"  [warn] 교사 컬럼 미발견: {kname}")
            continue
        c = cols[0]
        sub = d.iloc[2:, [1, c]].copy()
        sub.columns = ["dt", "val"]
        sub["obs_date"] = pd.to_datetime(sub["dt"], errors="coerce")
        sub["val"] = pd.to_numeric(sub["val"], errors="coerce")
        sub = sub.dropna(subset=["obs_date", "val"])
        rows.append(pd.DataFrame({
            "commodity_code": cc, "indicator": "SUPPLY_DEMAND", "freq": "M",
            "obs_date": sub["obs_date"].dt.date, "val": sub["val"], "src": "KOMIS"}))
    out = pd.concat(rows, ignore_index=True)
    out = out.drop_duplicates(["commodity_code", "indicator", "obs_date"], keep="last")
    return out


def run(db: str | None = None) -> dict:
    prices, teacher = load_prices(), load_teacher()
    con = duckdb.connect(db or DB_PATH)
    # SYNTH 백업(보존 정책) 후 제거 — 실데이터로 완전 교체
    for tbl in ("fact_price", "fact_indicator"):
        n_synth = con.execute(f"SELECT count(*) FROM {tbl} WHERE src='SYNTH'").fetchone()[0]
        if n_synth:
            con.execute(f"CREATE OR REPLACE TABLE {tbl}_synth_backup AS "
                        f"SELECT * FROM {tbl} WHERE src='SYNTH'")
            con.execute(f"DELETE FROM {tbl} WHERE src='SYNTH'")
            print(f"  [synth] {tbl}: {n_synth}행 → {tbl}_synth_backup 백업 후 제거")
    # 기존 KOMIS 적재분 갱신(재실행 멱등): 동일 키 삭제 후 삽입
    con.register("_p", prices)
    con.execute("DELETE FROM fact_price WHERE src='KOMIS' AND freq='W'")
    con.execute("INSERT INTO fact_price SELECT commodity_code, price_type, freq, obs_date, val, unit, src FROM _p")
    con.register("_t", teacher)
    con.execute("DELETE FROM fact_indicator WHERE src='KOMIS' AND indicator='SUPPLY_DEMAND'")
    con.execute("INSERT INTO fact_indicator SELECT commodity_code, indicator, freq, obs_date, val, src FROM _t")
    con.execute("CHECKPOINT")
    chk = con.execute("""
        SELECT commodity_code, min(obs_date), max(obs_date), count(*)
        FROM fact_price WHERE freq='W' GROUP BY 1 ORDER BY 1""").fetchall()
    con.close()
    print(f"[komis] fact_price {len(prices)}행, fact_indicator {len(teacher)}행 적재")
    for r in chk:
        print("  ", r)
    return {"prices": len(prices), "teacher": len(teacher)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    run(ap.parse_args().db)
