# -*- coding: utf-8 -*-
"""진단모델 최적화 — 백데이터(실가격·교사 2020~2026 + 지정학 2016~) 기반 체계적 비교.

diagnosis.py(베이스라인, 단일 홀드아웃)의 최적화판. 차이:
  1) 워크포워드 3폴드(test=2023/2024/2025~) — 단일 분할의 운(luck) 제거
  2) 후보군 확장 — 과업지시서 명시 모델(로지스틱·DT·RF) + Ridge/HistGBM + 광종별 vs 풀링
  3) 지정학 파생피처 — geo lag1·EWMA3·Δ, burst 확률(geo_prob), 가격 z(52주)
  4) 타깃 이원화 — (a) 교사 회귀→분위수 매핑 (b) 4단계 직접 분류, 지표는 QWK·macroF1·RPS
     (4단계 라벨 = alert.py와 동일한 위기지수 분위수 컷 — 레이어 간 정의 일치)
  5) 붙임1 필수 분석 — 피처 상관행렬·VIF, 최적모델 민감도(피처 제거 시 QWK 변화)

산출: outputs/model_opt/{comparison.csv, per_commodity.csv, corr_vif.txt, report.md}
실행: MSR_DB=<warehouse> python -m msr.models.diagnosis_opt
"""
from __future__ import annotations
import os, json, warnings

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.metrics import cohen_kappa_score, f1_score, mean_absolute_error, r2_score

from ..config import DB_PATH, OUT

warnings.filterwarnings("ignore")

BASE_FEATS = ["volatility_12w", "import_hhi", "import_yoy", "import_cagr3",
              "spread_pct", "geopolitical_risk", "ref_price"]
# VIF 정제(1차 실행 실측): geo level·lag1·chg 완전공선(chg=level-lag), ewma3도 corr 0.9 —
# level+chg만 유지. y_lag1(전월 교사)=자기회귀항: 진단(nowcast)에서 전월 지표는 운영상 가용
# 정보이며, 이것 없이는 어떤 모델도 지속성 Naive를 못 이김(1차 실측 QWK 0.884 vs 0.746).
GEO_DERIVED = ["geo_chg", "p_burst", "price_z52", "y_lag1"]
Q_CUT = {1: 0.50, 2: 0.70, 3: 0.85, 4: 0.95}     # alert.py와 동일 분위 컷(단계 0~4)
FOLDS = [("2023-01-01", "2024-01-01"), ("2024-01-01", "2025-01-01"), ("2025-01-01", "2027-01-01")]


# ─────────────────────────────── 데이터 ───────────────────────────────
def build_panel(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    df = con.execute(f"""
        WITH w AS (
          SELECT commodity_code, date_trunc('month',obs_date) AS month, obs_date,
                 {','.join(BASE_FEATS)}, teacher_supply_demand AS y
          FROM mart_weekly_diagnosis
          WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL
        )
        SELECT commodity_code, month,
               {','.join(f'avg({c}) AS {c}' for c in BASE_FEATS)},
               last(y ORDER BY obs_date) AS y
        FROM w GROUP BY 1,2 ORDER BY commodity_code, month""").df()
    # 확률 레이어(geo_prob, 주간) → 월 최대 p_burst
    try:
        pb = con.execute("""
            SELECT commodity_code, date_trunc('month', CAST(period AS DATE)) AS month,
                   max(p_burst_next) AS p_burst
            FROM geo_prob GROUP BY 1,2""").df()
        df = df.merge(pb, on=["commodity_code", "month"], how="left")
    except Exception:
        df["p_burst"] = np.nan
    # 주간 가격 z(52주) → 월 마지막 값
    try:
        pz = con.execute("""
            WITH p AS (
              SELECT commodity_code, obs_date, ref_price,
                     avg(ref_price) OVER w AS m52, stddev_samp(ref_price) OVER w AS s52
              FROM mart_weekly_diagnosis
              WINDOW w AS (PARTITION BY commodity_code ORDER BY obs_date
                           ROWS BETWEEN 51 PRECEDING AND CURRENT ROW)
            )
            SELECT commodity_code, date_trunc('month',obs_date) AS month,
                   last((ref_price-m52)/NULLIF(s52,0) ORDER BY obs_date) AS price_z52
            FROM p GROUP BY 1,2""").df()
        df = df.merge(pz, on=["commodity_code", "month"], how="left")
    except Exception:
        df["price_z52"] = np.nan
    con.close()

    df["month"] = pd.to_datetime(df["month"])
    df = df.sort_values(["commodity_code", "month"]).reset_index(drop=True)
    g = df.groupby("commodity_code")["geopolitical_risk"]
    df["geo_chg"] = df["geopolitical_risk"] - g.shift(1)
    df["y_lag1"] = df.groupby("commodity_code")["y"].shift(1)
    df["crisis_index"] = 100 - df["y"]
    return df


def stage_labels(df: pd.DataFrame, train_mask: pd.Series) -> pd.Series:
    """4단계 라벨(0정상~4심각): '학습기간' 광종별 위기지수 분위수 컷 — 테스트 누수 방지."""
    lab = pd.Series(0, index=df.index)
    for cc, g in df.groupby("commodity_code"):
        tr = g[train_mask.loc[g.index]]
        cuts = {k: tr["crisis_index"].quantile(q) for k, q in Q_CUT.items()}
        ci = g["crisis_index"]
        s = pd.Series(0, index=g.index)
        for k in sorted(cuts):
            s[ci >= cuts[k]] = k
        lab.loc[g.index] = s
    return lab


# ─────────────────────────────── 모델 정의 ───────────────────────────────
def _prep(feats):
    return Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())])


