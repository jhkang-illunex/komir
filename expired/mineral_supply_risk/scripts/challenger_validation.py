# -*- coding: utf-8 -*-
"""3모듈 신챔피언(도전자) 통합 재현·검증 스크립트 (2026-07-25, /goal
"챔피언을 넘을 때까지 변형·탐색" 종결 산출물).

주말 탐색(R1~R3, WORKLOG 최신㉑)에서 확정된 세 모듈의 챔피언 초과 구성을
한 번에 재현한다. 공통 통찰: **원시 주간 신호의 시간 구조(누적 z·감쇠 가중·
월말 상태)가 기존의 압축·평균 방식을 이긴다**(MIDAS 관점의 승리).

  [진단 Δ조기경보] p_burst(NB2 확률) → gsev_z13(심각 이벤트 13주합의 52주 z) 대체
    QWK 0.8392→0.8609 (CI [+0.007,+0.038] P=0.997), 전환·FAR 비악화, 이웃 9설정
    중 7개 유의(나머지 2개 방향 양). 운영 레벨 모델은 무영향(y_lag1 지배).
  [예측 ton] BASE + MIDAS지수(주간 geo_index 지수감쇠 λ∈{0,0.2,0.6,1.5}, 창 13주)
    WAPE 0.287→0.273(6오리진)·0.296→0.289(18오리진), P=0.992 양쪽, 전 오리진 비악화.
  [예측 unit] BASE + U-MIDAS 가격·환율(월말 레벨 w0+13주 기울기 slope)
    WAPE 0.2005→0.1928(18오리진), CI [+0.001,+0.014] P=0.990.
  [지수 확률화·CO] NB2 base3 + x_z13(심각 13주합 z) 병행 — CO Brier 0.2053→0.1739
    (CI [+0.005,+0.064] P=0.992), 기존 약점(상수기준 0.1919 열세)도 해소.
    풀링은 0.1243→0.1191(전 9설정 일관, P=0.967)로 CO만 광종별 채택.

실행: MSR_DB=<warehouse> python -m scripts.challenger_validation
산출: outputs/model_opt/challenger_validation.md
"""
from __future__ import annotations
import os, sys, warnings

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from msr.config import OUT                                                # noqa: E402
import msr.models.forecast_unit as fu                                     # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import (                          # noqa: E402
    add_dynamics, e2_delta_classifier,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F          # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                      # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                       # noqa: E402
    build_pmi, PMI_F, bootstrap_diff,
)
from scripts.diag_refine1 import build_refined                            # noqa: E402
from scripts.midas_eval import build_midas_panel, LAMBDAS                 # noqa: E402
from scripts.forecast_alt_refit import direct_forecast_alt                # noqa: E402
from scripts.geo_prob_alt_refit import build_weekly_panel                 # noqa: E402
from geo.prob_model import _p_ge, EWMA_HALFLIFE, TRAIN_END                # noqa: E402

ORIG18 = [f"{y}-{m:02d}-01" for y in [2024, 2025] for m in range(1, 13)][:18]


