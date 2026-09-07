# -*- coding: utf-8 -*-
"""HS코드 → 5대 광종 매핑 (감사·검증된 hs_commodity_map.csv 사용)"""
import pandas as pd
from ..config import HS_MAP_CSV

def load_map():
    # utf-8-sig: CSV 선두 BOM 제거(컬럼명이 '﻿hs10'로 깨지는 것 방지). 컬럼 공백도 정리.
    m = pd.read_csv(HS_MAP_CSV, dtype=str, encoding="utf-8-sig")
    m.columns = [c.strip() for c in m.columns]
    m["hs10"] = m["hs10"].str.strip()
    return m

def core_hs_list(map_df=None):
    """5대 광종에 해당하는 HS10 목록 반환(수집 대상)."""
    m = map_df if map_df is not None else load_map()
    return m[m["is_core5"].astype(str).str.upper().isin(["Y","TRUE","1"])]["hs10"].tolist()

def attach_commodity(trade_df, hs_col="hscode"):
    """교역 DataFrame에 commodity_code 부여(HS 매핑 기준)."""
    m = load_map()[["hs10", "commodity_code"]].copy()
    # 매핑의 빈 commodity_code(비-core HS)는 ''가 아닌 결측으로 취급 → merge 후 NaN 유지
    m["commodity_code"] = m["commodity_code"].replace("", pd.NA)
    trade_df = trade_df.copy(); trade_df[hs_col] = trade_df[hs_col].astype(str).str.strip()
    return trade_df.merge(m, left_on=hs_col, right_on="hs10", how="left").drop(columns=["hs10"])
