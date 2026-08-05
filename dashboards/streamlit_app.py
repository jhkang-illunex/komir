# -*- coding: utf-8 -*-
"""핵심광물 모델 체크 데모 (Streamlit) — 2026-08-05.

현재 확정 챔피언 3종을 DB에서 직접 재적합·예측해 보여주는 점검용 앱.
`out_diagnosis_alert`/`out_import_forecast_unit` 같은 발행 테이블을 읽지 않고
매번 그 자리에서 다시 학습·예측한다(운영 DB 갱신이 늦어도 최신 mart 데이터
기준 결과를 볼 수 있음, 08-05 조사에서 out_diagnosis_alert가 한 달 이상
정체돼 있던 걸 확인 — 그 문제를 피하기 위한 설계).

- 지정학 위기지수: geo_index/geo_prob 최신값 그대로 조회(연산 없음).
- 수급위기 진단: `msr.models.nowcast`의 Ridge(풀링+광종더미) 챔피언으로 전
  기간 재적합 → `msr.models.alert`의 규칙 오버라이드(변동성·HHI 분위)+2주
  히스테리시스까지 그대로 적용해 실제 발행 로직과 동일한 경보 단계를 표시,
  Ridge의 정확한 선형 기여도 분해를 설명으로 병기. 보조로 Δ 조기경보 앙상블
  (Bagging25×2+CLI, `scripts.aux_early_warning`)도 표시.
- 12개월 수요량·단가 예측: `msr.models.forecast_unit`의 ExtraTrees(direct
  다지평) 챔피언 + conformal 구간보정(`_conformal_q`, 보정 원점 24/18/12개월
  전 — 프로덕션 run()과 동일 절차)까지 재사용, SHAP 기반 설명 포함.

⚠ 읽기 전용 — 모든 DB 연결은 read_only=True(각 build_panel 함수 내부에서
보장). 운영 발행 테이블(out_*, mart_diagnosis_nowcast 등)은 건드리지 않는다
— 그건 각 모듈의 run()이 하는 일이고, 이 앱은 그 run()을 호출하지 않는다.

⚠ 프로덕션과 남은 차이(2026-08-05 사용자 요청으로 conformal·규칙엔진 반영
후 기준, 의도적 단순화):
  1) 재귀/direct 방식 자동선택은 생략, 현재 채택 방식인 "direct"로 고정
     (mart_forecast_method_log 최신 판정과 동일 — 프로덕션이 방식을 바꾸면
     이 앱은 자동 추종하지 않음, 수동 갱신 필요).
  2) 진단 경보의 지정학 severity 격상 오버라이드는 프로덕션 기본값(off,
     `ALERT_OVERRIDE_GEO`)을 그대로 따름 — 이미 폐지된 규칙이라 기본 동작과
     일치.
  그 외(conformal 구간보정, 규칙 오버라이드, 히스테리시스, 경보 사유문)는
  프로덕션 run()과 동일한 함수를 그대로 호출해 재현한다.

실행: MSR_DB=<warehouse> streamlit run dashboards/streamlit_app.py
"""
from __future__ import annotations

import json
import os
import sys

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

MSR_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mineral_supply_risk")
sys.path.insert(0, MSR_ROOT)

DEFAULT_DB = "/home/nuri/dev/git/ws/mine_ws/komir/warehouse/minerals.duckdb"
os.environ.setdefault("MSR_DB", DEFAULT_DB)

