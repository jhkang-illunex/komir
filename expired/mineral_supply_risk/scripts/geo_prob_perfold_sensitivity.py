# -*- coding: utf-8 -*-
"""p_burst(geo_prob 발행값) 피처 제거 민감도 — 폴드별 분해. 2026-08-14 사용자 지시.

배경: `outputs/model_opt/lookahead_bias_audit_260813.md` §2 — geo_prob(p_burst) 발행값은
`prob_model.py`가 전체 이력(2016~현재)에 파라미터를 한 번 적합한 뒤 과거 전체 주차에 역산해
쓰는 구조적 lookahead다. `diagnosis_opt.py`의 표준 피처제거민감도(`report.md`)는 "제거해도
QWK 불변(dQWK≈0)이라 현재 챔피언 성능엔 무해"라는 근거로 쓰였는데, 적대적 검증에서 이 수치가
**FOLDS[-1](2025~2027) 단일 폴드에서만** 측정된 것이라는 약점이 지적됐다 — lookahead 오염이
이론적으로 가장 클 것으로 예상되는 초기 폴드(2023년 테스트, 즉 2016~2022 학습분에 미래 2024~26
정보가 더 크게 섞여 들어갈 수 있는 구간)는 한 번도 확인된 적이 없었다.

이 스크립트는 diagnosis_opt.py와 동일한 워크포워드 3폴드(FOLDS) 각각에서 p_burst 제거
민감도(dQWK)를 따로 계산해, "폴드별로 다른가"를 직접 확인한다. 2026-08-14 기준 geo_prob는
이미 07-24(NB2 수렴버그 수정)·07-25(CO x_z13 반영) 이후 값으로 갱신돼 있음(DB 실측 확인,
max period 2026-08-03) — report.md도 같은 날 최신코드로 재생성 완료(전체 dQWK -0.003, 이전과
동일 결론 재확인). 순수 진단 — 코드/geo_prob 변경 없음.

실행: MSR_DB=<warehouse> python -m scripts.geo_prob_perfold_sensitivity
산출: outputs/model_opt/geo_prob_perfold_sensitivity.md
"""
from __future__ import annotations
import os, sys

import pandas as pd
from sklearn.metrics import cohen_kappa_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                          # noqa: E402
from msr.models.diagnosis_opt import (                                       # noqa: E402
    build_panel, BASE_FEATS, GEO_DERIVED, FOLDS, stage_labels,
    _fit_predict_reg, reg_to_stage,
)


def run(db=None, out_dir=None):
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)

    df = build_panel(db)
    feats_full = BASE_FEATS + GEO_DERIVED
    feats_full = [f for f in feats_full if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    if "p_burst" not in feats_full:
        raise RuntimeError(f"p_burst가 유효 피처 목록에 없음(결측/상수 필터에 걸림): {feats_full}")
    feats_no_pburst = [f for f in feats_full if f != "p_burst"]
    print(f"전체 피처: {feats_full}")
    print(f"p_burst 제외: {feats_no_pburst}")

    rows = []
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        yte_s = y_stage[te.index].values

        py_full, _ = _fit_predict_reg("Ridge", tr, te, feats_full, per_commodity=False)
        pred_full = reg_to_stage(py_full, te, tr)
        qwk_full = cohen_kappa_score(yte_s, pred_full, weights="quadratic")

        py_rm, _ = _fit_predict_reg("Ridge", tr, te, feats_no_pburst, per_commodity=False)
        pred_rm = reg_to_stage(py_rm, te, tr)
        qwk_rm = cohen_kappa_score(yte_s, pred_rm, weights="quadratic")

        rows.append(dict(fold=t0[:4], n_test=len(te),
                         QWK_full=round(qwk_full, 4), QWK_no_pburst=round(qwk_rm, 4),
                         dQWK=round(qwk_full - qwk_rm, 4)))

    res = pd.DataFrame(rows)
    print("\n=== 폴드별 p_burst 제거 민감도 ===")
    print(res.to_string(index=False))
    mean_dqwk = res["dQWK"].mean()
    max_dqwk = res["dQWK"].max()
    print(f"\n평균 dQWK={mean_dqwk:.4f} | 최대 dQWK={max_dqwk:.4f}")

    res.to_csv(f"{out_dir}/geo_prob_perfold_sensitivity.csv", index=False)
    with open(f"{out_dir}/geo_prob_perfold_sensitivity.md", "w") as fo:
        fo.write(
            "# p_burst 피처 제거 민감도 — 폴드별 분해\n\n"
            "적대적 검증 지적(마지막 폴드만 측정됨) 대응 — 3폴드 전부 개별 계산.\n\n"
            f"{res.to_markdown(index=False)}\n\n"
            f"평균 dQWK={mean_dqwk:.4f}, 최대 dQWK={max_dqwk:.4f}\n"
        )
    print(f"저장: {out_dir}/geo_prob_perfold_sensitivity.md")
    return res


if __name__ == "__main__":
    run()
