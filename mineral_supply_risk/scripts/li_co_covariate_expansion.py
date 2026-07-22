# -*- coding: utf-8 -*-
"""LI/CO 부진 원인분석(C-4) — 피드백기반_수정플랜 P2.

C-1(prob_target_v1_v2_separation.md)에서 NB2 target 개편(v1→v2)이 CU·NI·REE는 개선했으나
CO는 동률, **LI는 열세**(-0.0103)였음이 확인됨 — 원인 미분석 상태였다. 이 스크립트는 LI·CO의
NB2 확률모델(x_ewma·x_geo·x_vol)에 가격(price_z52)·수입편중(import_hhi)·가격변동성
(spread_pct)·정책이벤트 주간건수(geo_event.dimension='policy') 공변량을 추가한 확장모델을
시험 적합해, 기존모델 대비 Brier/ECE 개선 여부로 "피처 부족이 원인인지"를 확인한다.
prob_model.py의 _fit_one·_p_ge를 그대로 재사용(재구현 없음, feats 리스트만 확장).

주의(weekday 앵커): prob_model 패널은 일요일 앵커, mart_weekly_diagnosis/geo_event는
월요일 앵커 — geo/publish.py의 geo_prob 발행 경계 보정과 동일하게 +1일 정렬 후 병합.

실행: python3 -m scripts.li_co_covariate_expansion
산출: outputs/model_opt/li_co_covariate_expansion.md
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import log_loss

HERE = Path(__file__).resolve().parent
KOMIR = HERE.parent.parent
sys.path.insert(0, str(KOMIR))
os.environ.setdefault("GEO_DATA", str(KOMIR / "geo_data"))
os.environ.setdefault("GEO_EVENT_SOURCE", "file")

from geo.prob_model import _weekly_panel, _attach_geo_idx, _features, _fit_one, _p_ge, TRAIN_END  # noqa: E402
from scripts.prob_calibration_extended import ece  # noqa: E402

from msr.config import DB_PATH, OUT

BASE_FEATS = ["x_ewma", "x_geo", "x_vol"]
# spread_pct는 mart_weekly_diagnosis에서 CO·LI·REE가 100% 결측(실측: count(spread_pct)=0,
# CU·NI만 존재) — 구조적 데이터 공백이라 LI/CO 확장피처에서는 제외(포함 시 dropna로 표본 0).
EXT_FEATS = BASE_FEATS + ["price_z52", "import_hhi", "n_policy"]
TARGETS = ["LI", "CO"]


def load_covariates(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    cov = con.execute("""
        WITH p AS (
          SELECT commodity_code, obs_date, ref_price, import_hhi, spread_pct,
                 avg(ref_price) OVER w AS m52, stddev_samp(ref_price) OVER w AS s52
          FROM mart_weekly_diagnosis
          WINDOW w AS (PARTITION BY commodity_code ORDER BY obs_date
                       ROWS BETWEEN 51 PRECEDING AND CURRENT ROW)
        )
        SELECT commodity_code, obs_date::date obs_date, import_hhi, spread_pct,
               (ref_price - m52) / NULLIF(s52, 0) AS price_z52
        FROM p
    """).fetchdf()
    # date_trunc('week', d)는 DuckDB에서 이미 ISO 월요일 기준(실측 확인: 2024-01-10 수요일 →
    # 2024-01-08 월요일) — 별도 +1 보정 불필요(geo_prob의 Sunday→Monday 보정과는 다른 케이스).
    pol = con.execute("""
        SELECT commodity_code, date_trunc('week', obs_date::date) AS _monday, count(*) n_policy
        FROM geo_event WHERE dimension = 'policy' AND obs_date IS NOT NULL
        GROUP BY 1, 2
    """).fetchdf()
    con.close()
    return cov, pol


def build_expanded_panel(feat: pd.DataFrame, cov: pd.DataFrame, pol: pd.DataFrame) -> pd.DataFrame:
    feat = feat.copy()
    feat["_monday"] = pd.to_datetime(feat["week"]) + pd.Timedelta(days=1)
    cov["_monday"] = pd.to_datetime(cov["obs_date"])
    pol["_monday"] = pd.to_datetime(pol["_monday"])
    merged = feat.merge(cov[["commodity_code", "_monday", "import_hhi", "spread_pct", "price_z52"]]
                         .rename(columns={"commodity_code": "commodity"}),
                         on=["commodity", "_monday"], how="left")
    merged = merged.merge(pol.rename(columns={"commodity_code": "commodity"}),
                           on=["commodity", "_monday"], how="left")
    merged["n_policy"] = merged["n_policy"].fillna(0.0)
    return merged


def evaluate(train: pd.DataFrame, test: pd.DataFrame, feats: list[str]) -> dict:
    tr = train.dropna(subset=feats)
    te = test.dropna(subset=feats)
    if len(tr) < 30 or len(te) < 10:
        return dict(n=len(te), brier=None, ece=None, log_loss=None, note="표본부족")
    burst_k = max(2, int(np.ceil(tr["y_next"].quantile(0.90))))
    X = sm.add_constant(tr[feats].astype(float))
    y = tr["y_next"].astype(float)
    try:
        m = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        mu = np.clip(m.fittedvalues.values, 1e-9, None)
        aux = ((y.values - mu) ** 2 - y.values) / mu
        alpha = float(np.sum(aux * mu) / np.sum(mu ** 2))
        if not (np.isfinite(alpha) and alpha > 1e-3):
            alpha, family = 0.0, "poisson"
            params = m.params
        else:
            m2 = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
            params, family = m2.params, "nb2"
    except Exception as e:
        return dict(n=len(te), brier=None, ece=None, log_loss=None, note=f"적합실패:{e}")

    Xte = np.column_stack([np.ones(len(te)), te[feats].astype(float).values])
    lam = np.exp(np.clip(Xte @ np.asarray(params, dtype=float), -20, 10))
    p = _p_ge(lam, alpha, family, burst_k)
    p = np.clip(p, 1e-6, 1 - 1e-6)
    yb = (te["y_next"].values >= burst_k).astype(float)
    brier = float(np.mean((p - yb) ** 2))
    e = ece(p, yb)
    ll = float(log_loss(yb, p)) if len(set(yb)) > 1 else None
    return dict(n=len(te), burst_k=burst_k, brier=round(brier, 4), ece=round(e, 4),
                log_loss=round(ll, 4) if ll is not None else None, note="")


def run():
    db = os.environ.get("MSR_DB", DB_PATH)
    feat = _features(_attach_geo_idx(_weekly_panel()))
    cov, pol = load_covariates(db)
    print(f"공변량: {len(cov):,}행, 정책이벤트 주간집계: {len(pol):,}행")
    merged = build_expanded_panel(feat, cov, pol)

    rows = []
    for c in TARGETS:
        g = merged[merged["commodity"] == c].sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        n_cov_missing = int(train[["price_z52", "import_hhi"]].isna().any(axis=1).sum())
        print(f"\n=== {c} === (train={len(train)}, test={len(test)}, 공변량결측 학습행={n_cov_missing})")
        base = evaluate(train, test, BASE_FEATS)
        ext = evaluate(train, test, EXT_FEATS)
        print(f"  기존({BASE_FEATS}): {base}")
        print(f"  확장({EXT_FEATS}): {ext}")
        rows.append(dict(commodity=c, variant="기존(x_ewma,x_geo,x_vol)", **base))
        rows.append(dict(commodity=c, variant="확장(+price_z52,import_hhi,n_policy)", **ext))

    res = pd.DataFrame(rows)
    write_report(res)


def write_report(res: pd.DataFrame):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "li_co_covariate_expansion.md")
    L = []
    L.append("# LI/CO 부진 원인분석 — 공변량 확장 시험 (C-4)\n")
    L.append("작성: 2026-07-16 · C-1에서 NB2 target 개편이 LI에서 열세(-0.0103)·CO는 동률"
             "이었던 원인을 피처 부족 가설로 검증 — price_z52(가격)·import_hhi(수입편중)·"
             "n_policy(정책이벤트 주간건수, geo_event.dimension='policy') 3개 공변량을 "
             "prob_model.py의 x_ewma·x_geo·x_vol에 추가한 확장모델을 동일 평가(TRAIN_END 기준 "
             "검증분할, Brier/ECE/log_loss)로 비교. **spread_pct(가격변동성)는 원래 계획에 "
             "있었으나 실측 결과 CO·LI·REE에서 100% 결측(`mart_weekly_diagnosis`, CU·NI만 "
             "populated)임을 확인해 제외**했다 — 이 자체가 별도로 기록할 데이터 공백.\n")

    L.append("\n## 기존 vs 확장 비교\n")
    L.append("| 광종 | 버전 | n | Brier | ECE | log_loss | 비고 |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in res.iterrows():
        b = "—" if r["brier"] is None else f"{r['brier']:.4f}"
        e = "—" if r["ece"] is None else f"{r['ece']:.4f}"
        ll = "—" if r["log_loss"] is None else f"{r['log_loss']:.4f}"
        L.append(f"| {r['commodity']} | {r['variant']} | {int(r['n'])} | {b} | {e} | {ll} | {r['note']} |")

    L.append("\n## 광종별 판정\n")
    for c in res["commodity"].unique():
        sub = res[res["commodity"] == c]
        base = sub[sub["variant"].str.startswith("기존")].iloc[0]
        ext = sub[sub["variant"].str.startswith("확장")].iloc[0]
        if base["brier"] is None or ext["brier"] is None:
            L.append(f"- **{c}**: 적합 실패 또는 표본 부족으로 비교 불가({base['note']}/{ext['note']}).\n")
            continue
        d = ext["brier"] - base["brier"]
        d_ece = ext["ece"] - base["ece"]
        verdict = "확장모델이 개선(공변량 부족이 원인이었을 가능성)" if d < -0.01 else \
                  ("확장모델이 악화(공변량 추가가 오히려 과적합/잡음 유입)" if d > 0.01 else "차이 미미(공변량 부족이 주원인은 아님)")
        ece_note = f", 단 ECE는 {base['ece']:.4f}→{ext['ece']:.4f}(Δ{d_ece:+.4f})로 {'함께 개선' if d_ece < 0 else '오히려 악화(Brier와 상반) — 확률 자체는 더 정확해졌지만 보정(calibration)은 나빠졌을 수 있어 운용 전 재검토 필요'}" if abs(d_ece) > 0.01 else ""
        L.append(f"- **{c}**: Brier {base['brier']:.4f}→{ext['brier']:.4f}(Δ{d:+.4f}) — {verdict}{ece_note}\n")

    L.append("\n## 한계\n")
    L.append("검증분할이 C-6·D-1과 달리 TRAIN_END 기준 단순 1회 분할(60/40 재분할 없음) — LI/CO "
             "테스트 표본이 원래도 적어(주간 데이터) 재분할 시 표본이 더 줄어드는 것을 피하기 "
             "위함. n_policy는 dimension='policy'로 분류된 이벤트의 단순 주간 카운트로, 심각도"
             "·방향은 반영하지 않은 최소 피처 — 개선이 없다고 확인돼도 정책이벤트를 더 정교하게"
             "(severity 가중 등) 반영하면 다른 결과가 나올 가능성은 남는다.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[li_co_covariate_expansion] 리포트 → {path}")


if __name__ == "__main__":
    run()
