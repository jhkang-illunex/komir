# -*- coding: utf-8 -*-
"""진단모델 대안 재피팅 — 전체 피처(기존+Tier1+Tier2) × 다른 모델 계열
(2026-07-25, 사용자 지시 "기존과 다른 방식으로 전부 재피팅").

⚠ 맥락(재시도 금지와의 관계): 07-24 y_lag1 심층검토의 "모델교체 재시도 금지"는
**외부 직교 데이터 확보 전** 조건부였음 — 이후 INV·CNINV·PMI·Tier1·Tier2가
확보됐고, 이번은 사용자 직접 지시의 전피처×모델계열 스윕이므로 별개 검정.
광종별 분리학습(풀링 해제)은 07-24 감사에서 열세 확인 — 재시도하지 않음.

두 프레임 × 세 모델 계열 × 두 피처셋:
  레벨(운영 등급예측): 현행 챔피언 = Ridge + ALL_FEATS(GEO+PRICE, y_lag1 포함)
    대안 = HistGBM(비선형 부스팅)·RandomForest(배깅) × {현행, FULL(전피처)}
  Δ분류(보조 조기경보): 현행 챔피언 = Logistic + 채택 동작점(NOLAG+INV+CNINV+PMI)
    대안 = HGB·RandomForest × {채택 동작점, FULL_NOLAG(전피처, y_lag1 제외)}

평가: 동일 워크포워드 3폴드(2023/2024/2025+), QWK·전환적중·FAR. 최우수 대안은
챔피언과 페어드 부트스트랩(행 리샘플 4000회) QWK차이 CI.

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_alt_refit
산출: outputs/model_opt/diagnosis_alt_refit.md
"""
from __future__ import annotations
import os, sys

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                                  # noqa: E402
from scripts.diagnosis_retrain_answer import (                              # noqa: E402
    build_panel, ALL_FEATS, GEO_ONLY_NO_LAG, FOLDS, _fit_predict_reg,
)
from scripts.diagnosis_ylag_deep_review import (                            # noqa: E402
    add_dynamics, e2_delta_classifier, evaluate, qwk, pooled_design,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F            # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                        # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                         # noqa: E402
    build_trd, build_pmi, TRD_F, PMI_F,
)
from scripts.diagnosis_tier1_eval import (                                  # noqa: E402
    build_tier1, SUP_F, COT2_F, FXP_F, CNOI_F,
)
from scripts.diagnosis_tier2_eval import (                                  # noqa: E402
    build_tier2, CLP_F, COINV_F, SEMI_F, KIP_F, KINV_F,
)

EXT_F = (INV_F + exch.CNINV_F + TRD_F + PMI_F
         + SUP_F + COT2_F + FXP_F + CNOI_F
         + CLP_F + COINV_F + SEMI_F + KIP_F + KINV_F)


def level_frame(df: pd.DataFrame, feats: list[str], model: str):
    """레벨(등급 직접) 워크포워드 — 풀링. pred 연속값을 반올림해 평가, 원시값도 반환."""
    ys, lags, preds = [], [], []
    for t0, t1 in FOLDS:
        tr = df[df["obs_date"] < t0].copy()
        te = df[(df["obs_date"] >= t0) & (df["obs_date"] < t1)].copy()
        if len(te) == 0 or len(tr) < 60:
            continue
        if model in ("Ridge", "HistGBM"):
            p = _fit_predict_reg(model, tr, te, feats, per_commodity=False)
        else:  # RandomForest — 챔피언 프레임과 동일한 풀링·더미·중앙값 대치
            tr2 = pd.get_dummies(tr, columns=["commodity_code"], prefix="cc")
            te2 = pd.get_dummies(te, columns=["commodity_code"], prefix="cc")
            for c in [c for c in tr2.columns if c.startswith("cc_")]:
                if c not in te2:
                    te2[c] = 0
            feats2 = feats + [c for c in tr2.columns if c.startswith("cc_")]
            med = tr2[feats2].median(numeric_only=True)
            m = RandomForestRegressor(n_estimators=400, min_samples_leaf=5,
                                      random_state=0, n_jobs=-1)
            m.fit(tr2[feats2].fillna(med), tr2["grade_ord"].values)
            p = m.predict(te2[feats2].fillna(med))
        ys.append(te["grade_ord"].astype(int).values)
        lags.append(te["grade_lag1"].round().clip(0, 2).astype(int).values)
        preds.append(np.asarray(p))
    y = np.concatenate(ys); lag = np.concatenate(lags)
    p = np.concatenate(preds)
    pr = np.clip(np.rint(p), 0, 2).astype(int)
    return evaluate(y, lag, pr, None), (y, lag, pr)


def delta_rf(df: pd.DataFrame, feats: list[str]):
    """Δ분류 RandomForest — e2 프레임과 동일 골격(클래스 가중 리샘플 가중치)."""
    from scripts.diagnosis_ylag_deep_review import walkforward_collect

    def fit_predict(tr, te):
        dtr = np.clip(tr["grade_ord"].values - tr["grade_lag1"].round().values,
                      -1, 1).astype(int)
        Xtr, Xte = pooled_design(tr, te, feats)
        w = np.ones(len(dtr))
        for cls in np.unique(dtr):
            w[dtr == cls] = len(dtr) / (len(np.unique(dtr)) * (dtr == cls).sum())
        m = RandomForestClassifier(n_estimators=400, min_samples_leaf=5,
                                   random_state=0, n_jobs=-1)
        m.fit(Xtr, dtr, sample_weight=w)
        dhat = m.predict(Xte).astype(int)
        lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
        return np.clip(lag + dhat, 0, 2), dhat != 0
    return walkforward_collect(df, fit_predict)


