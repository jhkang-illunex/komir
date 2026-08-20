# -*- coding: utf-8 -*-
"""모델 재현 로직 — `dashboards/streamlit_app.py`의 `load_geo`/`load_diagnosis_level`/
`load_diagnosis_alert`/`load_delta_ew`/`load_forecast`를 그대로 이식(재구현 금지,
CONTAINER_ARCHITECTURE.md §1·§8 3단계).

Streamlit 전용 부분(st.cache_data, plotly 차트, 화면 배치)만 제거하고, DataFrame/dict를
그대로 돌려주는 순수 함수로 옮겼다. 캐시는 `deps.cached()`가 대신한다(동일하게 DB
mtime을 키로 씀). 원본과 마찬가지로 **읽기 전용** — 모든 DB 접근은 `_read()`(→
`shared.db.read_sql(..., target=DB_PATH)`, SELECT만) 또는 각 msr 모듈의 read-only
재적합 함수이고, 운영 발행 테이블(out_*, mart_diagnosis_nowcast 등)에 쓰지 않는다.
`shared.db.read_sql_msr()`(→ `Settings.MSR_DB`)는 일부러 안 쓴다 — `MSR_DB` env가
비어있을 때 `Settings.MSR_DB`와 `msr.config.DB_PATH`의 기본값이 서로 달라 조회와
재적합이 다른 파일을 읽는 조용한 불일치가 생길 수 있어서다(2026-08-19).

⚠ 프로덕션과 남은 차이는 원본 docstring과 동일(direct 방식 고정, ALERT_OVERRIDE_GEO
기본값 off) — 자세한 사유는 `dashboards/streamlit_app.py` 모듈 docstring 참고."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from . import _bootstrap  # noqa: F401 — sys.path 부트스트랩

from shared.db import read_sql  # noqa: E402

from msr.config import DB_PATH  # noqa: E402


def _read(query: str) -> pd.DataFrame:
    """`read_sql_msr()`(→ `Settings.MSR_DB`)를 쓰지 않고 `DB_PATH`(msr.config, 이 모듈의
    재적합 함수들이 실제로 읽는 대상)를 명시적으로 겨냥한다 — `MSR_DB` env가 비어있는
    경우 두 설정 로더의 기본값이 서로 달라(`Settings.MSR_DB`는
    `data_lake/db/minerals.duckdb`, `msr.config.DB_PATH`는
    `mineral_supply_risk/data/processed/minerals.duckdb`) 조회와 재적합이 서로 다른
    파일을 읽는 조용한 불일치를 막기 위함(2026-08-19, 코드리뷰 지적)."""

    return read_sql(query, target=DB_PATH)
from msr.models.diagnosis_opt import (  # noqa: E402
    BASE_FEATS,
    GEO_DERIVED,
    build_panel as build_panel_level,
)
from msr.models.nowcast import LEVELS, _fit_full, _stage_of, _stage_probs  # noqa: E402
from msr.models.alert import _build_evidence_json, _build_reasons, compute_alerts  # noqa: E402
from msr.models.forecast_unit import (  # noqa: E402
    _build_explanations,
    _conformal_q,
    _direct_forecast,
    _mc_value_interval,
    build_panel as build_panel_fc,
)
from scripts.diagnosis_retrain_answer import (  # noqa: E402
    GEO_ONLY_NO_LAG,
    build_panel as build_panel_delta,
)
from scripts.diagnosis_ylag_deep_review import add_dynamics, pooled_design  # noqa: E402
from scripts.diagnosis_aux_features_eval import INV_F, build_aux  # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch  # noqa: E402
from scripts.diagnosis_priority_feeds_eval import PMI_F, build_pmi  # noqa: E402
from scripts.diag_refine1 import build_refined  # noqa: E402
from scripts.aux_early_warning import CLI_F, GRADE_KO, build_cli  # noqa: E402
from sklearn.ensemble import BaggingClassifier  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

BACKTEST_SNAPSHOT_PATH = str(
    _bootstrap.MSR_ENGINE_ROOT.parent / "dashboards" / "forecast_backtest_snapshot.json"
)


def load_backtest_snapshot() -> dict | None:
    if not os.path.exists(BACKTEST_SNAPSHOT_PATH):
        return None
    with open(BACKTEST_SNAPSHOT_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────── ① 지정학 위기지수 ───────────────────────────
def load_geo() -> tuple[pd.DataFrame, pd.DataFrame]:
    idx_w = _read(
        """SELECT commodity_code, CAST(period AS DATE) AS week,
        CAST(idx_value AS DOUBLE PRECISION) idx_value, n_events
        FROM geo_index WHERE freq='W' ORDER BY 1,2"""
    )
    prob = _read(
        """SELECT commodity_code, period, p_burst_next,
        p_severe_next, p_burst_adapt, lambda_next, family
        FROM geo_prob ORDER BY 1,2"""
    )
    idx_w["week"] = pd.to_datetime(idx_w["week"])
    return idx_w, prob


# ─────────────────────────── ② 수급위기 진단 ───────────────────────────
def load_diagnosis_level() -> tuple[pd.DataFrame, list[str]]:
    df = build_panel_level(DB_PATH)
    feats = [
        f for f in BASE_FEATS + GEO_DERIVED
        if df[f].notna().sum() > 50 and df[f].nunique() > 2
    ]
    m, prep, cc_cols, sigma, cuts = _fit_full(df, feats)
    med = pd.Series(prep["median"]); mu = pd.Series(prep["mu"]); sd = pd.Series(prep["sd"])
    Z = (df[feats].fillna(med) - mu) / sd
    D = pd.get_dummies(df["commodity_code"], prefix="cc")
    for c in cc_cols:
        if c not in D:
            D[c] = 0
    X = np.column_stack([Z.values, D[cc_cols].astype(float).values])
    y_pred = m.predict(X)
    ci_pred = 100 - y_pred
    coef_f = m.coef_[: len(feats)]
    contrib = -(Z.values * coef_f)

    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        cc = r["commodity_code"]
        cd = {feats[j]: round(float(contrib[i, j]), 3) for j in range(len(feats))}
        probs = _stage_probs(float(ci_pred[i]), sigma.get(cc), cuts[cc])
        stage = _stage_of(float(ci_pred[i]), cuts[cc])
        rows.append(dict(
            commodity_code=cc, month=r["month"],
            ci_pred=round(float(ci_pred[i]), 2),
            ci_teacher=round(float(r["crisis_index"]), 2) if pd.notna(r["crisis_index"]) else None,
            stage=stage, stage_name=LEVELS[stage],
            probs=probs, contrib=cd,
        ))
    return pd.DataFrame(rows), feats


def load_diagnosis_alert(lvl: pd.DataFrame | None = None) -> pd.DataFrame:
    """`msr.models.alert`의 compute_alerts/_build_reasons/_build_evidence_json을
    그대로 재사용 — (A) 위기지수 분위수 기본단계 (B) 규칙 오버라이드(변동성·HHI)
    (C) 2주 히스테리시스까지 챔피언과 동일 로직. run()과 달리 DB에 쓰지 않는다.

    `lvl`(load_diagnosis_level()의 첫 반환값)을 이미 갖고 있으면 넘겨서 Ridge
    재적합 중복을 피한다 — 호출자가 없으면 직접 계산(단독 호출도 가능하게 유지)."""

    if lvl is None:
        lvl, _ = load_diagnosis_level()
    nc = lvl[["commodity_code", "month", "ci_pred", "probs", "contrib"]].rename(
        columns={"ci_pred": "ci_model"})
    nc["stage_probs"] = nc["probs"].apply(lambda d: json.dumps(d, ensure_ascii=False))
    nc["contrib_json"] = nc["contrib"].apply(lambda d: json.dumps(d, ensure_ascii=False))
    nc = nc.drop(columns=["probs", "contrib"]).rename(columns={"contrib_json": "contrib"})

    df = _read(
        """SELECT commodity_code, obs_date, teacher_supply_demand,
        volatility_12w, import_hhi FROM mart_weekly_diagnosis
        WHERE obs_date >= '2020-01-01' AND teacher_supply_demand IS NOT NULL"""
    )
    geo_df = _read(
        """SELECT commodity_code, obs_date, event_type, country,
        severity, evidence_quote FROM geo_event
        WHERE commodity_code IS NOT NULL AND direction = 'supply_down'
          AND source IN ('US_FederalRegister','CN_MOFCOM','WoodMac','IEA','KOMIS',
                         'Argus','PPS','AsianMetal','EU_SCRREEN')"""
    )

    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["month"] = df["obs_date"].values.astype("datetime64[M]")
    df = df.merge(nc, on=["commodity_code", "month"], how="left").drop(columns=["month"])

    sev = {}
    if len(geo_df):
        g = geo_df.dropna(subset=["obs_date"]).copy()
        g["m"] = pd.to_datetime(g["obs_date"]).values.astype("datetime64[M]")
        gs = g.groupby(["commodity_code", "m"])["severity"].max()
        gsmap = {(cc, pd.Timestamp(m)): float(s) / 3.0 for (cc, m), s in gs.items()}
        sev = {(cc, d): gsmap.get((cc, pd.Timestamp(d).replace(day=1)))
               for cc, d in zip(df.commodity_code, df.obs_date)}

    res = compute_alerts(df, sev)
    res["reason"] = _build_reasons(res, geo_df)
    res["evidence_json"] = _build_evidence_json(res, geo_df)
    return res


def load_delta_ew() -> tuple[pd.DataFrame, dict]:
    """보조 신호 — Δ 조기경보 앙상블(Bagging25×2 + OECD 한국 CLI). 운영 등급예측과
    별개의 병기 신호(경보 등급을 바꾸지 않음, hard 결합은 과거 백테스트로 기각된
    이력 — CLAUDE.md/메모리 `feedback-revision-plan-execution` 참고)."""

    db = DB_PATH
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel_delta(db)
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_pmi(db, df)
    df = build_refined(db, df)
    df = build_cli(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    nolag_sub = [("gsev_z13" if f == "p_burst" else f) for f in nolag]
    feats_a = nolag + INV_F + exch.CNINV_F + PMI_F + CLI_F
    feats_b = nolag_sub + INV_F + exch.CNINV_F + PMI_F + CLI_F

    last = df["obs_date"].max()
    tr = df.copy()
    te = df[df["obs_date"] == last].copy()
    dtr = np.clip(tr["grade_ord"].values - tr["grade_lag1"].round().values,
                  -1, 1).astype(int)

    probs_list, classes = [], None
    global_imp = {}
    for tag, feats in (("A(p_burst)", feats_a), ("B(gsev_z13)", feats_b)):
        Xtr, Xte = pooled_design(tr, te, feats)
        mdl = BaggingClassifier(
            LogisticRegression(max_iter=2000, class_weight="balanced"),
            n_estimators=25, random_state=0, n_jobs=-1)
        mdl.fit(Xtr, dtr)
        probs_list.append(mdl.predict_proba(Xte))
        classes = list(mdl.classes_)
        coef_abs = np.mean([np.abs(e.coef_) for e in mdl.estimators_], axis=0)
        tr2 = pd.get_dummies(tr, columns=["commodity_code"], prefix="cc")
        cc_cols = [c for c in tr2.columns if c.startswith("cc_")]
        feat_names = feats + cc_cols
        rank = sorted(zip(feat_names, coef_abs.mean(axis=0)), key=lambda kv: -kv[1])[:6]
        global_imp[tag] = rank

    P = np.mean(probs_list, axis=0)
    dhat = np.array(classes)[P.argmax(axis=1)].astype(int)

    def pcol(cls):
        return P[:, classes.index(cls)] if cls in classes else np.zeros(len(te))

    out = pd.DataFrame({
        "commodity_code": te["commodity_code"].values,
        "obs_date": pd.Timestamp(last).date(),
        "delta_pred": dhat,
        "direction": [GRADE_KO[int(v)] for v in dhat],
        "trigger": (dhat != 0),
        "p_down": np.round(pcol(-1), 3),
        "p_stay": np.round(pcol(0), 3),
        "p_up": np.round(pcol(1), 3),
    })
    return out, global_imp


# ─────────────────────────── ③ 12개월 수요량·단가 예측 ───────────────────────────
def load_forecast() -> tuple[pd.DataFrame, pd.Timestamp, float, float]:
    db = DB_PATH
    df = build_panel_fc(db)
    last_m = df["month"].max()

    cal_pub = tuple(str((last_m - pd.DateOffset(months=m_)).date())
                    for m_ in (24, 18, 12))
    qt_pub = _conformal_q(df, "ton", cal_pub)
    qu_pub = _conformal_q(df, "unit", cal_pub)

    fd_ton, models_ton = _direct_forecast(df, "ton", last_m, horizon=12,
                                          with_quantiles=True, return_models=True)
    fd_unit, models_unit = _direct_forecast(df, "unit", last_m, horizon=12,
                                            with_quantiles=True, return_models=True)
    fd_ton = fd_ton.rename(columns={"pred": "pred_ton", "q10": "ton_lo", "q90": "ton_hi"})
    fd_unit = fd_unit.rename(columns={"pred": "pred_unit_usd_per_ton",
                                      "q10": "unit_lo", "q90": "unit_hi"})
    out = fd_ton.merge(fd_unit, on=["commodity_code", "month", "h"])
    out["ton_lo"] *= np.exp(-qt_pub); out["ton_hi"] *= np.exp(qt_pub)
    out["unit_lo"] *= np.exp(-qu_pub); out["unit_hi"] *= np.exp(qu_pub)
    out["pred_value_usd"] = out["pred_ton"] * out["pred_unit_usd_per_ton"]
    vint = out.apply(lambda r: _mc_value_interval(
        (r["ton_lo"], r["pred_ton"], r["ton_hi"]),
        (r["unit_lo"], r["pred_unit_usd_per_ton"], r["unit_hi"])), axis=1)
    out[["pred_value_lo", "pred_value_mid", "pred_value_hi"]] = \
        pd.DataFrame(vint.tolist(), index=out.index)
    out = out.rename(columns={"month": "target_month"})

    expl_ton = ("direct", models_ton)
    expl_unit = ("direct", models_unit)
    reasons, explains = _build_explanations(out, expl_ton, expl_unit)
    out["reason"] = reasons
    out["explain_json"] = explains
    return out, last_m, qt_pub, qu_pub
