# -*- coding: utf-8 -*-
"""엔드투엔드 오케스트레이션: collect → preprocess → features → train
각 단계는 독립 실행 가능(멱등). 실패해도 다음 실행에서 이어서."""
import pandas as pd
from . import config
from .collectors import customs_api, ecos_api
from .preprocess import hs_mapping
from .features import builders, normalize as normalize_mod
from .storage import db

# ---- 1) 수집 ----
def collect_customs(strt="201301", end="202512", freq="A"):
    """freq: 'A' 연간(→raw_customs_annual) | 'M' 월간(→raw_customs_monthly).
    월간은 콜 수 12배(HS×월). 예: collect_customs('201501','202512','M').
    HS 단위 증분 적재(중단 시 손실 최소화). 첫 적재에서만 기존 테이블 전삭제(멱등)."""
    hs = hs_mapping.core_hs_list()
    table = "raw_customs_monthly" if freq == "M" else "raw_customs_annual"
    print(f"[collect] 관세청 HS {len(hs)}개, {strt}~{end}, freq={freq} → {table}")
    state = {"first": True, "n": 0}

    def _sink(df_hs):
        df_hs = hs_mapping.attach_commodity(df_hs)
        db.upsert_df(df_hs, table, del_where="1=1" if state["first"] else None)
        state["first"] = False
        state["n"] += len(df_hs)

    try:
        customs_api.collect(hs, strt, end, freq=freq, sink=_sink)
    except customs_api.QuotaExceeded as e:
        print(f"  [중단] {e}  (그때까지 {state['n']}행은 {table}에 보존됨)")
    print(f"  적재 {state['n']} 행 → {table}")
    return state["n"]

def collect_ecos():
    frames=[]
    for name, s0 in config.ECOS_SERIES.items():
        try:
            s = ecos_api.fetch_series(s0["stat"], s0["cycle"], s0["start"], s0["end"],
                                      item1=s0.get("item1",""), item2=s0.get("item2",""))
            if not s.empty:
                s["series"]=name; frames.append(s[["series","TIME","DATA_VALUE"]])
                print(f"  [ecos] {name}: {len(s)}행")
        except Exception as e:
            print(f"  [ecos] {name} 실패: {e}")
    if frames:
        out=pd.concat(frames); db.upsert_df(out, "raw_ecos", del_where="1=1"); return out
    return pd.DataFrame()

# ---- 2) 정규화(raw→fact) ----
def normalize():
    """랜딩(raw_customs_*) → 정본 팩트(fact_trade_*) + agg_trade_annual."""
    return normalize_mod.run()

# ---- 3) 피처(정본 팩트 기반) ----
def build_features():
    con=db.connect(read_only=True)
    # raw가 아닌 정본 팩트에서 읽음(단일 소스). 없으면 먼저 normalize.
    try: trade=con.execute("SELECT commodity_code, yr AS year, country, imp_usd FROM fact_trade_monthly").df()
    except Exception: trade=pd.DataFrame()
    con.close()
    if trade.empty: print("[features] fact_trade_monthly 비어있음(먼저 collect→normalize)"); return
    hhi=builders.import_hhi(trade); grw=builders.import_growth(trade)
    db.upsert_df(hhi,"feat_import_hhi",del_where="1=1")
    db.upsert_df(grw,"feat_import_growth",del_where="1=1")
    print(f"[features] HHI {len(hhi)} · growth {len(grw)}")

def run_all():
    collect_customs(); collect_ecos(); normalize(); build_features()
    print("[pipeline] 완료")
