# -*- coding: utf-8 -*-
"""y_lag1 의존 문제 심층 검토 — 미착수 대안 6계열 일괄 백테스트 (2026-07-24, 사용자 지시).

선행 검토에서 이미 기각된 것(재시도 아님):
  - 게이트 결합 변형 A(이탈크기)·B(지속이탈)·C(분류확률) — diagnosis_gate_backtest.py, 기각
  - y_lag1 단순 제외·단순평균 앙상블 — diagnosis_ylag_dependence.py, 기각
  - 광역 지정학 트리거·dimension c2 — 별도 백테스트, 기각
이번에 검정하는 미착수 대안(선행 리포트들이 "남은 후보"로 명시한 것 + 표준 기법):
  E1. 비대칭 상향 게이트 — 상방(악화) 전환만 오버라이드(diagnosis_gate_backtest.md 후보 1)
  E2. Δ타깃 전환모델 — 등급 자체가 아니라 변화 방향(Δ∈{-1,0,+1})을 직접 분류(class 불균형
      보정 가중), 예측 = clip(grade_lag1 + Δ̂). 잔차모델의 분류판.
  E3. 서수(ordinal) 모델 — statsmodels OrderedModel(logit). 등급의 순서구조를 명시적으로
      반영하면 지정학 피처가 결정경계에 더 기여하는지 검정.
  E4. 전환가중 학습 — 기존 챔피언(Ridge 풀링)에 전환주 표본가중(w 스윕)만 추가.
  E5. 동역학 피처 확장 — geo_chg4(4주 변화)·geo_z26(26주 z)·p_burst_chg·dur(현 등급
      체류기간, 과거정보만) 추가. 챔피언 구성/전환모델 양쪽에 투입.
  E6. 잔차 회귀 — Ridge로 (grade - grade_lag1)를 직접 회귀(전환가중 포함), 예측 =
      grade_lag1 + round(잔차예측). y_lag1 계수를 1로 고정하는 것과 동치(직교화 취지).

평가: diagnosis_retrain_answer.py와 동일 워크포워드 3폴드 풀링 — QWK·acc·chg_acc(전환주
적중)·up_acc(상향전환 적중)·FAR(비전환주 오발동)·Miss(전환주 미발동).
채택 기준(게이트 백테스트와 동일): QWK ≥ 순수지속성 − 0.10 이면서 chg_acc > 0 중 최고.

표본 확대(2016 이전) 불가 확인: geo_prob(p_burst)가 2016-01-04부터만 존재(실측) — 지정학
피처를 유지하는 한 학습기간 연장은 구조적으로 막혀 있음.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_ylag_deep_review
산출: outputs/model_opt/diagnosis_ylag_deep_review.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.override_backtest import qwk                                # noqa: E402
from scripts.diagnosis_retrain_answer import (                           # noqa: E402
    build_panel, GEO_FEATS, GEO_ONLY_NO_LAG, FOLDS, _fit_predict_reg, _prep,
)

DYN_FEATS = ["geo_chg4", "geo_z26", "p_burst_chg", "dur"]
TAUS = [0.3, 0.5, 0.7, 1.0, 1.3, 1.5, 2.0]
WEIGHTS = [3.0, 5.0, 10.0, 20.0]


# ─────────────────────────── 피처 확장 ───────────────────────────
def add_dynamics(df: pd.DataFrame) -> pd.DataFrame:
    """동역학 피처 4종 추가 — 전부 과거 정보만 사용(누수 없음)."""
    df = df.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    g = df.groupby("commodity_code")
    df["geo_chg4"] = g["geopolitical_risk"].transform(lambda s: s - s.shift(4))
    df["geo_z26"] = g["geopolitical_risk"].transform(
        lambda s: (s - s.rolling(26, min_periods=8).mean())
        / s.rolling(26, min_periods=8).std().replace(0, np.nan))
    df["p_burst_chg"] = g["p_burst"].transform(lambda s: s - s.shift(1))
    # dur: 직전 주까지 같은 등급이 몇 주 연속됐는지(당해 주 등급은 미사용 — grade_ord를
    # 블록화한 뒤 shift(1)로 한 주 밀어 과거 정보만 남김)
    def _dur(s: pd.Series) -> pd.Series:
        block = (s != s.shift(1)).cumsum()
        run = s.groupby(block).cumcount() + 1
        return run.shift(1)
    df["dur"] = g["grade_ord"].transform(_dur)
    return df


# ─────────────────────────── 공통 유틸 ───────────────────────────
def pooled_design(tr: pd.DataFrame, te: pd.DataFrame, feats: list[str],
                  drop_first: bool = False):
    """풀링(광종 더미) 디자인 행렬 — train에만 fit(imputer/scaler), 누수 없음."""
    tr2 = pd.get_dummies(tr, columns=["commodity_code"], prefix="cc", drop_first=drop_first)
    te2 = pd.get_dummies(te, columns=["commodity_code"], prefix="cc", drop_first=drop_first)
    cc_cols = [c for c in tr2.columns if c.startswith("cc_")]
    for c in cc_cols:
        if c not in te2:
            te2[c] = 0
    feats2 = feats + cc_cols
    prep = _prep(feats2)
    Xtr = prep.fit_transform(tr2[feats2])
    Xte = prep.transform(te2[feats2])
    return Xtr, Xte


def evaluate(y: np.ndarray, lag: np.ndarray, pred: np.ndarray,
             trigger: np.ndarray | None = None) -> dict:
    chg = lag != y
    steady = ~chg
    up = y > lag
    out = dict(QWK=qwk(y, pred, K=3), acc=float((y == pred).mean()),
               chg_acc=float((pred[chg] == y[chg]).mean()) if chg.sum() else np.nan,
               up_acc=float((pred[up] == y[up]).mean()) if up.sum() else np.nan,
               n_chg=int(chg.sum()), n_up=int(up.sum()))
    if trigger is not None:
        out["FAR"] = float(trigger[steady].mean()) if steady.sum() else np.nan
        out["Miss"] = float((~trigger[chg]).mean()) if chg.sum() else np.nan
        out["n_trigger"] = int(trigger.sum())
    else:
        out["FAR"] = np.nan; out["Miss"] = np.nan; out["n_trigger"] = 0
    return out


def walkforward_collect(df: pd.DataFrame, fit_predict):
    """폴드 순회 공통 골격 — fit_predict(tr, te) → (pred, trigger|None)를 풀링해 평가."""
    ys, lags, preds, trigs = [], [], [], []
    for t0, t1 in FOLDS:
        tr = df[df["obs_date"] < t0].copy()
        te = df[(df["obs_date"] >= t0) & (df["obs_date"] < t1)].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        pred, trig = fit_predict(tr, te)
        ys.append(te["grade_ord"].astype(int).values)
        lags.append(te["grade_lag1"].round().clip(0, 2).astype(int).values)
        preds.append(np.asarray(pred))
        trigs.append(np.ones(len(te), dtype=bool) if trig is None else np.asarray(trig))
    y = np.concatenate(ys); lag = np.concatenate(lags)
    p = np.concatenate(preds); tg = np.concatenate(trigs)
    return evaluate(y, lag, p, tg)


# ─────────────────────────── E1: 비대칭 상향 게이트 ───────────────────────────
def collect_raw_geo(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """GEO_ONLY_NO_LAG HistGBM(풀링) 연속예측을 테스트폴드 전체에 부착(게이트 백테스트와 동일)."""
    df = df.reset_index(drop=True)
    raw_all = pd.Series(np.nan, index=df.index)
    for t0, t1 in FOLDS:
        tr = df[df["obs_date"] < t0].copy()
        te = df[(df["obs_date"] >= t0) & (df["obs_date"] < t1)].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        raw_all.loc[te.index] = _fit_predict_reg("HistGBM", tr, te, feats, per_commodity=False)
    out = df.copy()
    out["raw_geo"] = raw_all
    return out.dropna(subset=["raw_geo"]).reset_index(drop=True)


def e1_asymmetric_gate(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    y = d["grade_ord"].astype(int).values
    lagf = d["grade_lag1"].values
    lag = d["grade_lag1"].round().clip(0, 2).astype(int).values
    raw = d["raw_geo"].values
    for tau in TAUS:
        trigger = (raw - lagf) >= tau            # 상방(악화)만
        override = np.clip(np.round(raw), 0, 2).astype(int)
        pred = np.where(trigger, np.maximum(override, lag), lag)
        rows.append(dict(setting=f"tau={tau}", **evaluate(y, lag, pred, trigger)))
    return pd.DataFrame(rows)


# ─────────────────────────── E2: Δ타깃 전환모델 ───────────────────────────
def e2_delta_classifier(df: pd.DataFrame, feats: list[str], clf_name: str) -> dict:
    def fit_predict(tr, te):
        dtr = np.clip(tr["grade_ord"].values - tr["grade_lag1"].round().values, -1, 1).astype(int)
        Xtr, Xte = pooled_design(tr, te, feats)
        if clf_name == "Logistic":
            m = LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0)
            m.fit(Xtr, dtr)
        else:
            w = np.ones(len(dtr))
            for cls in np.unique(dtr):
                w[dtr == cls] = len(dtr) / (len(np.unique(dtr)) * (dtr == cls).sum())
            m = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08,
                                               max_iter=250, random_state=0)
            m.fit(Xtr, dtr, sample_weight=w)
        dhat = m.predict(Xte).astype(int)
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        pred = np.clip(lag + dhat, 0, 2)
        return pred, dhat != 0
    return walkforward_collect(df, fit_predict)


# ─────────────────────────── E3: 서수 모델 ───────────────────────────
def e3_ordinal(df: pd.DataFrame, feats: list[str]) -> dict:
    from statsmodels.miscmodels.ordinal_model import OrderedModel

    def fit_predict(tr, te):
        Xtr, Xte = pooled_design(tr, te, feats, drop_first=True)
        ytr = tr["grade_ord"].astype(int).values
        classes = np.sort(np.unique(ytr))
        remap = {c: i for i, c in enumerate(classes)}
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        if len(classes) < 2:
            return lag, None
        try:
            om = OrderedModel(np.array([remap[v] for v in ytr]), Xtr, distr="logit")
            res = om.fit(method="bfgs", maxiter=300, disp=0)
            probs = res.model.predict(res.params, exog=Xte)
            pred = classes[np.asarray(probs).argmax(axis=1)]
        except Exception:
            pred = lag
        return pred.astype(int), None
    return walkforward_collect(df, fit_predict)


# ─────────────────────────── E4: 전환가중 학습 ───────────────────────────
def e4_transition_weighted(df: pd.DataFrame, feats: list[str], w_chg: float,
                           model_name: str) -> dict:
    def fit_predict(tr, te):
        Xtr, Xte = pooled_design(tr, te, feats)
        ytr = tr["grade_ord"].values.astype(float)
        chg_tr = tr["grade_ord"].round().values != tr["grade_lag1"].round().values
        w = np.where(chg_tr, w_chg, 1.0)
        if model_name == "Ridge":
            m = Ridge(alpha=1.0)
        else:
            m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.08,
                                              max_iter=250, random_state=0)
        m.fit(Xtr, ytr, sample_weight=w)
        pred = np.clip(np.round(m.predict(Xte)), 0, 2).astype(int)
        return pred, None
    return walkforward_collect(df, fit_predict)


# ─────────────────────────── E6: 잔차 회귀 ───────────────────────────
def e6_residual_ridge(df: pd.DataFrame, feats: list[str], w_chg: float) -> dict:
    def fit_predict(tr, te):
        Xtr, Xte = pooled_design(tr, te, feats)
        rtr = (tr["grade_ord"].values - tr["grade_lag1"].round().values).astype(float)
        chg_tr = rtr != 0
        w = np.where(chg_tr, w_chg, 1.0)
        m = Ridge(alpha=1.0)
        m.fit(Xtr, rtr, sample_weight=w)
        rhat = np.round(m.predict(Xte)).astype(int)
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        pred = np.clip(lag + rhat, 0, 2)
        return pred, rhat != 0
    return walkforward_collect(df, fit_predict)


# ─────────────────────────── 메인 ───────────────────────────
def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    df = add_dynamics(df)
    geo_feats = [f for f in GEO_FEATS if df[f].notna().sum() > 50]
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    dyn = [f for f in DYN_FEATS if df[f].notna().sum() > 50]
    print(f"패널 {df.shape} · 동역학 피처: {dyn}")

    results = []   # (계열, 설정, 지표dict)

    # 기준선
    def fp_persist(tr, te):
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        return lag, np.zeros(len(te), dtype=bool)
    base = walkforward_collect(df, fp_persist)
    results.append(("기준선", "순수 지속성", base))

    def fp_champion(tr, te):
        raw = _fit_predict_reg("Ridge", tr, te, geo_feats, per_commodity=False)
        return np.clip(np.round(raw), 0, 2).astype(int), None
    results.append(("기준선", "현행 챔피언 Ridge(풀링)+GEO_FEATS", walkforward_collect(df, fp_champion)))

    # E1
    d_raw = collect_raw_geo(df, nolag)
    for _, r in e1_asymmetric_gate(d_raw).iterrows():
        results.append(("E1 비대칭상향게이트", r["setting"],
                        {k: r[k] for k in r.index if k != "setting"}))

    # E2 — 기본 피처 / 동역학 확장 두 구성
    for feats, tag in [(nolag, "기본"), (nolag + dyn, "기본+동역학")]:
        for clf in ["Logistic", "HistGBM"]:
            results.append((f"E2 Δ타깃({clf})", tag, e2_delta_classifier(df, feats, clf)))

    # E3 — lag 포함/제외
    results.append(("E3 서수(OrderedModel)", "GEO_FEATS(lag포함)", e3_ordinal(df, geo_feats)))
    results.append(("E3 서수(OrderedModel)", "GEO_NOLAG+동역학", e3_ordinal(df, nolag + dyn)))

    # E4 — 가중 스윕 × 모델 2종
    for w in WEIGHTS:
        for mn in ["Ridge", "HistGBM"]:
            results.append((f"E4 전환가중({mn})", f"w={w}",
                            e4_transition_weighted(df, geo_feats, w, mn)))

    # E5 — 챔피언에 동역학 피처만 추가(가중 없음)
    def fp_champ_dyn(tr, te):
        raw = _fit_predict_reg("Ridge", tr, te, geo_feats + dyn, per_commodity=False)
        return np.clip(np.round(raw), 0, 2).astype(int), None
    results.append(("E5 동역학피처확장", "Ridge(풀링)+GEO_FEATS+동역학",
                    walkforward_collect(df, fp_champ_dyn)))
    def fp_champ_dyn_gbm(tr, te):
        raw = _fit_predict_reg("HistGBM", tr, te, geo_feats + dyn, per_commodity=False)
        return np.clip(np.round(raw), 0, 2).astype(int), None
    results.append(("E5 동역학피처확장", "HistGBM(풀링)+GEO_FEATS+동역학",
                    walkforward_collect(df, fp_champ_dyn_gbm)))

    # E6 — 잔차 회귀(가중 스윕, 기본/동역학)
    for w in WEIGHTS:
        results.append(("E6 잔차회귀(Ridge)", f"기본, w={w}", e6_residual_ridge(df, nolag, w)))
        results.append(("E6 잔차회귀(Ridge)", f"기본+동역학, w={w}",
                        e6_residual_ridge(df, nolag + dyn, w)))

    tab = pd.DataFrame([dict(계열=a, 설정=b, **m) for a, b, m in results])
    print(tab.round(4).to_string(index=False))

    # 판정(게이트 백테스트와 동일 기준)
    qwk_floor = base["QWK"] - 0.10
    cand = tab[(tab["계열"] != "기준선") & (tab["QWK"] >= qwk_floor) & (tab["chg_acc"] > 0)]
    if len(cand):
        best = cand.sort_values(["chg_acc", "QWK"], ascending=[False, False]).iloc[0]
        verdict = "채택후보"
    else:
        best = tab[tab["계열"] != "기준선"].sort_values(
            ["chg_acc", "QWK"], ascending=[False, False]).iloc[0]
        verdict = "전부기각"
    print(f"\n판정: {verdict} — {best['계열']} / {best['설정']} "
          f"(QWK={best['QWK']:.4f}, chg_acc={best['chg_acc']:.4f}, floor={qwk_floor:.4f})")

    write_report(tab, base, qwk_floor, best, verdict)


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def write_report(tab: pd.DataFrame, base: dict, qwk_floor: float, best, verdict: str):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_ylag_deep_review.md")
    L = []
    L.append("# y_lag1 의존 문제 심층 검토 — 미착수 대안 6계열 일괄 백테스트\n")
    L.append("작성: 2026-07-24 · 워크포워드 3폴드(test 2023/2024/2025~) 풀링, "
             "diagnosis_retrain_answer.py와 동일 패널·동일 평가. 선행 기각(게이트 A/B/C·"
             "단순제외·단순앙상블·광역트리거·dimension c2)은 재시도하지 않음.\n")
    L.append(f"- 채택 기준: QWK ≥ 순수지속성({base['QWK']:.4f}) − 0.10 = {qwk_floor:.4f} "
             f"이면서 chg_acc > 0 인 조합 중 chg_acc 최고.\n")
    L.append("- **표본 확대 불가(실측)**: geo_prob(p_burst)가 2016-01-04부터만 존재 — "
             "지정학 피처를 유지하는 한 2016 이전으로 학습기간을 늘릴 수 없음. "
             "(fact_diagnosis_answer는 2015-12-14부터 있으나 병목은 geo 피처.)\n")
    L.append("\n## 전체 결과표\n")
    L.append("| 계열 | 설정 | QWK | acc | chg_acc | up_acc | n_chg | FAR | Miss |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['계열']} | {r['설정']} | {_fmt(r['QWK'])} | {_fmt(r['acc'])} | "
                 f"{_fmt(r['chg_acc'])} | {_fmt(r['up_acc'])} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'])} | {_fmt(r['Miss'])} |")
    L.append("\n## 판정\n")
    L.append(f"- **{verdict}** — 최상 조합: {best['계열']} / {best['설정']} "
             f"(QWK={_fmt(best['QWK'])}, chg_acc={_fmt(best['chg_acc'])}, "
             f"up_acc={_fmt(best['up_acc'])}, FAR={_fmt(best['FAR'])}).\n")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[deep_review] 리포트 → {path}")


if __name__ == "__main__":
    main()
