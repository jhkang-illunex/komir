# -*- coding: utf-8 -*-
"""[3] 지수 산출(순수 결정론): geo_events → 광종별 주/월 지정학 위기 지수.
index = normalize( Σ severity × source_reliability × supply_concentration × sign(direction) )
"""
import pandas as pd
from . import config as C, store
from .schema import IndexConfig


def _reliability_map() -> dict:
    s = C.load_yaml("sources.yaml") or {}
    return {k: float(v) for k, v in (s.get("reliability") or {}).items()}


def _concentration_map() -> dict:
    s = C.load_yaml("sources.yaml") or {}
    # {"NI:Indonesia": 1.5, "REE:China": 1.8, ...}
    return {k: float(v) for k, v in (s.get("supply_concentration") or {}).items()}


def _load_refdata():
    """USGS refdata(연도별) 로드. 반환 (conc_df, hhi_df) 또는 (None,None)."""
    import os
    rd = C.CONFIG / "refdata"
    cf, hf = rd / "concentration.parquet", rd / "hhi.parquet"
    conc = pd.read_parquet(cf) if os.path.exists(cf) else None
    hhi = pd.read_parquet(hf) if os.path.exists(hf) else None
    return conc, hhi


def _nearest_weight(df, com, country, yr, keycols, valcol, default=1.0):
    """(commodity[,country]) 매칭 중 event 연도에 가장 가까운 값."""
    if df is None or country is None:
        return default
    q = df[df["commodity"] == com]
    if "country" in keycols:
        q = q[q["country"] == country]
    if len(q) == 0:
        return default
    q = q.assign(_d=(q["year"] - (yr or q["year"].max())).abs()).sort_values("_d")
    return float(q.iloc[0][valcol])


def _normalize(series: pd.Series, how: str, scale_k: float = 10.0) -> pd.Series:
    import numpy as np
    if how == "tanh0_100":
        # 절대 스케일 유계 변환: 과거 지수가 새 데이터로 재척도되지 않음(발행값 불변).
        # raw=0(이벤트 없음)→50, 심각(raw≈scale_k)→~88, 강한 호재(raw<0)→<50.
        return 50 + 50 * np.tanh(series.astype(float) / float(scale_k))
    if how == "zscore":
        sd = series.std(ddof=0)
        return (series - series.mean()) / sd if sd else series * 0
    # (구) minmax: 자기 히스토리 재척도 결함 — 하위호환용으로만 유지
    lo, hi = series.min(), series.max()
    return (series - lo) / (hi - lo) * 100 if hi > lo else series * 0 + 50


def compute() -> pd.DataFrame:
    ev = store.load_events()
    if len(ev) == 0:
        print("[index] 이벤트 없음"); return pd.DataFrame()
    man = store.load_manifest()[["doc_id", "source"]].drop_duplicates("doc_id")
    ev = ev.merge(man, on="doc_id", how="left")

    cfg = IndexConfig(**(C.load_yaml("index.yaml") or {}))
    rel = _reliability_map(); conc_static = _concentration_map()
    conc_df, hhi_df = _load_refdata()
    sign = cfg.direction_sign

    ev = ev.copy()
    ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    if len(ev) == 0:
        print("[index] 날짜 있는 이벤트 없음(obs_date/pub_date 확인)"); return pd.DataFrame()
    ev["yr"] = ev["date"].dt.year
    ev["rel"] = ev["source"].map(rel).fillna(1.0)

    if conc_df is not None:   # USGS refdata 우선(연도별 국가점유 + HHI배수)
        ev["conc"] = ev.apply(lambda r: _nearest_weight(
            conc_df, r["commodity"], r.get("country"), r["yr"], ["commodity","country"], "weight"), axis=1)
        ev["hhi_mult"] = ev.apply(lambda r: _nearest_weight(
            hhi_df, r["commodity"], "x", r["yr"], ["commodity"], "hhi_mult"), axis=1)
    else:                     # 폴백: sources.yaml 정적값
        ev["conc"] = (ev["commodity"] + ":" + ev["country"].fillna("")).map(conc_static).fillna(1.0)
        ev["hhi_mult"] = 1.0
    ev["sgn"] = ev["direction"].map(sign).fillna(0.2)
    ev["score"] = ev["severity"].astype(float) * ev["rel"] * ev["conc"] * ev["hhi_mult"] * ev["sgn"]

    out = []
    for freq, flabel in (("MS", "M"), ("W", "W")):
        for c, sub in ev.groupby("commodity"):
            g = (sub.set_index("date").resample(freq)["score"]
                    .agg(raw_score="sum", n_events="count").reset_index())
            g = g.rename(columns={"date": "period"})
            g["commodity"] = c
            g["freq"] = flabel
            g["index"] = _normalize(g["raw_score"], cfg.normalize, cfg.scale_k)
            out.append(g)
    res = pd.concat(out, ignore_index=True)
    res["period"] = pd.to_datetime(res["period"]).dt.strftime("%Y-%m-%d")
    return res[["commodity", "freq", "period", "raw_score", "n_events", "index"]]


def run():
    C.ensure_dirs()
    res = compute()
    if len(res):
        store.write_index(res)
        from .wiki import generate
        generate(res)
        print(f"[index] {len(res)}행 산출 → {C.INDEX}")
        print(res[res.freq=="M"].groupby("commodity")["n_events"].sum().to_string())
    return res


if __name__ == "__main__":
    run()
