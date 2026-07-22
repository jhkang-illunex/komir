# -*- coding: utf-8 -*-
"""엔드투엔드 오케스트레이션: collect → preprocess → features → train
각 단계는 독립 실행 가능(멱등). 실패해도 다음 실행에서 이어서."""
import pandas as pd
from . import config
from .collectors import customs_api, ecos_api
from .preprocess import hs_mapping
from .features import builders
from .storage import db

# ---- 1) 수집 ----
def collect_customs(strt="201301", end="202512"):
    hs = hs_mapping.core_hs_list()
    print(f"[collect] 관세청 HS {len(hs)}개, {strt}~{end}")
    df = customs_api.collect(hs, strt, end)
    if not df.empty:
        df = hs_mapping.attach_commodity(df)
        db.upsert_df(df, "raw_customs_monthly", del_where="1=1")
    print(f"  적재 {len(df)} 행")
    return df

def collect_ecos():
    frames=[]
    for name,(code,cyc,item) in config.ECOS_SERIES.items():
        try:
            s = ecos_api.fetch_series(code, cyc, "2010", "2026", item1=item or "")
            if not s.empty:
                s["series"]=name; frames.append(s[["series","TIME","DATA_VALUE"]])
                print(f"  [ecos] {name}: {len(s)}행")
        except Exception as e:
            print(f"  [ecos] {name} 실패: {e}")
    if frames:
        out=pd.concat(frames); db.upsert_df(out, "raw_ecos", del_where="1=1"); return out
    return pd.DataFrame()

# ---- 2) 피처 ----
def build_features():
    con=db.connect(read_only=True)
    try: trade=con.execute("SELECT * FROM raw_customs_monthly").df()
    except Exception: trade=pd.DataFrame()
    con.close()
    if trade.empty: print("[features] 관세청 데이터 없음(먼저 collect)"); return
    hhi=builders.import_hhi(trade); grw=builders.import_growth(trade)
    db.upsert_df(hhi,"feat_import_hhi",del_where="1=1")
    db.upsert_df(grw,"feat_import_growth",del_where="1=1")
    print(f"[features] HHI {len(hhi)} · growth {len(grw)}")

def run_all():
    collect_customs(); collect_ecos(); build_features()
    print("[pipeline] 완료")
