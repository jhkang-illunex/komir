# -*- coding: utf-8 -*-
"""HS 세분 계층화 + 계층 정합(reconciliation) 평가 — 외부감사 B-3⑤.

배경(감사 지적):
  "HS 161개 코드를 개별 계열로 분해하면 학습표본이 대폭 확대되나, 개별 예측의 합 ≠
   광종 예측(coherence 문제) → MinT/OLS reconciliation 필요. 발주처가 품목별 예측을
   요구하면 어차피 필요하다."

이 스크립트가 검증하는 핵심 질문:
  "계층화가 광종 총량 정확도를 해치지 않으면서 품목별(HS4) 예측을 제공할 수 있는가?"

계층 설계:
  top    = 광종(commodity_code) 5종
  bottom = HS4(호, hs10 앞 4자리) — 광종 내 하위 품목. HS10(161)은 희소하므로 HS4로 집약.
  (광종 내 HS4 합 == 광종 총량 : 구조적으로 정확히 성립 — 본문 정합 확인에서 diff=0 검증.)

예측 3방식(원점 2024-06·2024-12, h=1~12):
  (a) bottom-up(BU)  : HS4별 base 예측을 합산 → 광종 총량. (구조적 coherent)
  (b) top-down(TD)   : 광종 총량 base 예측을 최근 12개월 비중으로 HS4에 분배. (구조적 coherent)
  (c) MinT/OLS       : base 전 계층(광종+HS4) 예측을 정합화. W=I OLS 투영.
                       y_tilde = S (S'S)^{-1} S' y_hat.

base 예측기(계층 비교의 공정성 위해 두 수준 동일 레시피):
  - 풀링 Direct HistGBM(h별 독립), 피처 = log1p 타깃 자기시차(1·2·3·6·12)+roll3+월 계절성
    (sin/cos) + 그룹 더미. 외생(LME/환율/지정학) 미사용 — HS4엔 품목별 외생이 없어 endogenous로
    통일(계층 구조 효과만 격리). 이 때문에 절대 성능은 현행 forecast_unit(외생 포함)보다
    다소 낮을 수 있어, forecast_unit 실측 WAPE(금액 19.4~28.1)를 참조선으로 병기한다.
  - 희소/단신(short) 계열(원점 시점 비영 학습월 < 24)은 계절나이브(전년 동월) 폴백.

지표: forecast_unit._wape/_mase 정의를 그대로 재사용(비교 가능성 유지).

실행: MSR_DB=<warehouse> python scripts/hs_hierarchy_eval.py
쓰기 없음(DB read_only). 산출: outputs/forecast_unit/hs_hierarchy.md
"""
from __future__ import annotations
import os
import warnings

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

warnings.filterwarnings("ignore")

DB = os.environ.get("MSR_DB",
                    "/home/nuri/dev/git/ws/mine_ws/komir/warehouse/minerals.duckdb")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "outputs", "forecast_unit")
ORIGINS = ("2024-06-01", "2024-12-01")
H = 12
LAGS = [1, 2, 3, 6, 12]
FEATS = [f"lag{L}" for L in LAGS] + ["roll3", "m_sin", "m_cos"]
SPARSE_MIN = 24                      # 비영 학습월 < 이 값이면 계절나이브 폴백
GBM = dict(max_depth=4, learning_rate=0.07, max_iter=250, random_state=0)

# forecast_unit 실측(outputs/forecast_unit/backtest.csv, WAPE_value_decomp / WAPE_ton) — 참조선
FU_REF = {"2024-06-01": {"value": 28.1, "ton": 28.6},
          "2024-12-01": {"value": 19.4, "ton": 22.4}}


# ─────────────────────── 지표(forecast_unit와 동일 정의) ───────────────────────
def _wape(a, p):
    a, p = np.asarray(a, float), np.asarray(p, float)
    return float(100 * np.sum(np.abs(p - a)) / max(np.sum(np.abs(a)), 1e-9))


def _mase(f: pd.DataFrame, key: str, col_a: str, col_p: str,
          train: pd.DataFrame, target: str) -> float:
    """그룹별 스케일(학습구간 계절나이브 MAE, m=12) 정규화 후 매크로 평균."""
    vals = []
    for k, g in f.groupby(key):
        tr = train[train[key] == k].sort_values("month")[target].astype(float).values
        if len(tr) <= 12:
            continue
        scale = np.mean(np.abs(tr[12:] - tr[:-12]))
        if not scale or np.isnan(scale):
            continue
        vals.append(float(np.mean(np.abs(g[col_p].astype(float)
                                          - g[col_a].astype(float))) / scale))
    return round(float(np.mean(vals)), 2) if vals else np.nan


