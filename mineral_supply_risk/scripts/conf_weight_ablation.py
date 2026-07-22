# -*- coding: utf-8 -*-
"""LLM confidence 반영(conf_weight) 영향 검증 (#7, 2026-07-22).

`geo/indexer.py.compute(conf_weight=True)`(신규, 기본 False=기존 프로덕션과 완전 동일)로
conf_mult=0.7+0.3*confidence를 곱셈에 반영했을 때 지수 순위가 얼마나 바뀌는지 확인.
GeoEvent.confidence는 LLM 자체보고 추출 확신도(실측 295,157건: 0.1~1.0, 평균0.70,
표준편차0.11 — 상수 아님, `select confidence,count(*) from geo_event group by 1`로 확인).

실행: MSR_DB=../warehouse/minerals.duckdb GEO_EVENT_SOURCE=db GEO_PUBLISH_DB=../warehouse/minerals.duckdb \
      python3 -m scripts.conf_weight_ablation
산출: outputs/model_opt/conf_weight_ablation.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))

from geo import indexer  # noqa: E402
from msr.config import OUT

TOP_N = 20


def run():
    base = indexer.compute(conf_weight=False)
    alt = indexer.compute(conf_weight=True)
    wk_b = base[base["freq"] == "W"].copy(); wk_b["period"] = pd.to_datetime(wk_b["period"])
    wk_a = alt[alt["freq"] == "W"].copy(); wk_a["period"] = pd.to_datetime(wk_a["period"])

    rows = []
    for cc in sorted(wk_b["commodity"].unique()):
        b = wk_b[wk_b["commodity"] == cc].set_index("period")["index"]
        a = wk_a[wk_a["commodity"] == cc].set_index("period")["index"]
        common = b.index.intersection(a.index)
        corr = float(b.loc[common].corr(a.loc[common])) if len(common) > 1 else float("nan")
        mad = float((b.loc[common] - a.loc[common]).abs().mean())
        top_b = set(b.sort_values(ascending=False).head(TOP_N).index)
        top_a = set(a.sort_values(ascending=False).head(TOP_N).index)
        jac = len(top_b & top_a) / len(top_b | top_a) if (top_b | top_a) else float("nan")
        rows.append(dict(commodity=cc, n_week=len(common), corr=round(corr, 4),
                          mad=round(mad, 3), top20_jaccard=round(jac, 3)))
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    write_report(res)


def write_report(res: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "conf_weight_ablation.md")
    L = []
    L.append("# LLM confidence 반영(conf_weight) 영향 검증 (#7, 2026-07-22)\n")
    L.append("작성: 2026-07-22 · `geo/indexer.py.compute(conf_weight=True)`(conf_mult="
             "0.7+0.3·confidence)를 기존(conf_weight=False, conf_mult=1.0 고정) 대비 비교.\n")
    L.append("\n## 광종별 순위·값 안정성\n")
    L.append("| 광종 | 공통주간수 | 상관계수 | 평균절대차 | 상위20주 Jaccard |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['commodity']} | {int(r['n_week'])} | {r['corr']:.4f} | {r['mad']:.3f} | "
                 f"{r['top20_jaccard']:.3f} |")
    avg_corr = res["corr"].mean(); avg_jac = res["top20_jaccard"].mean()
    L.append(f"\n**결론**: 평균 상관계수 {avg_corr:.4f}, 평균 상위20주 Jaccard {avg_jac:.3f}. "
              "confidence가 낮은 이벤트를 최대 30%만 감쇠(0으로 죽이지 않음)하도록 설계해 "
              "순위가 크게 흔들리지 않으면서도 낮은 확신도 이벤트의 기여를 줄이는 것이 목적.\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[write] {path}")


if __name__ == "__main__":
    run()
