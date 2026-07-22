# -*- coding: utf-8 -*-
"""conc×imp_mult 이중노출 잔차화(resid) vs 현행(mult) 비교 (#4, 2026-07-22, 조언자 자문 기반).

`geo/indexer.py._apply_kr_exposure(mode=...)`(신규, 기본 "mult"=기존과 완전 동일)로 광종별
imp_mult를 conc에 대해 잔차화한 변형(resid)을 실제 파이프라인으로 산출해 mult와 비교한다.
사전 고정 채택 기준(조언자 권고, 2026-07-22): CU·LI·REE(고상관 광종, conc_impmult_corr_v2.md
r=0.78/0.61/0.97) 중 하나라도 상위20주 Jaccard<0.8이면 resid 채택, 아니면 "검토 후
기각·재시도 금지"로 WORKLOG 기록(피드백기반_수정플랜 경보 계열2 hard결합 기각 전례와 동일
절차).

실행: GEO_EVENT_SOURCE=db GEO_PUBLISH_DB=../warehouse/minerals.duckdb python3 -m scripts.kr_exposure_ablation
산출: outputs/model_opt/kr_exposure_ablation.md
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
HIGH_CORR = {"CU", "LI", "REE"}
JACCARD_ADOPT_THRESHOLD = 0.8


def run():
    base = indexer.compute(kr_exposure_mode="mult")
    alt = indexer.compute(kr_exposure_mode="resid")
    wk_b = base[base["freq"] == "W"].copy(); wk_b["period"] = pd.to_datetime(wk_b["period"])
    wk_a = alt[alt["freq"] == "W"].copy(); wk_a["period"] = pd.to_datetime(wk_a["period"])

    rows = []
    for cc in sorted(wk_b["commodity"].unique()):
        b = wk_b[wk_b["commodity"] == cc].set_index("period")["index"]
        a = wk_a[wk_a["commodity"] == cc].set_index("period")["index"]
        common = b.index.intersection(a.index)
        corr = float(b.loc[common].corr(a.loc[common])) if len(common) > 1 else float("nan")
        top_b = set(b.sort_values(ascending=False).head(TOP_N).index)
        top_a = set(a.sort_values(ascending=False).head(TOP_N).index)
        jac = len(top_b & top_a) / len(top_b | top_a) if (top_b | top_a) else float("nan")
        rows.append(dict(commodity=cc, n_week=len(common), corr=round(corr, 4),
                          top20_jaccard=round(jac, 3), high_corr_group=cc in HIGH_CORR))
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))

    triggered = res[res["high_corr_group"] & (res["top20_jaccard"] < JACCARD_ADOPT_THRESHOLD)]
    verdict = "채택(resid)" if len(triggered) else "기각(mult 유지) — 재시도 금지"
    print(f"\n판정: {verdict}")
    write_report(res, verdict, triggered)


def write_report(res: pd.DataFrame, verdict: str, triggered: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "kr_exposure_ablation.md")
    L = []
    L.append("# conc×imp_mult 이중노출 잔차화(resid) vs 현행(mult) 비교 (#4, 2026-07-22)\n")
    L.append("작성: 2026-07-22 · 조언자 자문(설계 검토 에이전트) 권고에 따라 사전 고정 채택 "
              f"기준(고상관군 CU·LI·REE 중 하나라도 상위20주 Jaccard<{JACCARD_ADOPT_THRESHOLD}) "
              "으로 판정.\n")
    L.append("\n## 광종별 mult 대비 순위·값 안정성\n")
    L.append("| 광종 | 공통주간수 | 상관계수 | 상위20주 Jaccard | 고상관군(conc×imp_mult) |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['commodity']} | {int(r['n_week'])} | {r['corr']:.4f} | "
                  f"{r['top20_jaccard']:.3f} | {'예' if r['high_corr_group'] else '아니오'} |")
    L.append(f"\n**판정: {verdict}**\n")
    if len(triggered):
        L.append(f"채택 기준을 충족한 광종: {', '.join(triggered['commodity'])}. "
                  "`geo/indexer.py.compute()`의 `kr_exposure_mode` 기본값을 'resid'로 전환 검토.\n")
    else:
        L.append("고상관군(CU·LI·REE) 모두 상위20주 Jaccard가 임계치 이상 — resid로 바꿔도 "
                  "실제 지수 순위에 미치는 영향이 미미해 도입 실익이 없다고 판정. "
                  "`kr_exposure_mode='mult'`(현행) 유지, 이 판단은 재검토하지 않는다(피드백기반_"
                  "수정플랜 경보 계열2 hard결합 기각과 동일한 절차 — 이유는 이 문서에 고정 기록됨: "
                  "conc·imp_mult 상관은 이중계상이 아니라 '중국이 생산·수입 양쪽의 공통원인'인 "
                  "정당한 공행성이며, mean-one 정규화가 이미 레벨 인플레를 차단).\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[write] {path}")


if __name__ == "__main__":
    run()
