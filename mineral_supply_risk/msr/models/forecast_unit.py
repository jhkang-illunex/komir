# -*- coding: utf-8 -*-
"""수입 예측 v2 — 단가 분해 구조 (2026-07-12 /goal 사양).

타깃 정의(사용자 지정):
  물량  = 월간 수입중량(톤)                          ← HS 확정 바스켓(161코드) 필터 합산
  단가  = 광물당 톤당 단위금액(USD/ton) = 수입액/중량
  금액  = 단가 × 톤  (실지출액 — 항등식이 정확히 성립하는 분해)
직접 금액 예측 대비 장점: 단가는 국제가격(LME)에 강하게 계류되어 예측이 쉽고, 물량은
계절성·산업수요를 따름 — 서로 다른 동학을 분리 학습한 뒤 곱으로 재조립한다.

지도학습: 관세청 월간(fact_trade_monthly, HS→광종 매핑 완료분)을 정답으로,
피처 = 자기시차(1·2·3·6·12) + 3M 롤링 + 월 계절성(sin/cos) + 외생(LME 월평균가·원달러
환율·지정학 지수 — 예측 구간에선 최종 관측값 고정, 시나리오 입력으로 교체 가능).
h=1~12 재귀 예측(단일스텝 HistGBM ×2: log(톤)·log(단가), 광종 풀링+더미).

검증: 워크포워드 2 오리진(2024-07·2025-01 기준 12개월) — 계절 나이브 및 '금액 직접예측'
대비 비교(분해 구조의 우위/동등 입증). 산출: out_import_forecast_unit + 백테스트 리포트.

실행: MSR_DB=<warehouse> python -m msr.models.forecast_unit
"""
from __future__ import annotations
import json, os, warnings

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from ..config import DB_PATH, OUT

warnings.filterwarnings("ignore")

H = 12
LAGS = [1, 2, 3, 6, 12]
FX_CSV = ("/home/nuri/dev/git/ws/mine_ws/komir/documents/1. 광물가격, 재고량, 지수 등 (1)/"
          "3. 원달러 환율.csv")


