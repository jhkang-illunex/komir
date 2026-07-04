# -*- coding: utf-8 -*-
"""⚠️ 합성(SYNTHETIC) 데모 데이터 생성 — 실데이터 부재 시 진단모델 end-to-end 검증용.
실 KOMIS/LME 가격·수급동향지표가 없어, 진단 파이프라인을 실증하기 위한 **가짜** 데이터를 만든다.
- fact_price(주간 LME_CASH/LME_3M/REF, src='SYNTH')
- fact_indicator(수급동향지표 SUPPLY_DEMAND 월간 교사신호, src='SYNTH')
교사신호는 가격변동성·수입편중(HHI)에 의존시켜 모델이 배울 구조를 갖게 함.
실데이터가 생기면 같은 fact 테이블(src≠'SYNTH')로 적재하면 되고, 이 스크립트는 쓰지 않는다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd, duckdb
from msr.config import DB_PATH
from msr.storage import db

# (기준가, 주간 로그변동성) — 대략적 규모만
COMS = {"CU": (8500, 0.02), "NI": (18000, 0.03), "LI": (15000, 0.05),
        "CO": (30000, 0.035), "REE": (60, 0.04)}


def generate(seed=42):
    rng = np.random.default_rng(seed)
    weeks = pd.date_range("2020-01-03", "2025-12-26", freq="W-FRI")
    price_rows, weekly = [], {}
    for com, (base, wv) in COMS.items():
        shocks = rng.normal(0, wv, len(weeks))
        for _ in range(3):  # 변동성 급등 국면 몇 번 주입
            i = int(rng.integers(20, len(weeks) - 10)); shocks[i:i+6] += rng.normal(0, wv*4, 6)
        logp = np.log(base) + np.cumsum(shocks)
        cash = np.exp(logp)
        m3 = cash * (1 + rng.normal(0.005, 0.01, len(weeks)))       # 소폭 contango
        weekly[com] = pd.DataFrame({"date": weeks, "logret": np.concatenate([[np.nan], np.diff(logp)])})
        for d, c, m in zip(weeks, cash, m3):
            price_rows.append((com, "LME_CASH", "W", d.date(), float(c), "USD/mt", "SYNTH"))
            price_rows.append((com, "LME_3M",   "W", d.date(), float(m), "USD/mt", "SYNTH"))
            price_rows.append((com, "REF",      "W", d.date(), float(c), "USD/mt", "SYNTH"))
    pf = pd.DataFrame(price_rows, columns=["commodity_code", "price_type", "freq", "obs_date", "val", "unit", "src"])

    # 수입편중 HHI(정본 팩트 기반) — 교사신호 종속변수로 사용
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        hhi = con.execute("SELECT commodity_code, year, import_hhi FROM agg_trade_annual").df()
    except Exception:
        hhi = pd.DataFrame(columns=["commodity_code", "year", "import_hhi"])
    con.close()
    hhimap = {(r.commodity_code, int(r.year)): r.import_hhi for r in hhi.itertuples()}

    recs = []
    for com, dfw in weekly.items():
        dfw = dfw.copy(); dfw["vol12"] = dfw["logret"].rolling(12, min_periods=4).std()
        dfw["month"] = dfw["date"].values.astype("datetime64[M]")
        mv = dfw.groupby("month")["vol12"].mean().reset_index()
        for _, r in mv.iterrows():
            yr = pd.Timestamp(r["month"]).year
            recs.append((com, pd.Timestamp(r["month"]), r["vol12"], hhimap.get((com, yr), np.nan)))
    rec = pd.DataFrame(recs, columns=["com", "month", "vol", "hhi"])
    rec["zvol"] = (rec["vol"] - rec["vol"].mean()) / rec["vol"].std()
    rec["zhhi"] = (rec["hhi"] - rec["hhi"].mean()) / rec["hhi"].std()
    # 수급동향지표(0~100): 변동성·편중 높을수록 낮음(=위기). 학습 가능한 신호 + 노이즈.
    rec["teacher"] = np.clip(65 - 22*rec["zvol"].fillna(0) - 8*rec["zhhi"].fillna(0) + rng.normal(0, 6, len(rec)), 0, 100)
    idf = pd.DataFrame([(r["com"], "SUPPLY_DEMAND", "M", pd.Timestamp(r["month"]).date(), float(r["teacher"]), "SYNTH")
                        for _, r in rec.iterrows()],
                       columns=["commodity_code", "indicator", "freq", "obs_date", "val", "src"])

    db.upsert_df(pf, "fact_price", del_where="src='SYNTH'")
    db.upsert_df(idf, "fact_indicator", del_where="src='SYNTH'")
    print(f"[synth] ⚠️ 합성 데모: fact_price(SYNTH) {len(pf)}행 · fact_indicator(SYNTH) {len(idf)}행 적재")
    return {"price": len(pf), "indicator": len(idf)}


if __name__ == "__main__":
    generate()
