# -*- coding: utf-8 -*-
"""지정학 지수(2-2) ↔ Tier2 물리 시계열 연계 검증 (2026-07-25).

목적: 뉴스 기반 geo_index가 이번에 확보한 **물리적 결과 변수**(칠레 구리 광산
생산, CO LME 재고)와 시간적으로 어떻게 연결되는지 실증 — 지수의 실물 타당성
검증(validation)이지 피처 채택 검정이 아님(진단·예측 채택 검정은 별도 스크립트).

방법:
  1) 선행상관: geo_index 월간(idx_value, freq='M')과 물리 변수의 log 변화율을
     시차 k=-6..+6에서 Spearman 상관(k>0 = 지수가 k개월 선행).
  2) 고지수 이벤트 스터디: 지수 상위 10% 월 이후 h=0..3개월 누적 물리 변화의
     평균을 나머지 월과 비교, 원형 블록 순열(블록 6개월, 2000회)로 p값.
     (자기상관 감안 — i.i.d. 순열은 p를 과소평가하므로 블록 순열 사용)

대상 쌍:
  CU: geo_index(CU) vs CL_CU_PROD_MINE(Cochilco) — 파업·사회불안·조업차질의
      대표 사례(2017-02 Escondida 파업 등)가 뉴스와 생산 양쪽에 남는 경로.
  CO: geo_index(CO) vs CO_LME_STOCK_T(USGS) — 재고는 완충 변수라 연결이 약할
      것으로 예상(정직 기대치), 대칭 검증용.

실행: MSR_DB=<warehouse> python -m scripts.geo_tier2_linkage
산출: outputs/model_opt/geo_tier2_linkage.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT  # noqa: E402

LAGS = range(-6, 7)
TOP_Q = 0.90
H_CUM = 3
N_PERM = 2000
BLOCK = 6
SEED = 20260725


def load_pair(db: str, cc: str, indicator: str) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    idx = con.execute("""SELECT period, idx_value FROM geo_index
        WHERE commodity_code=? AND freq='M' ORDER BY 1""", [cc]).df()
    phy = con.execute("""SELECT obs_date, val FROM fact_indicator
        WHERE indicator=? ORDER BY 1""", [indicator]).df()
    con.close()
    idx["month"] = pd.to_datetime(idx["period"])
    phy["month"] = pd.to_datetime(phy["obs_date"])
    d = idx[["month", "idx_value"]].merge(phy[["month", "val"]], on="month",
                                          how="inner").sort_values("month")
    d["idx_value"] = pd.to_numeric(d["idx_value"], errors="coerce")
    d["dlog"] = np.log(pd.to_numeric(d["val"], errors="coerce")).diff()
    return d.reset_index(drop=True)


def lead_lag(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for k in LAGS:
        # k>0: 지수(t) vs 물리 변화(t+k) — 지수가 k개월 선행
        x = d["idx_value"]
        y = d["dlog"].shift(-k)
        ok = x.notna() & y.notna()
        if ok.sum() < 24:
            continue
        r, p = spearmanr(x[ok], y[ok])
        rows.append(dict(k=k, n=int(ok.sum()), spearman=float(r), p=float(p)))
    return pd.DataFrame(rows)


def high_idx_event_study(d: pd.DataFrame, rng: np.random.Generator) -> dict:
    thr = d["idx_value"].quantile(TOP_Q)
    hi = (d["idx_value"] >= thr).to_numpy()
    # h=0..H_CUM 누적 log 변화
    cum = sum(d["dlog"].shift(-h) for h in range(H_CUM + 1))
    cum = cum.to_numpy()
    ok = ~np.isnan(cum)

    def gap(mask: np.ndarray) -> float:
        a = cum[mask & ok]
        b = cum[(~mask) & ok]
        if len(a) < 3 or len(b) < 3:
            return np.nan
        return float(np.nanmean(a) - np.nanmean(b))

    obs = gap(hi)
    n = len(d)
    perms = []
    for _ in range(N_PERM):
        s = int(rng.integers(0, n))          # 원형 블록 시프트(자기상관 보존)
        perms.append(gap(np.roll(hi, s)))
    perms = np.array([p for p in perms if not np.isnan(p)])
    p_two = float(np.mean(np.abs(perms) >= abs(obs))) if len(perms) else np.nan
    return dict(threshold=float(thr), n_hi=int((hi & ok).sum()), obs_gap=obs,
                p_perm=p_two)


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    rng = np.random.default_rng(SEED)
    out = {}
    for cc, ind, label in [("CU", "CL_CU_PROD_MINE", "칠레 광산생산(Cochilco)"),
                           ("CO", "CO_LME_STOCK_T", "LME 코발트 재고(USGS)")]:
        d = load_pair(db, cc, ind)
        ll = lead_lag(d)
        es = high_idx_event_study(d, rng)
        out[cc] = dict(label=label, n=len(d),
                       span=f"{d['month'].min().date()}~{d['month'].max().date()}",
                       ll=ll, es=es)
        best = ll.loc[ll["spearman"].abs().idxmax()]
        print(f"[{cc}] {label} n={len(d)} | 최대 |ρ| k={int(best['k'])}: "
              f"ρ={best['spearman']:+.3f}(p={best['p']:.3f}) | 고지수 이벤트: "
              f"gap={es['obs_gap']:+.4f} p_perm={es['p_perm']:.3f} "
              f"(상위10% {es['n_hi']}개월, h=0..{H_CUM} 누적)")
    write_report(out)


def write_report(out: dict):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "geo_tier2_linkage.md")
    L = ["# 지정학 지수 ↔ Tier2 물리 시계열 연계 검증\n",
         "작성: 2026-07-25 · 지수의 실물 타당성 검증(피처 채택 검정 아님 — "
         "그쪽은 diagnosis_tier2_eval/forecast_tier2_exog_eval 참조). "
         "선행상관 k>0 = 지수가 물리 변수를 k개월 선행. 이벤트 스터디는 지수 "
         "상위 10% 월의 h=0..3 누적 log변화 평균차, 원형 블록 순열 p(2000회).\n"]
    for cc, o in out.items():
        L.append(f"\n## {cc} — {o['label']} ({o['span']}, n={o['n']})\n")
        L.append("| k(개월) | n | Spearman ρ | p |")
        L.append("|---|---|---|---|")
        for _, r in o["ll"].iterrows():
            L.append(f"| {int(r['k']):+d} | {int(r['n'])} | {r['spearman']:+.3f} "
                     f"| {r['p']:.3f} |")
        es = o["es"]
        L.append(f"\n고지수 이벤트 스터디: 임계 {es['threshold']:.1f}, 상위월 "
                 f"{es['n_hi']}개, 누적변화 평균차 {es['obs_gap']:+.4f} "
                 f"(순열 p={es['p_perm']:.3f})")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[geo_tier2_linkage] 리포트 → {path}")


if __name__ == "__main__":
    main()