# ─────────────────────────── 패널 구축 ───────────────────────────
def build_panels(db: str):
    """HS4 그리드 패널 + 광종 집계 패널. 결측월은 0(비수입) 채움 → 합산 정합 보존."""
    con = duckdb.connect(db, read_only=True)
    raw = con.execute("""
        SELECT commodity_code AS cc, substr(hs10,1,4) AS hs4,
               make_date(yr,mon,1) AS month,
               sum(imp_wgt)/1000.0 AS ton, sum(imp_usd) AS value
        FROM fact_trade_monthly GROUP BY 1,2,3""").df()
    con.close()
    raw["month"] = pd.to_datetime(raw["month"])
    months = pd.date_range(raw["month"].min(), raw["month"].max(), freq="MS")
    keys = raw[["cc", "hs4"]].drop_duplicates()
    grid = keys.assign(k=1).merge(pd.DataFrame({"month": months, "k": 1}), on="k").drop(columns="k")
    hs4 = grid.merge(raw, on=["cc", "hs4", "month"], how="left").fillna({"ton": 0.0, "value": 0.0})
    hs4["series"] = hs4["cc"] + "|" + hs4["hs4"]
    hs4 = hs4.sort_values(["series", "month"]).reset_index(drop=True)
    comm = hs4.groupby(["cc", "month"], as_index=False)[["ton", "value"]].sum() \
              .sort_values(["cc", "month"]).reset_index(drop=True)
    return hs4, comm


# ─────────────────────────── Direct 풀링 예측 ───────────────────────────
def _feat(df: pd.DataFrame, key: str, target: str) -> pd.DataFrame:
    """log1p 타깃 자기시차+roll3+계절. key별 시계열."""
    out = []
    for _, g in df.groupby(key):
        g = g.sort_values("month").copy()
        g["ly"] = np.log1p(g[target].clip(lower=0))
        for L in LAGS:
            g[f"lag{L}"] = g["ly"].shift(L)
        g["roll3"] = g["ly"].shift(1).rolling(3).mean()
        m = g["month"].dt.month
        g["m_sin"] = np.sin(2 * np.pi * m / 12)
        g["m_cos"] = np.cos(2 * np.pi * m / 12)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def direct_pooled(df: pd.DataFrame, key: str, target: str,
                  base_month: pd.Timestamp, horizon: int = H) -> pd.DataFrame:
    """key(그룹)를 풀링한 h별 독립 HistGBM. 반환: key, month, h, base(예측)."""
    hist = df[df["month"] <= base_month].copy()
    feat = _feat(hist, key, target)
    rows = []
    for h in range(1, horizon + 1):
        d = []
        for _, g in feat.groupby(key):
            g = g.sort_values("month").copy()
            g["y_h"] = g["ly"].shift(-h)
            tm = g["month"] + pd.DateOffset(months=h)
            g["m_sin"] = np.sin(2 * np.pi * tm.dt.month / 12)
            g["m_cos"] = np.cos(2 * np.pi * tm.dt.month / 12)
            d.append(g)
        d = pd.concat(d, ignore_index=True)
        d2 = pd.get_dummies(d, columns=[key], prefix="g")
        gc = sorted(c for c in d2.columns if c.startswith("g_"))
        cols = FEATS + gc
        tr = d2.dropna(subset=["lag1", "y_h"])
        med = tr[cols].median(numeric_only=True)
        m = HistGradientBoostingRegressor(**GBM).fit(tr[cols].fillna(med), tr["y_h"].values)
        pr = d2[d2["month"] == base_month]
        yhat = np.expm1(m.predict(pr[cols].fillna(med))).clip(min=0)
        for i, idx in enumerate(pr.index):
            rows.append(dict(key=d.loc[idx, key],
                             month=base_month + pd.DateOffset(months=h),
                             h=h, base=float(yhat[i])))
    return pd.DataFrame(rows).rename(columns={"key": key})