# ─────────────────────────── 패널 구축 ───────────────────────────
def build_panel(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    t = con.execute("""
        SELECT commodity_code, make_date(yr, mon, 1) AS month,
               sum(imp_wgt)/1000.0 AS ton, sum(imp_usd) AS value_usd
        FROM fact_trade_monthly GROUP BY 1,2 ORDER BY 1,2""").df()
    px = con.execute("""
        SELECT commodity_code, date_trunc('month', obs_date) AS month, avg(val) AS lme
        FROM fact_price WHERE freq='W' AND price_type IN ('LME_CASH','REF')
        GROUP BY 1,2""").df()
    gi = con.execute("""
        SELECT commodity_code, CAST(period AS DATE) AS month, idx_value AS geo
        FROM geo_index WHERE freq='M'""").df()
    con.close()
    for d in (t, px, gi):
        d["month"] = pd.to_datetime(d["month"])
    df = t.merge(px, on=["commodity_code", "month"], how="left") \
          .merge(gi, on=["commodity_code", "month"], how="left")
    # 환율(주간 CSV → 월평균), cp949
    try:
        fx = pd.read_csv(FX_CSV, encoding="cp949", skiprows=2, names=["d", "v", "_"])
        fx["month"] = pd.to_datetime(fx["d"], format="%Y/%m/%d").values.astype("datetime64[M]")
        fx = fx.groupby("month", as_index=False)["v"].mean().rename(columns={"v": "fx"})
        fx["month"] = pd.to_datetime(fx["month"])
        df = df.merge(fx, on="month", how="left")
    except Exception:
        df["fx"] = np.nan
    df["unit"] = df["value_usd"] / df["ton"].replace(0, np.nan)   # USD/ton
    return df.sort_values(["commodity_code", "month"]).reset_index(drop=True)


def _features(df: pd.DataFrame, target: str) -> pd.DataFrame:
    """target(log스케일) 자기시차+롤링+계절+외생. 반환: 피처 프레임(y 포함)."""
    out = []
    for cc, g in df.groupby("commodity_code"):
        g = g.sort_values("month").copy()
        g["ly"] = np.log(g[target].clip(lower=1e-9))
        for L in LAGS:
            g[f"lag{L}"] = g["ly"].shift(L)
        g["roll3"] = g["ly"].shift(1).rolling(3).mean()
        m = g["month"].dt.month
        g["m_sin"] = np.sin(2 * np.pi * m / 12); g["m_cos"] = np.cos(2 * np.pi * m / 12)
        g["lme_l"] = np.log(g["lme"].clip(lower=1e-9))
        g["geo_f"] = g["geo"]
        g["fx_l"] = np.log(g["fx"].clip(lower=1e-9))
        out.append(g)
    return pd.concat(out, ignore_index=True)


FEATS = [f"lag{L}" for L in LAGS] + ["roll3", "m_sin", "m_cos", "lme_l", "geo_f", "fx_l"]

# ─────────────────────── 설명가능성(2026-07-24, 스코어카드 4-4 갭 해소) ───────────────────────
# HistGradientBoostingRegressor는 sklearn 공식 한계로 feature_importances_ 속성이 없음
# (RandomForest·GradientBoostingRegressor와 달리 히스토그램 기반 트리라 미지원) — 전역
# 중요도는 permutation_importance(모델-불가지론적 표준 기법)로 대체. 개별 예측 설명은
# SHAP TreeExplainer(트리 모델 전용, HistGradientBoostingRegressor 지원 확인됨,
# shap_values 합이 예측값-기준값과 정확히 일치함을 스모크테스트로 검증 후 채택).
FEAT_LABELS = {
    "lag1": "1개월 전 실적", "lag2": "2개월 전 실적", "lag3": "3개월 전 실적",
    "lag6": "6개월 전 실적", "lag12": "전년 동월 실적", "roll3": "최근 3개월 이동평균",
    "m_sin": "계절성(월)", "m_cos": "계절성(월)", "lme_l": "LME 국제가격",
    "geo_f": "지정학위기지수", "fx_l": "원달러 환율",
}


def _feat_label(name: str) -> str:
    if name in FEAT_LABELS:
        return FEAT_LABELS[name]
    if name.startswith("cc_"):
        return f"광종 고정효과({name[3:]})"
    return name


def _shap_top_contrib(model, X: pd.DataFrame, top_n: int = 3) -> list:
    """SHAP TreeExplainer로 X의 각 행(예측)에 대해 상위 top_n 기여 피처(부호 포함,
    log스케일 — 타깃 자체가 log(톤)/log(단가)라 SHAP값도 log기여분)를 반환."""
    import shap
    expl = shap.TreeExplainer(model)
    sv = expl.shap_values(X)
    sv = np.atleast_2d(sv)
    out = []
    for i in range(len(X)):
        row = sv[i]
        order = np.argsort(-np.abs(row))[:top_n]
        out.append([
            {"feature": str(X.columns[j]), "label": _feat_label(str(X.columns[j])),
             "shap_log": round(float(row[j]), 4), "value": round(float(X.iloc[i, j]), 4)}
            for j in order
        ])
    return out


def _global_importance(model, X: pd.DataFrame, y: np.ndarray, top_n: int = 5,
                       n_repeats: int = 8, seed: int = 0) -> list:
    """permutation_importance(sklearn.inspection) — 학습에 쓰인 데이터 기준(엄밀한
    held-out 검증 아님 — in-sample 전역 중요도임을 결과 JSON에 명시)."""
    from sklearn.inspection import permutation_importance
    r = permutation_importance(model, X, y, n_repeats=n_repeats, random_state=seed,
                               scoring="neg_mean_squared_error")
    order = np.argsort(-r.importances_mean)[:top_n]
    return [
        {"feature": str(X.columns[j]), "label": _feat_label(str(X.columns[j])),
         "importance_mean": round(float(r.importances_mean[j]), 5),
         "importance_std": round(float(r.importances_std[j]), 5)}
        for j in order
    ]


def _reason_sentence(cc: str, target_month, h: int, target_label: str,
                     contrib: list, direction_note: str = "") -> str:
    """진단기(out_diagnosis_alert.reason)와 동일한 스타일의 한국어 자연어 설명문 생성."""
    parts = []
    for c in contrib:
        sign = "+" if c["shap_log"] >= 0 else ""
        parts.append(f"{c['label']} {sign}{c['shap_log']}")
    contrib_str = ", ".join(parts)
    return (f"[{cc} {target_month} h={h} {target_label} 예측] "
            f"상위 기여 요인(로그스케일 기여분): {contrib_str}."
            + (f" {direction_note}" if direction_note else ""))


def _explain_local(expl_info, cc: str, h: int, top_n: int = 3):
    """expl_info=("direct", models) 또는 ("recursive", model, xrows, Xtr, ytr)에서
    (cc,h)에 해당하는 예측의 SHAP 상위기여를 뽑는다. 발행 시점에 실제 쓰인 모델·피처행을
    그대로 재사용(재적합 아님)."""
    if expl_info[0] == "direct":
        _, models = expl_info
        info = models.get(h)
        if info is None:
            return None
        X = info["Xpr_by_cc"].get(cc)
        if X is None:
            return None
        return _shap_top_contrib(info["model"], X, top_n=top_n)[0]
    _, model, xrows, _, _ = expl_info
    X = xrows.get((cc, h))
    if X is None:
        return None
    return _shap_top_contrib(model, X, top_n=top_n)[0]


def _explain_global(expl_info, top_n: int = 5):
    """expl_info로부터 전역 중요도(permutation_importance) — direct는 h=1(없으면 임의
    1개) 모델 기준, recursive는 전 h 공용 단일모델 기준."""
    if expl_info[0] == "direct":
        _, models = expl_info
        info = models.get(1) or (next(iter(models.values())) if models else None)
        if info is None:
            return []
        return _global_importance(info["model"], info["Xtr"], info["ytr"], top_n=top_n)
    _, model, _, Xtr, ytr = expl_info
    return _global_importance(model, Xtr, ytr, top_n=top_n)


def _build_explanations(out: pd.DataFrame, expl_ton, expl_unit) -> tuple:
    """out의 각 행(commodity_code,target_month,h)에 물량·단가 SHAP 상위기여를 결합한
    자연어 reason과 구조화 explain_json을 붙인다(2026-07-24, 스코어카드 4-4 갭 해소 —
    out_diagnosis_alert.reason/evidence_json과 동일한 설계 패턴)."""
    global_ton = _explain_global(expl_ton)
    global_unit = _explain_global(expl_unit)
    reasons, explains = [], []
    for _, r in out.iterrows():
        cc, h = r["commodity_code"], int(r["h"])
        loc_t = _explain_local(expl_ton, cc, h) or []
        loc_u = _explain_local(expl_unit, cc, h) or []
        parts = []
        if loc_t:
            s = ", ".join(f"{c['label']}{'+' if c['shap_log'] >= 0 else ''}{c['shap_log']}" for c in loc_t)
            parts.append(f"물량: {s}")
        if loc_u:
            s = ", ".join(f"{c['label']}{'+' if c['shap_log'] >= 0 else ''}{c['shap_log']}" for c in loc_u)
            parts.append(f"단가: {s}")
        reason = (f"[{cc} {r['target_month']} h={h}개월] 예측 기여요인(SHAP, 로그스케일) — "
                 + " / ".join(parts) + ".") if parts else \
                 f"[{cc} {r['target_month']} h={h}개월] 설명 정보 없음(모델 매칭 실패)."
        reasons.append(reason)
        explains.append(json.dumps({
            "local": {"ton": loc_t, "unit": loc_u},
            "global_top5": {"ton": global_ton, "unit": global_unit},
            "method": expl_ton[0],
            "note": ("SHAP은 log(톤)/log(단가) 타깃 기준 로그스케일 기여분(부호=방향, 크기=영향력). "
                    "전역중요도는 permutation_importance 기반, 학습데이터 기준(in-sample) — "
                    "엄밀한 held-out 검증치 아님."),
        }, ensure_ascii=False)[:4000])
    return reasons, explains


def _fit(df_feat: pd.DataFrame):
    d = pd.get_dummies(df_feat.dropna(subset=["lag1", "ly"]),
                       columns=["commodity_code"], prefix="cc")
    cc_cols = sorted(c for c in d.columns if c.startswith("cc_"))
    X = d[FEATS + cc_cols].fillna(d[FEATS + cc_cols].median(numeric_only=True))
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.07, max_iter=300,
                                       random_state=0)
    m.fit(X, d["ly"].values)
    return m, cc_cols


