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
FX_CSV = ("/home/nuri/dev/git/ws/mine_ws/documents/1. 광물가격, 재고량, 지수 등 (1)/"
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
                        horizon: int = H) -> pd.DataFrame:
    """base_month까지 학습 → h=1..horizon 재귀 예측. 외생은 최종 관측값 고정."""
    hist = df[df["month"] <= base_month].copy()
    feat = _features(hist, target)
    model, cc_cols = _fit(feat)
    preds = []
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
            new = last.copy(); new["month"] = tgt_m; new[target] = yhat
            state[cc] = pd.concat([g, new.to_frame().T], ignore_index=True)
    return pd.DataFrame(preds)


# ─────────────────────────── 검증·발행 ───────────────────────────
def _smape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    return float(100 * np.mean(2 * np.abs(p - a) / (np.abs(a) + np.abs(p) + 1e-9)))


def backtest(df: pd.DataFrame, origins=("2024-06-01", "2024-12-01")) -> pd.DataFrame:
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
        rows.append(dict(
            origin=o, n=len(f),
            SMAPE_ton=round(_smape(f["ton"], f["p_ton"]), 1),
            SMAPE_ton_naive=round(_smape(f["ton"], f["sn_ton"].fillna(f["ton"].mean())), 1),
            SMAPE_unit=round(_smape(f["unit"], f["p_unit"]), 1),
            SMAPE_value_decomp=round(_smape(f["value_usd"], f["p_value"]), 1),
            SMAPE_value_direct=round(_smape(f["value_usd"], f["p_val_direct"]), 1),
            SMAPE_value_naive=round(_smape(f["value_usd"], f["sn_val"].fillna(f["value_usd"].mean())), 1),
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
    print("\n=== 워크포워드 백테스트(12개월, SMAPE%) ===")
    print(bt.to_string(index=False))
    bt.to_csv(f"{out_dir}/backtest.csv", index=False)

    # 최종 발행: 최신월 기준 h=1~12
    f_ton = _recursive_forecast(df, "ton", last_m).rename(columns={"pred": "pred_ton"})
    f_unit = _recursive_forecast(df, "unit", last_m).rename(columns={"pred": "pred_unit_usd_per_ton"})
    out = f_ton.merge(f_unit, on=["commodity_code", "month", "h"])
    out["pred_value_usd"] = out["pred_ton"] * out["pred_unit_usd_per_ton"]   # 실지출액
    out["pred_value_kusd"] = (out["pred_value_usd"] / 1000).round(1)         # 천달러(과업 단위)
    out["pred_ton"] = out["pred_ton"].round(1)
    out["pred_unit_usd_per_ton"] = out["pred_unit_usd_per_ton"].round(1)
    out["pred_value_usd"] = out["pred_value_usd"].round(0)
    out = out.rename(columns={"month": "target_month"})
    out["base_month"] = last_m.strftime("%Y-%m-%d")
    out["target_month"] = out["target_month"].dt.strftime("%Y-%m-%d")
    out["model_version"] = "forecast_unit_v1(HistGBM×2 재귀, 단가분해)"
    out["basis"] = json.dumps({"backtest_SMAPE": bt.to_dict("records"),
                               "supervision": "관세청 월간(HS 161코드 바스켓→5광종)",
                               "identity": "value = unit(USD/ton) × ton"},
                              ensure_ascii=False)[:1500]
    out["generated_at"] = pd.Timestamp.utcnow().isoformat(timespec="seconds")

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
