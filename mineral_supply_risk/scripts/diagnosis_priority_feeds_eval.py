# -*- coding: utf-8 -*-
"""1~4순위 신규 수집분 검정 — CU 2축재고·REE/CO 무역흐름·중국 PMI
(2026-07-24, collect_priority_feeds.py 후속. 프레임은 기존과 동일:
E2 Δ타깃 Logistic, 워크포워드 3폴드 풀링, as-of 가용시점 시프트, 부트스트랩).

검정축:
  (a) CU만(전환주 13건 — 단일 광종 중 최대 검정력): NOLAG / +LME재고 / +LME+SHFE
      — NI에서 유의 실증된 2축 패턴이 CU에서 재현되는가(본 시험대)
  (b) REE만·CO만(전환주 각 3건 — 방향 참고 전용): NOLAG / +무역흐름(trd)
  (c) 풀링(전환주 26건): 기존최적(NOLAG+LME재고) 대비 +CN재고(CU·NI)/+PMI/+trd/전부
가용시점: 재고 주간 +3일(스냅샷 당일 공개), 무역흐름 월간 +60일(중국 보고 지연),
PMI 월간 +35일(익월 초 발표).

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_priority_feeds_eval
산출: outputs/model_opt/diagnosis_priority_feeds_eval.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.override_backtest import qwk                                # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG, FOLDS  # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics, pooled_design  # noqa: E402
from scripts.diagnosis_aux_features_eval import (                        # noqa: E402
    build_aux, INV_F, _asof_join, e2_delta_classifier,
)
import scripts.diagnosis_exch_inventory_eval as exch                     # noqa: E402

TRD_F = ["trd_yoy", "trd_chg3", "trd_z24"]
PMI_F = ["pmi_off", "pmi_off_chg3", "pmi_cx"]
CNINV_F = exch.CNINV_F


def build_trd(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    """Comtrade 월간 물량(톤) → yoy·3개월 변화·24개월 z. REE=중국 수출, CO=중국←DRC 수입."""
    con = duckdb.connect(db, read_only=True)
    t = con.execute("""SELECT commodity_code, CAST(obs_date AS DATE) AS obs_date, val
        FROM fact_indicator WHERE src='UN_COMTRADE' AND indicator LIKE '%_WGT'
        ORDER BY commodity_code, obs_date""").df()
    con.close()
    t["obs_date"] = pd.to_datetime(t["obs_date"]).astype("datetime64[ns]")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")
    t = t.sort_values(["commodity_code", "obs_date"]).reset_index(drop=True)
    g = t.groupby("commodity_code")["val"]
    t["trd_yoy"] = g.transform(lambda s: s.pct_change(12))
    t["trd_chg3"] = g.transform(lambda s: s.pct_change(3))
    t["trd_z24"] = g.transform(
        lambda s: (s - s.rolling(24, min_periods=12).mean())
        / s.rolling(24, min_periods=12).std().replace(0, np.nan))
    t[TRD_F] = t[TRD_F].replace([np.inf, -np.inf], np.nan)
    t["avail_date"] = t["obs_date"] + pd.Timedelta(days=60)
    return _asof_join(panel, t, TRD_F, by_commodity=True)


def build_pmi(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    s = con.execute("""SELECT series_code, CAST(obs_date AS DATE) AS obs_date, val
        FROM fact_series WHERE src='AKSHARE_MACRO' ORDER BY series_code, obs_date""").df()
    con.close()
    s["obs_date"] = pd.to_datetime(s["obs_date"]).astype("datetime64[ns]")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")

    def series_frame(code: str, fn, name: str) -> pd.DataFrame:
        x = s[s["series_code"] == code].sort_values("obs_date").reset_index(drop=True)
        out = pd.DataFrame({"avail_date": x["obs_date"] + pd.Timedelta(days=35),
                            name: fn(pd.to_numeric(x["val"], errors="coerce"))})
        return out.dropna(subset=[name])

    panel = _asof_join(panel, series_frame("CN_PMI_OFF_M", lambda v: v, "pmi_off"),
                       ["pmi_off"], by_commodity=False)
    panel = _asof_join(panel, series_frame("CN_PMI_OFF_M", lambda v: v.diff(3), "pmi_off_chg3"),
                       ["pmi_off_chg3"], by_commodity=False)
    panel = _asof_join(panel, series_frame("CN_PMI_CX_M", lambda v: v, "pmi_cx"),
                       ["pmi_cx"], by_commodity=False)
    return panel


def bootstrap_diff(dfx, feats_a, feats_b, nolag, rng, n_iter=4000):
    """같은 패널에서 A(기준)·B(신규) 예측을 만들고 주 리샘플로 QWK·chg_acc 차이 CI."""
    def preds(feats):
        ys, lags, ps = [], [], []
        for t0, t1 in FOLDS:
            tr = dfx[dfx["obs_date"] < t0].copy()
            te = dfx[(dfx["obs_date"] >= t0) & (dfx["obs_date"] < t1)].copy()
            if len(te) == 0 or len(tr) < 60:
                continue
            dtr = np.clip(tr["grade_ord"].values - tr["grade_lag1"].round().values,
                          -1, 1).astype(int)
            Xtr, Xte = pooled_design(tr, te, feats)
            m = LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0)
            m.fit(Xtr, dtr)
            dh = m.predict(Xte).astype(int)
            lag = te["grade_lag1"].round().clip(0, 2).astype(int).values
            ys.append(te["grade_ord"].astype(int).values)
            lags.append(lag)
            ps.append(np.clip(lag + dh, 0, 2))
        return np.concatenate(ys), np.concatenate(lags), np.concatenate(ps)
    y, lag, pA = preds(feats_a)
    _, _, pB = preds(feats_b)
    chg = lag != y
    n = len(y)
    dq, dca = [], []
    idx_chg = np.where(chg)[0]
    for _ in range(n_iter):
        i = rng.integers(0, n, n)
        dq.append(qwk(y[i], pB[i], K=3) - qwk(y[i], pA[i], K=3))
        b = rng.choice(idx_chg, len(idx_chg), replace=True)
        dca.append((pB[b] == y[b]).mean() - (pA[b] == y[b]).mean())
    dq, dca = np.array(dq), np.array(dca)
    steady_err = (int(((pA != y) & ~chg).sum()), int(((pB != y) & ~chg).sum()))
    return dict(qwk_ci=(float(np.percentile(dq, 2.5)), float(np.percentile(dq, 97.5))),
                qwk_p=float((dq > 0).mean()),
                chg_ci=(float(np.percentile(dca, 2.5)), float(np.percentile(dca, 97.5))),
                chg_p=float((dca > 0).mean()), steady_err=steady_err)


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}   # CU 중국거래소 재고 축 활성화
    df = build_panel(db)
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_trd(db, df)
    df = build_pmi(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    for c in ["cninv_z52", "trd_yoy", "pmi_off"]:
        cov = df.groupby("commodity_code")[c].apply(lambda s: float(s.notna().mean()))
        print(f"{c} 광종별 커버리지: {cov.round(2).to_dict()}")

    results = []
    # (a) CU만
    df_cu = df[df["commodity_code"] == "CU"].reset_index(drop=True)
    for tag, feats in [("NOLAG", nolag), ("NOLAG+LME재고", nolag + INV_F),
                        ("NOLAG+LME+SHFE", nolag + INV_F + CNINV_F)]:
        results.append(dict(축="CU만", 구성=tag, **e2_delta_classifier(df_cu, feats, "Logistic")))
    # (b) REE만·CO만 — 방향 참고
    for cc in ["REE", "CO"]:
        d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
        for tag, feats in [("NOLAG", nolag), ("NOLAG+무역흐름", nolag + TRD_F)]:
            results.append(dict(축=f"{cc}만(참고)", 구성=tag,
                                **e2_delta_classifier(d1, feats, "Logistic")))
    # (c) 풀링
    base = nolag + INV_F
    for tag, feats in [("기존최적(NOLAG+LME재고)", base),
                        ("+CN재고(CU·NI)", base + CNINV_F),
                        ("+PMI", base + PMI_F),
                        ("+무역흐름(REE·CO)", base + TRD_F),
                        ("전부 결합", base + CNINV_F + PMI_F + TRD_F)]:
        results.append(dict(축="풀링", 구성=tag, **e2_delta_classifier(df, feats, "Logistic")))
    tab = pd.DataFrame(results)
    print(tab.round(4).to_string(index=False))

    # 부트스트랩 — CU 2축, 풀링 전부결합
    rng = np.random.default_rng(0)
    bs_cu = bootstrap_diff(df_cu, nolag + INV_F, nolag + INV_F + CNINV_F, nolag, rng)
    print(f"\nCU 2축(vs LME만): QWK차이 CI {bs_cu['qwk_ci']}, P={bs_cu['qwk_p']:.3f} | "
          f"chg차이 CI {bs_cu['chg_ci']}, P={bs_cu['chg_p']:.3f} | "
          f"비전환오류 {bs_cu['steady_err'][0]}→{bs_cu['steady_err'][1]}")
    bs_all = bootstrap_diff(df, base, base + CNINV_F + PMI_F + TRD_F, nolag, rng)
    print(f"풀링 전부결합(vs 기존최적): QWK차이 CI {bs_all['qwk_ci']}, P={bs_all['qwk_p']:.3f} | "
          f"chg차이 CI {bs_all['chg_ci']}, P={bs_all['chg_p']:.3f} | "
          f"비전환오류 {bs_all['steady_err'][0]}→{bs_all['steady_err'][1]}")

    write_report(tab, bs_cu, bs_all)


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def write_report(tab, bs_cu, bs_all):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_priority_feeds_eval.md")
    L = []
    L.append("# 1~4순위 신규 수집분 검정 — CU 2축재고·REE/CO 무역흐름·중국 PMI\n")
    L.append("작성: 2026-07-24 · collect_priority_feeds.py 적재분을 기존 프레임"
             "(E2 Δ타깃 Logistic·워크포워드 3폴드·as-of 시프트)으로 검정. "
             "COMEX 구리는 무료 경로 부재(akshare 금·은만)로 후순위 이관.\n")
    L.append("\n## 결과표\n")
    L.append("| 축 | 구성 | QWK | acc | chg_acc | up_acc | n_chg | FAR |")
    L.append("|---|---|---|---|---|---|---|---|")
    for _, r in tab.iterrows():
        L.append(f"| {r['축']} | {r['구성']} | {_fmt(r['QWK'])} | {_fmt(r['acc'])} | "
                 f"{_fmt(r['chg_acc'])} | {_fmt(r['up_acc'])} | {int(r['n_chg'])} | "
                 f"{_fmt(r['FAR'])} |")
    L.append("\n## 부트스트랩(4,000회)\n")
    L.append(f"- **CU 2축(LME+SHFE vs LME만)**: QWK차이 95% CI "
             f"[{bs_cu['qwk_ci'][0]:+.3f}, {bs_cu['qwk_ci'][1]:+.3f}] (P={bs_cu['qwk_p']:.3f}), "
             f"chg_acc차이 CI [{bs_cu['chg_ci'][0]:+.3f}, {bs_cu['chg_ci'][1]:+.3f}] "
             f"(P={bs_cu['chg_p']:.3f}), 비전환주 오류 {bs_cu['steady_err'][0]}→"
             f"{bs_cu['steady_err'][1]}건")
    L.append(f"- **풀링 전부결합(vs 기존최적)**: QWK차이 95% CI "
             f"[{bs_all['qwk_ci'][0]:+.3f}, {bs_all['qwk_ci'][1]:+.3f}] (P={bs_all['qwk_p']:.3f}), "
             f"chg_acc차이 CI [{bs_all['chg_ci'][0]:+.3f}, {bs_all['chg_ci'][1]:+.3f}] "
             f"(P={bs_all['chg_p']:.3f}), 비전환주 오류 {bs_all['steady_err'][0]}→"
             f"{bs_all['steady_err'][1]}건")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[priority_feeds_eval] 리포트 → {path}")


if __name__ == "__main__":
    main()
