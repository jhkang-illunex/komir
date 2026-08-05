# -*- coding: utf-8 -*-
"""근사중복 잔존 영향 재정량화 (#6, 2026-07-22).

`neardup_impact_sim.py`(B-6, 2026-07-16)의 결론(2단계 임베딩 dedup 불필요, Jaccard 0.945)을
GKG 재정제 후 DB 정본(295,157건)과 오늘 재실행한 임베딩 잔존율(`validate_neardup_embedding_v2.py`,
전체 10.4%, 광종별 CO 0.1445/CU 0.0950/LI 0.0956/NI 0.1096/REE 0.0861)로 재검증한다.
방법은 원본과 완전 동일(재구현 없음, `store.load_events`만 몽키패치).

실행: GEO_EVENT_SOURCE=db GEO_PUBLISH_DB=../warehouse/minerals.duckdb python3 -m scripts.neardup_impact_sim_v2
산출: outputs/model_opt/neardup_impact_sim_v2.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))

from geo import store, indexer  # noqa: E402
from msr.config import OUT

RATE_BY_COMMODITY = {"CO": 0.1445, "CU": 0.0950, "LI": 0.0956, "NI": 0.1096, "REE": 0.0861}
DEFAULT_RATE = 0.10
SEED = 42
TOP_N = 20


def simulate_removal(ev: pd.DataFrame) -> pd.DataFrame:
    ev = ev.reset_index(drop=True).copy()
    date = pd.to_datetime(ev["obs_date"], errors="coerce")
    month = date.dt.to_period("M")
    rng = np.random.default_rng(SEED)
    keep = np.ones(len(ev), dtype=bool)
    for (cc, mo), idx in ev.groupby([ev["commodity"], month]).groups.items():
        rate = RATE_BY_COMMODITY.get(cc, DEFAULT_RATE)
        pos = np.asarray(idx)
        n_remove = int(round(len(pos) * rate))
        if n_remove > 0:
            remove_pos = rng.choice(pos, size=n_remove, replace=False)
            keep[remove_pos] = False
    n_removed = int((~keep).sum())
    print(f"  [sim-v2] 근사중복 시뮬레이션 제거: {n_removed:,}/{len(ev):,}건 "
          f"({n_removed/len(ev):.1%}, 2026-07-22 재측정 비율 적용)")
    return ev[keep].reset_index(drop=True)


def run():
    ev_base = store.load_events(source="db")
    print(f"기준 모집단(DB, GKG 재정제 후): {len(ev_base):,}건")
    ev_sim = simulate_removal(ev_base)

    orig_load = store.load_events

    def _patched(*a, **kw):
        return ev_sim
    store.load_events = _patched
    try:
        res_sim = indexer.compute()
    finally:
        store.load_events = orig_load
    res_base = indexer.compute()

    wk_base = res_base[res_base["freq"] == "W"].copy()
    wk_sim = res_sim[res_sim["freq"] == "W"].copy()

    rows = []
    for cc in sorted(wk_base["commodity"].unique()):
        b = wk_base[wk_base["commodity"] == cc].set_index("period")["index"]
        s = wk_sim[wk_sim["commodity"] == cc].set_index("period")["index"]
        common = b.index.intersection(s.index)
        b2, s2 = b.loc[common], s.loc[common]
        corr = float(b2.corr(s2)) if len(common) > 1 else float("nan")
        mad = float((b2 - s2).abs().mean())
        top_b = set(b.sort_values(ascending=False).head(TOP_N).index)
        top_s = set(s.sort_values(ascending=False).head(TOP_N).index)
        jac = len(top_b & top_s) / len(top_b | top_s) if (top_b | top_s) else float("nan")
        rows.append(dict(commodity=cc, n_week=len(common), corr=round(corr, 4),
                          mean_abs_diff=round(mad, 3), top20_jaccard=round(jac, 3)))
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    write_report(res, ev_base, ev_sim)


def write_report(res: pd.DataFrame, ev_base, ev_sim):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "neardup_impact_sim_v2.md")
    L = []
    L.append("# 근사중복 잔존 영향 재정량화 (#6, 2026-07-22)\n")
    L.append(f"작성: 2026-07-22 · GKG 재정제 후 DB 정본 {len(ev_base):,}건, 시뮬레이션 제거 후 "
             f"{len(ev_sim):,}건({(len(ev_base)-len(ev_sim))/len(ev_base):.1%} 제거). "
             "광종별 제거율은 `validate_neardup_embedding_v2.py`(2026-07-22, DB 정본 재측정) 사용.\n")
    L.append("\n## 지수 순위·값 영향 (freq='W', 광종별)\n")
    L.append("| 광종 | 공통 주간수 | 상관계수 | 평균절대차 | 상위20주 Jaccard |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['commodity']} | {int(r['n_week'])} | {r['corr']:.4f} | "
                 f"{r['mean_abs_diff']:.3f} | {r['top20_jaccard']:.3f} |")
    avg_corr = res["corr"].mean(); avg_jac = res["top20_jaccard"].mean()
    verdict = ("2단계(BGE-M3 전량 임베딩) 여전히 불필요 — 1단계로 충분"
               if avg_jac >= 0.85 else "재검토 필요 — 2단계 도입 근거 강화됨")
    L.append(f"\n**결론**: 평균 상관계수 {avg_corr:.4f}, 평균 상위20주 Jaccard {avg_jac:.3f} "
             f"(2026-07-16 구코퍼스 기준 0.9981/0.945였음). **{verdict}**\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[write] {path}")


if __name__ == "__main__":
    run()
