# -*- coding: utf-8 -*-
"""진단모델 베이스라인 학습 (월간 패널, 시간순 홀드아웃).
run(db, out_dir)로 호출. import만으로는 아무것도 실행하지 않는다(부작용 없음)."""
import os, json
import duckdb, numpy as np, pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from sklearn.inspection import permutation_importance
from ..config import DB_PATH, OUT

FEATS = ["volatility_12w", "import_hhi", "import_yoy", "import_cagr3", "production_hhi",
         "spread_pct", "geopolitical_risk", "geo_macro", "ref_price"]


def _rep(n, yt, yp):
    return dict(model=n, MAE=round(mean_absolute_error(yt, yp), 2),
                RMSE=round(float(np.sqrt(((yt - yp) ** 2).mean())), 2),
                R2=round(r2_score(yt, yp), 3))


def run(db=None, out_dir=None, min_rows=20):
    """mart_weekly_diagnosis(교사신호 존재분) → 월간 패널 학습·검증. 결과 dict 반환.
    데이터 부족 시 None 반환(스킵)."""
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model")
    os.makedirs(out_dir, exist_ok=True)

    con = duckdb.connect(db, read_only=True)
    # 마트 스키마 방어: canonical 마트(marts.py) 컬럼이 없으면(현 warehouse는 schema_core.sql
    # 버전이라 target_label/feat_json) 크래시 대신 스킵. raw→fact 통합 후 활성화된다.
    try:
        have = {c[0] for c in con.execute("DESCRIBE mart_weekly_diagnosis").fetchall()}
    except Exception:
        con.close(); print("[diagnosis] mart_weekly_diagnosis 없음 → 스킵."); return None
    need = set(FEATS) | {"teacher_supply_demand", "commodity_code", "obs_date"}
    missing = need - have
    if missing:
        con.close()
        print(f"[diagnosis] mart_weekly_diagnosis 컬럼 불일치(누락 {sorted(missing)}) → 스킵. "
              "marts.py 기반 canonical 마트(raw→fact 통합) 필요.")
        return None
    df = con.execute(f"""
        WITH w AS (
          SELECT commodity_code, date_trunc('month',obs_date) AS month, obs_date,
                 {','.join(FEATS)}, teacher_supply_demand AS y
          FROM mart_weekly_diagnosis
          WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL
        )
        SELECT commodity_code, month,
               {','.join(f'avg({c}) AS {c}' for c in FEATS)},
               last(y ORDER BY obs_date) AS y
        FROM w GROUP BY 1,2 ORDER BY commodity_code, month
    """).df()
    con.close()
    print("월간 패널:", df.shape)
    if len(df) < min_rows or df["y"].notna().sum() < min_rows:
        print(f"[diagnosis] 학습 데이터 부족(<{min_rows}행 또는 교사신호 없음) → 스킵. "
              "가격·지정학·교사신호(raw→fact) 확보 후 재시도.")
        return None

    df["month"] = pd.to_datetime(df["month"])
    train = df[df.month < "2025-01-01"].copy()
    test = df[df.month >= "2025-01-01"].copy()
    print(f"train {len(train)} / test {len(test)}  (test: 2025-01~)")
    if train.empty or test.empty:
        print("[diagnosis] 학습/검증 분할 중 한쪽이 비어 스킵.")
        return None

    # 전부 NULL/상수인 피처 제외(예: production_hhi·geopolitical_risk 미보유 → 학습 불가·binning 크래시 방지)
    feats = [c for c in FEATS if train[c].notna().sum() >= 2 and train[c].nunique(dropna=True) >= 2]
    dropped = [c for c in FEATS if c not in feats]
    if dropped: print(f"  제외 피처(전-NULL/상수): {dropped}")
    if not feats:
        print("[diagnosis] 사용 가능한 피처 없음 → 스킵."); return None
    print(f"  사용 피처 {len(feats)}: {feats}")

    X_cols = feats + ["commodity_code"]
    Xtr, ytr = train[X_cols], train["y"].values
    Xte, yte = test[X_cols], test["y"].values

    # 0) 나이브: 광종별 학습기간 평균
    naive_map = train.groupby("commodity_code")["y"].mean()
    naive_pred = test["commodity_code"].map(naive_map).values
    results = [_rep("Naive(광종평균)", yte, naive_pred)]

    num, cat = feats, ["commodity_code"]
    # 1) Ridge + 광종더미 + 표준화 + 결측대치
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), num),
        ("cat", OneHotEncoder(handle_unknown="ignore"), cat)])
    ridge = Pipeline([("pre", pre), ("m", Ridge(alpha=1.0))]).fit(Xtr, ytr)
    results.append(_rep("Ridge(+광종더미)", yte, ridge.predict(Xte)))

    # 2) HistGBM (결측 native 처리, 광종 ordinal)
    Xtr2, Xte2 = Xtr.copy(), Xte.copy()
    codes = {c: i for i, c in enumerate(sorted(df.commodity_code.unique()))}
    Xtr2["commodity_code"] = Xtr2["commodity_code"].map(codes)
    Xte2["commodity_code"] = Xte2["commodity_code"].map(codes)
    gbm = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=3,
          categorical_features=[len(feats)], random_state=42).fit(Xtr2, ytr)
    results.append(_rep("HistGBM(+광종)", yte, gbm.predict(Xte2)))

    print("\n=== 회귀 성능 (test=2025~) ===")
    for r in results: print("  ", r)

    # 이진 위기분류 (타깃<20 = 위기)
    thr = 20
    ytr_b, yte_b = (ytr < thr).astype(int), (yte < thr).astype(int)
    auc = None
    if yte_b.sum() > 0 and yte_b.sum() < len(yte_b):
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=3,
            categorical_features=[len(feats)], random_state=42).fit(Xtr2, ytr_b)
        auc = round(roc_auc_score(yte_b, clf.predict_proba(Xte2)[:, 1]), 3)
    print(f"\n=== 위기 이진분류(타깃<{thr}) AUC(test): {auc} | test 위기비율 {yte_b.mean():.2f} ===")

    # 피처 중요도 (permutation, GBM)
    pi = permutation_importance(gbm, Xte2, yte, n_repeats=10, random_state=42)
    imp = sorted(zip(X_cols, pi.importances_mean), key=lambda x: -x[1])
    print("\n=== 피처 중요도 (permutation, GBM) ===")
    for f, v in imp: print(f"  {f:18s}: {v:.2f}")

    # 저장(설정 가능한 out_dir)
    pd.DataFrame(results).to_csv(f"{out_dir}/model_metrics.csv", index=False)
    pd.DataFrame(imp, columns=["feature", "perm_importance"]).to_csv(f"{out_dir}/feature_importance.csv", index=False)
    df.to_csv(f"{out_dir}/monthly_panel.csv", index=False)
    summary = {"results": results, "auc_crisis": auc, "n_train": len(train), "n_test": len(test),
               "importance": [[f, round(float(v), 3)] for f, v in imp]}
    json.dump(summary, open(f"{out_dir}/model_summary.json", "w"), ensure_ascii=False, indent=2)
    print(f"\n저장: {out_dir}/ (metrics·importance·panel·summary)")
    return summary


if __name__ == "__main__":
    run()