from msr.config import DB_PATH, CORE_COMMODITIES                          # noqa: E402
from msr.models.diagnosis_opt import (                                    # noqa: E402
    build_panel as build_panel_level, BASE_FEATS, GEO_DERIVED,
)
from msr.models.nowcast import _fit_full, _stage_probs, _stage_of, LEVELS  # noqa: E402
from msr.models.alert import compute_alerts, _build_reasons, _build_evidence_json  # noqa: E402
from msr.models.forecast_unit import (                                    # noqa: E402
    build_panel as build_panel_fc, _direct_forecast, _build_explanations,
    _mc_value_interval, _conformal_q,
)
from scripts.diagnosis_retrain_answer import (                            # noqa: E402
    build_panel as build_panel_delta, GEO_ONLY_NO_LAG,
)
from scripts.diagnosis_ylag_deep_review import add_dynamics, pooled_design  # noqa: E402
from scripts.diagnosis_aux_features_eval import build_aux, INV_F           # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                       # noqa: E402
from scripts.diagnosis_priority_feeds_eval import build_pmi, PMI_F         # noqa: E402
from scripts.diag_refine1 import build_refined                             # noqa: E402
from scripts.aux_early_warning import build_cli, CLI_F, GRADE_KO           # noqa: E402
from sklearn.ensemble import BaggingClassifier                             # noqa: E402
from sklearn.linear_model import LogisticRegression                        # noqa: E402

CCS = ["CU", "NI", "CO", "LI", "REE"]
CC_KO = {cc: f"{CORE_COMMODITIES[cc]['ko']}({cc})" for cc in CCS}
STAGE_COLOR = {"정상": "#2e7d32", "관심": "#9e9d24", "주의": "#f9a825",
               "경계": "#ef6c00", "심각": "#c62828"}

st.set_page_config(page_title="핵심광물 모델 체크 데모", layout="wide")


def _db_key() -> float:
    try:
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0.0


BACKTEST_SNAPSHOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "forecast_backtest_snapshot.json")


