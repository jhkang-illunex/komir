# -*- coding: utf-8 -*-
"""근사중복 임베딩 표본 검증 재실행 (#6, 2026-07-22).

원본(`validate_neardup_embedding.py`, 2026-07-15)은 GKG 재정제 이전 코퍼스(1,815,194건,
관련성 71.4%)에서 표본을 뽑았다. 2026-07-20~21 GKG 관련성 재설계로 geo_event가 295,157건
(관련성 99.5%)으로 정리돼 근사중복 구성 자체가 달라졌을 수 있어(잡음 이벤트가 대량
제거되면 잔존 근사중복률도 바뀔 수 있음) DB 정본(운영 소스)에서 재실행한다. 방법은 원본과
동일(키 dedup 통과분에서 30버킷 표본, paraphrase-multilingual-MiniLM-L12-v2, cosine≥0.90).

실행: python3 -m scripts.validate_neardup_embedding_v2
산출: data_archive/analysis/neardup_embed_260722/report.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd

KOMIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, KOMIR)
os.environ.setdefault("GEO_PUBLISH_DB", os.path.join(KOMIR, "warehouse", "minerals.duckdb"))
from geo import store  # noqa: E402

N_BUCKETS = 30
BUCKET_MIN, BUCKET_CAP = 30, 400
COS_TH = 0.90
OUT_DIR = os.path.join(KOMIR, "data_archive", "analysis", "neardup_embed_260722")


def _key_dedup(ev: pd.DataFrame) -> pd.DataFrame:
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
    ev = _key_dedup(store.load_events(source="db"))
    ev = ev[ev["evidence_quote"].fillna("").str.len() >= 30]
    sizes = ev.groupby(["commodity", "_month"]).size()
    n_eligible = int((sizes >= BUCKET_MIN).sum())
    big = sizes[sizes >= BUCKET_MIN].sample(min(N_BUCKETS, n_eligible), random_state=0)
    print(f"[neardup-v2] 검증 버킷 {len(big)}개(광종·월, {BUCKET_MIN}건 이상, 대상 {n_eligible}개 중), "
          f"모집단 {len(ev):,}건 중")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device="cpu")
    rows, extra_total, n_total = [], 0, 0
    for (cc, mth), _n in big.items():
        g = ev[(ev["commodity"] == cc) & (ev["_month"] == mth)].head(BUCKET_CAP)
        emb = model.encode(g["evidence_quote"].str[:300].tolist(),
                           batch_size=64, show_progress_bar=False, normalize_embeddings=True)
        sim = emb @ emb.T
        np.fill_diagonal(sim, 0)
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
    by_commodity = rep.groupby("commodity").apply(
        lambda d: d["extra_dup"].sum() / d["n"].sum(), include_groups=False)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "report.md"), "w") as f:
        f.write("# 근사중복 임베딩 표본 검증 재실행 (#6, 2026-07-22, GKG 재정제 후 DB 정본)\n\n"
                f"- 모집단(DB, GKG 재정제 후): 키 dedup 통과 {len(ev):,}건 / 표본 버킷 "
                f"{len(big)}개({n_total:,}건)\n"
                f"- 판정 임계: cosine ≥ {COS_TH}\n"
                f"- **잔존 근사중복률(표본): {overall:.1%}** "
                f"(2026-07-15 구코퍼스 기준 12.0%였음 — 비교 참고)\n\n"
                "## 광종별 잔존율\n\n" + by_commodity.round(4).to_string() + "\n\n"
                "## 버킷별 상세\n\n" + rep.to_string(index=False) + "\n\n"
                "해석: 잔존율 ≤3%면 1단계(키 기반)로 충분 — 임베딩 전량 배치(BGE-M3, GPU)는\n"
                "보류. 초과 시 수집서버 GPU 배치로 2단계 도입 검토.\n")
    print(f"[neardup-v2] 표본 잔존 근사중복률 {overall:.1%} → {OUT_DIR}/report.md")
    print(rep.to_string(index=False))
    return overall, by_commodity


if __name__ == "__main__":
    run()