def paired_bootstrap_qwk(y, pa, pb, n_iter=4000, seed=0):
    """같은 행에 대한 두 예측의 QWK 차이(B-A) 부트스트랩 CI·P(diff>0)."""
    rng = np.random.default_rng(seed)
    n = len(y)
    diffs = []
    for _ in range(n_iter):
        i = rng.integers(0, n, n)
        diffs.append(qwk(y[i], pb[i], K=3) - qwk(y[i], pa[i], K=3))
    diffs = np.array(diffs)
    return (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)),
            float((diffs > 0).mean()))


def main():
    db = os.environ["MSR_DB"]
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    print(f"⚠ 평가 패널 종점(발주처 컷): {df['obs_date'].max().date()}")
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_trd(db, df)
    df = build_pmi(db, df)
    df = build_tier1(db, df)
    df = build_tier2(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    ext = [f for f in EXT_F if df[f].notna().sum() > 50]
    FULL = ALL_FEATS + ext                 # 레벨: y_lag1·가격 포함 전피처
    FULL_NOLAG = nolag + ext               # Δ: y_lag1 제외 전피처
    ADOPTED = nolag + INV_F + exch.CNINV_F + PMI_F
    print(f"피처 수: 현행 {len(ALL_FEATS)} → FULL {len(FULL)} (확장 {len(ext)})")

    rows, raw = [], {}
    # ── 레벨 프레임 ──
    for model in ["Ridge", "HistGBM", "RandomForest"]:
        for ftag, feats in [("현행피처", ALL_FEATS), ("FULL", FULL)]:
            if model == "Ridge" and ftag == "현행피처":
                tag = "Ridge+현행피처(챔피언)"
            else:
                tag = f"{model}+{ftag}"
            r, yp = level_frame(df, feats, model)
            rows.append(dict(프레임="레벨", 구성=tag, **r))
            raw[("레벨", tag)] = yp
            print(f"레벨 {tag}: QWK {r['QWK']:.4f} acc {r['acc']:.4f} "
                  f"chg {r['chg_acc']:.4f}")
    # ── Δ 프레임 ──
    for tag, fn in [
        ("Logistic+채택동작점(챔피언)", lambda: e2_delta_classifier(df, ADOPTED, "Logistic")),
        ("Logistic+FULL", lambda: e2_delta_classifier(df, FULL_NOLAG, "Logistic")),
        ("HGB+채택동작점", lambda: e2_delta_classifier(df, ADOPTED, "HGB")),
        ("HGB+FULL", lambda: e2_delta_classifier(df, FULL_NOLAG, "HGB")),
        ("RF+채택동작점", lambda: delta_rf(df, ADOPTED)),
        ("RF+FULL", lambda: delta_rf(df, FULL_NOLAG)),
    ]:
        r = fn()
        rows.append(dict(프레임="Δ분류", 구성=tag, **r))
        print(f"Δ {tag}: QWK {r['QWK']:.4f} chg {r['chg_acc']:.4f} "
              f"FAR {r['FAR']:.4f}")
    tab = pd.DataFrame(rows)

    # ── 레벨 최우수 대안 vs 챔피언 페어드 부트스트랩 ──
    champ_key = ("레벨", "Ridge+현행피처(챔피언)")
    lv = tab[tab["프레임"] == "레벨"]
    best_row = lv[lv["구성"] != champ_key[1]].loc[
        lv[lv["구성"] != champ_key[1]]["QWK"].idxmax()]
    y0, _, pa = raw[champ_key]
    y1, _, pb = raw[("레벨", best_row["구성"])]
    assert np.array_equal(y0, y1)
    lo, hi, p = paired_bootstrap_qwk(y0, pa, pb)
    bs_line = (f"레벨 최우수 대안({best_row['구성']}) vs 챔피언: QWK차이 CI "
               f"[{lo:+.4f},{hi:+.4f}] P(diff>0)={p:.3f}")
    print(bs_line)
    write_report(df, tab, bs_line)


def write_report(df, tab, bs_line):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_alt_refit.md")
    L = ["# 진단모델 대안 재피팅 — 전피처(기존+T1+T2) × 모델 계열\n",
         f"작성: 2026-07-25 · 패널 종점 {df['obs_date'].max().date()}(발주처 컷) · "
         "워크포워드 3폴드 · 레벨=운영 등급예측 프레임(y_lag1·가격 포함), "
         "Δ분류=보조 조기경보 프레임(y_lag1 제외). 광종별 분리학습은 07-24 감사에서 "
         "열세 확인돼 미시도.\n",
         "\n| 프레임 | 구성 | QWK | acc | chg_acc | n_chg | FAR |",
         "|---|---|---|---|---|---|---|"]
    for _, r in tab.iterrows():
        far = "—" if pd.isna(r["FAR"]) else f"{r['FAR']:.4f}"
        L.append(f"| {r['프레임']} | {r['구성']} | {r['QWK']:.4f} | {r['acc']:.4f} "
                 f"| {r['chg_acc']:.4f} | {int(r['n_chg'])} | {far} |")
    L.append(f"\n## 부트스트랩\n\n- {bs_line}")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[alt_refit] 리포트 → {path}")


if __name__ == "__main__":
    main()