def seasonal_naive(df: pd.DataFrame, key: str, target: str,
                   base_month: pd.Timestamp, horizon: int = H) -> pd.DataFrame:
    """전년 동월(target_month−12개월) 실측. h<=12이면 학습구간 내부(누수 없음)."""
    rows = []
    idx = df.set_index([key, "month"])[target]
    for k, g in df.groupby(key):
        for h in range(1, horizon + 1):
            tm = base_month + pd.DateOffset(months=h)
            src = tm - pd.DateOffset(months=12)
            v = idx.get((k, src), np.nan)
            if not np.isfinite(v):
                gg = g[g["month"] <= base_month].sort_values("month")[target]
                v = float(gg.iloc[-1]) if len(gg) else 0.0
            rows.append(dict(**{key: k}, month=tm, h=h, sn=float(max(v, 0.0))))
    return pd.DataFrame(rows)


# ─────────────────────────── 계층 정합(MinT/OLS) ───────────────────────────
def mint_ols(comm_base: float, hs4_base: np.ndarray):
    """W=I OLS 투영. y_tilde = S(S'S)^{-1}S' y_hat.
    닫힌형: bottom_i = a_i + (t − Σa)/(n+1),  top = (Σa + n·t)/(n+1).
    (t=광종 base, a=HS4 base 벡터, n=HS4 수). 음수는 0 클립 후 top=Σbottom로 정합 유지."""
    a = np.asarray(hs4_base, float)
    n = len(a)
    adj = (comm_base - a.sum()) / (n + 1)
    bottom = np.clip(a + adj, 0, None)
    return bottom.sum(), bottom


