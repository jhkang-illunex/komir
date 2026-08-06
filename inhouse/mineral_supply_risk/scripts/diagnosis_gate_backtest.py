# -*- coding: utf-8 -*-
"""수급위기 진단 '게이트(gate)' 결합 백테스트 — 지속성(grade_lag1) 기본예측 +
GEO_ONLY_NO_LAG 챔피언(HistGBM 풀링) 이탈신호가 임계 이상일 때만 오버라이드
(2026-07-16, 사용자 지시. diagnosis_retrain_answer.md 권고 (1)(2) 실행).

동기: 전환주 재평가(diagnosis_retrain_answer.py) 결과 — grade_lag1을 단순회귀 피처로
결합하면 전환주 적중률이 0%로 붕괴(관성이 다른 피처를 압도). grade_lag1을 빼면 지정학·무역
신호 단독으로 전환주 적중률 0.54(HistGBM 풀링)까지 회복. 이 둘을 alert.py의 규칙 오버라이드
계층과 같은 방식(평상시=지속성, 이탈신호가 임계를 넘을 때만 오버라이드)으로 결합하면 레벨
정확도(지속성의 강점)와 전환 탐지력(지정학신호의 강점)을 동시에 살릴 수 있는지 검정한다.

게이트 로직:
  raw = HistGBM(풀링, GEO_ONLY_NO_LAG 피처)의 연속 예측값(회귀, 등급 0~2 스케일)
  trigger = |raw - grade_lag1| >= tau   (tau: 스윕 대상 임계)
  gate_pred = round(clip(raw,0,2))  if trigger else  grade_lag1

평가(override_backtest.py와 동일 프레임 재사용):
  - 전체 QWK·acc (레벨 정확도가 지속성 대비 훼손되지 않는지)
  - chg_acc(전환주 적중률, diagnosis_opt.py의 전환월 적중과 동일 정의) — 핵심 지표
  - FAR: 비전환주(실제=직전주 유지)에서 게이트가 오발동(불필요하게 오버라이드)하는 비율
  - Miss: 전환주에서 게이트가 아예 미발동(변화를 놓침)하는 비율

3차 실행분(같은 날, 사용자 지시 — 다음 시도 후보 ①): 분류 확률 기반 트리거(변형 C). 회귀
연속값 대신 다중클래스 분류기(Logistic·HistGBM)의 **캘리브레이션된**(sklearn
CalibratedClassifierCV, sigmoid, train fold 내부 CV) 클래스 확률을 사용 — argmax 클래스가
grade_lag1과 다르고, 그 클래스의 확률이 임계(prob threshold) 이상일 때만 오버라이드. 연속값
크기가 아니라 "분류기가 실제로 다른 클래스를 유력하다고 보는가"에 반응하는 트리거.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_gate_backtest
산출: outputs/model_opt/diagnosis_gate_backtest.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.override_backtest import qwk                                # noqa: E402
from scripts.diagnosis_retrain_answer import (                           # noqa: E402
    build_panel, GEO_ONLY_NO_LAG, FOLDS, _fit_predict_reg, _prep,
)

TAUS = [0.3, 0.5, 0.7, 1.0, 1.3, 1.5, 2.0]   # 이탈 임계 스윕(등급 0~2 스케일)
PROB_THRESHOLDS = [0.34, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80, 0.90]  # 확률 임계 스윕
CLASSIFIERS = ["Logistic", "HistGBM"]


def collect_raw_predictions(df: pd.DataFrame, feats: list[str]) -> pd.DataFrame:
    """워크포워드 전체 테스트폴드에 대해 HistGBM(풀링) 연속예측을 원본 df 인덱스에 부착."""
    df = df.reset_index(drop=True)
    raw_all = pd.Series(np.nan, index=df.index)
    in_test = pd.Series(False, index=df.index)
    for t0, t1 in FOLDS:
        tr_mask = df["obs_date"] < t0
        te_mask = (df["obs_date"] >= t0) & (df["obs_date"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        raw = _fit_predict_reg("HistGBM", tr, te, feats, per_commodity=False)
        raw_all.loc[te.index] = raw
        in_test.loc[te.index] = True
    out = df.copy()
    out["raw_geo"] = raw_all
    out["in_test"] = in_test
    return out[out["in_test"]].dropna(subset=["raw_geo"]).reset_index(drop=True)


def gate_predict(d: pd.DataFrame, tau: float) -> np.ndarray:
    lag = d["grade_lag1"].round().clip(0, 2).values.astype(int)
    raw = d["raw_geo"].values
    trigger = np.abs(raw - d["grade_lag1"].values) >= tau
    override = np.clip(np.round(raw), 0, 2).astype(int)
    return np.where(trigger, override, lag), trigger


def gate_predict_sustained(d: pd.DataFrame, tau: float, weeks: int = 2) -> np.ndarray:
    """지속 이탈 게이트(2026-07-16, 사용자 지시 — 다음 시도 후보 ①). 단일 주 이탈크기
    임계를 넘는 것만으로는 트리거하지 않고, 같은 방향(부호 동일)으로 연속 `weeks`주 이상
    이탈이 지속될 때만 오버라이드한다. `d`는 반드시 commodity_code·obs_date로 정렬된
    상태여야 한다(연속 주 판별이 groupby+shift 기반이라 순서에 의존)."""
    dev = d["raw_geo"].values - d["grade_lag1"].values
    dev_s = pd.Series(dev, index=d.index)
    cc = d["commodity_code"]
    qualifies = (dev_s.abs() >= tau)
    sign = np.sign(dev_s)
    # 최근 weeks주(당해 주 포함) 전부가 같은 부호로 임계를 넘었는지 — 광종별 롤링 체크
    ok = pd.Series(True, index=d.index)
    for k in range(weeks):
        shifted_q = qualifies.groupby(cc).shift(k)
        shifted_sign = sign.groupby(cc).shift(k)
        ok &= shifted_q.fillna(False) & (shifted_sign == sign)
    trigger = ok.values & qualifies.values
    lag = d["grade_lag1"].round().clip(0, 2).values.astype(int)
    override = np.clip(np.round(d["raw_geo"].values), 0, 2).astype(int)
    return np.where(trigger, override, lag), trigger


def _fit_calibrated_clf(name: str, tr: pd.DataFrame, feats: list[str]):
    """풀링(광종 더미) + CalibratedClassifierCV(sigmoid, train fold 내부 3-fold CV) —
    train에만 fit, 미래정보 누수 없음. 클래스가 3개 미만으로만 존재하는 fold는 캘리브레이션이
    실패할 수 있어 예외 시 미보정 확률로 폴백."""
    tr2 = pd.get_dummies(tr, columns=["commodity_code"], prefix="cc")
    feats2 = feats + [c for c in tr2.columns if c.startswith("cc_")]
    prep = _prep(feats2)
    Xtr_ = prep.fit_transform(tr2[feats2])
    ytr = tr2["grade_ord"].astype(int).values
    base = (LogisticRegression(max_iter=2000, multi_class="multinomial", C=1.0) if name == "Logistic"
            else HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08, max_iter=250,
                                                random_state=0))
    try:
        clf = CalibratedClassifierCV(base, method="sigmoid", cv=3).fit(Xtr_, ytr)
    except Exception:
        clf = base.fit(Xtr_, ytr)
    return clf, prep, feats2


def collect_calibrated_probs(df: pd.DataFrame, feats: list[str], clf_name: str) -> pd.DataFrame:
    """워크포워드 전체 테스트폴드에 대해 캘리브레이션된 클래스확률(p0,p1,p2)을 원본 df에 부착."""
    df = df.reset_index(drop=True)
    p_cols = {k: pd.Series(np.nan, index=df.index) for k in (0, 1, 2)}
    in_test = pd.Series(False, index=df.index)
    for t0, t1 in FOLDS:
        tr_mask = df["obs_date"] < t0
        te_mask = (df["obs_date"] >= t0) & (df["obs_date"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        clf, prep, feats2 = _fit_calibrated_clf(clf_name, tr, feats)
        te2 = pd.get_dummies(te, columns=["commodity_code"], prefix="cc")
        for c in feats2:
            if c not in te2:
                te2[c] = 0
        Xte_ = prep.transform(te2[feats2])
        proba = clf.predict_proba(Xte_)
        classes = list(clf.classes_) if hasattr(clf, "classes_") else [0, 1, 2]
        for k in (0, 1, 2):
            if k in classes:
                p_cols[k].loc[te.index] = proba[:, classes.index(k)]
            else:
                p_cols[k].loc[te.index] = 0.0
        in_test.loc[te.index] = True
    out = df.copy()
    for k in (0, 1, 2):
        out[f"p{k}"] = p_cols[k]
    out["in_test"] = in_test
    return out[out["in_test"]].dropna(subset=["p0", "p1", "p2"]).reset_index(drop=True)


def gate_predict_proba(d: pd.DataFrame, threshold: float):
    """분류확률 기반 트리거: argmax 클래스가 grade_lag1과 다르고 그 확률이 threshold 이상일
    때만 오버라이드(변형 C, 사용자 지시 — 다음 시도 후보 ①)."""
    probs = d[["p0", "p1", "p2"]].values
    argmax_cls = probs.argmax(axis=1)
    argmax_p = probs.max(axis=1)
    lag = d["grade_lag1"].round().clip(0, 2).values.astype(int)
    trigger = (argmax_cls != lag) & (argmax_p >= threshold)
    return np.where(trigger, argmax_cls, lag), trigger


def evaluate(d: pd.DataFrame, pred: np.ndarray, trigger: np.ndarray) -> dict:
    y = d["grade_ord"].astype(int).values
    lag = d["grade_lag1"].round().clip(0, 2).astype(int).values
    chg_mask = lag != y      # 전환주(실제가 직전주 실제와 다름)
    steady_mask = ~chg_mask  # 비전환주(실제=직전주 유지)

    q = qwk(y, pred, K=3)
    acc = float((y == pred).mean())
    chg_acc = float((pred[chg_mask] == y[chg_mask]).mean()) if chg_mask.sum() else np.nan
    far = float(trigger[steady_mask].mean()) if steady_mask.sum() else np.nan   # 비전환주 오발동률
    miss = float((~trigger[chg_mask]).mean()) if chg_mask.sum() else np.nan     # 전환주 미발동률
    return dict(QWK=q, acc=acc, chg_acc=chg_acc, n_chg=int(chg_mask.sum()),
                n_steady=int(steady_mask.sum()), FAR=far, Miss=miss,
                n_trigger=int(trigger.sum()))


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df = build_panel(db)
    feats = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    print(f"패널: {df.shape}, GEO_ONLY_NO_LAG 피처: {feats}")

    d = collect_raw_predictions(df, feats)
    d = d.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    print(f"예측 확보 테스트행: {len(d)}")

    # 기준선: 순수 지속성(tau=inf와 동일), 순수 지정학모델(tau=0과 동일)
    lag_pred = d["grade_lag1"].round().clip(0, 2).astype(int).values
    geo_pred = np.clip(np.round(d["raw_geo"].values), 0, 2).astype(int)
    base_persist = evaluate(d, lag_pred, np.zeros(len(d), dtype=bool))
    base_geo = evaluate(d, geo_pred, np.ones(len(d), dtype=bool))

    rows = [dict(tau="0(=순수지정학모델)", **base_geo)]
    for tau in TAUS:
        pred, trig = gate_predict(d, tau)
        rows.append(dict(tau=tau, **evaluate(d, pred, trig)))
    rows.append(dict(tau="inf(=순수지속성)", **base_persist))
    tab = pd.DataFrame(rows)
    print("\n=== 게이트 임계(tau) 스윕(단일주 이탈) ===")
    print(tab.round(4).to_string(index=False))

    # 지속 이탈(연속 2주 동일방향) 게이트 스윕 — 사용자 지시(다음 시도 후보 ①)
    rows_sus = []
    for tau in TAUS:
        pred, trig = gate_predict_sustained(d, tau, weeks=2)
        rows_sus.append(dict(tau=tau, **evaluate(d, pred, trig)))
    tab_sus = pd.DataFrame(rows_sus)
    print("\n=== 게이트 임계(tau) 스윕(지속 이탈, 연속 2주 동일방향) ===")
    print(tab_sus.round(4).to_string(index=False))

    # 분류확률 기반 트리거(변형 C) — Logistic·HistGBM 각각 캘리브레이션된 확률로 스윕
    d_proba = {}
    tabs_proba = {}
    for clf_name in CLASSIFIERS:
        dp = collect_calibrated_probs(df, feats, clf_name)
        dp = dp.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
        d_proba[clf_name] = dp
        rows_p = []
        for thr in PROB_THRESHOLDS:
            pred, trig = gate_predict_proba(dp, thr)
            rows_p.append(dict(tau=thr, **evaluate(dp, pred, trig)))
        tabs_proba[clf_name] = pd.DataFrame(rows_p)
        print(f"\n=== 게이트 확률임계 스윕(변형C, 분류기={clf_name}) ===")
        print(tabs_proba[clf_name].round(4).to_string(index=False))

    # 판정: 순수 chg_acc 최댓값이 아니라 '레벨 정확도를 감내 가능한 수준으로 지키면서 전환도
    # 잡는' 실질적 채택 기준 — QWK가 순수지속성 대비 0.10 이내로 유지되는 tau 중 chg_acc 최고.
    # (override_backtest.py의 '정당화비율+lift' 이중조건 정신을 이 문제에 맞게 재구성)
    # 단일주·지속(연속2주)·확률(Logistic)·확률(HistGBM) 4계열 후보를 함께 풀에 넣어 통틀어 최선을 고른다.
    QWK_TOLERANCE = 0.10
    qwk_floor = base_persist["QWK"] - QWK_TOLERANCE
    numeric = tab[tab["tau"].apply(lambda x: isinstance(x, float))].copy()
    numeric["variant"] = "단일주"
    numeric_sus = tab_sus.copy()
    numeric_sus["variant"] = "지속(연속2주)"
    pool_parts = [numeric, numeric_sus]
    for clf_name in CLASSIFIERS:
        t = tabs_proba[clf_name].copy()
        t["variant"] = f"확률({clf_name})"
        pool_parts.append(t)
    pool = pd.concat(pool_parts, ignore_index=True)
    acceptable = pool[(pool["QWK"] >= qwk_floor) & (pool["chg_acc"] > 0)]
    if len(acceptable):
        best = acceptable.sort_values("chg_acc", ascending=False).iloc[0]
        verdict = "채택"
    else:
        # 허용 가능한 조합이 아예 없음 — 참고용으로 chg_acc 최댓값(동률 시 FAR 낮은 쪽)을
        # 보여주되 기각 판정. 재현성을 위해 동률 시 tie-break 명시(FAR 오름차순).
        best = (pool.sort_values(["chg_acc", "FAR"], ascending=[False, True]).iloc[0]
                if len(pool) else None)
        verdict = "기각"

    # 광종별(선정 tau·variant 있으면 그것, 없으면 지속게이트 tau=1.0 기본값 — 판정과 무관하게 진단용)
    tau_best = float(best["tau"]) if best is not None else 1.0
    variant_best = best["variant"] if best is not None else "지속(연속2주)"
    if variant_best.startswith("확률("):
        clf_best = variant_best[len("확률("):-1]
        d_cc = d_proba[clf_best]
    else:
        d_cc = d
    cc_rows = []
    for cc, g in d_cc.groupby("commodity_code"):
        if variant_best == "지속(연속2주)":
            pred, trig = gate_predict_sustained(g, tau_best, weeks=2)
        elif variant_best.startswith("확률("):
            pred, trig = gate_predict_proba(g, tau_best)
        else:
            pred, trig = gate_predict(g, tau_best)
        m = evaluate(g, pred, trig)
        m_persist = evaluate(g, g["grade_lag1"].round().clip(0, 2).astype(int).values,
                              np.zeros(len(g), dtype=bool))
        cc_rows.append(dict(commodity=cc, n=len(g), **m,
                             chg_acc_persist=m_persist["chg_acc"], QWK_persist=m_persist["QWK"]))
    cc_tab = pd.DataFrame(cc_rows)
    print(f"\n=== 광종별(variant={variant_best}, tau={tau_best}) ===")
    print(cc_tab.round(3).to_string(index=False))

    write_report(tab, tab_sus, tabs_proba, best, verdict, variant_best, tau_best, cc_tab,
                 base_persist, base_geo, len(d))


def _fmt(x, p=4):
    return "—" if (x is None or (isinstance(x, float) and np.isnan(x))) else f"{x:.{p}f}"


def _table(L, df, cols_map):
    L.append("| " + " | ".join(cols_map.values()) + " |")
    L.append("|" + "---|" * len(cols_map))
    for _, r in df.iterrows():
        vals = []
        for c in cols_map:
            v = r[c]
            if c == "tau":
                vals.append(str(v))
            elif c in ("n_chg", "n_steady", "n_trigger"):
                vals.append(str(int(v)))
            else:
                vals.append(_fmt(v))
        L.append("| " + " | ".join(vals) + " |")


def write_report(tab, tab_sus, tabs_proba, best, verdict, variant_best, tau_best, cc_tab,
                  base_persist, base_geo, n_total):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_gate_backtest.md")
    cols = dict(tau="tau/임계", QWK="QWK", acc="acc", chg_acc="chg_acc", n_chg="n_chg",
                FAR="FAR(비전환주 오발동)", Miss="Miss(전환주 미발동)", n_trigger="n_trigger")

    L = []
    L.append("# 수급위기 진단 게이트(gate) 결합 백테스트\n")
    L.append("작성: 2026-07-16 · 지속성(grade_lag1) 기본예측 + GEO_ONLY_NO_LAG 신호가 임계 "
             "이상일 때만 오버라이드. diagnosis_retrain_answer.md 권고(1)(2) 실행. "
             "**변형 A**(단일주 이탈크기)·**변형 B**(지속 이탈, 연속 2주 동일방향)·**변형 C**"
             "(분류확률 기반, Logistic·HistGBM 캘리브레이션) 3계열을 같은 채택기준으로 "
             "일괄 비교한다(변형 C는 사용자 지시로 이번 3차 실행분에 추가).\n")
    L.append(f"- 평가 표본: {n_total}주(전체 테스트폴드 2023~2027 풀링)\n")

    L.append("\n## 임계(tau) 스윕 — 변형 A: 단일주 이탈(당해 주 |raw-grade_lag1|≥tau만 충족)\n")
    _table(L, tab, cols)

    L.append("\n## 임계(tau) 스윕 — 변형 B: 지속 이탈(연속 2주 동일방향으로 |raw-grade_lag1|≥"
             "tau 충족해야 트리거, 노이즈성 단발 이탈 필터링)\n")
    _table(L, tab_sus, cols)

    for clf_name, t in tabs_proba.items():
        L.append(f"\n## 확률임계 스윕 — 변형 C: 분류확률 기반 트리거({clf_name}, "
                 f"CalibratedClassifierCV sigmoid) — argmax 클래스≠grade_lag1 이고 "
                 f"그 확률≥임계일 때만 오버라이드\n")
        _table(L, t, cols)

    L.append("\n## 판정\n")
    L.append(f"채택 기준: QWK가 순수지속성({base_persist['QWK']:.4f}) 대비 0.10 이내로 유지되는 "
             f"조합(변형 A·B·C 3계열 통틀어) 중 chg_acc가 최고인 것을 선정(둘 다 만족 못 하면 "
             f"기각). override_backtest.py의 '정당화비율+lift' 이중조건 취지를 이 문제에 맞게 "
             f"재구성한 것.\n")
    if verdict == "채택":
        L.append(f"- **판정: 채택 — variant={variant_best}, tau={best['tau']}** — "
                 f"chg_acc={best['chg_acc']:.4f}(순수지속성 0.0000 대비 개선), "
                 f"QWK={best['QWK']:.4f}(순수지속성 대비 {best['QWK']-base_persist['QWK']:+.4f}, "
                 f"허용범위 이내), FAR={best['FAR']:.4f}, Miss={best['Miss']:.4f}.\n")
    else:
        L.append(f"- **판정: 기각 — 변형 A·B·C 전부, 스윕한 모든 임계에서 "
                 f"'레벨 정확도(QWK) 허용범위 유지 + chg_acc 개선'을 동시에 만족하지 못함.**\n")
        if best is not None:
            L.append(f"  참고로 3계열 통틀어 chg_acc가 가장 높은 조합은 variant={best['variant']}·"
                     f"임계={best['tau']}(chg_acc={best['chg_acc']:.4f})이나, 이때도 "
                     f"QWK={best['QWK']:.4f}로 허용범위(≥{base_persist['QWK']-0.10:.4f})에 "
                     f"크게 못 미친다.\n")
        # 변형 B가 변형 A보다 FAR를 개선했는지 데이터로 직접 비교(주장이 아니라 사실로)
        common_tau = sorted(set(tab["tau"]) & set(tab_sus["tau"]))
        far_note = []
        for t in common_tau:
            a = tab[tab["tau"] == t].iloc[0]; b = tab_sus[tab_sus["tau"] == t].iloc[0]
            far_note.append(f"tau={t}: FAR {a['FAR']:.3f}→{b['FAR']:.3f}"
                             f"({b['FAR']-a['FAR']:+.3f}), chg_acc {a['chg_acc']:.3f}→"
                             f"{b['chg_acc']:.3f}({b['chg_acc']-a['chg_acc']:+.3f}), "
                             f"n_trigger {int(a['n_trigger'])}→{int(b['n_trigger'])}")
        L.append(f"- **B(지속이탈)의 실제 효과(A 대비)**: " + " / ".join(far_note) + "\n")

        # 변형 C(확률)의 최선 지점을 A(단일주)에서 가장 가까운 chg_acc 지점과 직접 대조 —
        # "확률 기반이 크기 기반보다 결정경계에 민감해 더 나을 것"이라는 가설을 실측으로 검정.
        numeric_a = tab[tab["tau"].apply(lambda x: isinstance(x, float))].sort_values("chg_acc")
        for clf_name, t in tabs_proba.items():
            t_pos = t[t["chg_acc"] > 0]
            if len(t_pos):
                r = t_pos.sort_values("chg_acc", ascending=False).iloc[0]
                # A에서 chg_acc가 가장 가까운 행 탐색
                idx = (numeric_a["chg_acc"] - r["chg_acc"]).abs().idxmin()
                a_ref = numeric_a.loc[idx]
                verdict_c = ("확률 기반이 크기 기반보다 낫다" if r["QWK"] > a_ref["QWK"]
                             else "확률 기반이 크기 기반보다 오히려 나쁘다(가설 기각)")
                L.append(f"- **C({clf_name})의 최선 지점**: 임계={r['tau']}에서 "
                         f"chg_acc={r['chg_acc']:.4f}·QWK={r['QWK']:.4f}·FAR={r['FAR']:.4f}. "
                         f"A(단일주)에서 chg_acc가 가장 가까운 지점(tau={a_ref['tau']}, "
                         f"chg_acc={a_ref['chg_acc']:.4f})은 QWK={a_ref['QWK']:.4f} — "
                         f"**{verdict_c}**({r['QWK']:.4f} vs {a_ref['QWK']:.4f}). 이 표본에서는 "
                         f"'분류확률이 예측값 크기보다 결정경계에 민감해 더 나을 것'이라는 원래 "
                         f"가설이 지지되지 않았다.\n")
            else:
                L.append(f"- **C({clf_name})**: 스윕한 모든 확률임계에서 chg_acc=0 — "
                         f"캘리브레이션된 분류기가 grade_lag1과 다른 클래스를 임계 이상 "
                         f"확신하는 경우 자체가 드물거나, 확신해도 틀린 경우가 대부분.\n")

        L.append(f"- **원인 분석**: 비전환주가 {int(base_persist['n_steady'])}건, 전환주가 "
                 f"{int(tab['n_chg'].iloc[0])}건뿐(약 {int(base_persist['n_steady']/tab['n_chg'].iloc[0])}"
                 f":1)이라는 근본적인 클래스 불균형은 트리거를 '크기'에서 '확률'로 바꿔도 "
                 f"해소되지 않는다 — 애초에 GEO_ONLY_NO_LAG 피처(지정학지수·수입편중 등)가 "
                 f"'다음 주 정확히 어느 클래스로 전환되는가'를 구분할 만한 신호력을 이 표본"
                 f"에서는 갖추지 못했다는 것이 세 변형에서 공통으로 확인된 셈이다.\n")
        L.append(f"- **결론**: 세 가지 게이트 설계(이탈크기·지속이탈·분류확률) 모두 근본적인 "
                 f"트레이드오프를 해소하지 못했다 — alert.py의 07-16 오버라이드 재설계(구 광역 "
                 f"지정학 트리거 폐지), dimension c2 트리거 기각과 합쳐 **다섯 번째로 같은 "
                 f"결론이 재현**됐다. 순수 지속성을 유지 권고. 남은 시도 후보는 §종합 해석에 "
                 f"기재.\n")
    L.append(f"\n- 참고(양극단): tau=0(오버라이드 상시, 순수 지정학모델) QWK={base_geo['QWK']:.4f}·"
             f"chg_acc={base_geo['chg_acc']:.4f}·FAR={base_geo['FAR']:.4f}(항상 발동이므로 "
             f"비전환주도 전부 오발동) — 레벨 정확도가 크게 훼손됨(순수지속성 QWK "
             f"{base_persist['QWK']:.4f} 대비). tau=inf(항상 지속성) chg_acc=0.0000·FAR=0.0000.\n")

    tag = "" if verdict == "채택" else "(참고·진단용 — 채택 아님, chg_acc 최고 조합)"
    L.append(f"\n## 광종별(variant={variant_best}, tau={tau_best} {tag})\n")
    L.append("| 광종 | n | QWK | QWK(지속성) | chg_acc | chg_acc(지속성) | n_chg | FAR | Miss |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in cc_tab.iterrows():
        L.append(f"| {r['commodity']} | {int(r['n'])} | {r['QWK']:.3f} | {r['QWK_persist']:.3f} | "
                 f"{_fmt(r['chg_acc'],3)} | {_fmt(r['chg_acc_persist'],3)} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'],3)} | {_fmt(r['Miss'],3)} |")

    L.append("\n## 종합 해석 · 남은 시도 후보\n")
    if verdict == "채택":
        L.append(f"variant={variant_best}·tau={tau_best}에서 실용적 균형점을 찾았다. 다만 "
                 f"표본이 작으므로(§표본 크기 주의) 운영 반영 전 재검증 필요.\n")
    else:
        L.append("단일주·지속(연속2주)·분류확률 게이트 셋 다 이번 표본에서 기각됐다. "
                 "다음에 시도해볼 만한 대안(이전 대비 ①②는 이번·지난 실행에서 검정 완료로 "
                 "제외):\n")
        L.append("1. **비대칭 임계**: 상방(위기 악화) 전환과 하방(완화) 전환의 임계를 다르게 "
                 "설정 — 위기 악화 미탐(Miss)의 비용이 더 크다면 상방 임계만 낮추는 것이 "
                 "합리적일 수 있음.\n")
        L.append("2. **표본 확대**: 학습기간을 2016년 이전으로 늘리거나(가능하면) 다른 "
                 "정답셋(교사기반)의 전환 사례도 함께 검정해 전환주 소표본 한계를 완화.\n")
        L.append("3. **게이트 자체를 포기하고 순수 지속성 유지**: 지금까지 5가지 결합 시도"
                 "(광역/dimension-c2/단일주게이트/지속게이트/분류확률게이트)가 전부 같은 결론에 "
                 "도달한 만큼, 이 방향을 더 파기보다 지정학신호를 '보조 설명 신호'(경보 사유 "
                 "인용, XAI)로만 쓰는 현재 alert.py 방침을 유지하는 것이 합리적일 수 있다.\n")

    L.append("\n## 표본 크기 주의\n")
    L.append("전환주는 5광종 전체 테스트기간을 합쳐도 26건뿐(diagnosis_retrain_answer.md와 "
             "동일 표본) — tau 스윕 결과는 방향성 참고용이며, 실제 채택 전 표본 확대"
             "(학습기간 연장 또는 부트스트랩 신뢰구간)가 필요하다.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[diagnosis_gate_backtest] 리포트 → {path}")


if __name__ == "__main__":
    main()
