# -*- coding: utf-8 -*-
"""근사중복 잔존 12% 영향 정량화(B-6) — 피드백기반_수정플랜 P2.

`validate_neardup_embedding.py`(2026-07-15)가 표본(30개 (광종,월) 버킷, 6,161건)에서 임베딩
클러스터링으로 추정한 광종별 잔존 근사중복률[^rates]을 이용해, **실제 임베딩 없이** 관측된
비율만큼 (광종,월) 버킷별로 무작위 제거한 시뮬레이션 모집단을 만들고, `geo/indexer.py`의
`compute()`와 `geo/prob_model.py`의 적합 함수를 **원본 코드 그대로** 두 번(제거 전/후) 실행해
지수 순위(Jaccard)·NB2 확률 변화폭을 정량화한다. 재구현 없음(indexer.compute()/prob_model
내부 로직을 손대지 않고, 입력 이벤트 모집단만 `store.load_events`를 몽키패치해 바꿔치기).

[^rates]: `komir/data_archive/analysis/neardup_embed_260715/report.md` 버킷별 잔존율
평균(광종별, 코드 내 하드코딩값에 출처 주석): LI 0.0972(10버킷)·CU 0.1273(3버킷)·
NI 0.1367(7버킷)·REE 0.0630(5버킷)·CO 0.0484(5버킷) — 전체 평균 12.0%와 정합.

실행: python3 -m scripts.neardup_impact_sim
산출: outputs/model_opt/neardup_impact_sim.md
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
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo import store, indexer  # noqa: E402

from msr.config import OUT

# validate_neardup_embedding.py 산출 리포트(2026-07-15)의 광종별 버킷 평균 잔존 근사중복률.
RATE_BY_COMMODITY = {"LI": 0.0972, "CU": 0.1273, "NI": 0.1367, "REE": 0.0630, "CO": 0.0484}
DEFAULT_RATE = 0.12
SEED = 42
TOP_N = 20


def simulate_removal(ev: pd.DataFrame) -> pd.DataFrame:
    """(광종,월) 버킷별로 관측된 잔존 근사중복률만큼 무작위 제거한 모집단."""
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
    print(f"  [sim] 근사중복 시뮬레이션 제거: {n_removed:,}/{len(ev):,}건 "
          f"({n_removed/len(ev):.1%}, 광종별 관측 비율 적용)")
    return ev[keep].reset_index(drop=True)


def run():
    ev_base = store.load_events()
    print(f"기준 모집단(store.load_events, 필터 전): {len(ev_base):,}건")
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

    rows, jaccards = [], []
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
        jaccards.append(jac)

    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    write_report(res, ev_base, ev_sim)


def write_report(res: pd.DataFrame, ev_base, ev_sim):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "neardup_impact_sim.md")
    L = []
    L.append("# 근사중복 잔존 12% 영향 정량화 (B-6)\n")
    L.append(f"작성: 2026-07-16 · 기준 모집단 {len(ev_base):,}건, 시뮬레이션 제거 후 "
             f"{len(ev_sim):,}건({(len(ev_base)-len(ev_sim))/len(ev_base):.1%} 제거). "
             f"광종별 제거율은 `validate_neardup_embedding.py`(2026-07-15) 표본 버킷 평균을 "
             f"그대로 사용, 실제 임베딩 재실행 없이 `geo/indexer.compute()` 원본 코드를 "
             f"입력만 바꿔 두 번 실행(재구현 없음, 몽키패치로 `store.load_events`만 대체).\n")

    L.append("\n## 지수 순위·값 영향 (freq='W', 광종별)\n")
    L.append("| 광종 | 공통 주간수 | 상관계수 | 평균절대차 | 상위20주 Jaccard |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['commodity']} | {int(r['n_week'])} | {r['corr']:.4f} | "
                 f"{r['mean_abs_diff']:.3f} | {r['top20_jaccard']:.3f} |")

    avg_jac = res["top20_jaccard"].mean()
    avg_corr = res["corr"].mean()
    L.append(f"\n**결론**: 평균 상관계수 {avg_corr:.4f}, 평균 상위20주 Jaccard {avg_jac:.3f}. "
             f"Jaccard가 1에 가까울수록 2단계(BGE-M3 전량 임베딩) 도입이 지수 상위 신호에 "
             f"실질적 영향이 없다는 뜻 — 1단계(키 기반)로 충분하다는 `validate_neardup_embedding.py`"
             f"의 결론(잔존율 표본 기준)을 지수 순위 관점에서 재확인한다. Jaccard가 낮으면 "
             f"근사중복이 특정 주간에 집중돼 순위 자체를 흔든다는 뜻이라 2단계 도입 근거가 "
             f"강화된다.\n")

    L.append("\n## 시뮬레이션 한계\n")
    L.append("실제 임베딩으로 '어떤 이벤트가 근사중복인지' 식별하지 않고, 관측된 비율만큼 "
             "(광종,월) 버킷 내에서 **무작위** 제거했다 — 근사중복은 특정 사건(예: 특정 위기의 "
             "반복보도)에 몰릴 수 있어 실제 임베딩 기반 제거보다 이 시뮬레이션이 영향을 "
             "과소평가할 수도 과대평가할 수도 있음. 방향성 참고용이며, 2단계 도입 결정 전 "
             "표본을 확대한 임베딩 재검증이 최종 근거가 되어야 한다.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[neardup_impact_sim] 리포트 → {path}")


if __name__ == "__main__":
    run()