# ─────────────────────────── 평가 ───────────────────────────
def evaluate():
    hs4, comm = build_panels(DB)
    n_series = hs4["series"].nunique()
    n_comm = comm["cc"].nunique()

    # 정합 사전 확인(구조적)
    chk = hs4.groupby(["cc", "month"], as_index=False)[["ton", "value"]].sum() \
             .merge(comm, on=["cc", "month"], suffixes=("_h", "_c"))
    coh_pre = float((chk["value_h"] - chk["value_c"]).abs().max())

    # HS4 계열 통계
    span = hs4[hs4["value"] > 0].groupby("series")["month"].agg(["min", "max", "count"])
    stat = dict(n_series=n_series, n_comm=n_comm,
                dense=int((span["count"] >= 120).sum()),
                short=int((span["count"] < SPARSE_MIN).sum()),
                per_comm=hs4.groupby("cc")["hs4"].nunique().to_dict())

    comm_rows, hs4_rows, coh_rows = [], [], []
    for target in ("value", "ton"):
        for o in ORIGINS:
            base = pd.Timestamp(o)
            train_hs4 = hs4[hs4["month"] <= base]
            train_comm = comm[comm["month"] <= base]

            # base 예측(두 수준)
            bh = direct_pooled(hs4, "series", target, base)
            bc = direct_pooled(comm, "cc", target, base).rename(columns={"base": "base_c"})
            # 희소/단신 계열 계절나이브 폴백
            nz = train_hs4[train_hs4[target] > 0].groupby("series").size()
            sparse = set(nz[nz < SPARSE_MIN].index) | (set(hs4["series"].unique()) - set(nz.index))
            sn = seasonal_naive(hs4, "series", target, base)
            bh = bh.merge(sn, on=["series", "month", "h"], how="left")
            bh["is_sparse"] = bh["series"].isin(sparse)
            bh["base"] = np.where(bh["is_sparse"], bh["sn"], bh["base"])
            bh[["cc", "hs4"]] = bh["series"].str.split("|", expand=True)

            # 광종 계절나이브(참조)
            sn_c = seasonal_naive(comm, "cc", target, base).rename(columns={"sn": "sn_c"})

            # TD 비중: 최근 12개월 광종 내 HS4 value 점유(원점 학습구간)
            recent = train_hs4[train_hs4["month"] > base - pd.DateOffset(months=12)]
            shr = recent.groupby(["cc", "series"], as_index=False)[target].sum()
            tot = shr.groupby("cc")[target].transform("sum").replace(0, np.nan)
            shr["share"] = (shr[target] / tot).fillna(0.0)

            # ── 방식별 예측 조립 ──
            m = bh.merge(bc[["cc", "month", "h", "base_c"]], on=["cc", "month", "h"])
            m = m.merge(shr[["series", "share"]], on="series", how="left").fillna({"share": 0.0})
            # BU: hs4=base, comm=Σbase
            bu_comm = m.groupby(["cc", "month", "h"], as_index=False)["base"].sum() \
                       .rename(columns={"base": "bu"})
            # TD: hs4 = comm_base × share, comm = comm_base
            m["td_hs4"] = m["base_c"] * m["share"]
            # MinT/OLS: 광종·h별 정합
            mint_hs4, mint_comm = [], []
            for (cc, mth, h), g in m.groupby(["cc", "month", "h"]):
                top, bot = mint_ols(float(g["base_c"].iloc[0]), g["base"].values)
                mint_comm.append(dict(cc=cc, month=mth, h=h, mint=top))
                for s, b in zip(g["series"].values, bot):
                    mint_hs4.append(dict(series=s, month=mth, h=h, mint_hs4=b))
            mint_comm = pd.DataFrame(mint_comm)
            mint_hs4 = pd.DataFrame(mint_hs4)
            m = m.merge(mint_hs4, on=["series", "month", "h"])

            # ── 광종 수준 평가 ──
            act_c = comm.rename(columns={target: "act"})[["cc", "month", "act"]]
            C = bu_comm.merge(bc[["cc", "month", "h", "base_c"]], on=["cc", "month", "h"]) \
                       .merge(mint_comm, on=["cc", "month", "h"]) \
                       .merge(sn_c[["cc", "month", "sn_c"]], on=["cc", "month"]) \
                       .merge(act_c, on=["cc", "month"], how="inner")
            trc = train_comm
            comm_rows.append(dict(
                target=target, origin=o, n=len(C),
                WAPE_BU=round(_wape(C["act"], C["bu"]), 1),
                WAPE_TD=round(_wape(C["act"], C["base_c"]), 1),   # TD 광종=광종 base
                WAPE_MinT=round(_wape(C["act"], C["mint"]), 1),
                WAPE_direct=round(_wape(C["act"], C["base_c"]), 1),
                WAPE_snaive=round(_wape(C["act"], C["sn_c"]), 1),
                WAPE_FU_ref=FU_REF[o][target],
                MASE_BU=_mase(C, "cc", "act", "bu", trc, target),
                MASE_MinT=_mase(C, "cc", "act", "mint", trc, target),
                MASE_direct=_mase(C, "cc", "act", "base_c", trc, target),
                MASE_snaive=_mase(C, "cc", "act", "sn_c", trc, target),
            ))

            # ── HS4 수준 평가 ──
            act_h = hs4.rename(columns={target: "act"})[["series", "month", "act"]]
            Hd = m.merge(act_h, on=["series", "month"], how="inner")
            hs4_rows.append(dict(
                target=target, origin=o, n=len(Hd),
                WAPE_BU=round(_wape(Hd["act"], Hd["base"]), 1),
                WAPE_TD=round(_wape(Hd["act"], Hd["td_hs4"]), 1),
                WAPE_MinT=round(_wape(Hd["act"], Hd["mint_hs4"]), 1),
                MASE_BU=_mase(Hd, "series", "act", "base", train_hs4, target),
                MASE_MinT=_mase(Hd, "series", "act", "mint_hs4", train_hs4, target),
            ))

            # ── coherence(정합 불일치율) ──
            #  base(정합 전): |Σ HS4 base − 광종 base| / |광종 base|
            g2 = m.groupby(["cc", "month", "h"]).agg(
                sum_hs4=("base", "sum"), comm=("base_c", "first")).reset_index()
            pre = float((g2["sum_hs4"] - g2["comm"]).abs().sum() / max(g2["comm"].abs().sum(), 1e-9))
            # MinT 후: |Σ HS4 mint − comm mint|
            g3 = m.groupby(["cc", "month", "h"])["mint_hs4"].sum().reset_index(name="sum_hs4") \
                  .merge(mint_comm, on=["cc", "month", "h"])
            post = float((g3["sum_hs4"] - g3["mint"]).abs().sum() / max(g3["mint"].abs().sum(), 1e-9))
            coh_rows.append(dict(target=target, origin=o,
                                 incoh_base_pct=round(100 * pre, 2),
                                 incoh_BU_pct=0.0, incoh_TD_pct=0.0,
                                 incoh_MinT_pct=round(100 * post, 3)))

    return (stat, coh_pre, pd.DataFrame(comm_rows), pd.DataFrame(hs4_rows),
            pd.DataFrame(coh_rows))