@st.cache_data
def load_backtest_snapshot():
    """예측(ton/unit) WAPE·MASE 18오리진 백테스트 스냅샷 — 정적 파일 조회(라이브
    재계산 아님, 18오리진×풀링/비풀링 비교라 매번 돌리면 수 분~십수 분 걸림).
    2026-08-05 리뷰 대응(MASE 컬럼 추가+unit 풀링 재검토)으로 생성, 필요시
    scratchpad의 mase_and_unit_pooling.py 재실행 후 이 파일을 갱신한다."""
    if not os.path.exists(BACKTEST_SNAPSHOT_PATH):
        return None
    with open(BACKTEST_SNAPSHOT_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────── 데이터/모델 로더(캐시) ───────────────────────────
@st.cache_data(show_spinner="지정학 위기지수 조회 중...")
def load_geo(_key: float):
    con = duckdb.connect(DB_PATH, read_only=True)
    idx_w = con.execute("""SELECT commodity_code, CAST(period AS DATE) AS week,
        CAST(idx_value AS DOUBLE) idx_value, n_events
        FROM geo_index WHERE freq='W' ORDER BY 1,2""").df()
    prob = con.execute("""SELECT commodity_code, period, p_burst_next,
        p_severe_next, p_burst_adapt, lambda_next, family
        FROM geo_prob ORDER BY 1,2""").df()
    con.close()
    idx_w["week"] = pd.to_datetime(idx_w["week"])
    return idx_w, prob


@st.cache_data(show_spinner="수급위기 진단모델(Ridge 챔피언) 재적합 중...")
def load_diagnosis_level(_key: float):
    df = build_panel_level(DB_PATH)
    feats = [f for f in BASE_FEATS + GEO_DERIVED
             if df[f].notna().sum() > 50 and df[f].nunique() > 2]
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
    coef_f = m.coef_[:len(feats)]
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


@st.cache_data(show_spinner="경보 규칙엔진(오버라이드+히스테리시스) 적용 중...")
def load_diagnosis_alert(_key: float):
    """msr.models.alert의 compute_alerts/_build_reasons/_build_evidence_json을
    그대로 재사용 — (A) 위기지수 분위수 기본단계 (B) 규칙 오버라이드(변동성·HHI)
    (C) 2주 히스테리시스까지 챔피언과 동일 로직. run()과 달리 DB에 쓰지 않는다."""
    lvl, _ = load_diagnosis_level(_key)
    nc = lvl[["commodity_code", "month", "ci_pred", "probs", "contrib"]].rename(
        columns={"ci_pred": "ci_model"})
    nc["stage_probs"] = nc["probs"].apply(lambda d: json.dumps(d, ensure_ascii=False))
    nc["contrib_json"] = nc["contrib"].apply(lambda d: json.dumps(d, ensure_ascii=False))
    nc = nc.drop(columns=["probs", "contrib"]).rename(columns={"contrib_json": "contrib"})

    con = duckdb.connect(DB_PATH, read_only=True)
    df = con.execute("""SELECT commodity_code, obs_date, teacher_supply_demand,
        volatility_12w, import_hhi FROM mart_weekly_diagnosis
        WHERE obs_date >= '2020-01-01' AND teacher_supply_demand IS NOT NULL""").df()
    geo_df = con.execute("""SELECT commodity_code, obs_date, event_type, country,
        severity, evidence_quote FROM geo_event
        WHERE commodity_code IS NOT NULL AND direction = 'supply_down'
          AND source IN ('US_FederalRegister','CN_MOFCOM','WoodMac','IEA','KOMIS',
                         'Argus','PPS','AsianMetal','EU_SCRREEN')""").df()
    con.close()

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


@st.cache_data(show_spinner="Δ 조기경보 앙상블(Bagging25×2) 적합 중...")
def load_delta_ew(_key: float):
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
        # 설명가능성: 25개 배깅 추정기의 |계수| 평균(클래스 평균) — 모델 전역 중요도.
        # 개별 관측치별 기여분해가 아니라 "이 모델이 전반적으로 어떤 피처에 크게
        # 반응하는가"를 보여준다(라벨링에 명시).
        coef_abs = np.mean([np.abs(e.coef_) for e in mdl.estimators_], axis=0)  # (n_cls, n_feat)
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


@st.cache_data(show_spinner="12개월 수요량·단가 예측(ExtraTrees) 재적합 중... "
                            "(conformal 구간보정 포함, 수 분 소요될 수 있음)")
def load_forecast(_key: float):
    db = DB_PATH
    df = build_panel_fc(db)
    last_m = df["month"].max()

    # conformal 보정(프로덕션 run()과 동일 절차) — 보정 원점 3개(24/18/12개월 전)로
    # 가산폭 산출 후 구간에 반영. 원점마다 direct_forecast를 다시 돌려야 해 느리다.
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


# ─────────────────────────────── 화면 구성 ───────────────────────────────
st.title("핵심광물 수급위기 모델 체크 데모")
st.caption(f"DB: `{DB_PATH}` · 읽기 전용 재적합(발행 테이블 미참조) · "
          f"광종: {', '.join(CC_KO.values())}")

with st.sidebar:
    st.header("설정")
    cc = st.selectbox("광종 선택", CCS, format_func=lambda c: CC_KO[c])
    if st.button("모델 다시 적합(캐시 초기화)"):
        st.cache_data.clear()
        st.rerun()
    st.caption("DB 파일이 갱신되면 자동으로 캐시가 무효화됩니다(mtime 기준).")

tab_geo, tab_diag, tab_fc = st.tabs(
    ["① 지정학 위기지수", "② 수급위기 진단", "③ 12개월 수요량·단가 예측"])

key = _db_key()

# ── ① 지정학 위기지수 ──
with tab_geo:
    idx_w, prob = load_geo(key)
    g = idx_w[idx_w["commodity_code"] == cc].sort_values("week")
    p = prob[prob["commodity_code"] == cc].sort_values("period")
    if g.empty:
        st.warning("geo_index에 해당 광종 데이터가 없습니다.")
    else:
        latest = g.iloc[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("최신 주간 위기지수(0~100)", f"{latest['idx_value']:.1f}",
                  help=f"기준주 {latest['week'].date()}")
        if not p.empty:
            pl = p.iloc[-1]
            c2.metric("차주 급증확률(p_burst_next)", f"{pl['p_burst_next']*100:.1f}%",
                      help=f"기준 {pl['period']} · family={pl['family']}")
            c3.metric("심각확률(p_severe_next)", f"{pl['p_severe_next']*100:.1f}%")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["week"], y=g["idx_value"], mode="lines",
                                 name="주간 위기지수", line=dict(color="#c62828")))
        fig.update_layout(height=380, margin=dict(t=20, b=20),
                          yaxis_title="위기지수(0~100, 절대스케일)", xaxis_title="주")
        st.plotly_chart(fig, width='stretch')

        with st.expander("설명 — 지수는 어떻게 산출되나(모델이 아니라 산식)"):
            st.markdown(
                "지정학 위기지수는 학습 모델이 아니라 **뉴스·공시 이벤트 기반 산식**의 "
                "출력이다: `severity × 발행처신뢰도 × 국가점유율 × HHI배수 × 방향` 가중합을 "
                "tanh 함수로 0~100 절대스케일에 매핑(과거값은 표본이 늘어도 불변). "
                "`p_burst_next`(차주 급증확률)는 NB2(음이항) 카운트 모델이 이 지수의 "
                "이벤트 누적을 입력으로 산출한다."
            )
        if not p.empty:
            st.dataframe(p.tail(8)[["period", "p_burst_next", "p_severe_next",
                                    "p_burst_adapt", "family"]],
                        width='stretch', hide_index=True)

