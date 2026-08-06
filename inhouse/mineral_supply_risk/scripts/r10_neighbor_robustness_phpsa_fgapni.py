# -*- coding: utf-8 -*-
"""ph_psa·fgap_ni 이웃 강건성 점검 (2026-08-04 ㊾ 재현성 검토 후속).

WORKLOG ㊾/r10_repro_check_260804.md가 결정론 재현·시드 강건성·절단 대조·재발행
효과(08-01 cron)까지는 확인했으나, r10_retune_harness.py가 명시하는 세 번째 축
"이웃 강건성"(등록 파라미터를 살짝 흔들어도 유의가 유지되는지, 07-25 gsev_z13
9설정 스윕과 동일 방법론)은 아직 미수행이었음 — 이 스크립트로 보완.

- ph_psa: SERIES_SPEC 등록 lag_days=75(발표지연 as-of 보수치)의 이웃
  {45,60,75,90,105}을 스윕. 하네스와 동일 as-of 처리(build_new_features 로직 재현).
- fgap_ni: build_derived_features의 z-window(기본 24, GROUPS lag=120 고정)의 이웃
  {16,20,24,28,32}를 스윕. gap 정의(수입합-수출합)·lag은 등록값 유지.

판정 규칙은 하네스와 동일(QWK CI 하한>0 채택, 그 외 방향긍정 보류) — 등록값
1점만이 아니라 이웃 다수에서도 넘는지가 이 점검의 핵심 질문.
"""
import os
import sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG      # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics, e2_delta_classifier  # noqa: E402
from scripts.diagnosis_aux_features_eval import build_aux, INV_F, _asof_join   # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                           # noqa: E402
from scripts.diagnosis_priority_feeds_eval import build_pmi, PMI_F, bootstrap_diff  # noqa: E402
from scripts.diag_refine1 import build_refined                                 # noqa: E402
from scripts.r10_retune_harness import _z                                      # noqa: E402


def build_base_panel(db):
    df = build_panel(db)
    df = add_dynamics(df); df = build_aux(db, df)
    df = exch.build_cninv(db, df); df = build_pmi(db, df); df = build_refined(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    base_feats = nolag + INV_F + exch.CNINV_F  # PER_CC_CHAMP["NI"] (하네스와 동일)
    return df, base_feats, nolag


def ph_psa_feats_for_lag(db, df, lag):
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT commodity_code, indicator, CAST(obs_date AS DATE)
        obs_date, CAST(val AS DOUBLE) val FROM fact_indicator
        WHERE indicator='PH_NI_EXPORT_WGT_PSA' ORDER BY obs_date""").df()
    con.close()
    ind["obs_date"] = pd.to_datetime(ind["obs_date"])
    x = ind.sort_values("obs_date").copy()
    name = f"ph_psa_l{lag}"
    feats = [f"{name}_yoy", f"{name}_chg3", f"{name}_z24"]
    v = x["val"]
    x[feats[0]] = v.pct_change(12)
    x[feats[1]] = v.pct_change(3)
    x[feats[2]] = _z(v)
    x["avail_date"] = x["obs_date"] + pd.Timedelta(days=lag)
    x["commodity_code"] = "NI"
    x = x.replace([np.inf, -np.inf], np.nan)
    panel = _asof_join(df.copy(), x, feats, by_commodity=True)
    return panel, feats


def fgap_ni_feats_for_window(db, df, w):
    con = duckdb.connect(db, read_only=True)
    ind = con.execute("""SELECT commodity_code cc, indicator,
        CAST(obs_date AS DATE) obs_date, CAST(val AS DOUBLE) val
        FROM fact_indicator WHERE indicator LIKE '%_WGT'""").df()
    con.close()
    ind["obs_date"] = pd.to_datetime(ind["obs_date"])
    piv = ind.pivot_table(index="obs_date", columns="indicator", values="val")
    imp = [c for c in ["CN_NI_IMPORT_WGT", "JP_NI_IMPORT_WGT", "DE_NI_IMPORT_WGT"]
           if c in piv.columns]
    expo = [c for c in ["ID_NI_EXPORT_WGT", "PH_NI_EXPORT_WGT", "NO_NI_EXPORT_WGT"]
            if c in piv.columns]
    base = piv[imp].sum(axis=1) - piv[expo].sum(axis=1)
    name = f"fgap_ni_w{w}"
    feats = [f"{name}_z24", f"{name}_chg3"]
    f = pd.DataFrame({"obs_date": base.index})
    f[feats[0]] = _z(base.reset_index(drop=True), w=w, mp=max(6, w // 2))
    f[feats[1]] = base.reset_index(drop=True).diff(3)
    f["commodity_code"] = "NI"
    f["avail_date"] = f["obs_date"] + pd.Timedelta(days=120)  # 등록 lag 고정
    f = f.replace([np.inf, -np.inf], np.nan)
    panel = _asof_join(df.copy(), f, feats, by_commodity=True)
    return panel, feats


def run_sweep(label, values, build_fn, db, df, base_feats, nolag, rng):
    print(f"\n=== {label} 이웃 강건성 스윕 ===")
    d1 = df[df["commodity_code"] == "NI"].reset_index(drop=True)
    base = e2_delta_classifier(d1, base_feats, "Logistic")
    n_adopt = 0
    rows = []
    for v in values:
        panel, feats = build_fn(db, df, v)
        d1v = panel[panel["commodity_code"] == "NI"].reset_index(drop=True)
        cov = d1v[feats[0]].notna().mean()
        r = e2_delta_classifier(d1v, base_feats + feats, "Logistic")
        b = bootstrap_diff(d1v, base_feats, base_feats + feats, nolag, rng)
        adopt = b["qwk_ci"][0] > 0
        n_adopt += adopt
        tag = "채택" if adopt else "보류"
        print(f"  값={v}: 커버리지 {cov:.0%} QWK {r['QWK']:.4f} | 부트스트랩 CI "
              f"[{b['qwk_ci'][0]:+.4f},{b['qwk_ci'][1]:+.4f}] P={b['qwk_p']:.3f} → {tag}")
        rows.append((v, cov, r["QWK"], b["qwk_ci"], b["qwk_p"], adopt))
    print(f"  → {label}: 이웃 {len(values)}개 중 {n_adopt}개 채택 기준 통과 "
          f"(기준선 QWK {base['QWK']:.4f})")
    return rows, n_adopt


def main():
    db = os.environ["MSR_DB"]
    df, base_feats, nolag = build_base_panel(db)
    print(f"패널 종점: {df['obs_date'].max().date()} (base_feats={len(base_feats)}개)")
    rng = np.random.default_rng(0)

    ph_rows, ph_adopt = run_sweep(
        "ph_psa (lag_days 이웃, 등록값=75)", [45, 60, 75, 90, 105],
        ph_psa_feats_for_lag, db, df, base_feats, nolag, rng)

    fg_rows, fg_adopt = run_sweep(
        "fgap_ni (z-window 이웃, 등록값=24)", [16, 20, 24, 28, 32],
        fgap_ni_feats_for_window, db, df, base_feats, nolag, rng)

    print("\n=== 요약 ===")
    print(f"ph_psa: {ph_adopt}/5 이웃에서 채택 기준(QWK CI 하한>0) 통과")
    print(f"fgap_ni: {fg_adopt}/5 이웃에서 채택 기준(QWK CI 하한>0) 통과")


if __name__ == "__main__":
    main()
