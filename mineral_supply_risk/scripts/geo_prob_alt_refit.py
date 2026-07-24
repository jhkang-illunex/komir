# -*- coding: utf-8 -*-
"""지정학 지수 확률화(2-2 부속) 대안 재피팅 — NB2 강도모델 vs GBM 분류기 × 확장피처
(2026-07-25, 사용자 지시 "기존과 다른 방식으로 전부 재피팅").

현행 챔피언: NB2(음이항 회귀, 피처 3개 = 심각수 EWMA·geo_idx·log1p(주간 전체
이벤트)) → P(다음주 심각 이벤트 급증 ≥ burst_k). 대안:
  GBM-base : HistGradientBoostingClassifier, 동일 3피처 — 모델 계열 효과 분리
  GBM-full : + 이벤트 동역학(심각수 lag1·4주합·13주합·전체 EWMA·지수 4주변화)
             + 물리 피처(Tier1/2, as-of 지연 반영): SUP 공급흐름 yoy(+75일)·
             CNOI z52(+3일)·CLP 칠레생산 yoy(CU, +70일)·KIP 전방산업 yoy(+40일)·
             SEMI 반도체 yoy(CU/REE, +40일)·KINV 1차금속재고 z24(CU/NI, +40일)·
             COINV CO LME재고 z24(+210일)
  LOGIT-full: 위 full 피처의 로지스틱(선형 대조군)

패널·분할·타깃은 prob_model.py와 동일 재현(DB 발행본 geo_event/geo_index 사용):
주간 grid(2016+)·train ≤2023-12-31·burst_k=max(2, ceil(train P90))·Brier(vs 상수
강도 기준선)·AUC. NB2는 geo.prob_model._fit_one/_predict/_p_ge 실제 코드 재사용.

실행: MSR_DB=<warehouse> python -m scripts.geo_prob_alt_refit
산출: outputs/model_opt/geo_prob_alt_refit.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from msr.config import OUT                                    # noqa: E402
from geo.prob_model import (                                  # noqa: E402
    _fit_one, _predict, _p_ge, SEVERE_MIN, EWMA_HALFLIFE, TRAIN_END,
)

BASE_F = ["x_ewma", "x_geo", "x_vol"]
DYN_F = ["x_sev_lag1", "x_sev_sum4", "x_sev_sum13", "x_all_ewma", "x_geo_chg4"]
PHY_F = ["sup_yoy", "cnoi_z52", "clp_yoy", "kip_yoy", "semi_yoy", "kinv_z24",
         "coinv_z24"]
FULL_F = BASE_F + DYN_F + PHY_F

SUP_MAP = {"NI": "ID_NI_EXPORT_WGT", "LI": "AU_LI_EXPORT_WGT",
           "CU": "CL_CU_EXPORT_WGT", "REE": "CN_REE_IMPORT_MMR_WGT"}
CNOI_MAP = {"NI": "SHFE_NI_OI_W", "CU": "SHFE_CU_OI_W", "LI": "GFEX_LC_OI_W"}
KIP_MAP = {"CU": "KIP_ELEC_M", "NI": "KIP_METAL_M", "LI": "KIP_ELEQ_M",
           "CO": "KIP_ELEQ_M", "REE": "KIP_AUTO_M"}


def _z(s: pd.Series, w: int, mp: int) -> pd.Series:
    return (s - s.rolling(w, min_periods=mp).mean()) \
        / s.rolling(w, min_periods=mp).std().replace(0, np.nan)


def build_weekly_panel(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    ev = con.execute("""SELECT commodity_code AS commodity,
            CAST(obs_date AS DATE) AS date, severity FROM geo_event
        WHERE obs_date >= '2016-01-01'""").df()
    idx = con.execute("""SELECT commodity_code AS commodity,
            CAST(period AS DATE) AS week, CAST(idx_value AS DOUBLE) AS geo_idx
        FROM geo_index WHERE freq='W'""").df()
    con.close()
    ev["date"] = pd.to_datetime(ev["date"])
    ev = ev[ev["date"] <= pd.Timestamp.now()]
    grid = pd.date_range(ev["date"].min(), ev["date"].max(), freq="W")
    total = ev.set_index("date").resample("W").size().reindex(grid, fill_value=0)
    rows = []
    for c, sub in ev.groupby("commodity"):
        s = sub.set_index("date")
        n_all = s.resample("W").size().reindex(grid, fill_value=0)
        n_sev = (s[s["severity"] >= SEVERE_MIN].resample("W").size()
                 .reindex(grid, fill_value=0))
        rows.append(pd.DataFrame({"commodity": c, "week": grid,
                                  "n_severe": n_sev.values, "n_all": n_all.values,
                                  "n_total_week": total.values}))
    panel = pd.concat(rows, ignore_index=True)
    idx["week"] = pd.to_datetime(idx["week"])
    panel = panel.merge(idx, on=["commodity", "week"], how="left")
    panel["geo_idx"] = panel["geo_idx"].fillna(50.0)
    return panel


def add_features(panel: pd.DataFrame, db: str) -> pd.DataFrame:
    out = []
    for c, g in panel.groupby("commodity"):
        g = g.sort_values("week").copy()
        g["x_ewma"] = g["n_severe"].ewm(halflife=EWMA_HALFLIFE).mean()
        g["x_geo"] = g["geo_idx"]
        g["x_vol"] = np.log1p(g["n_total_week"])
        g["x_sev_lag1"] = g["n_severe"].shift(1)
        g["x_sev_sum4"] = g["n_severe"].rolling(4).sum()
        g["x_sev_sum13"] = g["n_severe"].rolling(13).sum()
        g["x_all_ewma"] = g["n_all"].ewm(halflife=EWMA_HALFLIFE).mean()
        g["x_geo_chg4"] = g["geo_idx"].diff(4)
        g["y_next"] = g["n_severe"].shift(-1)
        out.append(g)
    panel = pd.concat(out, ignore_index=True)

    # ── 물리 피처(as-of, 지연 실측 반영) ──
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT commodity_code, indicator,
            CAST(obs_date AS DATE) obs_date, CAST(val AS DOUBLE) val
        FROM fact_indicator WHERE indicator IN
            ('ID_NI_EXPORT_WGT','AU_LI_EXPORT_WGT','CL_CU_EXPORT_WGT',
             'CN_REE_IMPORT_MMR_WGT','CL_CU_PROD_MINE','CO_LME_STOCK_T')""").df()
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) obs_date,
            CAST(val AS DOUBLE) val FROM fact_series WHERE series_code IN
            ('SHFE_NI_OI_W','SHFE_CU_OI_W','GFEX_LC_OI_W','KIP_ELEC_M',
             'KIP_METAL_M','KIP_ELEQ_M','KIP_AUTO_M','WSTS_BILL_WW_M',
             'KINV_METAL_M')""").df()
    con.close()
    for d in (ind, ser):
        d["obs_date"] = pd.to_datetime(d["obs_date"])

    def asof_attach(panel, src_df, key_map, feat, fn, lag_days,
                    only_cc=None):
        frames = []
        for cc, code in key_map.items():
            x = src_df[src_df.iloc[:, 0] == code] if src_df.columns[0] == \
                "series_code" else src_df[(src_df["indicator"] == code)]
            x = x.sort_values("obs_date").copy()
            if len(x) == 0:
                continue
            x[feat] = fn(x["val"])
            x["avail"] = x["obs_date"] + pd.Timedelta(days=lag_days)
            x["commodity"] = cc
            frames.append(x[["commodity", "avail", feat]])
        if not frames:
            panel[feat] = np.nan
            return panel
        allx = pd.concat(frames).replace([np.inf, -np.inf], np.nan)
        outp = []
        for cc, g in panel.groupby("commodity"):
            g = g.sort_values("week")
            xx = allx[allx["commodity"] == cc].sort_values("avail")
            if len(xx) == 0:
                g[feat] = np.nan
            else:
                g = pd.merge_asof(g, xx[["avail", feat]], left_on="week",
                                  right_on="avail").drop(columns=["avail"])
            outp.append(g)
        return pd.concat(outp, ignore_index=True)

    panel = asof_attach(panel, ind, SUP_MAP, "sup_yoy",
                        lambda v: v.pct_change(12), 75)
    panel = asof_attach(panel, ser, CNOI_MAP, "cnoi_z52",
                        lambda v: _z(v, 52, 20), 3)
    panel = asof_attach(panel, ind, {"CU": "CL_CU_PROD_MINE"}, "clp_yoy",
                        lambda v: v.pct_change(12), 70)
    panel = asof_attach(panel, ser, KIP_MAP, "kip_yoy",
                        lambda v: v.pct_change(12), 40)
    panel = asof_attach(panel, ser, {"CU": "WSTS_BILL_WW_M",
                                     "REE": "WSTS_BILL_WW_M"}, "semi_yoy",
                        lambda v: v.pct_change(12), 40)
    panel = asof_attach(panel, ser, {"CU": "KINV_METAL_M", "NI": "KINV_METAL_M"},
                        "kinv_z24", lambda v: _z(v, 24, 12), 40)
    panel = asof_attach(panel, ind, {"CO": "CO_LME_STOCK_T"}, "coinv_z24",
                        lambda v: _z(v, 24, 12), 210)
    return panel


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def main():
    db = os.environ["MSR_DB"]
    panel = build_weekly_panel(db)
    feat = add_features(panel, db)
    rows = []
    for c, g in feat.groupby("commodity"):
        g = g.sort_values("week")
        hist = g.dropna(subset=["y_next"])
        train = hist[hist["week"] <= TRAIN_END]
        test = hist[hist["week"] > TRAIN_END]
        if len(train) < 52 or len(test) < 20:
            continue
        burst_k = max(2, int(np.ceil(train["y_next"].quantile(0.90))))
        ytr = (train["y_next"] >= burst_k).astype(int).values
        yte = (test["y_next"] >= burst_k).astype(int).values
        base_rate = float(ytr.mean())

        # 챔피언: NB2(실제 코드 재사용)
        params, alpha, family = _fit_one(train)
        lam_t, _ = _predict(params, alpha, family, test)
        p_nb2 = _p_ge(lam_t, alpha, family, burst_k)

        preds = {"NB2-base(챔피언)": p_nb2,
                 "상수강도(기준선)": np.full(len(yte), base_rate)}
        for name, feats, mk in [
            ("GBM-base", BASE_F, "hgb"), ("GBM-full", FULL_F, "hgb"),
            ("LOGIT-full", FULL_F, "logit"),
        ]:
            Xtr, Xte = train[feats].values, test[feats].values
            if mk == "hgb":
                m = HistGradientBoostingClassifier(
                    max_depth=3, learning_rate=0.05, max_iter=200, random_state=0)
                m.fit(Xtr, ytr)
            else:
                m = make_pipeline(SimpleImputer(strategy="median"),
                                  StandardScaler(),
                                  LogisticRegression(max_iter=2000, C=1.0))
                m.fit(Xtr, ytr)
            preds[name] = m.predict_proba(Xte)[:, 1] if len(np.unique(ytr)) > 1 \
                else np.full(len(yte), base_rate)

        for name, p in preds.items():
            auc = roc_auc_score(yte, p) if 0 < yte.mean() < 1 and \
                len(np.unique(p)) > 1 else np.nan
            rows.append(dict(commodity=c, model=name, burst_k=burst_k,
                             n_test=len(yte), test_rate=float(yte.mean()),
                             Brier=brier(p, yte), AUC=auc))
        got = {r_["model"]: r_["Brier"] for r_ in rows if r_["commodity"] == c}
        print(f"[{c}] burst_k={burst_k} test={len(yte)}주 rate={yte.mean():.2f} | "
              + " | ".join(f"{k} {v:.4f}" for k, v in got.items()))
    tab = pd.DataFrame(rows)

    # 풀링 Brier(광종 합산)
    pool = tab.groupby("model").apply(
        lambda x: np.average(x["Brier"], weights=x["n_test"])).round(4)
    print("\n풀링 Brier(가중):")
    print(pool.to_string())
    write_report(tab, pool)


def write_report(tab, pool):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "geo_prob_alt_refit.md")
    L = ["# 지정학 지수 확률화 대안 재피팅 — NB2 vs GBM/로지스틱 × 확장피처\n",
         "작성: 2026-07-25 · prob_model과 동일 패널·분할(train ≤2023-12-31 / "
         "test 2024+)·burst 타깃(주간 심각수 ≥ 학습 P90). Brier 낮을수록·AUC "
         "높을수록 좋음. 물리 피처는 as-of 지연 실측 반영.\n",
         "\n| 광종 | 모델 | burst_k | n_test | 실현율 | Brier | AUC |",
         "|---|---|---|---|---|---|---|"]
    for _, r in tab.iterrows():
        auc = "—" if pd.isna(r["AUC"]) else f"{r['AUC']:.3f}"
        L.append(f"| {r['commodity']} | {r['model']} | {int(r['burst_k'])} | "
                 f"{int(r['n_test'])} | {r['test_rate']:.2f} | {r['Brier']:.4f} "
                 f"| {auc} |")
    L.append("\n## 풀링 Brier(광종 n_test 가중)\n")
    for k, v in pool.items():
        L.append(f"- {k}: {v:.4f}")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[geo_prob_alt_refit] 리포트 → {path}")


if __name__ == "__main__":
    main()
