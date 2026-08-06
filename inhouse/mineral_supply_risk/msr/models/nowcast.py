# -*- coding: utf-8 -*-
"""진단 nowcast + XAI — 최적 구성(diagnosis_opt 실측 1위: Ridge 풀링+자기회귀+분위매핑)의
운영용 산출기. 교사(수급동향지표)는 월간 발표·지연되므로, 그 공백을 모델로 메꾸고(nowcast)
alert 레이어의 점수단계 원천으로 공급한다.

XAI(설명가능성) — 착수보고 약속 이행:
  - 기여도: Ridge는 선형이라 예측이 Σ(계수×표준화값)로 '정확히' 분해됨(SHAP의 선형 특수해와
    동일). 위기지수 기여도 = -계수×z (crisis=100-y 부호 반전). 광종 더미는 '광종 기저'로 합산.
  - Confidence: 학습 잔차 표준편차(광종별) 기반 정규근사로 단계별 확률 분포 제공
    (예: "경계 55%, 심각 30%" — 착수보고 Confidence Score 사양).

산출: warehouse 테이블 mart_diagnosis_nowcast(월×광종: ci_pred·stage·단계확률·기여도 json)
     + outputs/model_opt/{final_model.joblib, xai_latest.md}
실행: MSR_DB=<warehouse> python -m msr.models.nowcast
"""
from __future__ import annotations
import json, os, warnings

import duckdb
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import Ridge

from ..config import DB_PATH, OUT
from .diagnosis_opt import BASE_FEATS, GEO_DERIVED, Q_CUT, anchored_cuts, build_panel

warnings.filterwarnings("ignore")

LEVELS = {0: "정상", 1: "관심", 2: "주의", 3: "경계", 4: "심각"}


def _fit_full(df: pd.DataFrame, feats: list):
    """전 기간 적합(운영 발행용). 반환: (모델, 전처리 통계, 광종 더미 목록, 광종별 잔차σ·컷)."""
    d = pd.get_dummies(df, columns=["commodity_code"], prefix="cc")
    cc_cols = sorted(c for c in d.columns if c.startswith("cc_"))
    X_cols = feats + cc_cols
    med = d[feats].median()
    mu, sd = {}, {}
    Xf = d[feats].fillna(med)
    for c in feats:
        mu[c], sd[c] = float(Xf[c].mean()), float(Xf[c].std(ddof=0) or 1.0)
    Z = (Xf - pd.Series(mu)) / pd.Series(sd)
    X = np.column_stack([Z.values, d[cc_cols].astype(float).values])
    y = d["y"].values
    m = Ridge(alpha=1.0).fit(X, y)
    pred = m.predict(X)
    resid = pd.DataFrame({"cc": df["commodity_code"].values, "r": y - pred})
    sigma = resid.groupby("cc")["r"].std().to_dict()
    # 감사 A-1(c): 전체 분포 분위(상대 눈금) → 기준기간 동결 컷(절대 눈금)
    cuts = anchored_cuts(df)
    return m, dict(median=med.to_dict(), mu=mu, sd=sd), cc_cols, sigma, cuts


def _stage_probs(ci_pred: float, sigma: float, cuts: dict) -> dict:
    """정규근사 P(단계): 컷 경계 구간 질량. sigma가 0/결측이면 결정적(현 단계 100%)."""
    if not sigma or not np.isfinite(sigma) or sigma <= 0:
        stage = _stage_of(ci_pred, cuts)
        return {LEVELS[k]: (1.0 if k == stage else 0.0) for k in LEVELS}
    b = [-np.inf] + [cuts[k] for k in sorted(cuts)] + [np.inf]
    probs = {}
    for k in LEVELS:
        lo, hi = b[k], b[k + 1]
        probs[LEVELS[k]] = float(stats.norm.cdf(hi, ci_pred, sigma) -
                                 stats.norm.cdf(lo, ci_pred, sigma))
    return probs


def _stage_of(ci: float, cuts: dict) -> int:
    s = 0
    for k in sorted(cuts):
        if ci >= cuts[k]:
            s = k
    return s


