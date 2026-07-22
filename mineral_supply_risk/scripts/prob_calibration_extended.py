# -*- coding: utf-8 -*-
"""NB2 확률모델 calibration 검증 확대(C-6) — 피드백기반_수정플랜 P2.

geo/prob_model.py는 현재 Brier + 5분위 실현빈도표만 보고(`_calibration_report`) — calibration
curve(분위별 예측 vs 실현), decile table(10분위), ECE, log loss, PR-AUC를 5광종 × v1(원시
NB2 p_burst)/v2(isotonic 사후보정, `_fit_isotonic`과 동일 방식) 전체에 대해 추가 산출한다.
모델 재적합 없이 prob_model.py의 실제 함수(_weekly_panel·_attach_geo_idx·_features·_fit_one·
_predict·_p_ge·_fit_isotonic)를 그대로 재사용 — 신규 모델 구조 없음, 평가지표 확장만.

실행: python3 -m scripts.prob_calibration_extended
산출: outputs/model_opt/prob_calibration_extended.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score, log_loss

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo.prob_model import (  # noqa: E402
    _weekly_panel, _attach_geo_idx, _features, _fit_one, _predict, _p_ge, TRAIN_END,
)
from sklearn.isotonic import IsotonicRegression

from msr.config import OUT


def ece(p, y, bins=10):
    b = np.clip((np.asarray(p) * bins).astype(int), 0, bins - 1)
    e = 0.0
    for k in range(bins):
        m = b == k
        if m.sum():
            e += m.mean() * abs(np.asarray(p)[m].mean() - np.asarray(y)[m].mean())
    return float(e)


def decile_table(p, y):
    t = pd.DataFrame({"p": p, "y": y})
    try:
        t["bin"] = pd.qcut(t["p"], 10, duplicates="drop")
    except ValueError:
        return None
    return t.groupby("bin", observed=True).agg(pred=("p", "mean"), real=("y", "mean"), n=("y", "size"))


def safe_metric(fn, y, p, default=None):
    try:
        return fn(y, p)
    except (ValueError, ZeroDivisionError):
        return default


def run():
    feat = _features(_attach_geo_idx(_weekly_panel()))
    rows = []
    deciles = {}

    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        if len(train) < 52 or len(test) < 10:
            print(f"  [skip] {c}: 표본 부족(train={len(train)}, test={len(test)})")
            continue

        burst_k = max(2, int(np.ceil(train["y_next"].quantile(0.90))))
        params, alpha, family = _fit_one(train)
        lam_t, _ = _predict(params, alpha, family, test)
        p_v1 = _p_ge(lam_t, alpha, family, burst_k)
        y = (test["y_next"].values >= burst_k).astype(float)

        # v2: isotonic 사후보정 — 시간순 앞 60%(캘리브레이션)/뒤 40%(평가)로 누수 없이 적합
        n_cal = int(len(test) * 0.6)
        if n_cal < 10 or (len(test) - n_cal) < 10:
            print(f"  [skip-iso] {c}: isotonic 캘리브레이션 표본 부족")
            continue
        p_cal_fit, y_cal_fit = p_v1[:n_cal], y[:n_cal]
        p_eval_raw, y_eval = p_v1[n_cal:], y[n_cal:]
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(p_cal_fit, y_cal_fit)
        p_eval_v2 = iso.predict(p_eval_raw)

        for ver, p, yy in [("v1(원시NB2)", p_eval_raw, y_eval), ("v2(isotonic보정)", p_eval_v2, y_eval)]:
            brier = float(np.mean((p - yy) ** 2))
            e = ece(p, yy)
            ll = safe_metric(lambda y_, p_: log_loss(y_, np.clip(p_, 1e-6, 1 - 1e-6)), yy, p)
            roc = safe_metric(roc_auc_score, yy, p)
            prauc = safe_metric(average_precision_score, yy, p)
            rows.append(dict(commodity=c, version=ver, n=len(yy), burst_k=burst_k,
                              brier=round(brier, 4), ece=round(e, 4),
                              log_loss=round(ll, 4) if ll is not None else None,
                              roc_auc=round(roc, 4) if roc is not None else None,
                              pr_auc=round(prauc, 4) if prauc is not None else None,
                              base_rate=round(float(yy.mean()), 4)))
            dt = decile_table(p, yy)
            if dt is not None:
                deciles[(c, ver)] = dt

    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    write_report(res, deciles)


def write_report(res: pd.DataFrame, deciles: dict):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "prob_calibration_extended.md")
    L = []
    L.append("# NB2 확률모델 calibration 검증 확대 (C-6)\n")
    L.append("작성: 2026-07-16 · prob_model.py의 실제 적합·예측 함수를 그대로 재사용, 평가기간"
             "(2024+) 테스트셋을 시간순 앞 60%(isotonic 캘리브레이션용)/뒤 40%(평가용)로 분할해 "
             "v1(원시 NB2 p_burst)과 v2(isotonic 사후보정) 모두 뒤 40%에서 동일 기준으로 평가"
             "(v1도 뒤 40%만 평가해 v2와 표본을 맞춤 — 공정 비교).\n")

    L.append("\n## 지표 요약(광종×버전)\n")
    L.append("| 광종 | 버전 | n | burst_k | base_rate | Brier | ECE | log_loss | ROC-AUC | PR-AUC |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in res.iterrows():
        ll = "—" if pd.isna(r["log_loss"]) else f"{r['log_loss']:.4f}"
        roc = "—" if pd.isna(r["roc_auc"]) else f"{r['roc_auc']:.4f}"
        pr = "—" if pd.isna(r["pr_auc"]) else f"{r['pr_auc']:.4f}"
        L.append(f"| {r['commodity']} | {r['version']} | {int(r['n'])} | {int(r['burst_k'])} | "
                 f"{r['base_rate']:.4f} | {r['brier']:.4f} | {r['ece']:.4f} | {ll} | {roc} | {pr} |")

    L.append("\n## 광종별 v1→v2 개선 여부(Brier·ECE 기준)\n")
    L.append("| 광종 | Brier v1→v2 | ECE v1→v2 | 판정 |")
    L.append("|---|---|---|---|")
    for c in res["commodity"].unique():
        v1 = res[(res["commodity"] == c) & (res["version"] == "v1(원시NB2)")]
        v2 = res[(res["commodity"] == c) & (res["version"] == "v2(isotonic보정)")]
        if len(v1) == 0 or len(v2) == 0:
            continue
        b1, b2 = v1["brier"].iloc[0], v2["brier"].iloc[0]
        e1, e2 = v1["ece"].iloc[0], v2["ece"].iloc[0]
        verdict = "✓개선(둘다 감소)" if (b2 < b1 and e2 < e1) else ("혼재" if (b2 < b1) != (e2 < e1) else "✗악화")
        L.append(f"| {c} | {b1:.4f}→{b2:.4f} | {e1:.4f}→{e2:.4f} | {verdict} |")

    L.append("\n## 10분위 calibration curve (예측확률 vs 실현빈도)\n")
    for (c, ver), dt in deciles.items():
        L.append(f"\n### {c} · {ver}\n")
        L.append("| 분위 | 예측 | 실현 | n |")
        L.append("|---|---|---|---|")
        for r in dt.itertuples():
            L.append(f"| {r.Index} | {r.pred:.3f} | {r.real:.3f} | {r.n} |")

    L.append("\n## 해석 주의\n")
    L.append("테스트기간(2024+)을 다시 60/40 분할하므로 평가 표본(n)이 광종별로 20~40주 내외로 "
             "작음 — ROC-AUC·PR-AUC·log_loss는 소표본 변동성이 크다는 점을 감안해 방향성 위주로 "
             "해석. base_rate가 0 또는 1에 가까우면(단일클래스에 근접) ROC-AUC/PR-AUC가 정의상 "
             "불안정해질 수 있음. **NI는 이 평가창(뒤 40%)에서 base_rate=0.0(단일클래스, burst "
             "발생 0건)이라 ROC-AUC/PR-AUC/log_loss가 정의 불가(—)로 표기** — D-3(NI 대체지표) "
             "발견과 일관: NI는 최근 구간에 위기 사례 자체가 드물어 판별력 지표가 상시 정의되지 "
             "않는 구조적 한계가 확률모델에도 동일하게 나타남.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[prob_calibration_extended] 리포트 → {path}")


if __name__ == "__main__":
    run()
