# -*- coding: utf-8 -*-
"""수입 예측 베이스라인.
raw_customs_monthly(월간 수입) → 광종·월 패널 → 지연/계절 피처 →
시간순 홀드아웃 백테스트(MAE/R2) + 최종모델 재귀예측(h=1..12).
산출: mart_monthly_forecast_input(입력 패널), out_import_forecast(예측).
타깃: volume(imp_wgt, kg) · value(imp_usd, $).
"""
import numpy as np, pandas as pd, duckdb
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from ..config import DB_PATH

_LAGS = [1, 2, 3, 12]
_FEATS = [f"lag{l}" for l in _LAGS] + ["roll3", "msin", "mcos"]
_TARGETS = ("volume", "value")


def walk_forward(df, target, feats, group="commodity_code", tcol="date", split=None):
    """단일 시간분할 백테스트(유틸). df<split 학습 → df>=split 평가."""
    df = df.sort_values(tcol)
    tr = df[df[tcol] < split]; te = df[df[tcol] >= split]
    codes = {c: i for i, c in enumerate(sorted(df[group].unique()))}
    Xtr = tr[feats].assign(_g=tr[group].map(codes)); Xte = te[feats].assign(_g=te[group].map(codes))
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=3,
        categorical_features=[len(feats)], random_state=42).fit(Xtr, tr[target])
    pred = m.predict(Xte)
    return {"MAE": round(mean_absolute_error(te[target], pred), 3),
            "R2": round(r2_score(te[target], pred), 3), "n_test": len(te)}, m


def _monthly_panel(db):
    """광종·월 수입 합계. 정본 팩트(fact_trade_monthly)에서 읽음(단일 소스).
    광종별 월간 그리드로 reindex(결측월=0) — 수입 없는 달이 행에서 빠지면
    행 기반 lag가 달력과 어긋나므로(builders DR3와 동일 원리) 그리드를 보장한다."""
    con = duckdb.connect(db, read_only=True)
    df = con.execute("""
        SELECT commodity_code,
               make_date(yr, mon, 1) AS date,
               SUM(imp_wgt) AS volume, SUM(imp_usd) AS value
        FROM fact_trade_monthly
        WHERE commodity_code IS NOT NULL AND mon IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
    """).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    if df.empty:
        return df
    end = df["date"].max()
    frames = []
    for c, g in df.groupby("commodity_code"):
        grid = pd.date_range(g["date"].min(), end, freq="MS")
        g = (g.set_index("date").reindex(grid)
               .rename_axis("date").reset_index())
        g["commodity_code"] = c
        g[["volume", "value"]] = g[["volume", "value"]].fillna(0.0)  # 결측월=수입 0
        frames.append(g)
    return pd.concat(frames, ignore_index=True)[["commodity_code", "date", "volume", "value"]]


def _build_feats(d):
    """광종별 지연·롤링·계절 피처(그룹 경계 유지). commodity_code 컬럼 보존."""
    d = d.sort_values(["commodity_code", "date"]).copy()
    grp = d.groupby("commodity_code")["y"]
    for l in _LAGS:
        d[f"lag{l}"] = grp.shift(l)
    d["roll3"] = grp.transform(lambda s: s.shift(1).rolling(3).mean())
    mo = d["date"].dt.month
    d["msin"] = np.sin(2 * np.pi * mo / 12.0)
    d["mcos"] = np.cos(2 * np.pi * mo / 12.0)
    return d


def _fit(train, codes):
    X = train[_FEATS].assign(_g=train["commodity_code"].map(codes))
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_depth=3,
        categorical_features=[len(_FEATS)], random_state=42).fit(X, train["y"])


def run(db=None, model_version="fc_hgb_v1", horizon=12, test_months=6):
    """전체 파이프라인 실행 → 마트·예측 적재. 반환: metrics·행수 요약."""
    db = db or DB_PATH
    panel = _monthly_panel(db)
    now = pd.Timestamp.now().floor("s")
    codes = {c: i for i, c in enumerate(sorted(panel["commodity_code"].unique()))}
    mart_rows, out_rows, metrics = [], [], {}

    for target in _TARGETS:
        d = panel[["commodity_code", "date", target]].rename(columns={target: "y"})
        d["y"] = d["y"].astype(float).fillna(0.0)
        for _, r in d.iterrows():
            mart_rows.append((r["commodity_code"], target, r["date"].date(), float(r["y"]), None))

        usable = _build_feats(d).dropna(subset=_FEATS + ["y"]).copy()
        months = sorted(usable["date"].unique())
        if len(months) < test_months + 2:
            metrics[target] = {"skipped": f"usable months={len(months)} (<{test_months+2})"}
            continue

        split = months[-test_months]
        tr, te = usable[usable["date"] < split], usable[usable["date"] >= split].copy()
        model = _fit(tr, codes)
        pred = model.predict(te[_FEATS].assign(_g=te["commodity_code"].map(codes)))
        metrics[target] = {"MAE": round(float(mean_absolute_error(te["y"], pred)), 2),
                           "R2": round(float(r2_score(te["y"], pred)), 3), "n_test": int(len(te))}
        te["_resid"] = te["y"].values - pred
        resid_std = te.groupby("commodity_code")["_resid"].std().to_dict()
        pooled = float(np.nanstd(te["_resid"].values))

        final = _fit(usable, codes)
        base_date = panel["date"].max()
        for c in codes:
            series = d[d["commodity_code"] == c].sort_values("date")["y"].astype(float).tolist()
            sc = resid_std.get(c, np.nan)
            # NaN(잔차 <2점)만 pooled로 폴백. sd==0(퇴화: 잔차 전부 동일)은 결측이 아니므로
            # 그대로 사용 — 결측/퇴화 혼동 제거(0폭 구간은 데이터가 말하는 그대로).
            sd = float(sc) if sc == sc else (pooled if pooled == pooled else 0.0)
            for h in range(1, horizon + 1):
                lag = lambda l: series[-l] if len(series) >= l else np.nan
                frow = {f"lag{l}": lag(l) for l in _LAGS}
                frow["roll3"] = np.mean(series[-3:]) if len(series) >= 3 else np.nan
                fmonth = (base_date.month + h - 1) % 12 + 1
                frow["msin"] = np.sin(2 * np.pi * fmonth / 12.0)
                frow["mcos"] = np.cos(2 * np.pi * fmonth / 12.0)
                Xf = pd.DataFrame([frow])[_FEATS].assign(_g=codes[c])
                yh = max(0.0, float(final.predict(Xf)[0]))
                series.append(yh)
                z = 1.28 * sd * np.sqrt(h)
                out_rows.append((c, target, base_date.date(), h, round(yh, 4),
                                 round(max(0.0, yh - z), 4), round(yh + z, 4), model_version, now))

    from ..storage import db as store
    mart_df = pd.DataFrame(mart_rows, columns=["commodity_code", "target", "obs_date", "y_val", "feat_json"])
    out_df = pd.DataFrame(out_rows, columns=["commodity_code", "target", "base_date", "horizon",
                                             "yhat", "yhat_lo", "yhat_hi", "model_version", "generated_at"])
    store.upsert_df(mart_df, "mart_monthly_forecast_input", del_where="1=1")
    store.upsert_df(out_df, "out_import_forecast", del_where="1=1")
    return {"metrics": metrics, "mart_rows": len(mart_df), "forecast_rows": len(out_df),
            "commodities": list(codes), "base_date": str(panel["date"].max().date())}
