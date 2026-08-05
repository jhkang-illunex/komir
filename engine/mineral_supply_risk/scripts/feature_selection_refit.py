# -*- coding: utf-8 -*-
"""중요도 기반 피처 선정 재피팅 — "문제 수정 후 피처선정·중요도판별 재피팅" 검정
(2026-07-25, 사용자 질문 "문제된 부분을 수정해 피처 선정·중요도 판별 피팅을
다시 하면 결과가 어떻게 될까"에 대한 실측 답변).

지금까지의 피처 검정은 전부 '그룹 단위 가설검정'(사람이 그룹을 정해 추가/기각)
이었고, 데이터 주도의 자동 선택(임베디드 L1·순열중요도 top-k)은 미시도였다.
이번에 전피처(기존+T1+T2) 풀에서 자동 선택 → 재적합을 수행한다.

⚠ 선택 누수 방지: 피처 선택은 반드시 각 폴드의 학습기간 내부에서만 수행
(내부 시계열 분할: 학습 마지막 20%를 내부검증으로). 테스트 폴드 정보는 선택에
절대 사용하지 않는다. 예측모델은 첫 오리진(2024-03) 이전 데이터로만 1회 선택.

변형:
  진단 레벨: ①Lasso 선택→Ridge 재적합(relaxed lasso) ②HGB 순열중요도 top-11
             (챔피언 피처 수와 동일 예산) → Ridge/HGB 재적합
  진단 Δ  : ①L1-Logistic 선택→L2 재적합 ②Logistic 순열중요도 top-8 재적합
  예측     : HistGBM 순열중요도 top-11(BASE 수와 동일 예산) → 동일 프레임 WAPE

실행: MSR_DB=<warehouse> python -m scripts.feature_selection_refit
산출: outputs/model_opt/feature_selection_refit.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LassoCV, LogisticRegression, Ridge
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                                  # noqa: E402
from scripts.diagnosis_retrain_answer import (                              # noqa: E402
    build_panel, ALL_FEATS, GEO_ONLY_NO_LAG, FOLDS,
)
from scripts.diagnosis_ylag_deep_review import (                            # noqa: E402
    add_dynamics, evaluate, walkforward_collect, pooled_design,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F            # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                        # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                         # noqa: E402
    build_trd, build_pmi, PMI_F,
)
from scripts.diagnosis_tier1_eval import build_tier1                        # noqa: E402
from scripts.diagnosis_tier2_eval import build_tier2                        # noqa: E402
from scripts.diagnosis_alt_refit import EXT_F, level_frame                  # noqa: E402
import msr.models.forecast_unit as fu                                       # noqa: E402
from scripts.forecast_exog_eval import build_exog, seasonal_naive, ORIGINS  # noqa: E402
from scripts.forecast_tier2_exog_eval import build_exog2                    # noqa: E402
from scripts.forecast_alt_refit import EXOG_ALL, wape_eval_alt              # noqa: E402


# ─────────────────── 진단: 폴드 내부 선택 유틸 ───────────────────
def _inner_split(tr: pd.DataFrame):
    """학습기간 내부 시계열 분할 — 마지막 20% 주를 내부검증으로."""
    weeks = np.sort(tr["obs_date"].unique())
    cut = weeks[int(len(weeks) * 0.8)]
    return tr[tr["obs_date"] < cut], tr[tr["obs_date"] >= cut]


def select_lasso_level(tr: pd.DataFrame, pool: list[str]) -> list[str]:
    imp = SimpleImputer(strategy="median")
    sc = StandardScaler()
    X = sc.fit_transform(imp.fit_transform(tr[pool]))
    y = tr["grade_ord"].values.astype(float)
    m = LassoCV(cv=3, random_state=0, max_iter=20000).fit(X, y)
    sel = [f for f, c in zip(pool, m.coef_) if abs(c) > 1e-8]
    return sel if sel else pool[:5]


def select_permimp(tr: pd.DataFrame, pool: list[str], task: str,
                   k: int) -> list[str]:
    """내부검증 순열중요도 top-k. task='level'|'delta'."""
    itr, ival = _inner_split(tr)
    if task == "level":
        ytr, yval = itr["grade_ord"].values, ival["grade_ord"].values
        est = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                            Ridge(alpha=1.0))
        scoring = "neg_mean_absolute_error"
    else:
        ytr = np.clip(itr["grade_ord"].values
                      - itr["grade_lag1"].round().values, -1, 1).astype(int)
        yval = np.clip(ival["grade_ord"].values
                       - ival["grade_lag1"].round().values, -1, 1).astype(int)
        est = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                            LogisticRegression(max_iter=3000,
                                               class_weight="balanced"))
        scoring = "balanced_accuracy"
    est.fit(itr[pool], ytr)
    if task == "delta" and len(np.unique(yval)) < 2:
        return pool[:k]
    r = permutation_importance(est, ival[pool], yval, n_repeats=10,
                               random_state=0, scoring=scoring)
    order = np.argsort(-r.importances_mean)
    return [pool[i] for i in order[:k]]


def level_selected(df: pd.DataFrame, pool: list[str], selector: str,
                   refit: str) -> tuple[dict, dict]:
    """레벨 프레임 — 폴드마다 선택→재적합. 선택된 피처 기록도 반환."""
    ys, lags, preds, chosen = [], [], [], {}
    for t0, t1 in FOLDS:
        tr = df[df["obs_date"] < t0].copy()
        te = df[(df["obs_date"] >= t0) & (df["obs_date"] < t1)].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        sel = (select_lasso_level(tr, pool) if selector == "lasso"
               else select_permimp(tr, pool, "level", 11))
        chosen[t0] = sel
        from scripts.diagnosis_retrain_answer import _fit_predict_reg
        p = _fit_predict_reg(refit, tr, te, sel, per_commodity=False)
        ys.append(te["grade_ord"].astype(int).values)
        lags.append(te["grade_lag1"].round().clip(0, 2).astype(int).values)
        preds.append(np.asarray(p))
    y = np.concatenate(ys); lag = np.concatenate(lags)
    pr = np.clip(np.rint(np.concatenate(preds)), 0, 2).astype(int)
    return evaluate(y, lag, pr, None), chosen


def delta_selected(df: pd.DataFrame, pool: list[str], selector: str):
    chosen = {}

    def fit_predict(tr, te):
        if selector == "l1":
            itr = tr
            imp = SimpleImputer(strategy="median"); sc = StandardScaler()
            X = sc.fit_transform(imp.fit_transform(itr[pool]))
            d = np.clip(itr["grade_ord"].values
                        - itr["grade_lag1"].round().values, -1, 1).astype(int)
            l1 = LogisticRegression(penalty="l1", solver="saga", C=0.5,
                                    max_iter=5000, class_weight="balanced")
            l1.fit(X, d)
            mask = (np.abs(l1.coef_).max(axis=0) > 1e-8)
            sel = [f for f, m_ in zip(pool, mask) if m_] or pool[:5]
        else:
            sel = select_permimp(tr, pool, "delta", 8)
        chosen[str(tr["obs_date"].max().date())] = sel
        dtr = np.clip(tr["grade_ord"].values
                      - tr["grade_lag1"].round().values, -1, 1).astype(int)
        Xtr, Xte = pooled_design(tr, te, sel)
        m = LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0)
        m.fit(Xtr, dtr)
        dhat = m.predict(Xte).astype(int)
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        return np.clip(lag + dhat, 0, 2), dhat != 0
    return walkforward_collect(df, fit_predict), chosen


# ─────────────────── 예측: 오리진1 이전 데이터로 1회 선택 ───────────────────
def select_forecast_feats(df: pd.DataFrame, target: str, pool: list[str],
                          k: int) -> list[str]:
    base = pd.Timestamp(ORIGINS[0])
    hist = df[df["month"] <= base].copy()
    feat = fu._features(hist, target)
    d = fu._direct_matrix(feat, 6)                       # 중간 지평 h=6 대표
    d2 = pd.get_dummies(d, columns=["commodity_code"], prefix="cc")
    cc_cols = sorted(c for c in d2.columns if c.startswith("cc_"))
    tr = d2.dropna(subset=["lag1", "y_h"]).sort_values("month")
    cut = tr["month"].quantile(0.8)
    itr, ival = tr[tr["month"] < cut], tr[tr["month"] >= cut]
    cols = pool + cc_cols
    med = itr[cols].median(numeric_only=True)
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.07,
                                      max_iter=300, random_state=0)
    m.fit(itr[cols].fillna(med), itr["y_h"].values)
    r = permutation_importance(m, ival[cols].fillna(med), ival["y_h"].values,
                               n_repeats=10, random_state=0,
                               scoring="neg_mean_absolute_error")
    imp = {c: v for c, v in zip(cols, r.importances_mean)
           if not c.startswith("cc_")}
    return [c for c, _ in sorted(imp.items(), key=lambda x: -x[1])[:k]]


def main():
    db = os.environ["MSR_DB"]
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    print(f"⚠ 평가 패널 종점(발주처 컷): {df['obs_date'].max().date()}")
    df = add_dynamics(df); df = build_aux(db, df); df = exch.build_cninv(db, df)
    df = build_trd(db, df); df = build_pmi(db, df)
    df = build_tier1(db, df); df = build_tier2(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    ext = [f for f in EXT_F if df[f].notna().sum() > 50]
    FULL = ALL_FEATS + ext
    FULL_NOLAG = nolag + ext
    ADOPTED = nolag + INV_F + exch.CNINV_F + PMI_F

    rows, sel_log = [], []
    # 챔피언 기준선
    r, _ = level_frame(df, ALL_FEATS, "Ridge")
    rows.append(dict(프레임="레벨", 구성="Ridge+현행피처(챔피언)", **r))
    from scripts.diagnosis_ylag_deep_review import e2_delta_classifier
    r = e2_delta_classifier(df, ADOPTED, "Logistic")
    rows.append(dict(프레임="Δ분류", 구성="Logistic+채택동작점(챔피언)", **r))

    # 레벨: 자동 선택 변형
    for tag, selector, refit in [("Lasso선택→Ridge", "lasso", "Ridge"),
                                 ("PermImp11→Ridge", "permimp", "Ridge"),
                                 ("PermImp11→HistGBM", "permimp", "HistGBM")]:
        r, chosen = level_selected(df, FULL, selector, refit)
        rows.append(dict(프레임="레벨", 구성=tag, **r))
        last = list(chosen.values())[-1]
        sel_log.append(f"레벨 {tag} 최종폴드 선택({len(last)}개): {last}")
        print(f"레벨 {tag}: QWK {r['QWK']:.4f} chg {r['chg_acc']:.4f} "
              f"| 최종폴드 {len(last)}개 선택")
    # Δ: 자동 선택 변형
    for tag, selector in [("L1선택→Logistic", "l1"),
                          ("PermImp8→Logistic", "permimp")]:
        (r, chosen) = delta_selected(df, FULL_NOLAG, selector)
        rows.append(dict(프레임="Δ분류", 구성=tag, **r))
        last = list(chosen.values())[-1]
        sel_log.append(f"Δ {tag} 최종폴드 선택({len(last)}개): {last}")
        print(f"Δ {tag}: QWK {r['QWK']:.4f} chg {r['chg_acc']:.4f} "
              f"FAR {r['FAR']:.4f} | 최종폴드 {len(last)}개")
    tab = pd.DataFrame(rows)

    # 예측
    fdf = fu.build_panel(db); fdf = build_exog(db, fdf); fdf = build_exog2(db, fdf)
    base_feats = list(fu.FEATS)
    pool = base_feats + EXOG_ALL
    frows = [seasonal_naive(fdf).assign(variant="계절나이브"),
             wape_eval_alt(fdf, base_feats, "HistGBM").assign(variant="HistGBM+BASE(현행)")]
    for target_note in ["ton", "unit"]:
        sel = select_forecast_feats(fdf, target_note, pool, 11)
        sel_log.append(f"예측 {target_note} PermImp11 선택: {sel}")
    # 선택은 타깃별이지만 wape_eval_alt는 두 타깃 공통 피처를 쓰므로
    # ton 기준 선택(주 타깃)과 unit 기준 선택을 각각 변형으로 평가
    for target_note in ["ton", "unit"]:
        sel = select_forecast_feats(fdf, target_note, pool, 11)
        t = wape_eval_alt(fdf, sel, "HistGBM")
        t["variant"] = f"PermImp11({target_note}기준)→HistGBM"
        frows.append(t)
        tot = t[t["commodity"] == "전체"]
        print(f"예측 PermImp11({target_note}): " + " | ".join(
            f"{r_['target']} WAPE {r_['WAPE']:.3f}" for _, r_ in tot.iterrows()))
    fres = pd.concat(frows, ignore_index=True)
    write_report(df, tab, fres, sel_log)


def write_report(df, tab, fres, sel_log):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "feature_selection_refit.md")
    L = ["# 중요도 기반 피처 선정 재피팅 — 자동 선택(L1·순열중요도) vs 챔피언\n",
         f"작성: 2026-07-25 · 패널 종점 {df['obs_date'].max().date()} · 선택은 "
         "폴드 학습기간 내부에서만(내부 20% 시계열 검증, 선택 누수 차단). "
         "예측은 첫 오리진(2024-03) 이전 데이터로 1회 선택.\n",
         "\n## 진단\n",
         "| 프레임 | 구성 | QWK | acc | chg_acc | n_chg | FAR |",
         "|---|---|---|---|---|---|---|"]
    for _, r in tab.iterrows():
        far = "—" if pd.isna(r["FAR"]) else f"{r['FAR']:.4f}"
        L.append(f"| {r['프레임']} | {r['구성']} | {r['QWK']:.4f} | {r['acc']:.4f} "
                 f"| {r['chg_acc']:.4f} | {int(r['n_chg'])} | {far} |")
    L.append("\n## 예측(전체 풀링 WAPE)\n")
    L.append("| 변형 | ton WAPE | unit WAPE |")
    L.append("|---|---|---|")
    piv = fres[fres["commodity"] == "전체"].pivot_table(
        index="variant", columns="target", values="WAPE", sort=False)
    for v, r in piv.iterrows():
        L.append(f"| {v} | {r.get('ton', float('nan')):.4f} | "
                 f"{r.get('unit', float('nan')):.4f} |")
    L.append("\n## 선택된 피처(참고)\n")
    for s in sel_log:
        L.append(f"- {s}")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[feature_selection_refit] 리포트 → {path}")


if __name__ == "__main__":
    main()
