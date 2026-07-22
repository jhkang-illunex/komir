# -*- coding: utf-8 -*-
"""정제 후 SRS 재검증(2026-07-20 /goal) — gkg_backfill_relevance.py 실행 후 cleaned geo_event
모집단에서 새 단순임의표본을 뽑아 관련성(오염률)을 재확인한다. 방법론은
srs_contamination_check.py와 동일(계층 없는 순수 무작위, Wilson CI) — 다만 seed는 이전
표본(0.42)과 달라야 독립적 사후검증이 된다.

실행 순서:
  1. DuckDB에서 setseed(0.91)로 새 n=200 표본 추출 → CSV.
  2. 표본을 evidence_quote 기준으로 Claude가 직접 판정(R/I/U) → JUDGMENTS 딕셔너리 채움.
  3. write_report()로 Wilson CI 포함 보고서 출력.
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def draw_sample(db_path: str, out_csv: str, seed: float = 0.91, n: int = 200):
    import duckdb
    con = duckdb.connect(db_path, read_only=True)
    con.execute(f"SELECT setseed({seed})")
    df = con.execute(f"""
        SELECT event_id, doc_id, commodity_code, evidence_quote, event_type, severity
        FROM geo_event
        WHERE doc_id ~ '^[0-9]{{14}}-[0-9]+$'
        ORDER BY random()
        LIMIT {n}
    """).fetchdf()
    df.to_csv(out_csv, index=False)
    print(f"[srs_post_cleanup] 표본 {len(df)}건 저장 → {out_csv}")
    return df


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z ** 2 / n
    center = p + z ** 2 / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return ((center - half) / denom, (center + half) / denom)


def write_report(judgments: dict, out_md: str, sample_csv: str):
    import pandas as pd
    df = pd.read_csv(sample_csv)
    r = sum(1 for v in judgments.values() if v == "R")
    i = sum(1 for v in judgments.values() if v == "I")
    u = sum(1 for v in judgments.values() if v == "U")
    n = r + i
    rate = i / n if n else 0.0
    lo, hi = _wilson_ci(i, n)
    lines = [
        "# GKG 정제 후 SRS 재검증 결과 (2026-07-20 /goal)",
        "",
        f"- 표본 n={len(df)} (U 제외 n={n})",
        f"- R(관련) {r} / I(오염) {i} / U(판단불가) {u}",
        f"- **정제 후 오염률 = {i}/{n} = {rate:.1%} (95% Wilson CI [{lo:.1%}, {hi:.1%}])**",
        f"- **관련성(유효성) = {1 - rate:.1%}**",
        "",
        "정제 전(07-20 최초 SRS): 오염률 71.4% (95% CI [64.3%, 77.6%]) — 비교 기준.",
    ]
    Path(out_md).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/minerals.duckdb")
    ap.add_argument("--out-csv", default="/tmp/srs_post_cleanup.csv")
    ap.add_argument("--seed", type=float, default=0.91)
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    draw_sample(a.db, a.out_csv, a.seed, a.n)
