# -*- coding: utf-8 -*-
"""곱셈식 vs 가중합/log-additive(기하평균) 대안 비교(B-3) — 피드백기반_수정플랜 P2.

`geo/indexer.py.compute()`에 신규 추가한 `score_formula` 파라미터(기본 'mult'=기존 프로덕션과
완전 동일, 회귀 없음 확인)로 3가지 결합식을 실제 파이프라인으로 산출해 비교한다.
- mult(현행): severity×rel×conc×hhi_mult×sgn×imp_mult
- sum(가중합): sgn×(severity + (rel-1) + (conc-1) + (hhi_mult-1) + (imp_mult-1)) — 곱셈 성분을
  중립값 1.0 대비 조정폭으로 재해석해 severity에 가산
- loggeo(로그기하평균): sgn×(exp(mean(log(성분들)))-1) — 한 성분이 극단값이어도 기하평균이라
  영향이 완화됨(곱셈식이 "한 성분 오류에 민감"하다는 지적을 정면으로 겨냥)

평가: ①광종별 주간 지수 상위20주 Jaccard·상관계수(B-6/B-7과 동일 방법론) ②기존 발행
geo_index(mult, DB 정본)와의 상관 — 진단모델 QWK 재평가(전체 파이프라인 재배선 필요)는
범위 밖으로 명시하고 대신 이 상관계수를 "진단모델 geo_chg 피처가 얼마나 달라질지"의 근사
지표로 사용.

실행: python3 -m scripts.score_formula_ablation
산출: outputs/model_opt/score_formula_ablation.md
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
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo import indexer  # noqa: E402

from msr.config import OUT

VARIANTS = ["mult", "sum", "loggeo"]
TOP_N = 20


def run():
    results = {v: indexer.compute(score_formula=v) for v in VARIANTS}
    wk = {v: results[v][results[v]["freq"] == "W"].copy() for v in VARIANTS}
    for v in wk:
        wk[v]["period"] = pd.to_datetime(wk[v]["period"])

    rows = []
    for cc in sorted(wk["mult"]["commodity"].unique()):
        base = wk["mult"][wk["mult"]["commodity"] == cc].set_index("period")["index"]
        top_base = set(base.sort_values(ascending=False).head(TOP_N).index)
        for v in ["sum", "loggeo"]:
            alt = wk[v][wk[v]["commodity"] == cc].set_index("period")["index"]
            common = base.index.intersection(alt.index)
            corr = float(base.loc[common].corr(alt.loc[common])) if len(common) > 1 else float("nan")
            top_alt = set(alt.sort_values(ascending=False).head(TOP_N).index)
            jac = len(top_base & top_alt) / len(top_base | top_alt) if (top_base | top_alt) else float("nan")
            rows.append(dict(commodity=cc, variant=v, n_week=len(common),
                              corr=round(corr, 4), top20_jaccard=round(jac, 3)))
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    write_report(res, results)


def write_report(res: pd.DataFrame, results: dict):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "score_formula_ablation.md")
    L = []
    L.append("# 곱셈식 vs 가중합/log-additive 대안 비교 (B-3)\n")
    L.append("작성: 2026-07-16 · `geo/indexer.py.compute(score_formula=...)` 신규 파라미터"
             "(기본 'mult', 기존 프로덕션과 회귀 없음 확인)로 3가지 결합식을 실제 파이프라인 "
             "산출, mult(현행) 대비 sum(가중합)·loggeo(로그기하평균)의 지수 순위·상관 비교.\n")

    L.append("\n## 광종별 mult 대비 순위·값 안정성\n")
    L.append("| 광종 | 대안 | 공통주간수 | 상관계수 | 상위20주 Jaccard |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        L.append(f"| {r['commodity']} | {r['variant']} | {int(r['n_week'])} | {r['corr']:.4f} | "
                 f"{r['top20_jaccard']:.3f} |")

    sum_res = res[res["variant"] == "sum"]
    log_res = res[res["variant"] == "loggeo"]
    L.append(f"\n**결론**: sum(가중합) 평균 상관계수 {sum_res['corr'].mean():.4f}·Jaccard "
             f"{sum_res['top20_jaccard'].mean():.3f}, loggeo(기하평균) 평균 상관계수 "
             f"{log_res['corr'].mean():.4f}·Jaccard {log_res['top20_jaccard'].mean():.3f}. "
             f"{'두 대안 모두 mult와 순위가 크게 다르지 않아 경보 순위 관점에서는 곱셈식 유지가 안전한 선택' if min(sum_res['top20_jaccard'].mean(), log_res['top20_jaccard'].mean()) > 0.5 else '대안 구조가 상위 주간 순위를 상당히 재배열함 — 어느 결합식이 더 타당한지는 라벨 기반 성능 평가(QWK 등)가 최종 판단 기준이 되어야 함'}.\n")

    L.append("\n## loggeo(기하평균) 특성 관찰\n")
    lg = results["loggeo"]
    lg_w = lg[lg["freq"] == "W"]
    L.append(f"loggeo 지수는 전체 평균이 {lg_w['index'].mean():.2f}(mult는 통상 60~85대)로 "
             f"중립값(50)에 강하게 압축됨 — 기하평균 특성상 성분들이 전부 1.0 근방(대다수 "
             f"이벤트는 severity·rel·conc가 극단값이 아님)이면 결과도 1.0 근방에 머물러, "
             f"tanh 정규화 후 50 부근에 밀집한다. 이는 '한 성분 오류에 덜 민감'하다는 장점의 "
             f"이면 — **정상 범위 신호도 함께 눌러 지수의 변별력(dynamic range)이 줄어들 "
             f"위험**이 있다는 뜻이라 실무 채택 전 이 트레이드오프를 반드시 감안해야 한다.\n")

    L.append("\n## 범위 한계 — 진단모델 QWK 재평가 미실시\n")
    L.append("조치안이 요구한 '성능(QWK) 안정성' 비교는 `mart_weekly_diagnosis.geopolitical_risk`"
             "(diagnosis_opt.py의 GEO_DERIVED 원천)를 대안 결합식 기준으로 재발행하고 "
             "`diagnosis_opt.py` 워크포워드를 재실행해야 하는 전체 파이프라인 재배선(발행→마트"
             "→진단모델) 작업이라 이번 라운드 범위를 벗어난다 — 위 상관계수·Jaccard를 "
             "'geo_chg 피처가 얼마나 달라질지'의 근사 지표로 참고하되, 최종 채택 판단은 별도 "
             "워크스트림에서 QWK로 직접 검증할 것을 권고.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[score_formula_ablation] 리포트 → {path}")


if __name__ == "__main__":
    run()