def _recursive_forecast(df: pd.DataFrame, target: str, base_month: pd.Timestamp,
                        horizon: int = H, return_models: bool = False):
    """base_month까지 학습 → h=1..horizon 재귀 예측. 외생은 최종 관측값 고정.
    return_models=True면 (예측df, model, {(cc,h): Xrow}, Xtr, ytr) 튜플 반환
    (2026-07-24 설명가능성 — 재귀는 모델 1개를 전 h에 재사용하므로 model은 하나,
    피처행만 (광종,h)별로 다름)."""
    hist = df[df["month"] <= base_month].copy()
    feat = _features(hist, target)
    model, cc_cols = _fit(feat)
    preds = []
    xrows = {}
    state = {cc: g.sort_values("month").copy() for cc, g in hist.groupby("commodity_code")}
    for h in range(1, horizon + 1):
        tgt_m = base_month + pd.DateOffset(months=h)
        for cc, g in state.items():
            last = g.iloc[-1]
            # 재귀 append(concat) 후 object dtype 승격 방어 — 숫자 강제
            ly = np.log(pd.to_numeric(g[target], errors="coerce").clip(lower=1e-9))
            row = {f"lag{L}": (ly.iloc[-L] if len(g) >= L else np.nan) for L in LAGS}
            row["roll3"] = ly.iloc[-3:].mean() if len(g) >= 3 else np.nan
            row["m_sin"] = np.sin(2 * np.pi * tgt_m.month / 12)
            row["m_cos"] = np.cos(2 * np.pi * tgt_m.month / 12)
            row["lme_l"] = np.log(max(1e-9, last["lme"])) if pd.notna(last["lme"]) else np.nan
            row["geo_f"] = last["geo"]
            row["fx_l"] = np.log(max(1e-9, last["fx"])) if pd.notna(last["fx"]) else np.nan
            for c in cc_cols:
                row[c] = 1.0 if c == f"cc_{cc}" else 0.0
            Xrow = pd.DataFrame([row])[FEATS + cc_cols]
            yhat = float(np.exp(model.predict(Xrow)[0]))
            preds.append(dict(commodity_code=cc, month=tgt_m, h=h, pred=yhat))
            if return_models:
                xrows[(cc, h)] = Xrow
            new = last.copy(); new["month"] = tgt_m; new[target] = yhat
            state[cc] = pd.concat([g, new.to_frame().T], ignore_index=True)
    if return_models:
        d = pd.get_dummies(feat.dropna(subset=["lag1", "ly"]), columns=["commodity_code"], prefix="cc")
        Xtr = d[FEATS + cc_cols].fillna(d[FEATS + cc_cols].median(numeric_only=True))
        ytr = d["ly"].values
        return pd.DataFrame(preds), model, xrows, Xtr, ytr
    return pd.DataFrame(preds)