# ── ② 수급위기 진단 ──
with tab_diag:
    lvl, feats = load_diagnosis_level(key)
    alert_res = load_diagnosis_alert(key)
    g = lvl[lvl["commodity_code"] == cc].sort_values("month")
    ga = alert_res[alert_res["commodity_code"] == cc].sort_values("obs_date")
    if g.empty:
        st.warning("진단 패널에 해당 광종 데이터가 없습니다.")
    else:
        latest = g.iloc[-1]
        latest_a = ga.iloc[-1] if not ga.empty else None
        c1, c2 = st.columns([1, 2])
        with c1:
            if latest_a is not None:
                st.markdown(f"### {pd.Timestamp(latest_a['obs_date']).strftime('%Y-%m-%d')} "
                           f"발행 경보(규칙엔진 적용)")
                color = STAGE_COLOR.get(latest_a["alert_name"], "#888")
                st.markdown(
                    f"<div style='background:{color};color:white;padding:16px;"
                    f"border-radius:8px;text-align:center;font-size:28px;font-weight:700'>"
                    f"{latest_a['alert_name']}</div>", unsafe_allow_html=True)
                ev = json.loads(latest_a["evidence_json"])
                badges = []
                if ev["override_applied"]:
                    badges.append(f"규칙 오버라이드 발동({latest_a['triggers']})")
                if ev["hysteresis_applied"]:
                    badges.append("히스테리시스로 하향 보류")
                st.caption(" · ".join(badges) if badges else
                          "오버라이드·히스테리시스 미발동(모델 단계 그대로 발행)")
                st.caption(latest_a["reason"])
            else:
                st.markdown(f"### {latest['month'].strftime('%Y-%m')} 판정(Ridge 원모델)")
                color = STAGE_COLOR.get(latest["stage_name"], "#888")
                st.markdown(
                    f"<div style='background:{color};color:white;padding:16px;"
                    f"border-radius:8px;text-align:center;font-size:28px;font-weight:700'>"
                    f"{latest['stage_name']}</div>", unsafe_allow_html=True)
            st.metric("모델 예측 위기지수", f"{latest['ci_pred']:.1f}",
                      delta=(f"{latest['ci_pred']-latest['ci_teacher']:+.1f} vs 교사"
                            if latest["ci_teacher"] is not None else None))
            probs = latest["probs"]
            pf = go.Figure(go.Bar(x=list(probs.values()), y=list(probs.keys()),
                                  orientation="h",
                                  marker_color=[STAGE_COLOR.get(k, "#888") for k in probs]))
            pf.update_layout(height=220, margin=dict(t=10, b=10, l=10, r=10),
                             xaxis_title="확률", title="단계별 확률(정규근사)")
            st.plotly_chart(pf, width='stretch')
        with c2:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=g["month"], y=g["ci_pred"], name="모델 예측",
                                     line=dict(color="#1565c0")))
            fig.add_trace(go.Scatter(x=g["month"], y=g["ci_teacher"], name="교사(실측)",
                                     line=dict(color="#9e9e9e", dash="dot")))
            fig.update_layout(height=300, margin=dict(t=20, b=20),
                              yaxis_title="위기지수(0~100)", title="위기지수 추이 — Ridge 챔피언")
            st.plotly_chart(fig, width='stretch')

            st.markdown("#### 설명 가능한 결과 — 이번 달 예측에 대한 피처 기여도")
            st.caption("Ridge는 선형모델이라 예측이 Σ(계수×표준화값)로 정확히 분해된다 "
                      "(SHAP의 선형 특수해와 동일). +는 위기지수를 끌어올리는 방향.")
            cd = latest["contrib"]
            cd_sorted = dict(sorted(cd.items(), key=lambda kv: -abs(kv[1])))
            cf = go.Figure(go.Bar(
                x=list(cd_sorted.values()), y=list(cd_sorted.keys()), orientation="h",
                marker_color=["#c62828" if v >= 0 else "#1565c0" for v in cd_sorted.values()]))
            cf.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10),
                             xaxis_title="위기지수 기여도(+가 위기↑)")
            st.plotly_chart(cf, width='stretch')

        st.divider()
        st.markdown("#### 보조 신호 — Δ 조기경보 앙상블(Bagging25×2 + OECD 한국 CLI)")
        st.caption("운영 등급예측과 별개의 병기 신호(경보 등급을 바꾸지 않음, hard 결합은 "
                  "과거 백테스트로 기각된 이력). 목표: 다음 판정 시 등급이 상향/유지/하향 "
                  "될지의 방향 확률.")
        ew, gimp = load_delta_ew(key)
        e = ew[ew["commodity_code"] == cc]
        if e.empty:
            st.info("해당 광종의 최신 관측주 데이터가 없습니다.")
        else:
            r = e.iloc[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("하향 확률", f"{r['p_down']*100:.1f}%")
            c2.metric("유지 확률", f"{r['p_stay']*100:.1f}%")
            c3.metric("상향 확률", f"{r['p_up']*100:.1f}%")
            st.markdown(f"**예측 방향: {r['direction']}** "
                       f"({'트리거 작동' if r['trigger'] else '트리거 없음'})")
            with st.expander("설명 — 이 앙상블이 전역적으로 어떤 피처에 민감한가"):
                st.caption("개별 예측의 기여분해가 아니라, 25개 배깅 추정기 계수의 "
                          "절댓값 평균(전역 중요도)이다.")
                for tag, rank in gimp.items():
                    st.markdown(f"**모델 {tag}** 상위 피처: " +
                              ", ".join(f"{k}({v:.2f})" for k, v in rank))

# ── ③ 12개월 수요량·단가 예측 ──
with tab_fc:
    fc, base_m, qt_pub, qu_pub = load_forecast(key)
    g = fc[fc["commodity_code"] == cc].sort_values("h")
    st.caption(f"기준월(base_month) {base_m:%Y-%m} — 관세청 월간 통관 실적 최신 확보월 "
              f"기준(실시간 아님, 통상 수개월 래그). 방식: direct(호라이즌별 독립모델), "
              f"ton=ExtraTrees+MIDAS지정학지수, unit=ExtraTrees+U-MIDAS 가격·환율. "
              f"구간은 conformal 보정 적용(가산폭 로그공간 ton {qt_pub:.3f}/unit {qu_pub:.3f}, "
              f"프로덕션과 동일 절차 — 보정 원점 24/18/12개월 전).")
    if g.empty:
        st.warning("예측 패널에 해당 광종 데이터가 없습니다.")
    else:
        h1, h6, h12 = g[g["h"] == 1].iloc[0], g[g["h"] == 6].iloc[0], g[g["h"] == 12].iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric(f"h=1 ({h1['target_month']}) 예측물량", f"{h1['pred_ton']:,.0f} 톤")
        c2.metric(f"h=6 ({h6['target_month']}) 예측물량", f"{h6['pred_ton']:,.0f} 톤")
        c3.metric(f"h=12 ({h12['target_month']}) 예측물량", f"{h12['pred_ton']:,.0f} 톤")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["target_month"], y=g["pred_ton"], name="예측 물량(톤)",
                                 line=dict(color="#2e7d32")))
        fig.add_trace(go.Scatter(x=g["target_month"], y=g["ton_hi"], name="상단(q90)",
                                 line=dict(color="#a5d6a7", dash="dot")))
        fig.add_trace(go.Scatter(x=g["target_month"], y=g["ton_lo"], name="하단(q10)",
                                 line=dict(color="#a5d6a7", dash="dot"), fill="tonexty"))
        fig.update_layout(height=300, margin=dict(t=20, b=20), title="물량(ton) 12개월 예측",
                          yaxis_title="톤")
        st.plotly_chart(fig, width='stretch')

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=g["target_month"], y=g["pred_unit_usd_per_ton"],
                                  name="예측 단가(USD/ton)", line=dict(color="#1565c0")))
        fig2.add_trace(go.Scatter(x=g["target_month"], y=g["unit_hi"], name="상단(q90)",
                                  line=dict(color="#90caf9", dash="dot")))
        fig2.add_trace(go.Scatter(x=g["target_month"], y=g["unit_lo"], name="하단(q10)",
                                  line=dict(color="#90caf9", dash="dot"), fill="tonexty"))
        fig2.update_layout(height=300, margin=dict(t=20, b=20), title="단가(USD/ton) 12개월 예측",
                           yaxis_title="USD/ton")
        st.plotly_chart(fig2, width='stretch')

        st.markdown("#### 수입액(물량×단가) 12개월 예측")
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=g["target_month"], y=g["pred_value_usd"]/1000,
                                  name="예측 수입액(천USD)", line=dict(color="#6a1b9a")))
        fig3.add_trace(go.Scatter(x=g["target_month"], y=g["pred_value_hi"]/1000,
                                  name="상단", line=dict(color="#ce93d8", dash="dot")))
        fig3.add_trace(go.Scatter(x=g["target_month"], y=g["pred_value_lo"]/1000,
                                  name="하단", line=dict(color="#ce93d8", dash="dot"),
                                  fill="tonexty"))
        fig3.update_layout(height=300, margin=dict(t=20, b=20), yaxis_title="천 USD")
        st.plotly_chart(fig3, width='stretch')
        st.caption("구간은 물량×단가 몬테카를로(로그정규) 합성 — 분위를 직접 곱하지 않음. "
                  "물량·단가 각 구간엔 conformal 보정이 이미 반영됨.")

        st.markdown("#### 성능지표 — WAPE vs 계절나이브 (18오리진 워크포워드 백테스트 스냅샷)")
        snap = load_backtest_snapshot()
        if snap is None:
            st.info("백테스트 스냅샷 파일이 없습니다 — "
                   "`scratchpad/mase_and_unit_pooling.py` 실행 후 "
                   "`dashboards/forecast_backtest_snapshot.json`으로 저장하세요.")
        else:
            met = [r for r in snap["champion_metrics"] if r["commodity"] == cc]
            mc1, mc2 = st.columns(2)
            for r in met:
                col = mc1 if r["target"] == "ton" else mc2
                verdict = "챔피언 우세" if r["beats_naive"] else "나이브 우세"
                delta_pct = (r["snaive_oos_WAPE"] - r["WAPE"]) / r["snaive_oos_WAPE"] * 100
                col.metric(f"{r['target']} WAPE (챔피언 / 계절나이브 OOS)",
                          f"{r['WAPE']:.3f} / {r['snaive_oos_WAPE']:.3f}",
                          delta=f"{delta_pct:+.1f}% ({verdict})",
                          help=f"동일 18오리진×h1..12 그리드 out-of-sample 비교. "
                               f"참고용 in-sample MASE={r['MASE_insample_refonly']:.3f}"
                               f"(절대기준 아님, 스케일 안내에서 설명). n={r['n']}")
            st.caption(f"스냅샷 생성 {snap['meta']['generated_at']}(정정 {snap['meta']['corrected_at']}) "
                      f"· {snap['meta']['method']} — 라이브 재계산 아님.")
            with st.expander("⚠ MASE 컬럼을 왜 참고용으로만 표시하나(리뷰어 지적으로 정정)"):
                st.caption(snap["meta"]["note"])
            with st.expander("unit 풀링(5광종 동시학습) vs 비풀링(광종별 독립) 재검토 결과"):
                st.caption("리뷰 피드백 대응(2026-08-05) — unit 모델을 풀링 구조로 유지할지 "
                          "재검정. 같은 ExtraTrees 구성으로 풀링/비풀링만 바꿔 18오리진 비교.")
                dfc = pd.DataFrame(snap["unit_pool_vs_depool"])
                st.dataframe(dfc.set_index("commodity")[["w_pool", "w_dep", "m_pool", "m_dep",
                                                          "verdict"]],
                            width='stretch')
                bt = snap["bootstrap"]
                st.markdown(f"**전체 페어드 부트스트랩**: 95% CI [{bt['ci95'][0]:+.4f},"
                           f"{bt['ci95'][1]:+.4f}], P(비풀링 우세)={bt['p_depool_better']:.3f} "
                           f"→ **{bt['verdict']}**")
                st.caption("특히 NI(현 챔피언의 최약 셀)는 비풀링 시 오히려 악화(WAPE "
                          "0.382→0.396) — 다른 광종의 가격·환율 동학 정보가 소량표본 NI에 "
                          "실제로 도움이 된다는 뜻. 풀링 구조는 유지하고, CO ton·NI unit 두 "
                          "약점 셀은 각각 개별 원인이 달라(CO=고변동 소량 원자재 → EN+긴 "
                          "감쇠hl36 특화, NI=풀링 내 최약 셀 → XT+감쇠hl24 특화) 이미 "
                          "2026-07-26에 개별 특화 반영됨(모델 교체 4종은 재시도 금지).")

        st.markdown("#### 설명 가능한 결과 — 호라이즌 선택 후 SHAP 기여도")
        h_sel = st.select_slider("호라이즌(h, 개월)", options=list(range(1, 13)), value=1)
        row = g[g["h"] == h_sel].iloc[0]
        st.markdown(f"**{row['target_month']} (h={h_sel})** — {row['reason']}")
        ex = json.loads(row["explain_json"])
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**물량(ton) 개별 기여 — 상위 요인**")
            for it in ex["local"]["ton"]:
                st.write(f"- {it['label']}: {it['shap_log']:+.3f} (값={it['value']})")
            st.markdown("**물량 전역 중요도(permutation, in-sample)**")
            for it in ex["global_top5"]["ton"]:
                st.write(f"- {it['label']}: {it['importance_mean']:.5f}")
        with cc2:
            st.markdown("**단가(USD/ton) 개별 기여 — 상위 요인**")
            for it in ex["local"]["unit"]:
                st.write(f"- {it['label']}: {it['shap_log']:+.3f} (값={it['value']})")
            st.markdown("**단가 전역 중요도(permutation, in-sample)**")
            for it in ex["global_top5"]["unit"]:
                st.write(f"- {it['label']}: {it['importance_mean']:.5f}")
        st.caption(ex["note"])

        with st.expander("전체 h=1~12 표"):
            st.dataframe(
                g[["h", "target_month", "pred_ton", "pred_unit_usd_per_ton",
                   "pred_value_usd"]].round(1),
                width='stretch', hide_index=True)