def _fit_predict_stage(name, Xtr, ytr, Xte, feats):
    """분류 계열: 4단계 직접 예측."""
    prep = _prep(feats)
    Xtr_ = prep.fit_transform(Xtr[feats]); Xte_ = prep.transform(Xte[feats])
    if name == "Logistic":
        m = LogisticRegression(max_iter=2000, multi_class="multinomial", C=1.0)
    elif name == "DecisionTree":
        m = DecisionTreeClassifier(max_depth=4, min_samples_leaf=10, random_state=0)
    elif name == "RandomForest":
        m = RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=5,
                                    random_state=0, n_jobs=4)
    else:
        raise ValueError(name)
    m.fit(Xtr_, ytr)
    return m.predict(Xte_)


def _fit_predict_reg(name, tr, te, feats, per_commodity=False):
    """회귀 계열: 교사 예측 → 반환은 연속값(단계 매핑은 호출부)."""
    def one(tr_, te_):
        prep = _prep(feats)
        Xtr_ = prep.fit_transform(tr_[feats]); Xte_ = prep.transform(te_[feats])
        if name == "Ridge":
            m = Ridge(alpha=1.0)
        elif name == "HistGBM":
            m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.08,
                                               max_iter=250, random_state=0)
        else:
            raise ValueError(name)
        m.fit(Xtr_, tr_["y"].values)
        return m.predict(Xte_)
    if not per_commodity:
        # 풀링: 광종 더미
        tr2 = pd.get_dummies(tr, columns=["commodity_code"], prefix="cc")
        te2 = pd.get_dummies(te, columns=["commodity_code"], prefix="cc")
        cc_cols = [c for c in tr2.columns if c.startswith("cc_")]
        for c in cc_cols:
            if c not in te2:
                te2[c] = 0
        return one(tr2.assign(), te2), None
    preds = pd.Series(index=te.index, dtype=float)
    for cc, g_te in te.groupby("commodity_code"):
        g_tr = tr[tr["commodity_code"] == cc]
        if len(g_tr) < 24:
            preds.loc[g_te.index] = g_tr["y"].mean()
            continue
        preds.loc[g_te.index] = one(g_tr, g_te)
    return preds.values, None


def reg_to_stage(pred_y, te, tr):
    """회귀 예측(교사) → 위기지수 → 학습기간 분위 컷으로 4단계 매핑(광종별)."""
    ci_pred = 100 - pred_y
    out = pd.Series(0, index=te.index)
    for cc, g in te.groupby("commodity_code"):
        tr_ci = tr[tr["commodity_code"] == cc]["crisis_index"]
        cuts = {k: tr_ci.quantile(q) for k, q in Q_CUT.items()}
        s = pd.Series(0, index=g.index)
        cp = pd.Series(ci_pred, index=te.index).loc[g.index]
        for k in sorted(cuts):
            s[cp >= cuts[k]] = k
        out.loc[g.index] = s
    return out.values