# ─────────────────── Direct 다중기간 + 분위(구간) 예측 ───────────────────
# 감사 B-3①③(2026-07-13): 재귀는 h가 깊어질수록 오차가 누적(특히 단가) — h별 독립 모델
# (Direct)로 비교하고, 분위 모델(q10/q90)로 예측구간을 병행 산출한다. 물량×단가의 금액
# 구간은 분위 곱이 아니라 몬테카를로 합성(각 마진을 lognormal 근사 후 곱 분포의 분위).
QUANTS = (0.1, 0.9)
_Z80 = 1.2816                     # 표준정규 90% 분위(lognormal σ 적합용)


def _direct_matrix(feat: pd.DataFrame, h: int) -> pd.DataFrame:
    """시점 t 피처 → t+h 타깃(직접). 계절항은 타깃 월(t+h) 기준으로 교체."""
    out = []
    for _, g in feat.groupby("commodity_code"):
        g = g.sort_values("month").copy()
        g["y_h"] = g["ly"].shift(-h)
        tm = g["month"] + pd.DateOffset(months=h)
        g["m_sin"] = np.sin(2 * np.pi * tm.dt.month / 12)
        g["m_cos"] = np.cos(2 * np.pi * tm.dt.month / 12)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def _direct_forecast(df: pd.DataFrame, target: str, base_month: pd.Timestamp,
                     horizon: int = H, with_quantiles: bool = False,
                     return_models: bool = False):
    """h별 독립 HistGBM(광종 풀링+더미). with_quantiles면 q10/q90 분위 모델 병행.
    return_models=True면 (예측df, {h: {"model","Xpr_by_cc","Xtr","ytr"}}) 튜플 반환
    (2026-07-24 설명가능성 — 발행 시점 예측에 실제 쓰인 모델·피처행을 그대로 재사용해
    SHAP·permutation_importance를 계산하기 위함, 재적합 아님)."""
    hist = df[df["month"] <= base_month].copy()
    feat = _features(hist, target)
    rows = []
    models = {}
    for h in range(1, horizon + 1):
        d = _direct_matrix(feat, h)
        d2 = pd.get_dummies(d, columns=["commodity_code"], prefix="cc")
        cc_cols = sorted(c for c in d2.columns if c.startswith("cc_"))
        cols = FEATS + cc_cols
        tr = d2.dropna(subset=["lag1", "y_h"])
        med = tr[cols].median(numeric_only=True)
        Xtr, ytr = tr[cols].fillna(med), tr["y_h"].values
        pr = d2[d2["month"] == base_month]           # 광종별 1행(예측 기점 피처)
        Xpr = pr[cols].fillna(med)
        mk = dict(max_depth=4, learning_rate=0.07, max_iter=300, random_state=0)
        m = HistGradientBoostingRegressor(**mk).fit(Xtr, ytr)
        yhat = np.exp(m.predict(Xpr))
        qv = {}
        if with_quantiles:
            for q in QUANTS:
                mq = HistGradientBoostingRegressor(loss="quantile", quantile=q, **mk) \
                    .fit(Xtr, ytr)
                qv[q] = np.exp(mq.predict(Xpr))      # log-공간 분위 → 지수(단조변환 보존)
        cc_of = d.loc[pr.index, "commodity_code"] if "commodity_code" in d else None
        for i, idx in enumerate(pr.index):
            r = dict(commodity_code=d.loc[idx, "commodity_code"],
                     month=base_month + pd.DateOffset(months=h), h=h, pred=float(yhat[i]))
            if with_quantiles:
                r["q10"], r["q90"] = float(qv[0.1][i]), float(qv[0.9][i])
            rows.append(r)
        if return_models:
            Xpr_by_cc = {d.loc[idx, "commodity_code"]: Xpr.loc[[idx]] for idx in pr.index}
            models[h] = {"model": m, "Xpr_by_cc": Xpr_by_cc, "Xtr": Xtr, "ytr": ytr}
    out = pd.DataFrame(rows)
    return (out, models) if return_models else out


def _conformal_q(df: pd.DataFrame, target: str, origins: tuple, horizon: int = H,
                 alpha: float = 0.2) -> float:
    """CQR 보수화(감사 후속 2026-07-14): 분위 HistGBM 구간이 실측 과소커버(0.60~0.72)라
    보정 원점들의 OOS conformity score E=max(q10−y, y−q90) (log공간)의 유한표본 보정
    (1−α) 분위를 가산폭으로 반환 — 구간을 [q10·e^{−Q}, q90·e^{+Q}]로 넓힌다.
    보정 원점은 반드시 평가/발행 기점보다 과거여야 누수가 없다."""
    scores = []
    act = df[["commodity_code", "month", target]]
    for o in origins:
        fd = _direct_forecast(df, target, pd.Timestamp(o), horizon, with_quantiles=True)
        m = fd.merge(act, on=["commodity_code", "month"], how="inner")
        ly = np.log(m[target].clip(lower=1e-9).astype(float))
        l10 = np.log(m["q10"].clip(lower=1e-9))
        l90 = np.log(m["q90"].clip(lower=1e-9))
        scores.append(np.maximum(l10 - ly, ly - l90).values)
    s = np.concatenate(scores)
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return 0.0
    k = min(1.0, np.ceil((len(s) + 1) * (1 - alpha)) / len(s))   # 유한표본 conformal 분위
    return max(0.0, float(np.quantile(s, k)))