def run(db=None, out_dir=None) -> pd.DataFrame:
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    df = build_panel(db)
    feats = [f for f in BASE_FEATS + GEO_DERIVED
             if df[f].notna().sum() > 50 and df[f].nunique() > 2]
    m, prep, cc_cols, sigma, cuts = _fit_full(df, feats)

    # 전 행 예측 + XAI 분해
    med = pd.Series(prep["median"]); mu = pd.Series(prep["mu"]); sd = pd.Series(prep["sd"])
    Z = (df[feats].fillna(med) - mu) / sd
    D = pd.get_dummies(df["commodity_code"], prefix="cc")
    for c in cc_cols:
        if c not in D:
            D[c] = 0
    X = np.column_stack([Z.values, D[cc_cols].astype(float).values])
    y_pred = m.predict(X)
    ci_pred = 100 - y_pred

    coef_f = m.coef_[:len(feats)]
    contrib = -(Z.values * coef_f)              # 위기지수 기여(+ = 위기 방향)
    base_cc = -(D[cc_cols].astype(float).values @ m.coef_[len(feats):] + m.intercept_) + 100

    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        cc = r["commodity_code"]
        cd = {feats[j]: round(float(contrib[i, j]), 2) for j in range(len(feats))}
        probs = _stage_probs(float(ci_pred[i]), sigma.get(cc), cuts[cc])
        stage = _stage_of(float(ci_pred[i]), cuts[cc])
        rows.append(dict(
            commodity_code=cc, month=r["month"].date(),
            ci_pred=round(float(ci_pred[i]), 2),
            ci_teacher=round(float(r["crisis_index"]), 2) if pd.notna(r["crisis_index"]) else None,
            stage_pred=stage, stage_name=LEVELS[stage],
            stage_probs=json.dumps({k: round(v, 3) for k, v in probs.items()}, ensure_ascii=False),
            contrib=json.dumps(cd, ensure_ascii=False),
            base_level=round(float(base_cc[i]), 2),
        ))
    out = pd.DataFrame(rows)
    out["generated_at"] = pd.Timestamp.utcnow().isoformat(timespec="seconds")

    con = duckdb.connect(db)
    con.register("_n", out)
    con.execute("CREATE OR REPLACE TABLE mart_diagnosis_nowcast AS SELECT * FROM _n")
    con.execute("CHECKPOINT"); con.close()

    import joblib
    joblib.dump(dict(model=m, feats=feats, prep=prep, cc_cols=cc_cols,
                     sigma=sigma, cuts=cuts, spec="Ridge(pooled)+AR+quantile_map",
                     trained_rows=len(df)), f"{out_dir}/final_model.joblib")

    # XAI 최신월 리포트
    latest = out.sort_values("month").groupby("commodity_code").tail(1)
    lines = ["# 진단 nowcast XAI — 최신월", ""]
    for _, r in latest.iterrows():
        probs = json.loads(r["stage_probs"]); cd = json.loads(r["contrib"])
        top = sorted(cd.items(), key=lambda kv: -abs(kv[1]))[:4]
        lines += [f"## {r['commodity_code']} — {r['month']} : **{r['stage_name']}** "
                  f"(위기지수 {r['ci_pred']})",
                  "- 단계 확률: " + ", ".join(f"{k} {v*100:.0f}%" for k, v in probs.items() if v >= 0.01),
                  "- 기여도(위기지수 방향, +가 위기↑): "
                  + ", ".join(f"{k} {v:+.1f}" for k, v in top),
                  f"- 광종 기저 {r['base_level']:.1f} + 기여 합 = 예측 {r['ci_pred']}", ""]
    with open(f"{out_dir}/xai_latest.md", "w") as f:
        f.write("\n".join(lines))
    print(f"[nowcast] mart_diagnosis_nowcast {len(out)}행 · 모델·XAI 저장 → {out_dir}/")
    print("\n".join(lines[:14]))
    return out


if __name__ == "__main__":
    run()
