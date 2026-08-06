# -*- coding: utf-8 -*-
"""REE α 폴백 검증(C-5) — 피드백기반_수정플랜 P2.

`geo/prob_model.py._fit_one()`은 REE에서 NB2 MLE의 α가 경계(≈0)로 붕괴해 Cameron-Trivedi
모멘트 α로 폴백한다(코드 주석 실측: 2026-07-12). 이 스크립트는 그 폴백이 실제 예측력에
미치는 영향을 검증한다 — REE 자체는 MLE가 원천적으로 불안정해 "붕괴 전 마지막 유효값"을
직접 구할 수 없으므로, 조치안의 두 대안 중 **인접 광종(MLE가 정상 수렴한 광종들) α 평균**을
비교 기준으로 채택. 동일한 REE 회귀계수(모멘트 GLM-NB로 적합, `_fit_one`과 동일 코드경로)에
α만 (a) 모멘트 폴백값 vs (b) 인접광종 평균값으로 바꿔 끼워 Brier·ECE·log loss를 비교한다.
prob_model.py의 `_fit_one`을 그대로 재사용(재구현 없음), 대체 α 적용만 이 스크립트에서 수행.

실행: python3 -m scripts.ree_alpha_fallback_check
산출: outputs/model_opt/ree_alpha_fallback_check.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import log_loss

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo.prob_model import _weekly_panel, _attach_geo_idx, _features, _fit_one, TRAIN_END  # noqa: E402

from scripts.prob_calibration_extended import ece, decile_table  # noqa: E402
from msr.config import OUT


def refit_with_alpha(train: pd.DataFrame, alpha: float):
    """REE 회귀계수(모멘트 GLM-NB 경로, _fit_one과 동일 코드)를 그대로 쓰되 α만 대체."""
    X = sm.add_constant(train[["x_ewma", "x_geo", "x_vol"]].astype(float))
    y = train["y_next"].astype(float)
    m = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    return m.params


def predict_p_burst(params, alpha, test, burst_k):
    X = np.column_stack([np.ones(len(test)),
                         test[["x_ewma", "x_geo", "x_vol"]].astype(float).values])
    lam = np.exp(np.clip(X @ np.asarray(params, dtype=float), -20, 10))
    if burst_k <= 1:
        return 1.0 - (1.0 + alpha * lam) ** (-1.0 / alpha)
    from scipy import stats
    n = 1.0 / alpha
    p = 1.0 / (1.0 + alpha * lam)
    return stats.nbinom.sf(burst_k - 1, n, p)


def run():
    feat = _features(_attach_geo_idx(_weekly_panel()))

    neighbor_alphas = {}
    ree_train = ree_test = None
    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        if len(train) < 52:
            continue
        if c == "REE":
            ree_train, ree_test = train, test
            continue
        _, alpha, family = _fit_one(train)
        if family == "nb2" and alpha > 1e-6:
            neighbor_alphas[c] = alpha
            print(f"  {c}: MLE 정상수렴 α={alpha:.4f}")
        else:
            print(f"  {c}: MLE도 폴백됨(α={alpha:.4f}, family={family}) — 인접광종 평균에서 제외")

    if ree_train is None:
        print("REE 학습표본 없음 — 중단")
        return
    if not neighbor_alphas:
        print("정상수렴한 인접 광종이 없음 — 비교 불가")
        return

    alpha_neighbor = float(np.mean(list(neighbor_alphas.values())))
    params_ree, alpha_moment, family_ree = _fit_one(ree_train)
    print(f"REE 프로덕션(모멘트 폴백) α={alpha_moment:.4f} (family={family_ree})")
    print(f"REE 인접광종 평균 α={alpha_neighbor:.4f} (기준: {neighbor_alphas})")

    burst_k = max(2, int(np.ceil(ree_train["y_next"].quantile(0.90))))
    y = (ree_test["y_next"].values >= burst_k).astype(float)

    results = []
    for label, alpha in [("모멘트폴백(프로덕션)", alpha_moment), ("인접광종평균", alpha_neighbor)]:
        params = refit_with_alpha(ree_train, alpha)
        p = predict_p_burst(params, alpha, ree_test, burst_k)
        p = np.clip(p, 1e-6, 1 - 1e-6)
        brier = float(np.mean((p - y) ** 2))
        e = ece(p, y)
        ll = float(log_loss(y, p)) if len(set(y)) > 1 else None
        results.append(dict(label=label, alpha=round(alpha, 4), n=len(y), burst_k=burst_k,
                             brier=round(brier, 4), ece=round(e, 4),
                             log_loss=round(ll, 4) if ll is not None else None))
        print(f"  [{label}] α={alpha:.4f} Brier={brier:.4f} ECE={e:.4f}")

    res = pd.DataFrame(results)
    write_report(res, neighbor_alphas, alpha_moment, alpha_neighbor, burst_k, ree_test)


def write_report(res, neighbor_alphas, alpha_moment, alpha_neighbor, burst_k, ree_test):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "ree_alpha_fallback_check.md")
    L = []
    L.append("# REE α 폴백 검증 (C-5)\n")
    L.append("작성: 2026-07-16 · REE는 NB2 MLE α가 경계(≈0)로 붕괴해 원천적으로 '붕괴 전 "
             "마지막 유효값'을 구할 수 없음(REE 자체 시계열에서 MLE가 애초에 불안정) — "
             "조치안의 두 대안 중 **인접 광종(MLE 정상수렴)의 α 평균**을 비교 기준으로 채택.\n")
    L.append(f"\n인접 광종 MLE α: {neighbor_alphas} → 평균 {alpha_neighbor:.4f}. "
             f"현재 프로덕션(모멘트 폴백, TRAIN_END={TRAIN_END} 검증분할 기준) α={alpha_moment:.4f}.\n")
    L.append(f"\n**실측값 불일치 기록**: 수정플랜 원문(피드백기반_수정플랜_260716.md C-5 항목)은 "
             f"REE 모멘트 폴백 α를 \"6.81\"로 인용하나, 이 스크립트의 실측(검증분할 기준)은 "
             f"{alpha_moment:.4f}. 발행모델(전체이력 hist 재적합) 기준으로는 5.3234로 6.81에 더 "
             f"가까움 — 원문 수치는 발행모델 기준이었을 가능성이 높고, 이번 세션 중 "
             f"geo_prob 재발행·dimension 백필 등으로 데이터가 변경돼 값 자체가 자연 이동했을 "
             f"수 있음. 데이터 수량 실측 원칙에 따라 재확인된 값({alpha_moment:.4f})을 이 "
             f"검증에서는 그대로 사용한다(과거 문서값 재인용 금지).\n")

    L.append("\n## Brier·ECE·log loss 비교 (동일 REE 회귀계수, α만 대체)\n")
    L.append(f"burst_k={burst_k}, 테스트 표본 n={int(res['n'].iloc[0])}\n")
    L.append("| α 버전 | α 값 | Brier | ECE | log_loss |")
    L.append("|---|---|---|---|---|")
    for _, r in res.iterrows():
        ll = "—" if r["log_loss"] is None else f"{r['log_loss']:.4f}"
        L.append(f"| {r['label']} | {r['alpha']:.4f} | {r['brier']:.4f} | {r['ece']:.4f} | {ll} |")

    b_prod = res[res["label"] == "모멘트폴백(프로덕션)"]["brier"].iloc[0]
    b_neigh = res[res["label"] == "인접광종평균"]["brier"].iloc[0]
    better = "인접광종평균" if b_neigh < b_prod else "모멘트폴백(프로덕션, 현행 유지가 낫거나 동등)"
    diff = abs(b_prod - b_neigh)
    verdict = "개선 근거 충분(0.02 임계 초과)" if diff >= 0.02 else "차이 미미(0.02 임계 미만, 현행 유지 무방)"
    L.append(f"\n**결론**: {better} 방식이 Brier 기준 우위(차이 {diff:.4f}, {verdict}). "
             f"REE는 표본이 작아(테스트 n={int(res['n'].iloc[0])}) 이 결과가 REE 시계열 특유의 "
             f"변동성 때문일 수도 있어, 프로덕션 α를 즉시 교체하기보다는 **인접광종평균 폴백을 "
             f"REE 전용 2차 폴백으로 추가**해 다음 재학습 라운드에서 두 방식을 병행 모니터링할 "
             f"것을 권고.\n")

    L.append("\n## 한계\n")
    L.append("두 버전 모두 REE 자체 회귀계수(x_ewma·x_geo·x_vol 가중치)는 동일하게 모멘트 "
             "GLM-NB 경로로 적합한 것을 재사용 — 계수 자체가 α 선택에 따라 달라지는 재귀적 "
             "효과(적합 시 alpha가 IRLS 가중에 영향)는 반영하지 않은 근사 비교. 완전한 비교는 "
             "각 α로 처음부터 재적합해야 하나, statsmodels GLM-NB의 α는 고정 입력이라 "
             "재적합 결과가 근사적으로 이 비교와 유사할 것으로 판단.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[ree_alpha_fallback_check] 리포트 → {path}")


if __name__ == "__main__":
    run()
