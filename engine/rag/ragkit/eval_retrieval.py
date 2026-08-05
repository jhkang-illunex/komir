# -*- coding: utf-8 -*-
"""검색 품질 평가 — rag/docs/estimate_question(2,800여 문항, 문서별 정답 source가 이미
frontmatter에 있음)을 골든셋으로 재사용(가이드 §7: 골든셋 기반 평가). LLM 호출 없이
임베딩+BM25만으로 끝까지 도는 것이 핵심 — 생성 품질과 분리해 리트리버 자체의
실패모드를 진단한다(가이드 §1: 실패유형을 먼저 진단하고 그다음 아키텍처를 고른다)."""
from __future__ import annotations

import glob
import os
import re
import time
from dataclasses import dataclass

import duckdb
import numpy as np

from .build_index import DB_PATH
from .embed import get_model
from .tokenize_ko import to_fts_text

QUESTION_DIR = "rag/docs/estimate_question"
RRF_K = 60
FANOUT = 30
KS = (1, 3, 5, 10)


@dataclass
class GoldenItem:
    question: str
    source_path: str
    week: str


def load_golden_questions() -> list[GoldenItem]:
    """(question, golden_source_path) 목록. README.md(인덱스 파일)는 제외."""
    out = []
    for path in sorted(glob.glob(f"{QUESTION_DIR}/**/*.md", recursive=True)):
        if os.path.basename(path) == "README.md":
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        m_src = re.search(r"^source:\s*(.+)$", text, re.M)
        m_wk = re.search(r"^week:\s*(.+)$", text, re.M)
        if not m_src:
            continue
        source = m_src.group(1).strip()
        week = m_wk.group(1).strip() if m_wk else ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("- "):
                q = line[2:].strip()
                if q:
                    out.append(GoldenItem(question=q, source_path=source, week=week))
    return out


def _load_corpus(con: duckdb.DuckDBPyConnection):
    rows = con.execute(
        "SELECT c.chunk_id, c.doc_id, c.embedding, d.source_path FROM chunk c JOIN doc d USING (doc_id)"
    ).fetchall()
    chunk_ids = [r[0] for r in rows]
    doc_id_by_chunk = {r[0]: r[1] for r in rows}
    embeddings = np.array([r[2] for r in rows], dtype=np.float32)
    source_by_doc = {r[1]: r[3] for r in rows}
    return chunk_ids, doc_id_by_chunk, embeddings, source_by_doc


