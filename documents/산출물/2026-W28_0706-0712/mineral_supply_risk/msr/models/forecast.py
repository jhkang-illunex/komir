# -*- coding: utf-8 -*-
"""수입 예측 베이스라인 (월간 확보 시 12개월 선행). 현재 연간 패널 지원."""
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

def walk_forward(df, target, feats, group="commodity_code", tcol="date", split=None):
    df = df.sort_values(tcol)
    tr = df[df[tcol] < split]; te = df[df[tcol] >= split]
    codes = {c:i for i,c in enumerate(sorted(df[group].unique()))}
    Xtr = tr[feats].assign(_g=tr[group].map(codes)); Xte = te[feats].assign(_g=te[group].map(codes))
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=3,
        categorical_features=[len(feats)], random_state=42).fit(Xtr, tr[target])
    pred = m.predict(Xte)
    return {"MAE": round(mean_absolute_error(te[target],pred),3),
            "R2": round(r2_score(te[target],pred),3), "n_test": len(te)}, m