def validate_diagnosis(db: str) -> list[str]:
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    df = add_dynamics(df); df = build_aux(db, df)
    df = exch.build_cninv(db, df); df = build_pmi(db, df)
    df = build_refined(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    nolag_sub = [("gsev_z13" if f == "p_burst" else f) for f in nolag]
    CHAMP = nolag + INV_F + exch.CNINV_F + PMI_F
    CAND = nolag_sub + INV_F + exch.CNINV_F + PMI_F
    r0 = e2_delta_classifier(df, CHAMP, "Logistic")
    r1 = e2_delta_classifier(df, CAND, "Logistic")
    b = bootstrap_diff(df, CHAMP, CAND, nolag, np.random.default_rng(0))
    lines = [
        f"구챔피언: QWK {r0['QWK']:.4f} chg {r0['chg_acc']:.4f} FAR {r0['FAR']:.4f}",
        f"신챔피언(p_burst→gsev_z13): QWK {r1['QWK']:.4f} chg {r1['chg_acc']:.4f} "
        f"FAR {r1['FAR']:.4f}",
        f"부트스트랩: QWK CI [{b['qwk_ci'][0]:+.4f},{b['qwk_ci'][1]:+.4f}] "
        f"P={b['qwk_p']:.3f} | chg P={b['chg_p']:.3f} | 비전환오류 "
        f"{b['steady_err'][0]}→{b['steady_err'][1]}",
    ]
    return lines


def _wape_boot(fdf, target, base, cand, origins, seed=0):
    def preds(fs):
        ps = [direct_forecast_alt(fdf, target, pd.Timestamp(o), fs, "HistGBM")
              for o in origins]
        p = pd.concat(ps, ignore_index=True)
        act = fdf.set_index(["commodity_code", "month"])[target]
        p["actual"] = [act.get((c, m), np.nan)
                       for c, m in zip(p["commodity_code"], p["month"])]
        return p.dropna(subset=["actual"])
    pb, pv = preds(base), preds(cand)
    j = pb.merge(pv, on=["commodity_code", "month", "h"], suffixes=("_b", "_v"))
    eb = (j["pred_b"] - j["actual_b"]).abs().values
    ev = (j["pred_v"] - j["actual_v"]).abs().values
    a = j["actual_b"].abs().values
    rng = np.random.default_rng(seed)
    n = len(j)
    d = np.array([(eb[i].sum() - ev[i].sum()) / a[i].sum()
                  for i in (rng.integers(0, n, n) for _ in range(4000))])
    return (eb.sum() / a.sum(), ev.sum() / a.sum(),
            np.percentile(d, 2.5), np.percentile(d, 97.5), float((d > 0).mean()), n)


def validate_forecast(db: str) -> list[str]:
    fdf = fu.build_panel(db)
    fdf, _ = build_midas_panel(db, fdf)
    base = list(fu.FEATS)
    ton_cand = base + [f"wgeo_{t}" for t in LAMBDAS]
    unit_cand = base + ["wpx_w0", "wpx_slope", "wfx_w0", "wfx_slope"]
    lines = []
    for target, cand, name in [("ton", ton_cand, "ton +MIDAS지수"),
                               ("unit", unit_cand, "unit +U-MIDAS(wpx/wfx)")]:
        wb, wv, lo, hi, p, n = _wape_boot(fdf, target, base, cand, ORIG18)
        lines.append(f"{name} [18오리진]: WAPE {wb:.4f}→{wv:.4f} | "
                     f"ΔCI [{lo:+.4f},{hi:+.4f}] P(개선)={p:.3f} (n={n})")
    return lines


def _nb2_p(train, test, cols, burst_k):
    tr = train.dropna(subset=cols)
    X = sm.add_constant(tr[cols].astype(float))
    y = tr["y_next"].astype(float)
    try:
        from statsmodels.discrete.count_model import NegativeBinomialP
        m = NegativeBinomialP(y, X, p=2).fit(disp=0, maxiter=200)
        ok = np.isfinite(m.params).all() and m.mle_retvals.get("converged", False)
        alpha = float(m.params.iloc[-1])
        if not ok or alpha <= 1e-6:
            raise RuntimeError()
        params = m.params.iloc[:-1]; fam = "nb2"
    except Exception:
        pois = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        mu = np.clip(pois.fittedvalues.values, 1e-9, None)
        aux = ((y.values - mu) ** 2 - y.values) / mu
        alpha = float(np.sum(aux * mu) / np.sum(mu ** 2))
        if np.isfinite(alpha) and alpha > 1e-3:
            m = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
            params = m.params; fam = "nb2"
        else:
            params = pois.params; alpha = 0.0; fam = "poisson"
    Xt = np.column_stack([np.ones(len(test))]
                         + [test[c].astype(float).fillna(0).values for c in cols])
    lam = np.exp(np.clip(Xt @ np.asarray(params, dtype=float), -30, 30))
    return _p_ge(lam, alpha, fam, burst_k)


def validate_geo(db: str) -> list[str]:
    panel = build_weekly_panel(db)
    out = []
    for c, g in panel.groupby("commodity"):
        g = g.sort_values("week").copy()
        g["x_ewma"] = g["n_severe"].ewm(halflife=EWMA_HALFLIFE).mean()
        g["x_geo"] = g["geo_idx"]
        g["x_vol"] = np.log1p(g["n_total_week"])
        s = g["n_severe"].rolling(13).sum()
        g["x_z13"] = (s - s.rolling(52, min_periods=20).mean()) \
            / s.rolling(52, min_periods=20).std().replace(0, np.nan)
        g["y_next"] = g["n_severe"].shift(-1)
        out.append(g)
    feat = pd.concat(out, ignore_index=True)
    lines = []
    pool_c, pool_v, pool_n = 0.0, 0.0, 0
    rng = np.random.default_rng(0)
    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        if len(train) < 52:
            continue
        bk = max(2, int(np.ceil(train["y_next"].quantile(0.90))))
        yte = (test["y_next"] >= bk).astype(int).values
        pc = _nb2_p(train, test, ["x_ewma", "x_geo", "x_vol"], bk)
        pv = _nb2_p(train, test, ["x_ewma", "x_geo", "x_z13", "x_vol"], bk)
        bc = float(((pc - yte) ** 2).mean()); bv = float(((pv - yte) ** 2).mean())
        pool_c += bc * len(yte); pool_v += bv * len(yte); pool_n += len(yte)
        if c == "CO":     # 광종별 채택 대상 — 블록 부트스트랩
            diff = (pc - yte) ** 2 - (pv - yte) ** 2
            n = len(diff); B = 8; boots = []
            for _ in range(4000):
                nb = int(np.ceil(n / B))
                starts = rng.integers(0, n, nb)
                sel = np.concatenate(
                    [diff[(np.arange(B) + st) % n] for st in starts])[:n]
                boots.append(sel.mean())
            boots = np.array(boots)
            base_rate = float((train["y_next"] >= bk).mean())
            bb = float(((base_rate - yte) ** 2).mean())
            lines.append(f"CO: Brier {bc:.4f}→{bv:.4f} (상수기준 {bb:.4f}) | "
                         f"ΔCI [{np.percentile(boots,2.5):+.5f},"
                         f"{np.percentile(boots,97.5):+.5f}] "
                         f"P(개선)={float((boots>0).mean()):.3f}")
    lines.append(f"풀링(참고): {pool_c/pool_n:.4f}→{pool_v/pool_n:.4f} "
                 f"(전 광종 병행 시 — 채택은 CO만)")
    return lines


def main():
    db = os.environ["MSR_DB"]
    sections = [("진단 Δ조기경보 — p_burst→gsev_z13 대체", validate_diagnosis(db)),
                ("예측 — ton +MIDAS지수 / unit +U-MIDAS(가격·환율)", validate_forecast(db)),
                ("지수 확률화 — CO NB2+x_z13 병행", validate_geo(db))]
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "challenger_validation.md")
    L = ["# 3모듈 신챔피언 통합 검증(2026-07-25)\n",
         "탐색 이력·이웃 강건성은 WORKLOG 최신㉑ 참조. 전부 CU SHFE 복구 상태·"
         "패널 종점 2026-06-08(발주처 컷).\n"]
    for title, lines in sections:
        print(f"\n== {title} ==")
        L.append(f"\n## {title}\n")
        for ln in lines:
            print(" ", ln)
            L.append(f"- {ln}")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"\n[challenger_validation] 리포트 → {path}")


if __name__ == "__main__":
    main()
