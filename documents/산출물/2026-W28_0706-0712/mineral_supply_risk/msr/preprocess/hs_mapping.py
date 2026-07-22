# -*- coding: utf-8 -*-
"""HS코드 → 5대 광종 매핑 (감사·검증된 hs_commodity_map.csv 사용)"""
import pandas as pd
from ..config import HS_MAP_CSV

def load_map():
    m = pd.read_csv(HS_MAP_CSV, dtype=str)
    m["hs10"] = m["hs10"].str.strip()
    return m

def core_hs_list(map_df=None):
    """5대 광종에 해당하는 HS10 목록 반환(수집 대상)."""
    m = map_df if map_df is not None else load_map()
    return m[m["is_core5"].astype(str).str.upper().isin(["Y","TRUE","1"])]["hs10"].tolist()

def attach_commodity(trade_df, hs_col="hscode"):
    """교역 DataFrame에 commodity_code 부여(HS 매핑 기준)."""
    m = load_map()[["hs10","commodity_code"]]
    trade_df = trade_df.copy(); trade_df[hs_col] = trade_df[hs_col].astype(str).str.strip()
    return trade_df.merge(m, left_on=hs_col, right_on="hs10", how="left").drop(columns=["hs10"])
