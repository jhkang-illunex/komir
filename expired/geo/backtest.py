# -*- coding: utf-8 -*-
"""[3] 백테스트: 2016+ 전 이벤트로 만든 지수를 실제 결과(가격/수입)와 대조.
   유명충격 대조가 아니라 데이터주도 검증:
     (a) 리드-래그 상관: index[t] vs 결과의 미래 수익률[t+h]
     (b) 이벤트 스터디: 지수 급등(분위수 초과) 이후 h개월 평균 결과 변화
     (c) 경보 적중률: index>임계 → h개월내 불리한 움직임 hit-rate
   결과 시계열(outcome)은 별도 parquet로 주입: columns = commodity, period, value
     (가격 또는 수입량; 예: fact_price / raw_customs_monthly 월간집계)
  python -m geo index --backtest   또는   python -m geo.backtest --outcome path.parquet
"""
import argparse, os
import numpy as np, pandas as pd
from . import config as C, store

HORIZONS = [1, 2, 3, 6]          # 개월
SPIKE_Q = 0.8                    # 지수 급등 분위수
ALERT_THRESH = 70               # 0~100 지수 경보 임계


def _outcome_path(explicit=None):
    return explicit or os.environ.get("GEO_OUTCOME_PARQUET") or str(C.CONFIG / "refdata" / "outcome.parquet")


def _prep(idx, out, commodity):
    a = idx[(idx.commodity == commodity) & (idx.freq == "M")][["period", "index"]].copy()
    b = out[out.commodity == commodity][["period", "value"]].copy()
    for d in (a, b):
        d["period"] = pd.to_datetime(d["period"])
    m = a.merge(b, on="period", how="inner").sort_values("period").reset_index(drop=True)
    m["ret"] = m["value"].pct_change()
    return m


def backtest_commodity(m: pd.DataFrame, commodity: str) -> dict:
    res = {"commodity": commodity, "n": len(m)}
    if len(m) < 12:
        res["note"] = "표본부족"; return res
    # (a) 리드-래그: index[t] vs 미래 h개월 누적수익률
    for h in HORIZONS:
        fwd = m["value"].shift(-h) / m["value"] - 1
        res[f"corr_h{h}"] = round(m["index"].corr(fwd), 3)
    # (b) 이벤트 스터디: 지수 급등月 이후 평균 미래수익률 vs 전체 평균
    thr = m["index"].quantile(SPIKE_Q)
    spike = m["index"] >= thr
    for h in HORIZONS:
        fwd = m["value"].shift(-h) / m["value"] - 1
        res[f"es_h{h}"] = round(fwd[spike].mean() - fwd.mean(), 4)
    # (c) 경보 적중률: index>임계 → h내 가격상승(공급위기=가격↑)
    alert = m["index"] >= ALERT_THRESH
    if alert.sum():
        for h in HORIZONS:
            fwd = m["value"].shift(-h) / m["value"] - 1
            res[f"hit_h{h}"] = round((fwd[alert] > 0).mean(), 3)
    return res


def run(outcome=None):
    idx = store.load_events() if False else None
    from .store import _read
    idx = _read(C.INDEX)
    if len(idx) == 0:
        print("[backtest] 지수 없음(먼저 index)"); return
    path = _outcome_path(outcome)
    if not os.path.exists(path):
        print(f"[backtest] outcome 시계열 없음: {path}\n"
              "  → 가격/수입 월간 parquet(commodity,period,value)를 두거나 GEO_OUTCOME_PARQUET 지정.")
        return
    out = pd.read_parquet(path)
    rows = [backtest_commodity(_prep(idx, out, c), c) for c in sorted(idx.commodity.unique())]
    rep = pd.DataFrame(rows)
    rep.to_parquet(C.STORE / "geo_backtest.parquet", index=False)
    print("[backtest] 2016+ 데이터주도 검증 결과:")
    print(rep.to_string(index=False))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--outcome", default=None, help="결과 시계열 parquet(commodity,period,value)")
    run(ap.parse_args().outcome)