def _lognorm_params(q10, q50, q90):
    """(q10,q50,q90) → lognormal(μ,σ) 근사. σ는 분위 간격, μ는 중앙값."""
    mu = np.log(max(q50, 1e-9))
    sigma = max((np.log(max(q90, 1e-9)) - np.log(max(q10, 1e-9))) / (2 * _Z80), 1e-6)
    return mu, sigma


def _mc_value_interval(ton_q: tuple, unit_q: tuple, n: int = 4000, seed: int = 0) -> tuple:
    """금액 구간 = 물량·단가 마진(lognormal 근사)의 독립 표본 곱 분포 분위(MC 합성).
    분위 직접 곱(q10×q10)은 결합 분위가 아니므로 금지(감사 B-3③ 주의사항)."""
    rng = np.random.default_rng(seed)
    mt, st = _lognorm_params(*ton_q)
    mu_, su = _lognorm_params(*unit_q)
    v = np.exp(rng.normal(mt, st, n)) * np.exp(rng.normal(mu_, su, n))
    return tuple(float(np.quantile(v, q)) for q in (0.1, 0.5, 0.9))


# ─────────────────────────── 검증·발행 ───────────────────────────
# 지표 선택(2026-07-13 보강): SMAPE는 0 근처 값에서 분모 붕괴·비율 폭발, 광종 간 스케일
# 300배 차(CU 20만톤 vs REE 700톤)에서 개별 비율 평균이 소광종에 왜곡됨. M4/M5 이후 표준을
# 따라 WAPE(Σ|F−A|/Σ|A| — 총합 비율이라 0값·저값에 강건, 총지출 관점)와 MASE(계절 m=12
# 나이브 스케일링, Hyndman 정의 — 광종별 정규화 후 매크로 평균, <1이면 계절나이브보다 우수)를
# 주지표로 병기한다. SMAPE는 기존 백테스트와의 이력 비교용으로 유지.
def _smape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    return float(100 * np.mean(2 * np.abs(p - a) / (np.abs(a) + np.abs(p) + 1e-9)))


def _wape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    return float(100 * np.sum(np.abs(p - a)) / max(np.sum(np.abs(a)), 1e-9))


def _mase(f: pd.DataFrame, col_a: str, col_p: str, train: pd.DataFrame, target: str) -> float:
    """광종별 스케일(학습구간 계절나이브 MAE, m=12) 정규화 후 매크로 평균."""
    vals = []
    for cc, g in f.groupby("commodity_code"):
        tr = train[train["commodity_code"] == cc].sort_values("month")[target].astype(float).values
        if len(tr) <= 12:
            continue
        scale = np.mean(np.abs(tr[12:] - tr[:-12]))
        if not scale or np.isnan(scale):
            continue
        vals.append(float(np.mean(np.abs(g[col_p].astype(float) - g[col_a].astype(float))) / scale))
    return round(float(np.mean(vals)), 2) if vals else np.nan


