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
    # GKG 이벤트는 ingest→manifest를 거치지 않아(gkg_parse.py가 store에 직접 append) source가
    # 항상 NaN → 아래서 fillna(1.0)로 조용히 기본 신뢰도가 적용되어 sources.yaml의 GDELT 가중치가
    # 무시되는 문제가 있었음(2026-07-06 발견). provider 기준으로 보정.
    if "provider" in ev.columns:
        ev["source"] = ev["source"].fillna(ev["provider"].map({"gkg": "GDELT"}))
    # gkg_verify 재검증 통과분은 provider가 LLM provider(openai_compat 등)로 바뀌어 위 매핑을
    # 빠져나감(2026-07-08 발견) — manifest 미매칭(=GKG 유래뿐: 문서·gnews·gdelt collector는 전부
    # inbox→manifest 경유)인 잔여 NaN은 전부 GDELT로 귀속해 0.7 가중을 보존한다.
    ev["source"] = ev["source"].fillna("GDELT")

    # GKG "뉴스"(규칙기반 폴백 티어) 제외 — 실측(2026-07-06) 확인: 오프셋 근접성·2차 신호어 게이트를
    # 거친 뒤에도 이 티어는 GDELT 자체의 테마 오귀속(예: "구리"가 맥주 브루잉 설비·동전 등과 혼동,
    # 채굴 관련 테마가 동반돼도 실제로는 광산주 내부자거래 공시처럼 무관한 경우 다수)으로 정밀도가
    # 낮게 남는다. 제재/분쟁/정책/재해로 분류된 건(오프셋 근접성 검증됨)과 gkg_verify.py로 LLM
    # 재검증을 거쳐 extractor="llm"이 된 건만 지수에 반영한다.
    if "provider" in ev.columns and "extractor" in ev.columns:
        gkg_news_noise = (ev["provider"] == "gkg") & (ev["extractor"] == "rule") & (ev["event_type"] == "뉴스")
        n_excl = int(gkg_news_noise.sum())
        if n_excl:
            print(f"  [index] GKG 규칙기반 '뉴스' 티어 {n_excl}건 지수 계산에서 제외"
                  f"(LLM 재검증 전까지 신뢰도 부족 — gkg-verify로 승격 가능)")
        ev = ev[~gkg_news_noise]
    if len(ev) == 0:
        print("[index] 지수 반영 가능한 이벤트 없음(GKG 뉴스 티어 전량 제외됨)"); return pd.DataFrame()

    cfg = IndexConfig(**(C.load_yaml("index.yaml") or {}))
    rel = _reliability_map(); conc_static = _concentration_map()
    conc_df, hhi_df = _load_refdata()
    sign = cfg.direction_sign

    ev = ev.copy()
    ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    n_drop = int(ev["date"].isna().sum())
    if n_drop:
        print(f"  [warn] 날짜 미상 이벤트 {n_drop}건 지수에서 제외(obs_date/pub_date 없음)")
    ev = ev.dropna(subset=["date"])
    if len(ev) == 0:
        print("[index] 날짜 있는 이벤트 없음(obs_date/pub_date 확인)"); return pd.DataFrame()

    # 동일 사건 반복보도 중복합산 방지(실측 2026-07-08): 진행형 위기(예: DRC 코발트 수출중단)는
    # Argus 일일보고서 등에서 매일 거의 같은 근거문구로 재보도됨 — 이걸 그대로 합산하면 "같은 위기가
    # 계속 진행 중"이 "매일 새 위기 발생"처럼 과대산정됨. 같은 광종·같은 달(month)·근거인용 앞 40자가
    # 같으면 동일 사건의 반복보도로 간주해 최고 severity 1건만 남김(문서/이벤트 원본은 삭제하지 않음,
    # 지수 산출에서만 dedup). 실측: 6,510건 중 53건(<1%)이 이 케이스, CO(코발트)에 집중.
    ev["_quote_key"] = ev["evidence_quote"].fillna("").str.strip().str[:40]
    ev["_month"] = ev["date"].dt.to_period("M")
    before = len(ev)
    ev = (ev.sort_values("severity", ascending=False)
            .drop_duplicates(subset=["commodity", "_month", "_quote_key"], keep="first"))
    n_dedup = before - len(ev)
    if n_dedup:
        print(f"  [index] 동일사건 반복보도 중복 {n_dedup}건 제외(월+광종+근거문구 동일, 최고심각도만 유지)")

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
            g = g[g["n_events"] > 0]          # 근거(이벤트) 없는 중간 공백 기간은 발행하지 않음
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
