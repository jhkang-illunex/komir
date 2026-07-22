# -*- coding: utf-8 -*-
"""피처 산출: 수입 HHI/CAGR/YoY, 가격 변동성, Cash-3M 스프레드, geo_pressure 결합"""
import numpy as np, pandas as pd

def import_hhi(trade_df, value="imp_usd", by=("commodity_code","year")):
    """국가별 수입액 점유율 제곱합 ×10000 (0~10000)"""
    g = trade_df.dropna(subset=["commodity_code"]).groupby(list(by)+["country"])[value].sum().reset_index()
    tot = g.groupby(list(by))[value].transform("sum")
    g["share2"] = (g[value]/tot.replace(0,np.nan))**2
    return g.groupby(list(by))["share2"].sum().mul(10000).rename("import_hhi").reset_index()

def import_growth(trade_df, value="imp_usd", by=("commodity_code",), tcol="year"):
    """연도별 총수입 → YoY, 3년 CAGR"""
    t = (trade_df.dropna(subset=["commodity_code"])
         .groupby(list(by)+[tcol])[value].sum().reset_index().sort_values(list(by)+[tcol]))
    t["import_yoy"] = t.groupby(list(by))[value].pct_change()
    t["import_cagr3"] = (t[value]/t.groupby(list(by))[value].shift(3))**(1/3)-1
    return t

def volatility(price_df, price="value", by="commodity_code", dcol="obs_date", win=12):
    """로그수익률 rolling 표준편차"""
    d = price_df.sort_values([by,dcol]).copy()
    d["logret"] = d.groupby(by)[price].transform(lambda s: np.log(s/s.shift()))
    d["volatility"] = d.groupby(by)["logret"].transform(lambda s: s.rolling(win,min_periods=4).std())
    return d

def cash3m_spread(cash_df, m3_df, on=("commodity_code","obs_date")):
    """(Cash-3M)/3M ×100"""
    m = cash_df.merge(m3_df, on=list(on), suffixes=("_cash","_3m"))
    m["spread_pct"] = (m["value_cash"]-m["value_3m"])/m["value_3m"].replace(0,np.nan)*100
    return m[list(on)+["spread_pct"]]