def backtest(df: pd.DataFrame, origins=("2024-06-01", "2024-12-01")) -> pd.DataFrame:
    # conformal 가산폭 — 보정 원점(2022-06/12)은 두 평가 원점의 예측 대상기간보다 전부
    # 과거(실측 ~2023-12)라 누수 없음. 평가에서 커버리지 개선을 실증한다.
    cal = ("2022-06-01", "2022-12-01")
    qt = _conformal_q(df, "ton", cal)
    qu = _conformal_q(df, "unit", cal)
    print(f"[conformal] 보정 원점 {cal} → 가산폭(log) ton {qt:.3f}, unit {qu:.3f}")
    rows = []
    for o in origins:
        base = pd.Timestamp(o)
        f_ton = _recursive_forecast(df, "ton", base).rename(columns={"pred": "p_ton"})
        f_unit = _recursive_forecast(df, "unit", base).rename(columns={"pred": "p_unit"})
        f_val = _recursive_forecast(df, "value_usd", base).rename(columns={"pred": "p_val_direct"})
        f = f_ton.merge(f_unit, on=["commodity_code", "month", "h"]) \
                 .merge(f_val, on=["commodity_code", "month", "h"])
        act = df[["commodity_code", "month", "ton", "unit", "value_usd"]]
        f = f.merge(act, on=["commodity_code", "month"], how="inner")
        # 계절 나이브: 전년 동월(없으면 마지막 관측)
        sn = df.copy(); sn["month"] = sn["month"] + pd.DateOffset(years=1)
        f = f.merge(sn[["commodity_code", "month", "ton", "value_usd"]]
                    .rename(columns={"ton": "sn_ton", "value_usd": "sn_val"}),
                    on=["commodity_code", "month"], how="left")
        f["p_value"] = f["p_ton"] * f["p_unit"]           # 분해 재조립(실지출액)
        f["sn_ton_f"] = f["sn_ton"].fillna(f["ton"].mean())
        f["sn_val_f"] = f["sn_val"].fillna(f["value_usd"].mean())
        train = df[df["month"] <= base]
        # Direct 다중기간(+분위) — 재귀와 정면 비교(감사 B-3①), 구간 커버리지 검증(B-3③)
        fd_t = _direct_forecast(df, "ton", base, with_quantiles=True) \
            .rename(columns={"pred": "pd_ton", "q10": "t10", "q90": "t90"})
        fd_u = _direct_forecast(df, "unit", base, with_quantiles=True) \
            .rename(columns={"pred": "pd_unit", "q10": "u10", "q90": "u90"})
        f = f.merge(fd_t, on=["commodity_code", "month", "h"], how="left") \
             .merge(fd_u, on=["commodity_code", "month", "h"], how="left")
        f["pd_value"] = f["pd_ton"] * f["pd_unit"]
        vint = f.apply(lambda r: _mc_value_interval(
            (r["t10"], r["pd_ton"], r["t90"]), (r["u10"], r["pd_unit"], r["u90"])), axis=1)
        f[["v10", "v50", "v90"]] = pd.DataFrame(vint.tolist(), index=f.index)
        cov80 = float(((f["value_usd"] >= f["v10"]) & (f["value_usd"] <= f["v90"])).mean())
        # conformal 보수화 구간 커버리지(같은 MC 합성, 넓힌 마진 사용)
        vint_c = f.apply(lambda r: _mc_value_interval(
            (r["t10"] * np.exp(-qt), r["pd_ton"], r["t90"] * np.exp(qt)),
            (r["u10"] * np.exp(-qu), r["pd_unit"], r["u90"] * np.exp(qu))), axis=1)
        f[["vc10", "_", "vc90"]] = pd.DataFrame(vint_c.tolist(), index=f.index)
        cov80c = float(((f["value_usd"] >= f["vc10"]) & (f["value_usd"] <= f["vc90"])).mean())
        # 단가의 정직성 검사(감사 B-3②): 원자재 가격은 약형 효율 — 드리프트 없는 랜덤워크
        # (=원점 시점 단가 유지)를 못 이기면 "단가를 예측한다"고 주장할 수 없다. 항상 병기.
        rw = train.sort_values("month").groupby("commodity_code")["unit"].last().rename("rw_unit")
        f = f.merge(rw, on="commodity_code", how="left")
        rows.append(dict(
            origin=o, n=len(f),
            # 주지표: WAPE(총합 비율·0값 강건) + MASE(계절나이브 스케일, <1=우수)
            WAPE_ton=round(_wape(f["ton"], f["p_ton"]), 1),
            WAPE_value_decomp=round(_wape(f["value_usd"], f["p_value"]), 1),
            WAPE_value_direct=round(_wape(f["value_usd"], f["p_val_direct"]), 1),
            WAPE_value_naive=round(_wape(f["value_usd"], f["sn_val_f"]), 1),
            MASE_ton=_mase(f, "ton", "p_ton", train, "ton"),
            MASE_unit=_mase(f, "unit", "p_unit", train, "unit"),
            MASE_unit_rw=_mase(f, "unit", "rw_unit", train, "unit"),
            MASE_value_decomp=_mase(f, "value_usd", "p_value", train, "value_usd"),
            MASE_value_direct=_mase(f, "value_usd", "p_val_direct", train, "value_usd"),
            MASE_value_naive=_mase(f, "value_usd", "sn_val_f", train, "value_usd"),
            # Direct 다중기간(h별 독립 모델) — 재귀 대비
            WAPE_value_D=round(_wape(f["value_usd"], f["pd_value"]), 1),
            MASE_value_D=_mase(f, "value_usd", "pd_value", train, "value_usd"),
            MASE_ton_D=_mase(f, "ton", "pd_ton", train, "ton"),
            MASE_unit_D=_mase(f, "unit", "pd_unit", train, "unit"),
            cov80_value=round(cov80, 2),          # 80% 구간 실측 커버리지(목표 0.80)
            cov80_value_conf=round(cov80c, 2),    # conformal 보수화 후(목표 0.80)
            # 이력 비교용(과거 백테스트와의 연속성)
            SMAPE_ton=round(_smape(f["ton"], f["p_ton"]), 1),
            SMAPE_ton_naive=round(_smape(f["ton"], f["sn_ton_f"]), 1),
            SMAPE_unit=round(_smape(f["unit"], f["p_unit"]), 1),
            SMAPE_value_decomp=round(_smape(f["value_usd"], f["p_value"]), 1),
            SMAPE_value_direct=round(_smape(f["value_usd"], f["p_val_direct"]), 1),
            SMAPE_value_naive=round(_smape(f["value_usd"], f["sn_val_f"]), 1),
        ))
    return pd.DataFrame(rows)


