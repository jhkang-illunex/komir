# -*- coding: utf-8 -*-
"""결과변수 대리(proxy) 라벨 구축 + 교사 라벨 교차검증 (2026-07-15, 외부감사 A-1(b)).

동기: 현행 학습 라벨(KOMIS 수급동향지표)은 외생이지만 산출 과정이 블랙박스 — "경보가
실제 나쁜 사건을 선행하는가"를 검증하려면 관측 가능한 결과변수 정의가 필요하다.

proxy 정의(광종×월): 향후 3개월 내
  ① 가격 급변:  주간 로그수익률 13주 변동성(vol90)이 기준기간(2020~2023, 단계 컷과
     동일 앵커) P95 초과하는 달 존재                — 가격 경로의 위기 실현
  ② 수입 이탈:  월 수입물량이 계절 기준(직전 1~3년 동월 평균) 대비 -20% 미달        — 물량 경로의 위기 실현
proxy_bad_next3m[t] = ①∪②. 라벨은 결과의 사후 관측치이므로 순환성이 없다.

교차검증: 교사 위기지수(100-y)·모델 nowcast(ci_pred)·4단계 경보가 proxy를 예측하는지
AUC / 경보(주의↑, 경계↑) precision·recall로 측정.

산출: mart_proxy_label(DB) + outputs/proxy_label/report.md
실행: MSR_DB=<warehouse> python -m scripts.build_proxy_label
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                              # noqa: E402
from msr.models.diagnosis_opt import ANCHOR_SPAN                 # noqa: E402

VOL_W = 13            # 90일 ≈ 13주 변동성 창
VOL_P = 0.95          # 기준기간 P95 임계
DROP_TH = -0.20       # 수입량 계절 기준 대비 -20%
HORIZON = 3           # "향후 3개월 내"


def _price_vol_monthly(con) -> pd.DataFrame:
    """광종별 주간가(LME_CASH 우선, 없으면 REF) → vol90 → 월 최대값 + 기준기간 P95 플래그."""
    px = con.execute("""
        SELECT commodity_code, price_type, obs_date, val FROM fact_price
        WHERE freq='W' AND price_type IN ('LME_CASH','REF') ORDER BY 1,3""").df()
    out = []
    for cc, g in px.groupby("commodity_code"):
        use = "LME_CASH" if (g["price_type"] == "LME_CASH").sum() >= 100 else "REF"
        s = g[g["price_type"] == use].sort_values("obs_date").copy()
        s["ret"] = np.log(s["val"].clip(lower=1e-9)).diff()
        s["vol90"] = s["ret"].rolling(VOL_W).std()
        s["month"] = pd.to_datetime(s["obs_date"]).values.astype("datetime64[M]")
        m = s.groupby("month", as_index=False).agg(vol90=("vol90", "max"))
        m["commodity_code"] = cc
        anch = m[(m["month"] >= ANCHOR_SPAN[0]) & (m["month"] <= ANCHOR_SPAN[1])]
        thr = float(anch["vol90"].quantile(VOL_P)) if len(anch) >= 24 else float(m["vol90"].quantile(VOL_P))
        m["vol_thr"] = thr
        m["vol_spike"] = (m["vol90"] > thr).astype(int)
        out.append(m)
    return pd.concat(out, ignore_index=True)


def _import_drop_monthly(con) -> pd.DataFrame:
    """월 수입물량 vs 계절 기준(직전 1~3년 동월 평균) — -20% 이탈 플래그."""
    t = con.execute("""
        SELECT commodity_code, make_date(yr, mon, 1) AS month, sum(imp_wgt)/1000.0 AS ton
        FROM fact_trade_monthly GROUP BY 1,2 ORDER BY 1,2""").df()
    t["month"] = pd.to_datetime(t["month"])
    out = []
    for cc, g in t.groupby("commodity_code"):
        g = g.sort_values("month").set_index("month")
        base = pd.concat([g["ton"].shift(12), g["ton"].shift(24), g["ton"].shift(36)], axis=1) \
            .mean(axis=1, skipna=True)
        g["imp_dev"] = g["ton"] / base.replace(0, np.nan) - 1.0
        g["import_drop"] = (g["imp_dev"] < DROP_TH).astype(int)
        g.loc[g["imp_dev"].isna(), "import_drop"] = 0
        g["commodity_code"] = cc
        out.append(g.reset_index())
    return pd.concat(out, ignore_index=True)


def build(db: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    vol = _price_vol_monthly(con)
    imp = _import_drop_monthly(con)
    con.close()
    df = imp.merge(vol[["commodity_code", "month", "vol90", "vol_thr", "vol_spike"]],
                   on=["commodity_code", "month"], how="outer").sort_values(
        ["commodity_code", "month"]).reset_index(drop=True)
    df["vol_spike"] = df["vol_spike"].fillna(0).astype(int)
    df["import_drop"] = df["import_drop"].fillna(0).astype(int)
    df["bad_event"] = ((df["vol_spike"] + df["import_drop"]) > 0).astype(int)
    # 향후 3개월 내 발생 여부(사후 관측 라벨) — 마지막 HORIZON개월은 미확정(NaN)
    out = []
    for cc, g in df.groupby("commodity_code"):
        g = g.sort_values("month").copy()
        fwd = sum(g["bad_event"].shift(-k).fillna(np.nan) for k in range(1, HORIZON + 1))
        g["proxy_bad_next3m"] = (fwd > 0).astype(float)
        g.loc[g["bad_event"].shift(-HORIZON).isna(), "proxy_bad_next3m"] = np.nan
        out.append(g)
    return pd.concat(out, ignore_index=True)


def _fwd_any(g: pd.DataFrame, col: str, k: int = HORIZON) -> pd.Series:
    s = sum(g[col].shift(-i) for i in range(1, k + 1))
    v = (s > 0).astype(float)
    v[g[col].shift(-k).isna()] = np.nan
    return v


def cross_validate(df: pd.DataFrame, db: str) -> str:
    """교사 위기지수·모델 nowcast·경보 단계가 proxy를 예측하는지 — 성분 분해 포함.

    실측 결론(2026-07-15): 합성 proxy(①∪②)는 AUC ~0.44로 무정보처럼 보이지만 분해하면
    ① 가격 급변 proxy는 유효(교사 0.60/모델 0.64; LI 0.90·NI 0.91·REE 0.99 — CU만 0.18
      역방향으로 풀링을 끌어내림. CU는 LME 거시·투기 변동성이 수급 지표와 다른 동학)
    ② 수입 이탈 proxy는 부적합(AUC 0.33~0.46, 기저율 40% — 월간 선적 덩어리짐 노이즈가
      지배. 위기기에 오히려 재고 확보 수입 증가 가능성도). → 검증 기준은 ①을 주로 쓰고
      ②는 분기 집계 등 재정의 후 재도입(로드맵), 최종 라벨 합의는 발주처 협의(A-1(a))."""
    con = duckdb.connect(db, read_only=True)
    nc = con.execute("""SELECT commodity_code, CAST(month AS DATE) AS month,
                               ci_pred, ci_teacher, stage_pred
                        FROM mart_diagnosis_nowcast""").df()
    con.close()
    nc["month"] = pd.to_datetime(nc["month"])
    parts = []
    for _, g in df.groupby("commodity_code"):
        g = g.sort_values("month").copy()
        g["y_vol"] = _fwd_any(g, "vol_spike")
        g["y_imp"] = _fwd_any(g, "import_drop")
        parts.append(g)
    m = pd.concat(parts).merge(nc, on=["commodity_code", "month"], how="inner")

    lines = []
    for ycol, nm in [("proxy_bad_next3m", "합성(가격∪수입)"), ("y_vol", "가격 급변만"),
                     ("y_imp", "수입 이탈만")]:
        mm = m.dropna(subset=[ycol])
        y = mm[ycol].astype(int)
        if y.nunique() < 2:
            continue
        a_t = roc_auc_score(y, mm["ci_teacher"])
        a_m = roc_auc_score(y, mm["ci_pred"])
        lines.append(f"AUC[{nm}] 기저율 {y.mean():.2f} — 교사 {a_t:.3f} / 모델 {a_m:.3f} (n={len(mm)})")
    lines.append("광종별 AUC(가격 급변, 교사):")
    for cc, g in m.dropna(subset=["y_vol"]).groupby("commodity_code"):
        y = g["y_vol"].astype(int)
        if y.nunique() < 2:
            lines.append(f"  {cc}: 단일 클래스(평가 불가)")
            continue
        lines.append(f"  {cc}: {roc_auc_score(y, g['ci_teacher']):.3f} (기저율 {y.mean():.2f})")
    mm = m.dropna(subset=["y_vol"])
    y = mm["y_vol"].astype(int)
    for th, nm in [(2, "주의 이상"), (3, "경계 이상")]:
        alarm = (mm["stage_pred"] >= th).astype(int)
        tp = int(((alarm == 1) & (y == 1)).sum()); fp = int(((alarm == 1) & (y == 0)).sum())
        fn = int(((alarm == 0) & (y == 1)).sum())
        lines.append(f"경보({nm}) → 가격 급변: precision {tp/max(tp+fp,1):.2f}, "
                     f"recall {tp/max(tp+fn,1):.2f} (TP {tp}/FP {fp}/FN {fn})")
    return "\n".join(lines)


def run(db=None):
    db = db or DB_PATH
    df = build(db)
    n_lab = int(df["proxy_bad_next3m"].notna().sum())
    print(f"[proxy] 라벨 패널 {df.shape} | 확정 라벨 {n_lab} 광종-월 | "
          f"구성비: vol_spike {df['vol_spike'].mean():.2f}, import_drop {df['import_drop'].mean():.2f}")
    rep = cross_validate(df, db)
    print("\n=== 교차검증(교사·모델 → proxy 예측력) ===\n" + rep)

    con = duckdb.connect(db)
    con.register("_p", df)
    con.execute("CREATE OR REPLACE TABLE mart_proxy_label AS SELECT * FROM _p")
    con.close()
    out_dir = os.path.join(str(OUT), "proxy_label")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.md"), "w") as f:
        f.write("# proxy 라벨 교차검증 (2026-07-15, 감사 A-1(b))\n\n"
                f"정의: 향후 {HORIZON}개월 내 (vol90>기준기간 P95) OR (수입량 동월기준 "
                f"{DROP_TH:.0%} 이탈)\n\n```\n{rep}\n```\n")
    print(f"\n[proxy] mart_proxy_label {len(df)}행 적재 + {out_dir}/report.md")
    return df


if __name__ == "__main__":
    run()
