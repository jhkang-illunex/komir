# -*- coding: utf-8 -*-
"""NB2 확률화 레이어 피처 제거 민감도 (피드백기반_수정플랜 2026-07-16 C-2).

diagnosis_opt.py의 "피처 제거 민감도(dQWK)"와 동일한 방법론을 prob_model.py의
λ = exp(β0 + β1·x_ewma + β2·x_geo + β3·x_vol) 회귀에 적용한다 — 각 피처(x_ewma/x_geo/x_vol)를
하나씩 빼고 재적합했을 때 test 구간(2024+) burst 예측 Brier가 얼마나 나빠지는지(dBrier>0 =
제거 시 성능 하락 = 기여 피처) 측정해, b1(EWMA, 관성)이 지배적인지(=사실상 관성모델인지)를
직접 확인한다.

실행: python -m geo.prob_decompose (GEO_DATA env 필요, prob_model.py와 동일 입력)
산출: outputs 표는 stdout + geo/outputs/prob_decompose.md
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import statsmodels.api as sm

from . import config as C
from .prob_model import _weekly_panel, _attach_geo_idx, _features, _p_ge, TRAIN_END

ALL_FEATS = ["x_ewma", "x_geo", "x_vol"]
FEAT_KO = {"x_ewma": "x_ewma(EWMA 심각이벤트수, 관성)", "x_geo": "x_geo(geo_idx, 지정학지수)",
           "x_vol": "x_vol(log1p 주간전체이벤트수, 보도량통제)"}


def _fit(train: pd.DataFrame, feats: list[str]):
    X = sm.add_constant(train[feats].astype(float))
    y = train["y_next"].astype(float)
    try:
        from statsmodels.discrete.count_model import NegativeBinomialP
        m = NegativeBinomialP(y, X, p=2).fit(disp=0, maxiter=200)
        if not np.isfinite(m.params).all():
            raise RuntimeError("non-finite")
        alpha = float(m.params.iloc[-1])
        if alpha <= 1e-6:
            raise RuntimeError("alpha~0")
        return m.params.iloc[:-1], alpha, "nb2"
    except Exception:
        pass
    try:
        pois = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        mu = np.clip(pois.fittedvalues.values, 1e-9, None)
        aux = ((y.values - mu) ** 2 - y.values) / mu
        alpha = float(np.sum(aux * mu) / np.sum(mu ** 2))
        if np.isfinite(alpha) and alpha > 1e-3:
            m = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
            return m.params, alpha, "nb2"
        return pois.params, 0.0, "poisson"
    except Exception:
        m = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        return m.params, 0.0, "poisson"


def _predict(params, alpha, family, df, feats):
    X = np.column_stack([np.ones(len(df))] + [df[f].astype(float).values for f in feats])
    lam = np.exp(np.clip(X @ np.asarray(params, dtype=float), -20, 10))
    return lam


def _brier_burst(train, test, feats):
    burst_k = max(2, int(np.ceil(train["y_next"].quantile(0.90))))
    params, alpha, family = _fit(train, feats)
    lam = _predict(params, alpha, family, test, feats)
    p = _p_ge(lam, alpha, family, burst_k)
    hit = (test["y_next"].values >= burst_k).astype(float)
    return float(np.mean((p - hit) ** 2)), burst_k, family, alpha


def run():
    panel = _attach_geo_idx(_weekly_panel())
    feat = _features(panel)

    rows = []
    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        if len(train) < 52 or len(test) < 10:
            print(f"  [prob_decompose] {c}: 표본 부족 — 스킵"); continue

        full_brier, burst_k, family, alpha = _brier_burst(train, test, ALL_FEATS)
        row = {"commodity": c, "burst_k": burst_k, "family": family,
               "alpha": round(alpha, 3), "brier_full": round(full_brier, 4)}
        for f in ALL_FEATS:
            remain = [x for x in ALL_FEATS if x != f]
            try:
                b, _, _, _ = _brier_burst(train, test, remain)
                row[f"dBrier_{f}"] = round(b - full_brier, 4)   # >0: 제거 시 악화=기여 피처
            except Exception as e:
                row[f"dBrier_{f}"] = float("nan")
        rows.append(row)

    tab = pd.DataFrame(rows)
    print(tab.to_string(index=False))

    # 광종 풀링 평균(공통 결론용)
    avg = {f"dBrier_{f}": tab[f"dBrier_{f}"].mean() for f in ALL_FEATS}
    print("\n=== 광종 평균 dBrier(제거 시 악화폭 = 기여도) ===")
    for f in ALL_FEATS:
        print(f"  {FEAT_KO[f]}: {avg[f'dBrier_{f}']:+.4f}")
    dominant = max(ALL_FEATS, key=lambda f: avg[f"dBrier_{f}"])
    print(f"\n최대 기여: {FEAT_KO[dominant]}")

    out_dir = C.STORE.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "prob_decompose.md"
    L = ["# NB2 확률화 레이어 피처 제거 민감도 (dBrier, C-2)\n",
         "dBrier>0 = 제거 시 test(2024+) burst Brier 악화 = 기여 피처. "
         "diagnosis_opt.py의 dQWK와 동일 방법론(피처 1개 제외 재적합 후 test 성능 비교).\n",
         "\n## 광종별\n",
         "| commodity | burst_k | family | alpha | brier_full | dBrier_x_ewma | dBrier_x_geo | dBrier_x_vol |",
         "|---|---|---|---|---|---|---|---|"]
    for _, r in tab.iterrows():
        L.append(f"| {r['commodity']} | {r['burst_k']} | {r['family']} | {r['alpha']} | "
                 f"{r['brier_full']} | {r['dBrier_x_ewma']:+.4f} | {r['dBrier_x_geo']:+.4f} | "
                 f"{r['dBrier_x_vol']:+.4f} |")
    L.append("\n## 광종 평균(공통 결론)\n")
    L.append("| 피처 | 평균 dBrier | 해석 |")
    L.append("|---|---|---|")
    for f in ALL_FEATS:
        L.append(f"| {FEAT_KO[f]} | {avg[f'dBrier_{f}']:+.4f} | "
                 f"{'기여(제거시 악화)' if avg[f'dBrier_{f}']>0 else '무기여/역효과(제거해도 악화 없음)'} |")
    L.append(f"\n**최대 기여 피처: {FEAT_KO[dominant]}**\n")
    with open(path, "w") as fp:
        fp.write("\n".join(L) + "\n")
    print(f"\n[prob_decompose] 리포트 → {path}")
    return tab


if __name__ == "__main__":
    run()