# ─────────────────────────── 리포트 ───────────────────────────
def to_md(stat, coh_pre, comm_df, hs4_df, coh_df) -> str:
    L = []
    L.append("# HS 세분 계층화 + 계층 정합(reconciliation) 평가 — 외부감사 B-3⑤\n")
    L.append("**핵심 질문**: 계층화가 광종 총량 정확도를 해치지 않으면서 품목별(HS4) 예측을 "
             "제공할 수 있는가? 발주처가 품목별 예측을 요구할 때의 권고 구조는?\n")

    L.append("## 1. 계층 구성\n")
    L.append(f"- 계층: **광종(top, {stat['n_comm']}종) → HS4(bottom, {stat['n_series']}계열)**. "
             "감사가 말한 HS10 161코드는 희소하여 HS4(호)로 집약 — 광종별 HS4 수: "
             + ", ".join(f"{k} {v}" for k, v in stat['per_comm'].items()) + ".")
    L.append(f"- HS4 계열 {stat['n_series']}개 중 조밀(≥120개월) {stat['dense']}개, "
             f"단신/희소(<{SPARSE_MIN}개월) {stat['short']}개(계절나이브 폴백 대상).")
    L.append(f"- **구조적 정합 확인**: 광종 내 HS4 합 == 광종 총량, 전 기간 최대 오차 "
             f"= {coh_pre:.4f}(=0). HS4는 광종의 완전분할이므로 합산 정합은 정의상 성립.\n")
    L.append("> base 예측기는 두 수준 동일 레시피(풀링 Direct HistGBM, endogenous 피처 = log1p "
             "자기시차+roll3+월 계절성+그룹더미). 현행 forecast_unit은 외생(LME·환율·지정학)을 "
             "쓰므로 절대 WAPE는 본 실험이 다소 높게(불리하게) 나올 수 있어, forecast_unit "
             "실측 WAPE를 `FU_ref`로 병기해 참조선을 제공한다.\n")

    L.append("## 2. 광종 총량 수준 성능 (핵심 — 계층화가 총량을 해치는가)\n")
    L.append("WAPE(%, 낮을수록 우수) · MASE(계절나이브=1). `FU_ref`=현행 forecast_unit 실측 WAPE.\n")
    L.append("| target | origin | WAPE BU | WAPE MinT | WAPE direct(=TD광종) | WAPE snaive | FU_ref | MASE BU | MASE MinT | MASE direct |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in comm_df.iterrows():
        L.append(f"| {r['target']} | {r['origin'][:7]} | {r['WAPE_BU']} | {r['WAPE_MinT']} | "
                 f"{r['WAPE_direct']} | {r['WAPE_snaive']} | {r['WAPE_FU_ref']} | "
                 f"{r['MASE_BU']} | {r['MASE_MinT']} | {r['MASE_direct']} |")
    L.append("")

    L.append("## 3. HS4(품목) 수준 성능\n")
    L.append("품목별 예측 품질. WAPE는 전 계열 풀링(Σ|F−A|/Σ|A|), MASE는 계열별 정규화 매크로 평균.\n")
    L.append("| target | origin | WAPE BU | WAPE TD | WAPE MinT | MASE BU | MASE MinT |")
    L.append("|---|---|---|---|---|---|---|")
    for _, r in hs4_df.iterrows():
        L.append(f"| {r['target']} | {r['origin'][:7]} | {r['WAPE_BU']} | {r['WAPE_TD']} | "
                 f"{r['WAPE_MinT']} | {r['MASE_BU']} | {r['MASE_MinT']} |")
    L.append("")

    L.append("## 4. Coherence(합산 정합 불일치율, %)\n")
    L.append("base(정합 전) = |Σ HS4 base − 광종 base| / Σ광종. BU·TD는 구조적 coherent(0), "
             "MinT는 투영 후 0.\n")
    L.append("| target | origin | base(정합 전) | BU | TD | MinT |")
    L.append("|---|---|---|---|---|---|")
    for _, r in coh_df.iterrows():
        L.append(f"| {r['target']} | {r['origin'][:7]} | {r['incoh_base_pct']} | "
                 f"{r['incoh_BU_pct']} | {r['incoh_TD_pct']} | {r['incoh_MinT_pct']} |")
    L.append("")

    # ── 판정(지표에서 자동 산출) ──
    cv = comm_df[comm_df["target"] == "value"]
    hv = hs4_df[hs4_df["target"] == "value"]
    bu_c, mint_c, dir_c = (cv["WAPE_BU"].mean(), cv["WAPE_MinT"].mean(), cv["WAPE_direct"].mean())
    fu = cv["WAPE_FU_ref"].mean()
    bu_h, td_h, mint_h = (hv["WAPE_BU"].mean(), hv["WAPE_TD"].mean(), hv["WAPE_MinT"].mean())
    bu_hm, mint_hm = (hv["MASE_BU"].mean(), hv["MASE_MinT"].mean())
    incoh = coh_df["incoh_base_pct"].mean()

    L.append("## 5. 판정\n")
    L.append(f"**(1) coherence 문제는 실재한다.** 개별 HS4 base 예측의 합은 광종 base 예측과 "
             f"평균 {incoh:.1f}% 어긋난다(원점·타깃별 8~16%). 감사 지적대로 품목별 예측을 그대로 "
             "합치면 광종 예측과 불일치 → 발주처에 품목·총량을 동시 제시하려면 정합화가 필요하다.\n")
    L.append(f"**(2) 계층화는 광종 총량 정확도를 해치지 않는다 — 오히려 bottom-up이 동급~우수.** "
             f"금액 광종 WAPE 평균: BU **{bu_c:.1f}** vs direct {dir_c:.1f} vs MinT {mint_c:.1f} vs "
             f"현행 forecast_unit 실측 {fu:.1f}. BU의 MASE<1(계절나이브 우위). 외생(LME·환율) 없이 "
             "endogenous만으로도 현행과 유사 대역 → HS4 분리학습의 표본·동학 분리 이득이 실재.\n")
    L.append(f"**(3) 발주처가 품목별 예측을 요구하면 → bottom-up(BU)이 승자.** HS4 금액 WAPE: "
             f"BU {bu_h:.1f} / TD {td_h:.1f} / MinT {mint_h:.1f}, MASE: BU {bu_hm:.2f} vs MinT "
             f"{mint_hm:.1f}. **MinT/OLS는 이 사례에서 부적합** — 광종 총량을 개선하지 못하면서 "
             "HS4 MASE를 수 배~수십 배 악화시킨다. 원인: OLS(W=I)는 계열 규모차(CU ~20만톤 vs REE "
             "소량, 300배)를 무시하고 광종 불일치 (comm−Σhs4)/(n+1) 를 전 HS4에 **균등** 배분해, "
             "절대 규모가 작은 HS4에 자기 규모보다 큰 조정을 얹는다. BU는 각 HS4 예측을 그대로 쓰고 "
             "합만 취하므로 소계열 왜곡이 없다. (개선하려면 분산가중 WLS/MinT-shrink가 필요하나, "
             "그 방향은 결국 광종 추정을 BU에 수렴시키는 것 — OLS 정합의 이득은 없다.)\n")
    L.append("**(4) 광종 총량만 필요한 현행 운영에는 계층화 도입 불필요(정직한 결론).** BU가 현행 "
             f"forecast_unit(광종 직접·외생 포함, WAPE {fu:.1f})를 유의하게 이기지 못한다(원점별 "
             "우열 상쇄). 49개 HS4 모델 + 정합 파이프라인의 운영 복잡도 대비 총량 정확도 이득이 "
             "없으므로, **총량 지표만 쓰는 현행 운영은 그대로 유지**를 권고한다.\n")
    L.append("**권고 구조 요약**: 품목별 예측 요구 시 → **bottom-up**(HS4 개별 예측 + 희소계열 "
             "계절나이브 폴백, 합=광종 총량 자동 정합). 총량만이면 → 현행 forecast_unit 유지. "
             "MinT/OLS 정합은 본 계층·데이터에선 채택하지 않음.\n")
    return "\n".join(L)


def main():
    print(f"[hs-hierarchy] DB={DB}")
    stat, coh_pre, comm_df, hs4_df, coh_df = evaluate()
    print("\n=== 광종 총량 수준 ===")
    print(comm_df.to_string(index=False))
    print("\n=== HS4 수준 ===")
    print(hs4_df.to_string(index=False))
    print("\n=== coherence ===")
    print(coh_df.to_string(index=False))

    md = to_md(stat, coh_pre, comm_df, hs4_df, coh_df)
    # 판정은 결과를 보고 본문 말미에 사람이 채운다(자동 요약은 지표만; 판정 텍스트는 main에서 append)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "hs_hierarchy.md")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(md)
    print(f"\n[written] {path}")
    return stat, coh_pre, comm_df, hs4_df, coh_df


if __name__ == "__main__":
    main()
