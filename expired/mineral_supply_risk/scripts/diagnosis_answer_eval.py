# -*- coding: utf-8 -*-
"""수급위기 진단모델 QWK 재평가 — KOMIS 가격이격률 등급(fact_diagnosis_answer)을
정답셋으로 사용 (2026-07-16, 사용자 지시).

기존 QWK(diagnosis_opt.py report.md의 0.925)는 **교사신호(수급동향지표) 기반 분위수 컷**을
정답으로 쓴다. 이번 재평가는 독립 정답셋(가격 이격률의 상방(+) σ이탈, 3단계)을 정답으로 써서
같은 로직(alert.py compute_alerts)의 예측력을 재확인한다.

방법: override_backtest.py의 load_inputs()/compute_alerts() 재사용(로직 무수정, 실제 운영값
그대로 — 마스킹 없음). 모델 예측(base_level 0~4, alert_level 0~4)을 정답셋과 동일한 3단계
스킴으로 하향매핑(0→0, 1→1, 2/3/4→2 — fact_diagnosis_answer의 grade_ord 정의와 동일하게
'주의+경계+심각'을 합침)한 뒤 QWK(K=3)를 계산한다. base_level(오버라이드 이전 순수 모델)과
alert_level(운영 배포값, 오버라이드+히스테리시스 포함)을 각각 평가해 오버라이드의 영향도 함께
확인한다.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_answer_eval
산출: outputs/model_opt/diagnosis_answer_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                    # noqa: E402
from msr.models.alert import compute_alerts                            # noqa: E402
from scripts.override_backtest import load_inputs, qwk, far_miss       # noqa: E402

# fact_diagnosis_answer.grade_ord와 동일한 3단계 하향매핑
TO_3TIER = {0: 0, 1: 1, 2: 2, 3: 2, 4: 2}


def load_answer(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    ans = con.execute("""SELECT commodity_code, obs_date, grade, grade_ord
        FROM fact_diagnosis_answer WHERE src='KOMIS_GRADE_MONITOR'""").df()
    con.close()
    ans["obs_date"] = pd.to_datetime(ans["obs_date"])
    return ans


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df, sev, _proxy = load_inputs(db)
    df = df.reset_index(drop=True)
    res = compute_alerts(df.copy(), sev)   # 실제 운영값(마스킹 없음) — 오버라이드 On(vol/hhi), geo off(기본)

    def align(r):
        return r.set_index(["commodity_code", "obs_date"]).reindex(
            pd.MultiIndex.from_frame(df[["commodity_code", "obs_date"]])).reset_index()
    res = align(res)
    res["base_3"] = res["base_level"].map(TO_3TIER)
    res["alert_3"] = res["alert_level"].map(TO_3TIER)

    ans = load_answer(db)
    m = res.merge(ans, on=["commodity_code", "obs_date"], how="inner")
    print(f"매칭 주수: {len(m)} / 모델패널 {len(res)} / 정답셋 {len(ans)}")

    # 나이브 기준선(프로젝트 관례 — 반드시 병기): (1) 항상 최빈클래스(정상=0),
    # (2) 지속성(직전 주 등급 유지, 광종별 시계열)
    m = m.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    m["persist"] = m.groupby("commodity_code")["grade_ord"].shift(1)
    m_p = m.dropna(subset=["persist"]).copy()
    m_p["persist"] = m_p["persist"].astype(int)

    rows = []
    for cc, g in m.groupby("commodity_code"):
        q_base = qwk(g["grade_ord"].values, g["base_3"].values, K=3)
        q_alert = qwk(g["grade_ord"].values, g["alert_3"].values, K=3)
        q_naive0 = qwk(g["grade_ord"].values, np.zeros(len(g), dtype=int), K=3)
        gp = m_p[m_p["commodity_code"] == cc]
        q_persist = qwk(gp["grade_ord"].values, gp["persist"].values, K=3) if len(gp) else float("nan")
        acc_base = float((g["grade_ord"] == g["base_3"]).mean())
        acc_alert = float((g["grade_ord"] == g["alert_3"]).mean())
        rows.append(dict(commodity=cc, n=len(g), QWK_base=q_base, QWK_alert=q_alert,
                          QWK_naive0=q_naive0, QWK_persist=q_persist,
                          acc_base=acc_base, acc_alert=acc_alert))
    tab = pd.DataFrame(rows)

    q_base_all = qwk(m["grade_ord"].values, m["base_3"].values, K=3)
    q_alert_all = qwk(m["grade_ord"].values, m["alert_3"].values, K=3)
    q_naive0_all = qwk(m["grade_ord"].values, np.zeros(len(m), dtype=int), K=3)
    q_persist_all = qwk(m_p["grade_ord"].values, m_p["persist"].values, K=3)
    acc_base_all = float((m["grade_ord"] == m["base_3"]).mean())
    acc_alert_all = float((m["grade_ord"] == m["alert_3"]).mean())

    # 참고: 기존 정의(교사기반) QWK도 같은 패널·같은 3단계 매핑으로 병기(있으면)
    from scripts.override_backtest import teacher_actual
    actual5 = teacher_actual(df)
    df5 = df.copy(); df5["actual5"] = actual5.values
    df5["actual3"] = df5["actual5"].map(TO_3TIER)
    df5 = df5.merge(res[["commodity_code", "obs_date", "base_3", "alert_3"]],
                     on=["commodity_code", "obs_date"], how="left")
    q_teacher_base = qwk(df5["actual3"].values, df5["base_3"].values, K=3)
    q_teacher_alert = qwk(df5["actual3"].values, df5["alert_3"].values, K=3)
    df5 = df5.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    df5["actual3_persist"] = df5.groupby("commodity_code")["actual3"].shift(1)
    df5_p = df5.dropna(subset=["actual3_persist"]).copy()
    df5_p["actual3_persist"] = df5_p["actual3_persist"].astype(int)
    q_teacher_persist = qwk(df5_p["actual3"].values, df5_p["actual3_persist"].values, K=3)

    print("\n=== 광종별(정답셋: KOMIS 가격등급) ===")
    print(tab.round(3).to_string(index=False))
    print(f"\n전체(풀링): QWK_base={q_base_all:.3f}, QWK_alert={q_alert_all:.3f}, "
          f"QWK_naive0={q_naive0_all:.3f}, QWK_persist={q_persist_all:.3f}, "
          f"acc_base={acc_base_all:.3f}, acc_alert={acc_alert_all:.3f}, n={len(m)}")
    print(f"\n참고 — 동일 3단계 매핑·동일 패널, 정답셋=교사기반(기존): "
          f"QWK_base={q_teacher_base:.3f}, QWK_alert={q_teacher_alert:.3f}, "
          f"QWK_persist={q_teacher_persist:.3f}")

    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_answer_eval.md")
    L = []
    L.append("# 수급위기 진단모델 QWK 재평가 — KOMIS 가격이격률 등급을 정답셋으로 사용\n")
    L.append("작성: 2026-07-16 · 방법: `alert.py compute_alerts()`(마스킹 없음, 실 운영값)의 "
             "base_level(순수 모델)·alert_level(운영값=오버라이드+히스테리시스 포함)을 "
             "`fact_diagnosis_answer.grade_ord`와 동일한 3단계(0정상/1관심/2주의경계심각)로 "
             "하향매핑 후 QWK(K=3) 계산.\n")
    L.append(f"- 매칭 주수: {len(m)} (모델패널 {len(res)}, 정답셋 {len(ans)})\n")
    L.append("\n## 광종별 (나이브 기준선 병기 — 프로젝트 관례)\n")
    L.append("| 광종 | n | QWK(base) | QWK(alert) | QWK(나이브, 항상 정상) | QWK(지속성) | acc(base) | acc(alert) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['commodity']} | {int(r['n'])} | {r['QWK_base']:.3f} | "
                 f"{r['QWK_alert']:.3f} | {r['QWK_naive0']:.3f} | {r['QWK_persist']:.3f} | "
                 f"{r['acc_base']:.3f} | {r['acc_alert']:.3f} |")
    L.append(f"\n## 전체(풀링)\n")
    L.append(f"- QWK(base, 오버라이드 전) = **{q_base_all:.3f}**")
    L.append(f"- QWK(alert, 운영 배포값) = **{q_alert_all:.3f}**")
    L.append(f"- QWK(나이브, 항상 '정상') = {q_naive0_all:.3f}")
    L.append(f"- QWK(지속성, 직전 주 등급 유지) = {q_persist_all:.3f}")
    L.append(f"- acc(base) = {acc_base_all:.3f}, acc(alert) = {acc_alert_all:.3f}, n={len(m)}")
    L.append(f"\n## 참고 — 정답셋 교체 효과 분리\n")
    L.append(f"동일 3단계 매핑·동일 패널에서 정답셋만 교체(기존 교사기반 vs 신규 KOMIS 가격등급):")
    L.append(f"- 교사기반(기존) 정답셋: QWK(base)={q_teacher_base:.3f}, QWK(alert)={q_teacher_alert:.3f}, "
             f"QWK(persist)={q_teacher_persist:.3f}")
    L.append(f"- KOMIS 가격등급(신규) 정답셋: QWK(base)={q_base_all:.3f}, QWK(alert)={q_alert_all:.3f}, "
             f"QWK(persist)={q_persist_all:.3f}")
    L.append(f"\n두 정답셋 모두 같은 모델 예측을 사용하므로, QWK 차이는 순수하게 "
             f"'정답셋 정의 차이'(교사=수급동향지표 다변량 vs KOMIS=가격 이격률 단변량·상방전용)"
             f"에서 온다.\n")
    L.append(f"\n## 핵심 발견 — 순개선(net gain)이 두 정답셋 모두에서 음(-)\n")
    L.append(f"| 정답셋 | QWK(모델 base) | QWK(지속성) | 순개선(base−persist) |")
    L.append(f"|---|---|---|---|")
    L.append(f"| KOMIS 가격등급(신규) | {q_base_all:.3f} | {q_persist_all:.3f} | "
             f"**{q_base_all-q_persist_all:+.3f}** |")
    L.append(f"| 교사기반(기존) | {q_teacher_base:.3f} | {q_teacher_persist:.3f} | "
             f"**{q_teacher_base-q_teacher_persist:+.3f}** |")
    L.append(f"\nKOMIS 가격등급 정답셋 기준으로는 지속성(직전 주 등급 유지) 기준선이 "
             f"QWK **{q_persist_all:.3f}**로 진단모델(base **{q_base_all:.3f}**)을 크게 "
             f"앞선다(순개선 {q_base_all-q_persist_all:+.3f}). **놀랍게도 기존 교사기반 "
             f"정답셋에서도 지속성이 QWK **{q_teacher_persist:.3f}**로 모델(**{q_teacher_base:.3f}**)"
             f"을 근소하게 앞선다**(순개선 {q_teacher_base-q_teacher_persist:+.3f}) — "
             f"즉 두 정답셋 모두에서 모델이 '아무것도 안 하는 것'보다 나은 순가치를 못 냈다. "
             f"차이는 정도(KOMIS는 크게 열세, 교사는 근소 열세)일 뿐 방향은 같다.\n")
    L.append(f"- **해석에 주의**: 이것이 '모델이 무의미하다'는 뜻은 아니다. 두 정답셋 모두 "
             f"느리게 변하는 상태량(σ밴드 이탈, 수급동향지표)이라 원래 자기상관이 극단적으로 "
             f"높아 지속성이 항상 강력한 기준선이 된다 — 이미 report.md의 피처 제거 민감도에서 "
             f"y_lag1(관성) dQWK=0.765로 압도적임이 확인된 것과 정확히 같은 현상이다. 또한 "
             f"진단모델의 crisis_index는 애초에 KOMIS 가격이격률 신호를 예측하도록 학습되지도 "
             f"않았다(교사=수급동향지표가 학습 타깃).\n")
    L.append(f"- 다만 이 결과는 **역으로 중요한 시사점**을 준다: 절대 QWK만 보고하면(예: "
             f"'QWK 0.925') 실제 부가가치를 과장할 위험이 크다 — 두 정답셋 모두에서 모델이 "
             f"지속성 대비 실질적으로 기여하지 못한다는 것이 이번에 직접 계산으로 확인됐다"
             f"(이전에는 y_lag1 dQWK 0.765라는 간접 증거만 있었음). 피드백기반_수정플랜 "
             f"D-1(y_lag1 의존도 완화)의 긴급도가 이 결과로 한 단계 높아졌다고 봐야 한다.\n")
    L.append(f"- **권고**: (1) 향후 모든 QWK 보고 시 QWK뿐 아니라 QWK−QWK_persist(순개선)를 "
             f"의무 병기 — 절대 QWK보다 이것이 정직한 모델 기여도. (2) KOMIS 가격등급을 "
             f"공식 정답셋으로 확정하려면 이 순개선 지표로 재판정. (3) 진단모델이 관성을 넘는 "
             f"조기경보력을 갖게 하려면 y_lag1 비중을 제한하는 구조변경(D-1) 실험이 필수 — "
             f"이번 결과가 그 근거를 보강한다. (4) 가격 이격률(σ배수) 자체를 신규 피처/보조"
             f"타깃으로 추가하는 실험도 병행 검토(현재 price_z52와 유사하나 정확한 σ밴드 계산"
             f" 방식은 다름 — 재현 필요).\n")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[diagnosis_answer_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
