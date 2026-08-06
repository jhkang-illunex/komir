# -*- coding: utf-8 -*-
"""피처 산출: 수입 HHI/CAGR/YoY, 가격 변동성, Cash-3M 스프레드, geo_pressure 결합"""
import numpy as np, pandas as pd

def import_hhi(trade_df, value="imp_usd", by=("commodity_code","year")):
    """국가별 수입액 점유율 제곱합 ×10000 (0~10000). 총수입 0/전무면 NaN(집중도 미산정)."""
    g = trade_df.dropna(subset=["commodity_code"]).groupby(list(by)+["country"])[value].sum().reset_index()
    tot = g.groupby(list(by))[value].transform("sum")
    g["share2"] = (g[value]/tot.replace(0,np.nan))**2
    # min_count=1: 전부 NaN(총수입 0)인 그룹은 0이 아니라 NaN으로(잘못된 '집중도 0' 방지)
    return g.groupby(list(by))["share2"].sum(min_count=1).mul(10000).rename("import_hhi").reset_index()

def import_growth(trade_df, value="imp_usd", by=("commodity_code",), tcol="year"):
    """연도별 총수입 → YoY, 3년 CAGR. 결측 연도를 연도그리드로 채워 **연도 기반**으로 계산
    (행 기반 shift가 결측연도에서 인접하지 않은 연도를 비교하던 버그 방지)."""
    by = list(by)
    t = (trade_df.dropna(subset=["commodity_code"])
         .groupby(by+[tcol])[value].sum().reset_index())
    frames = []
    for key, g in t.groupby(by):
        g = g.set_index(tcol).sort_index()
        g = g.reindex(range(int(g.index.min()), int(g.index.max())+1))  # 결측연도=NaN
        g["import_yoy"] = g[value] / g[value].shift(1) - 1              # 직전 '연도'
        g["import_cagr3"] = (g[value] / g[value].shift(3))**(1/3) - 1   # 3'년' 전
        keys = key if isinstance(key, tuple) else (key,)
        for col, val in zip(by, keys): g[col] = val
        frames.append(g.reset_index())
    res = pd.concat(frames, ignore_index=True)
    return res.dropna(subset=[value]).reset_index(drop=True)  # 채워넣은 결측연도 행 제거

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
