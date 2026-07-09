# -*- coding: utf-8 -*-
"""[3-부속] 지수 확률화 — 음이항(NB2) 강도 모델 (v1 문서 §6-3).

geo_idx(점수)를 "다음 주 심각(sev≥2) 이벤트 발생확률"로 번역한다.
  y[m,w+1] ~ NB2(λ[m,w], α)
  λ[m,w]   = exp(β₀ + β₁·EWMA(심각수, hl=4주) + β₂·geo_idx + β₃·log1p(주간 전체 이벤트수))
  발행값    = P(y≥1) = 1 − (1+α·λ)^(−1/α)

왜 순수 포아송이 아닌가: 실측(2026-07-09, 2016~ 주간) 분산/평균이 전체 이벤트 4~7배·심각
이벤트 3~4배 — 지정학 이벤트는 군집 발생(위기가 위기를, 보도가 보도를 부름)하므로 등산포
가정이 크게 깨진다. 강도가 상태에 따라 변하는 Cox process의 정상형인 NB2(포아송-감마 혼합)
를 쓰고, 그래도 α 추정이 실패하면 포아송으로 폴백한다.

β₃는 코퍼스 구성 변화(예: Argus 일일보고서는 2023+에만 존재) 때문에 생기는 보도량 비정상성
통제 — v1 문서 §5-2 media_base 정규화의 근사. GKG 재검증 병합처럼 코퍼스가 크게 바뀌면
재적합해야 한다.

CLI:  python -m geo prob            # 적합+검증+발행(store/geo_prob.parquet)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C, store

SEVERE_MIN = 2.0          # "심각" 임계(sev>=2 — 붙임2 계열 트리거와 동일 눈금)
EWMA_HALFLIFE = 4         # v0 문서 §1.2의 EWMA 반감기(주)
TRAIN_END = "2023-12-31"  # 시계열 분할(검증 리포트용) — 최종 발행 모델은 전 기간 재적합

GEO_PROB = C.STORE / "geo_prob.parquet"


def _weekly_panel() -> pd.DataFrame:
    """이벤트 → 광종별 주간 패널(빈 주 0 채움). 컬럼: n_severe, n_all, n_total_week."""
    ev = store.load_events()
    ev = ev.copy()
    ev["date"] = pd.to_datetime(ev["obs_date"], errors="coerce")
    ev = ev.dropna(subset=["date"])
    # 미래 obs_date 방어(extract.py에서 근본 교정 — 여기는 최후 방어선): 전망 시점이
    # 사건일로 남아 있으면 패널 그리드가 미래로 늘어나 가짜 0 주가 검증을 오염시킨다.
    ev = ev[(ev["date"] >= "2016-01-01") & (ev["date"] <= pd.Timestamp.now())]
    if len(ev) == 0:
        raise RuntimeError("이벤트 없음(2016+)")

    grid = pd.date_range(ev["date"].min(), ev["date"].max(), freq="W")
    total = ev.set_index("date").resample("W").size().reindex(grid, fill_value=0)

    rows = []
    for c, sub in ev.groupby("commodity"):
        s = sub.set_index("date")
        n_all = s.resample("W").size().reindex(grid, fill_value=0)
        n_sev = (s[s["severity"] >= SEVERE_MIN].resample("W").size()
                 .reindex(grid, fill_value=0))
        df = pd.DataFrame({"commodity": c, "week": grid,
                           "n_severe": n_sev.values, "n_all": n_all.values,
                           "n_total_week": total.values})
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


def _attach_geo_idx(panel: pd.DataFrame) -> pd.DataFrame:
    """store의 주간 geo_idx를 주 라벨 기준 결합. 미발행 주(이벤트 0)는 중립 50."""
    idx = store._read(C.INDEX)
    if len(idx) == 0:
        panel["geo_idx"] = 50.0
        return panel
    w = idx[idx["freq"] == "W"].copy()
    w["week"] = pd.to_datetime(w["period"])
    panel = panel.merge(w[["commodity", "week", "index"]].rename(columns={"index": "geo_idx"}),
                        on=["commodity", "week"], how="left")
    panel["geo_idx"] = panel["geo_idx"].astype(float).fillna(50.0)
    return panel


def _features(panel: pd.DataFrame) -> pd.DataFrame:
    """인과적 피처(주 w 정보만) + 타깃(주 w+1 심각수). 마지막 주는 타깃 없음(예측 전용)."""
    out = []
    for c, g in panel.groupby("commodity"):
        g = g.sort_values("week").copy()
        g["x_ewma"] = g["n_severe"].ewm(halflife=EWMA_HALFLIFE).mean()
        g["x_geo"] = g["geo_idx"]
        g["x_vol"] = np.log1p(g["n_total_week"])
        g["y_next"] = g["n_severe"].shift(-1)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def _fit_one(train: pd.DataFrame):
    """NB2 적합, 실패 시 포아송 폴백. 반환 (params, alpha, family)."""
    import statsmodels.api as sm
    X = sm.add_constant(train[["x_ewma", "x_geo", "x_vol"]].astype(float))
    y = train["y_next"].astype(float)
    try:
        from statsmodels.discrete.count_model import NegativeBinomialP
        m = NegativeBinomialP(y, X, p=2).fit(disp=0, maxiter=200)
        if not np.isfinite(m.params).all():
            raise RuntimeError("params non-finite")
        alpha = float(m.params.iloc[-1])
        if alpha <= 1e-6:
            raise RuntimeError("alpha~0 — 포아송으로 충분")
        return m.params.iloc[:-1], alpha, "nb2"
    except Exception:
        m = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        return m.params, 0.0, "poisson"


def _predict(params, alpha: float, family: str, df: pd.DataFrame) -> tuple:
    X = np.column_stack([np.ones(len(df)),
                         df[["x_ewma", "x_geo", "x_vol"]].astype(float).values])
    lam = np.exp(np.clip(X @ np.asarray(params, dtype=float), -20, 10))
    if family == "nb2":
        p0 = (1.0 + alpha * lam) ** (-1.0 / alpha)
    else:
        p0 = np.exp(-lam)
    return lam, 1.0 - p0


def _calibration_report(test: pd.DataFrame, p: np.ndarray, train_rate: float) -> str:
    """예측확률 분위(5구간)별 실현빈도 + Brier(vs 상수강도 기준선).
    기준선은 '학습기간 기저율'을 상수로 예측하는 모델 — 테스트 실현율을 기준선으로 쓰면
    미래를 훔쳐본 오라클이라 불공정(2026-07-09 수정)."""
    t = test.copy()
    t["p"] = p
    t["hit"] = (t["y_next"] >= 1).astype(float)
    brier = float(((t["p"] - t["hit"]) ** 2).mean())
    base_rate = train_rate
    brier_base = float(((base_rate - t["hit"]) ** 2).mean())
    try:
        t["bin"] = pd.qcut(t["p"], 5, duplicates="drop")
        cal = t.groupby("bin", observed=True).agg(pred=("p", "mean"), real=("hit", "mean"),
                                                   n=("hit", "size"))
        cal_s = "\n".join(f"    예측 {r.pred:.2f} → 실현 {r.real:.2f} (n={r.n})"
                          for r in cal.itertuples())
    except ValueError:
        cal_s = "    (분위 구성 불가 — 표본 부족)"
    return (f"Brier {brier:.4f} vs 기준선(상수강도 {base_rate:.2f}) {brier_base:.4f} "
            f"{'✓개선' if brier < brier_base else '✗열세'}\n{cal_s}")


def run() -> pd.DataFrame:
    C.ensure_dirs()
    panel = _attach_geo_idx(_weekly_panel())
    feat = _features(panel)

    results, reports = [], []
    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        if len(train) < 52:
            print(f"  [prob] {c}: 학습표본 부족({len(train)}주) — 스킵"); continue

        # 1) 검증 리포트(시계열 분할)
        params, alpha, family = _fit_one(train)
        _, p_test = _predict(params, alpha, family, test)
        train_rate = float((train["y_next"] >= 1).mean())
        reports.append(f"[{c}] {family} (α={alpha:.3f}) train {len(train)}주 / test {len(test)}주\n"
                       f"  {_calibration_report(test, p_test, train_rate)}")

        # 2) 발행 모델(전 기간 재적합) — 전 주차 확률 산출
        params_f, alpha_f, family_f = _fit_one(hist)
        lam, p1 = _predict(params_f, alpha_f, family_f, g)
        out = g[["commodity", "week"]].copy()
        out["lambda_next"] = lam
        out["p_severe_next"] = p1
        out["family"] = family_f
        out["alpha_disp"] = alpha_f
        results.append(out)

    print("\n=== 캘리브레이션 검증(train ~2023 / test 2024+) ===")
    for r in reports:
        print(r)

    res = pd.concat(results, ignore_index=True)
    res["week"] = res["week"].dt.strftime("%Y-%m-%d")
    store._write(res, GEO_PROB)
    print(f"\n[prob] {len(res)}행 → {GEO_PROB}")
    latest = res.sort_values("week").groupby("commodity").tail(1)
    print("=== 최신 주 발행값: P(다음주 심각 이벤트 ≥1) ===")
    print(latest[["commodity", "week", "lambda_next", "p_severe_next"]].to_string(index=False))
    return res


if __name__ == "__main__":
    run()
