# -*- coding: utf-8 -*-
"""근사중복 임베딩 표본 검증 (2026-07-15, 외부감사 B-1④ 2단계 판단자료).

1단계(키 기반: 정확 40자 + 정규화 80자 + 토큰정렬 키)가 indexer에 상시 적용됨.
이 스크립트는 임베딩 클러스터링(감사 원안: BGE-M3)까지 갔을 때 추가로 잡힐 잔존
근사중복이 얼마나 되는지 '표본'으로 추정한다 — 잔존율이 낮으면 GPU 배치(전량 임베딩)
없이 1단계로 충분하다는 근거, 높으면 2단계 도입 근거가 된다.

방법: 키 dedup을 통과한 이벤트를 (광종,월) 버킷에서 표본 추출 → 다국어 문장 임베딩
(CPU 표본용 paraphrase-multilingual-MiniLM-L12-v2; 운영 전량 배치 시 BGE-M3 권장) →
버킷 내 코사인 ≥0.90 쌍을 근사중복으로 카운트 → 잔존율(제거될 이벤트 비율) 추정.

실행: GEO_DATA=<geo_data> python -m scripts.validate_neardup_embedding
산출: komir/data_archive/analysis/neardup_embed_260715/report.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd

KOMIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOMIR)
from geo import store                                             # noqa: E402

N_BUCKETS = 30
BUCKET_MIN, BUCKET_CAP = 30, 400
COS_TH = 0.90
OUT_DIR = os.path.join(KOMIR, "data_archive", "analysis", "neardup_embed_260715")


def _key_dedup(ev: pd.DataFrame) -> pd.DataFrame:
    """indexer의 키 기반 dedup(정확·정규화·토큰) 복제 — 통과분이 검증 모집단."""
    ev = ev.copy()
    ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    ev = ev[(ev["date"] >= "2016-01-01") & (ev["date"] <= pd.Timestamp.now())]
    ev["_month"] = ev["date"].dt.to_period("M")
    ev["_quote_key"] = ev["evidence_quote"].fillna("").str.strip().str[:40]
    ev = (ev.sort_values("severity", ascending=False)
            .drop_duplicates(subset=["commodity", "_month", "_quote_key"], keep="first"))
    q = ev["evidence_quote"].fillna("").astype(str).str.lower()
    ev["_nkey"] = q.str.replace(r"[\d\W_]+", "", regex=True).str[:80]
    ev["_tkey"] = q.str.replace(r"[^\w가-힣 ]+", " ", regex=True).str.split().map(
        lambda t: " ".join(sorted(t)[:10]) if isinstance(t, list) else "")
    ev = ev[~((ev["_nkey"].str.len() >= 20)
              & ev.duplicated(subset=["commodity", "_month", "_nkey"], keep="first"))]
    ev = ev[~((ev["_tkey"].str.len() >= 20)
              & ev.duplicated(subset=["commodity", "_month", "_tkey"], keep="first"))]
    return ev


def run():
    from sentence_transformers import SentenceTransformer
    ev = _key_dedup(store.load_events(source="file"))
    ev = ev[ev["evidence_quote"].fillna("").str.len() >= 30]
    sizes = ev.groupby(["commodity", "_month"]).size()
    big = sizes[sizes >= BUCKET_MIN].sample(min(N_BUCKETS, (sizes >= BUCKET_MIN).sum()),
                                            random_state=0)
    print(f"[neardup] 검증 버킷 {len(big)}개(광종·월, {BUCKET_MIN}건 이상), "
          f"모집단 {len(ev):,}건 중")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device="cpu")
    rows, extra_total, n_total = [], 0, 0
    for (cc, mth), _n in big.items():
        g = ev[(ev["commodity"] == cc) & (ev["_month"] == mth)].head(BUCKET_CAP)
        emb = model.encode(g["evidence_quote"].str[:300].tolist(),
                           batch_size=64, show_progress_bar=False, normalize_embeddings=True)
        sim = emb @ emb.T
        np.fill_diagonal(sim, 0)
        # 근사중복 = 코사인≥TH 이웃이 있는 이벤트 중 클러스터 대표 1건 제외분(그리디)
        removed = set()
        order = np.argsort(-sim.max(axis=1))
        for i in order:
            if i in removed:
                continue
            dup = np.where(sim[i] >= COS_TH)[0]
            removed.update(j for j in dup if j not in removed and j != i)
        rows.append(dict(commodity=cc, month=str(mth), n=len(g), extra_dup=len(removed),
                         rate=round(len(removed) / len(g), 3)))
        extra_total += len(removed)
        n_total += len(g)
    rep = pd.DataFrame(rows).sort_values("rate", ascending=False)
    overall = extra_total / max(n_total, 1)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "report.md"), "w") as f:
        f.write("# 근사중복 임베딩 표본 검증 (키 dedup 잔존율)\n\n"
                f"- 모집단: 키 dedup 통과 {len(ev):,}건 / 표본 버킷 {len(big)}개({n_total:,}건)\n"
                f"- 판정 임계: cosine ≥ {COS_TH}\n"
                f"- **잔존 근사중복률(표본): {overall:.1%}**\n\n"
                + rep.to_string(index=False) + "\n\n"
                "해석: 잔존율 ≤3%면 1단계(키 기반)로 충분 — 임베딩 전량 배치(BGE-M3, GPU)는\n"
                "보류. 초과 시 수집서버 GPU 배치로 2단계 도입.\n")
    print(f"[neardup] 표본 잔존 근사중복률 {overall:.1%} → {OUT_DIR}/report.md")
    print(rep.head(8).to_string(index=False))
    return overall


if __name__ == "__main__":
    run()