def rps(y_true, y_pred, n_class=5):
    """Ranked Probability Score(결정적 예측 → one-hot 누적) — 낮을수록 좋음."""
    T = np.eye(n_class)[np.asarray(y_true, int)].cumsum(1)
    P = np.eye(n_class)[np.asarray(y_pred, int)].cumsum(1)
    return float(((P - T) ** 2).sum(1).mean() / (n_class - 1))


# ─────────────────────────────── 메인 ───────────────────────────────
def run(db=None, out_dir=None):
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    df = build_panel(db)
    feats_all = BASE_FEATS + GEO_DERIVED
    feats_all = [f for f in feats_all if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    print(f"패널 {df.shape} | 피처 {len(feats_all)}: {feats_all}")

    # ── 붙임1: 상관행렬 + VIF ──
    X = df[feats_all].dropna()
    corr = X.corr()
    vif = {}
    Xs = (X - X.mean()) / X.std(ddof=0)
    for i, c in enumerate(feats_all):
        others = [f for f in feats_all if f != c]
        beta, *_ = np.linalg.lstsq(Xs[others].values, Xs[c].values, rcond=None)
        r2 = 1 - ((Xs[c].values - Xs[others].values @ beta) ** 2).sum() / (Xs[c].values ** 2).sum()
        vif[c] = round(1 / max(1e-9, 1 - r2), 1)
    with open(f"{out_dir}/corr_vif.txt", "w") as f:
        f.write("=== 상관행렬 ===\n" + corr.round(2).to_string()
                + "\n\n=== VIF ===\n" + json.dumps(vif, ensure_ascii=False, indent=1))
    high_corr = [(a, b, round(corr.loc[a, b], 2)) for i, a in enumerate(feats_all)
                 for b in feats_all[i+1:] if abs(corr.loc[a, b]) > 0.8]
    print("고상관(>0.8) 쌍:", high_corr, "| VIF>10:", {k: v for k, v in vif.items() if v > 10})

    # ── 워크포워드 비교 ──
    rows = []
    candidates = [
        ("Naive(전월단계 유지)", "persist", None),
        ("Ridge(풀링)+매핑", "reg", dict(name="Ridge", per=False)),
        ("Ridge(광종별)+매핑", "reg", dict(name="Ridge", per=True)),
        ("HistGBM(풀링)+매핑", "reg", dict(name="HistGBM", per=False)),
        ("HistGBM(광종별)+매핑", "reg", dict(name="HistGBM", per=True)),
        ("Logistic(4단계 직접)", "clf", dict(name="Logistic")),
        ("DecisionTree(직접)", "clf", dict(name="DecisionTree")),
        ("RandomForest(직접)", "clf", dict(name="RandomForest")),
    ]
    for t0, t1 in FOLDS:
        tr_mask = df["month"] < t0
        te_mask = (df["month"] >= t0) & (df["month"] < t1)
        tr, te = df[tr_mask].copy(), df[te_mask].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        y_stage = stage_labels(df, tr_mask)
        ytr_s, yte_s = y_stage[tr.index].values, y_stage[te.index].values
        # 전환월(전월과 단계가 달라진 달) — naive가 구조적으로 전패하는, 모델의 실가치 구간
        stage_prev = pd.Series(y_stage.values, index=df.index) \
            .groupby(df["commodity_code"]).shift(1)[te.index]
        chg_mask = (stage_prev.notna()) & (stage_prev.values != yte_s)
        for label, kind, kw in candidates:
            if kind == "persist":
                prev = df.groupby("commodity_code")["month"].shift(0)  # 전월 단계
                stage_series = pd.Series(y_stage.values, index=df.index)
                pred = stage_series.groupby(df["commodity_code"]).shift(1)[te.index] \
                    .fillna(0).astype(int).values
                reg_metrics = {}
            elif kind == "reg":
                pred_y, _ = _fit_predict_reg(kw["name"], tr, te, feats_all, kw["per"])
                pred = reg_to_stage(pred_y, te, tr)
                reg_metrics = dict(MAE=round(mean_absolute_error(te["y"], pred_y), 2),
                                   R2=round(r2_score(te["y"], pred_y), 3))
            else:
                pred = _fit_predict_stage(kw["name"], tr, ytr_s, te, feats_all)
                reg_metrics = {}
            chg_acc = float((np.asarray(pred)[chg_mask.values] == yte_s[chg_mask.values]).mean()) \
                if chg_mask.sum() else np.nan
            rows.append(dict(fold=f"{t0[:4]}", model=label,
                             QWK=round(cohen_kappa_score(yte_s, pred, weights="quadratic"), 3),
                             macroF1=round(f1_score(yte_s, pred, average="macro"), 3),
                             RPS=round(rps(yte_s, pred), 4),
                             acc=round(float((yte_s == pred).mean()), 3),
                             chg_acc=round(chg_acc, 3) if chg_mask.sum() else None,
                             n_chg=int(chg_mask.sum()), **reg_metrics))
    res = pd.DataFrame(rows)
    agg = (res.groupby("model")[["QWK", "macroF1", "RPS", "acc", "chg_acc"]].mean().round(3)
              .sort_values("QWK", ascending=False))
    res.to_csv(f"{out_dir}/comparison_folds.csv", index=False)
    agg.to_csv(f"{out_dir}/comparison.csv")
    print("\n=== 워크포워드 평균(3폴드) — QWK 내림차순 ===")
    print(agg.to_string())

    # ── 최적모델 광종별 성능 + 피처 제거 민감도(마지막 폴드) ──
    best = agg.index[0]
    best_model = next((m for m in agg.index if "Naive" not in m), agg.index[0]) \
        if "Naive" in best else best
    t0, t1 = FOLDS[-1]
    tr = df[df["month"] < t0].copy(); te = df[(df["month"] >= t0) & (df["month"] < t1)].copy()
    y_stage = stage_labels(df, df["month"] < t0)
    kind, kw = next((k, w) for l, k, w in candidates if l == best_model)

    def eval_once(fset):
        if kind == "reg":
            py, _ = _fit_predict_reg(kw["name"], tr, te, fset, kw["per"])
            p = reg_to_stage(py, te, tr)
        else:
            p = _fit_predict_stage(kw["name"], tr, y_stage[tr.index].values, te, fset)
        return cohen_kappa_score(y_stage[te.index].values, p, weights="quadratic"), p

    qwk_full, pred_full = eval_once(feats_all)
    percc = []
    te_pred = pd.Series(pred_full, index=te.index)
    for cc, g in te.groupby("commodity_code"):
        percc.append(dict(commodity=cc,
                          QWK=round(cohen_kappa_score(y_stage[g.index], te_pred[g.index],
                                                       weights="quadratic"), 3),
                          n=len(g)))
    pd.DataFrame(percc).to_csv(f"{out_dir}/per_commodity.csv", index=False)
    sens = []
    for f in feats_all:
        q, _ = eval_once([x for x in feats_all if x != f])
        sens.append(dict(removed=f, dQWK=round(qwk_full - q, 3)))
    sens = sorted(sens, key=lambda r: -r["dQWK"])

    with open(f"{out_dir}/report.md", "w") as fo:
        fo.write(f"# 진단모델 최적화 리포트\n\n1위: **{best}** / 민감도 분석 대상(비-Naive 최상): **{best_model}**\n\n"
                 f"## 워크포워드 평균\n{agg.to_markdown()}\n\n"
                 f"## 광종별(최종 폴드)\n{pd.DataFrame(percc).to_markdown(index=False)}\n\n"
                 f"## 피처 제거 민감도(dQWK>0 = 제거 시 성능 하락 = 기여 피처)\n"
                 f"{pd.DataFrame(sens).to_markdown(index=False)}\n\n"
                 f"## 고상관 쌍(>0.8)\n{high_corr}\n\n## VIF\n{vif}\n")
    print(f"\n최적: {best} | 광종별 QWK: {percc}")
    print("피처 민감도 상위:", sens[:5])
    print(f"저장: {out_dir}/")
    return {"best": best, "agg": agg, "per_commodity": percc, "sensitivity": sens}


if __name__ == "__main__":
    run()