def run(db=None, out_dir=None):
    db = db or DB_PATH
    out_dir = out_dir or os.path.join(str(OUT), "forecast_unit")
    os.makedirs(out_dir, exist_ok=True)
    df = build_panel(db)
    last_m = df["month"].max()
    print(f"패널: {df.shape} | 기간 {df['month'].min():%Y-%m}~{last_m:%Y-%m} "
          f"| 광종별 {df.groupby('commodity_code').size().to_dict()}")

    bt = backtest(df)
    print("\n=== 워크포워드 백테스트(12개월) — 주지표 WAPE%·MASE, 참고 SMAPE% ===")
    print(bt.to_string(index=False))
    bt.to_csv(f"{out_dir}/backtest.csv", index=False)

    # 점추정 방식 선택: 백테스트 MASE(금액)로 재귀 vs Direct 자동 판정(env로 강제 가능)
    m_rec = float(bt["MASE_value_decomp"].mean())
    m_dir = float(bt["MASE_value_D"].mean())
    method_naive = "direct" if m_dir < m_rec else "recursive"
    env_forced = os.environ.get("MSR_FORECAST_METHOD")
    if env_forced:
        method = env_forced
    else:
        # E-1(피드백기반_수정플랜 P3): 재귀 근소 우위(격차 축소 추세, 원문 MASE 0.94 vs 1.02)가
        # 노이즈로 뒤집히며 매달 방식이 진동하는 것을 막기 위한 마진 임계 — 직전 채택 방식보다
        # 새 후보가 MARGIN 이상 우수해야만 전환. 로그가 없으면(최초 실행) 단순 최소값 채택.
        MARGIN = 0.05
        prev_method = None
        _c = None
        try:
            _c = duckdb.connect(db, read_only=True)
            _r = _c.execute("SELECT method_selected FROM mart_forecast_method_log "
                             "ORDER BY base_month DESC LIMIT 1").fetchone()
            prev_method = _r[0] if _r else None
        except Exception:
            prev_method = None
        finally:
            if _c is not None:
                _c.close()
        if prev_method is None:
            method = method_naive
        else:
            cur_mase = m_rec if prev_method == "recursive" else m_dir
            other_mase = m_dir if prev_method == "recursive" else m_rec
            other_method = "direct" if prev_method == "recursive" else "recursive"
            method = other_method if (cur_mase - other_mase) > MARGIN else prev_method
    print(f"\n[method] 금액 MASE 재귀 {m_rec:.2f} vs Direct {m_dir:.2f} → 단순채택 {method_naive} "
          f"/ 마진임계 적용 최종채택: {method}")

    log_row = pd.DataFrame([{
        "base_month": last_m.date(), "mase_recursive": round(m_rec, 4), "mase_direct": round(m_dir, 4),
        "gap": round(m_rec - m_dir, 4), "method_selected": method, "method_naive": method_naive,
        "margin_threshold": 0.05, "generated_at": pd.Timestamp.utcnow().floor("s"),
    }])
    _c = None
    try:
        _c = duckdb.connect(db)
        _c.register("_lg", log_row)
        _exists = _c.execute("SELECT count(*) FROM information_schema.tables "
                              "WHERE table_name='mart_forecast_method_log'").fetchone()[0]
        if not _exists:
            _c.execute("CREATE TABLE mart_forecast_method_log AS SELECT * FROM _lg")
        else:
            _c.execute("DELETE FROM mart_forecast_method_log WHERE base_month = ?", [last_m.date()])
            _c.execute("INSERT INTO mart_forecast_method_log SELECT * FROM _lg")
        _c.execute("CHECKPOINT")
        print(f"[method] mart_forecast_method_log 1행 기록(base_month={last_m:%Y-%m})")
    except Exception as e:
        print(f"  [warn] mart_forecast_method_log 기록 실패(무시하고 계속): {e}")
    finally:
        if _c is not None:
            try:
                _c.unregister("_lg")
            except Exception:
                pass
            _c.close()

    # 최종 발행: 최신월 기준 h=1~12. 구간(q10/q90)은 Direct 분위 모델 + conformal 보수화,
    # 점추정은 우승 방식. 발행용 가산폭은 최신 가용 원점 3개(실측 12개월 확보분)로 보정.
    cal_pub = tuple(str((last_m - pd.DateOffset(months=m_)).date())
                    for m_ in (24, 18, 12))
    qt_pub = _conformal_q(df, "ton", cal_pub)
    qu_pub = _conformal_q(df, "unit", cal_pub)
    print(f"[conformal] 발행 가산폭(log, 보정 원점 {cal_pub}): ton {qt_pub:.3f}, unit {qu_pub:.3f}")
    fd_ton, models_ton_d = _direct_forecast(df, "ton", last_m, with_quantiles=True, return_models=True)
    fd_ton = fd_ton.rename(columns={"pred": "d_ton", "q10": "ton_lo", "q90": "ton_hi"})
    fd_unit, models_unit_d = _direct_forecast(df, "unit", last_m, with_quantiles=True, return_models=True)
    fd_unit = fd_unit.rename(columns={"pred": "d_unit", "q10": "unit_lo", "q90": "unit_hi"})
    out = fd_ton.merge(fd_unit, on=["commodity_code", "month", "h"])
    out["ton_lo"] *= np.exp(-qt_pub); out["ton_hi"] *= np.exp(qt_pub)
    out["unit_lo"] *= np.exp(-qu_pub); out["unit_hi"] *= np.exp(qu_pub)
    if method == "direct":
        out["pred_ton"], out["pred_unit_usd_per_ton"] = out["d_ton"], out["d_unit"]
        expl_ton = ("direct", models_ton_d)
        expl_unit = ("direct", models_unit_d)
    else:
        f_ton, model_ton_r, xrows_ton_r, Xtr_ton_r, ytr_ton_r = _recursive_forecast(
            df, "ton", last_m, return_models=True)
        f_ton = f_ton.rename(columns={"pred": "pred_ton"})
        f_unit, model_unit_r, xrows_unit_r, Xtr_unit_r, ytr_unit_r = _recursive_forecast(
            df, "unit", last_m, return_models=True)
        f_unit = f_unit.rename(columns={"pred": "pred_unit_usd_per_ton"})
        out = out.merge(f_ton, on=["commodity_code", "month", "h"]) \
                 .merge(f_unit, on=["commodity_code", "month", "h"])
        expl_ton = ("recursive", model_ton_r, xrows_ton_r, Xtr_ton_r, ytr_ton_r)
        expl_unit = ("recursive", model_unit_r, xrows_unit_r, Xtr_unit_r, ytr_unit_r)
    out["pred_value_usd"] = out["pred_ton"] * out["pred_unit_usd_per_ton"]   # 실지출액
    # 금액 80% 구간 — 물량×단가 몬테카를로 합성(분위 직접 곱 금지)
    vint = out.apply(lambda r: _mc_value_interval(
        (r["ton_lo"], r["d_ton"], r["ton_hi"]), (r["unit_lo"], r["d_unit"], r["unit_hi"])), axis=1)
    out[["pred_value_lo", "_v50", "pred_value_hi"]] = pd.DataFrame(vint.tolist(), index=out.index)
    out = out.drop(columns=["d_ton", "d_unit", "_v50"])
    for c in ("ton_lo", "ton_hi", "unit_lo", "unit_hi", "pred_value_lo", "pred_value_hi"):
        out[c] = out[c].round(1)
    out["pred_value_kusd"] = (out["pred_value_usd"] / 1000).round(1)         # 천달러(과업 단위)
    out["pred_ton"] = out["pred_ton"].round(1)
    out["pred_unit_usd_per_ton"] = out["pred_unit_usd_per_ton"].round(1)
    out["pred_value_usd"] = out["pred_value_usd"].round(0)
    out = out.rename(columns={"month": "target_month"})
    out["base_month"] = last_m.strftime("%Y-%m-%d")
    out["target_month"] = out["target_month"].dt.strftime("%Y-%m-%d")
    out["model_version"] = f"forecast_unit_v2(HistGBM×2 {method}, 단가분해, 80%구간 MC합성)"
    out["basis"] = json.dumps({"backtest": bt.to_dict("records"),
                               "method": f"{method}(백테스트 금액 MASE 재귀 {m_rec:.2f} vs Direct {m_dir:.2f})",
                               "interval": f"q10/q90 분위 HistGBM(log공간) + conformal 보수화(가산폭 ton {qt_pub:.3f}/unit {qu_pub:.3f}, 보정원점 {list(cal_pub)}), 금액구간=물량×단가 lognormal MC 합성",
                               "metrics": "주지표 WAPE·MASE, SMAPE는 이력 비교용",
                               "supervision": "관세청 월간(HS 161코드 바스켓→5광종)",
                               "identity": "value = unit(USD/ton) × ton"},
                              ensure_ascii=False)[:4000]
    out["generated_at"] = pd.Timestamp.utcnow().isoformat(timespec="seconds")

    # 설명가능성(2026-07-24, 스코어카드 4-4 갭 해소): 발행에 실제 쓰인 모델·피처행 그대로
    # SHAP·permutation_importance 계산(재적합 없음) — out_diagnosis_alert.reason/
    # evidence_json과 동일한 패턴으로 reason(자연어)·explain_json(구조화) 컬럼 추가.
    try:
        reasons, explains = _build_explanations(out, expl_ton, expl_unit)
        out["reason"] = reasons
        out["explain_json"] = explains
        print(f"[explain] {len(out)}행에 SHAP 기반 reason/explain_json 부여 완료(method={method})")
    except Exception as e:
        print(f"  [warn] 설명가능성 계산 실패(발행은 계속 진행): {e}")
        out["reason"] = None
        out["explain_json"] = None

    con = duckdb.connect(db)
    con.register("_f", out)
    con.execute("CREATE OR REPLACE TABLE out_import_forecast_unit AS SELECT * FROM _f")
    con.execute("CHECKPOINT"); con.close()
    out.to_csv(f"{out_dir}/forecast_latest.csv", index=False)
    print(f"\n[forecast-unit] out_import_forecast_unit {len(out)}행 (base={last_m:%Y-%m}, h=1~12)")
    print(out[out["h"].isin([1, 6, 12])][["commodity_code", "target_month", "pred_ton",
          "pred_unit_usd_per_ton", "pred_value_kusd"]].to_string(index=False))
    return out


if __name__ == "__main__":
    run()