def evaluate(k_list=KS, fanout=FANOUT, sample: int | None = None, db_path: str = DB_PATH, seed: int = 0):
    golden = load_golden_questions()
    if sample:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(golden), size=min(sample, len(golden)), replace=False)
        golden = [golden[i] for i in idx]
    print(f"골든 질문 {len(golden)}건 로드")

    con = duckdb.connect(db_path, read_only=True)
    con.execute("INSTALL fts; LOAD fts;")
    chunk_ids, doc_id_by_chunk, embeddings, source_by_doc = _load_corpus(con)
    n_chunks = len(chunk_ids)
    print(f"청크 {n_chunks}개 로드 완료")

    doc_id_by_source = {v: k for k, v in source_by_doc.items()}
    items = [g for g in golden if g.source_path in doc_id_by_source]
    skipped = len(golden) - len(items)
    if skipped:
        missing = sorted({g.source_path for g in golden if g.source_path not in doc_id_by_source})
        print(f"인덱스에 없는 source {len(missing)}종(질문 {skipped}건 스킵): {missing[:5]}")

    t0 = time.time()
    model = get_model()
    qvecs = model.encode([f"query: {g.question}" for g in items], batch_size=64,
                          normalize_embeddings=True, show_progress_bar=True)
    print(f"질의 임베딩 {len(items)}건: {time.time()-t0:.1f}s")

    sims = qvecs @ embeddings.T  # (Nq, n_chunks), 정규화 벡터라 내적=코사인
    kth = min(fanout, n_chunks - 1)
    dense_top_idx = np.argpartition(-sims, kth=kth, axis=1)[:, :fanout]

    ranks: list[int | None] = []
    t0 = time.time()
    for qi, item in enumerate(items):
        row = sims[qi]
        order = dense_top_idx[qi][np.argsort(-row[dense_top_idx[qi]])]
        dense_rank = {chunk_ids[j]: r + 1 for r, j in enumerate(order)}

        fq = to_fts_text(item.question)
        bm25_rank: dict[str, int] = {}
        if fq.strip():
            bm_rows = con.execute(
                """
                SELECT chunk_id FROM (
                    SELECT chunk_id, fts_main_chunk.match_bm25(chunk_id, ?) AS score FROM chunk
                ) WHERE score IS NOT NULL ORDER BY score DESC LIMIT ?
                """,
                [fq, fanout],
            ).fetchall()
            bm25_rank = {r[0]: i + 1 for i, r in enumerate(bm_rows)}

        cand = set(dense_rank) | set(bm25_rank)
        scored = []
        for cid in cand:
            s = 0.0
            if cid in dense_rank:
                s += 1.0 / (RRF_K + dense_rank[cid])
            if cid in bm25_rank:
                s += 1.0 / (RRF_K + bm25_rank[cid])
            scored.append((cid, s))
        scored.sort(key=lambda x: -x[1])

        golden_doc = doc_id_by_source[item.source_path]
        found_rank = None
        for rank, (cid, _s) in enumerate(scored, 1):
            if doc_id_by_chunk[cid] == golden_doc:
                found_rank = rank
                break
        ranks.append(found_rank)
    print(f"검색+융합 {len(items)}건: {time.time()-t0:.1f}s")

    con.close()
    return items, ranks


def summarize(items: list[GoldenItem], ranks: list[int | None], k_list=KS) -> dict:
    n = len(items)
    recall = {k: sum(1 for r in ranks if r is not None and r <= k) / n for k in k_list}
    mrr = sum((1.0 / r) if r else 0.0 for r in ranks) / n
    zero = sum(1 for r in ranks if r is None or r > max(k_list))

    by_week: dict[str, list[int | None]] = {}
    for item, r in zip(items, ranks):
        by_week.setdefault(item.week, []).append(r)
    week_recall_at5 = {
        wk: sum(1 for r in rs if r is not None and r <= 5) / len(rs) for wk, rs in sorted(by_week.items())
    }

    return {
        "n": n,
        "recall": recall,
        "mrr": mrr,
        "miss_beyond_k": zero,
        "week_recall_at5": week_recall_at5,
    }


def worst_cases(items: list[GoldenItem], ranks: list[int | None], n: int = 15) -> list[tuple[GoldenItem, int | None]]:
    misses = [(item, r) for item, r in zip(items, ranks) if r is None or r > 10]
    return misses[:n]


if __name__ == "__main__":
    import sys

    sample = int(sys.argv[1]) if len(sys.argv) > 1 else None
    items, ranks = evaluate(sample=sample)
    stats = summarize(items, ranks)
    print("\n=== 검색 품질 요약 ===")
    print(f"질문수: {stats['n']}")
    for k, v in stats["recall"].items():
        print(f"recall@{k}: {v*100:.1f}%")
    print(f"MRR: {stats['mrr']:.4f}")
    print(f"완전 미스(순위>10 또는 없음): {stats['miss_beyond_k']}건 ({stats['miss_beyond_k']/stats['n']*100:.1f}%)")
    print("\n=== 주차별 recall@5 ===")
    for wk, v in stats["week_recall_at5"].items():
        print(f"  {wk}: {v*100:.1f}%")

    print("\n=== 완전 미스 샘플 ===")
    for item, r in worst_cases(items, ranks)[:15]:
        print(f"  [{item.week}] {item.source_path}")
        print(f"    Q: {item.question}")
