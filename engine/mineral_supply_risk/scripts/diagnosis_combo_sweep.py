# -*- coding: utf-8 -*-
"""진단 보조신호 피처그룹 전수 조합 스윕 (2026-07-24, 사용자 지시
"수집된·수집가능한 피처로 가능한 모든 케이스를 조합").

피처 그룹 7종의 파워셋(2^7=128 조합, 기반 NOLAG는 항상 포함)을 풀링 Δ분류 프레임
(E2 Logistic·워크포워드 3폴드)으로 전수 평가하고, (QWK↑, chg_acc↑, FAR↓) 파레토
프런티어와 상위 조합 부트스트랩(vs v1.7 채택 동작점)을 산출한다. CU·NI 단독도
6그룹(쿼터성 제외) 64조합씩 스윕.

그룹 정의(빌더·as-of 누수방지 포함):
  INV    : LME 재고(CU·NI, 2007~)            — v1.5 유의
  CNINV  : SHFE(CU·NI)·GFEX(LI) 재고(2005~)  — NI 유의·CU 기각
  TRD    : Comtrade 무역흐름(REE·CO, 2016~)  — 방향 긍정
  PMICN  : 중국 PMI 공식·차이신(2008~)        — v1.7 유의(전부결합 기여)
  PMIG   : 미국 ISM·유로 PMI ⚠피드 꼬리 낡음(2025-09까지) — 신선도 마스크 60일
  REALEST: 중국 부동산 국방경기지수 ⚠2025-12까지 — 신선도 마스크 75일
  CLN    : 기존 거시 12종(2021-06~) ⚠커버리지 교란으로 기각됐던 그룹 — 해석 주의 플래그

실행: MSR_DB=<warehouse> python -m scripts.diagnosis_combo_sweep
산출: outputs/model_opt/diagnosis_combo_sweep.md
"""
from __future__ import annotations
import itertools, os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                      # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import add_dynamics                # noqa: E402
from scripts.diagnosis_aux_features_eval import (                          # noqa: E402
    build_aux, INV_F, CLNW_F, CLNM_F, _asof_join, e2_delta_classifier,
)
import scripts.diagnosis_exch_inventory_eval as exch                       # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                        # noqa: E402
    build_trd, build_pmi, TRD_F, PMI_F, bootstrap_diff,
)

PMIG_F = ["ism", "ism_chg3", "eupmi"]
REALEST_F = ["re_lvl", "re_yoy"]


def _series_feat(ser: pd.DataFrame, code: str, fn, name: str, lag_days: int,
                 stale_days: int, panel: pd.DataFrame) -> pd.DataFrame:
    x = ser[ser["series_code"] == code].sort_values("obs_date").reset_index(drop=True)
    f = pd.DataFrame({"avail_date": x["obs_date"] + pd.Timedelta(days=lag_days),
                      name: fn(pd.to_numeric(x["val"], errors="coerce")),
                      f"_{name}_src": x["obs_date"]}).dropna(subset=[name])
    out = _asof_join(panel, f, [name, f"_{name}_src"], by_commodity=False)
    stale = (out["obs_date"] - out[f"_{name}_src"]) > pd.Timedelta(days=stale_days)
    out.loc[stale.fillna(True), name] = np.nan
    return out.drop(columns=[f"_{name}_src"])


def build_demand2(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    """ISM·유로 PMI(obs=발표일, avail=+2일)·중국 부동산(월참조, avail=+45일)."""
    con = duckdb.connect(db, read_only=True)
    ser = con.execute("""SELECT series_code, CAST(obs_date AS DATE) AS obs_date, val
        FROM fact_series WHERE src='AKSHARE_MACRO2' ORDER BY 1,2""").df()
    con.close()
    ser["obs_date"] = pd.to_datetime(ser["obs_date"]).astype("datetime64[ns]")
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")
    panel = _series_feat(ser, "US_ISM_PMI_M", lambda v: v, "ism", 2, 60, panel)
    panel = _series_feat(ser, "US_ISM_PMI_M", lambda v: v.diff(3), "ism_chg3", 2, 60, panel)
    panel = _series_feat(ser, "EU_PMI_M", lambda v: v, "eupmi", 2, 60, panel)
    panel = _series_feat(ser, "CN_REALEST_M", lambda v: v, "re_lvl", 45, 75, panel)
    panel = _series_feat(ser, "CN_REALEST_M", lambda v: v.pct_change(12), "re_yoy", 45, 75, panel)
    return panel


GROUPS = {
    "INV": INV_F,
    "CNINV": exch.CNINV_F,
    "TRD": TRD_F,
    "PMICN": PMI_F,
    "PMIG": PMIG_F,
    "REALEST": REALEST_F,
    "CLN": CLNW_F + CLNM_F,
}


def sweep(df: pd.DataFrame, nolag: list[str], group_names: list[str],
          label: str) -> pd.DataFrame:
    rows = []
    for r in range(len(group_names) + 1):
        for combo in itertools.combinations(group_names, r):
            feats = list(nolag)
            for g in combo:
                feats += GROUPS[g]
            m = e2_delta_classifier(df, feats, "Logistic")
            rows.append(dict(조합="+".join(combo) if combo else "(NOLAG만)",
                             n그룹=len(combo), **m))
    tab = pd.DataFrame(rows)
    tab["_score"] = tab["QWK"] + tab["chg_acc"]     # 참고용 합성점수(정렬 전용)
    print(f"\n=== {label}: 상위 12 (QWK+chg_acc 합성 정렬) ===")
    cols = ["조합", "QWK", "acc", "chg_acc", "up_acc", "FAR"]
    print(tab.sort_values("_score", ascending=False).head(12)[cols]
          .round(4).to_string(index=False))
    return tab


def pareto(tab: pd.DataFrame) -> pd.DataFrame:
    """(QWK↑, chg_acc↑, FAR↓) 3목적 비지배 프런티어."""
    keep = []
    for i, a in tab.iterrows():
        dominated = False
        for _, b in tab.iterrows():
            if (b["QWK"] >= a["QWK"] and b["chg_acc"] >= a["chg_acc"]
                    and b["FAR"] <= a["FAR"]
                    and (b["QWK"] > a["QWK"] or b["chg_acc"] > a["chg_acc"]
                         or b["FAR"] < a["FAR"])):
                dominated = True
                break
        if not dominated:
            keep.append(i)
    return tab.loc[keep].sort_values("chg_acc", ascending=False)


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    df = add_dynamics(df)
    df = build_aux(db, df)
    df = exch.build_cninv(db, df)
    df = build_trd(db, df)
    df = build_pmi(db, df)
    df = build_demand2(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    for c in ["ism", "re_lvl"]:
        print(f"{c} 커버리지: {float(df[c].notna().mean()):.2f}")

    all_groups = list(GROUPS.keys())
    tab = sweep(df, nolag, all_groups, "풀링(전환주 26건, 128조합)")
    fr = pareto(tab)
    print(f"\n=== 풀링 파레토 프런티어({len(fr)}개) ===")
    print(fr[["조합", "QWK", "chg_acc", "up_acc", "FAR"]].round(4).to_string(index=False))

    # CU·NI 단독(64조합: CLN 제외 6그룹 — CLN은 풀링에서 이미 교란 판정)
    sub_groups = [g for g in all_groups if g != "CLN"]
    tabs_cc = {}
    for cc in ["CU", "NI"]:
        d1 = df[df["commodity_code"] == cc].reset_index(drop=True)
        tabs_cc[cc] = sweep(d1, nolag, sub_groups, f"{cc}만(64조합)")

    # 부트스트랩: 풀링 합성점수 1위 vs v1.7 채택 동작점(INV+CNINV+PMICN+TRD)
    v17 = nolag + INV_F + exch.CNINV_F + PMI_F + TRD_F
    best_row = tab.sort_values("_score", ascending=False).iloc[0]
    best_feats = list(nolag)
    if best_row["조합"] != "(NOLAG만)":
        for g in best_row["조합"].split("+"):
            best_feats += GROUPS[g]
    rng = np.random.default_rng(0)
    bs = bootstrap_diff(df, v17, best_feats, nolag, rng)
    print(f"\n스윕 1위({best_row['조합']}) vs v1.7 동작점: QWK차이 CI "
          f"[{bs['qwk_ci'][0]:+.3f},{bs['qwk_ci'][1]:+.3f}] P={bs['qwk_p']:.3f} | "
          f"chg차이 CI [{bs['chg_ci'][0]:+.3f},{bs['chg_ci'][1]:+.3f}] P={bs['chg_p']:.3f} | "
          f"비전환오류 {bs['steady_err'][0]}→{bs['steady_err'][1]}")

    write_report(tab, fr, tabs_cc, best_row, bs)


def _fmt(x, p=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.{p}f}"


def _md_table(L, t, cols):
    L.append("| " + " | ".join(cols) + " |")
    L.append("|" + "---|" * len(cols))
    for _, r in t.iterrows():
        L.append("| " + " | ".join(
            str(r[c]) if c == "조합" else _fmt(r[c]) for c in cols) + " |")


def write_report(tab, fr, tabs_cc, best_row, bs):
    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "diagnosis_combo_sweep.md")
    L = []
    L.append("# 진단 보조신호 피처그룹 전수 조합 스윕(128+64×2 조합)\n")
    L.append("작성: 2026-07-24 · 그룹 7종 파워셋 전수 평가(풀링) + CU·NI 단독 6그룹 "
             "64조합. 프레임: E2 Δ타깃 Logistic·워크포워드 3폴드·as-of 누수방지. "
             "⚠ PMIG(ISM·유로)·REALEST(부동산)는 소스 피드가 2025-09/12에서 멈춰 "
             "신선도 마스크로 2025-10 이후 결측 처리(전환 다발기 커버 불가 — 불리), "
             "CLN(거시12종)은 기왕 판정된 커버리지 교란 그룹.\n")
    L.append("\n## 풀링 상위 15(QWK+chg_acc 합성 정렬)\n")
    top = tab.sort_values("_score", ascending=False).head(15)
    _md_table(L, top, ["조합", "QWK", "acc", "chg_acc", "up_acc", "FAR"])
    L.append(f"\n## 풀링 파레토 프런티어(QWK↑·chg_acc↑·FAR↓ 비지배, {len(fr)}개)\n")
    _md_table(L, fr, ["조합", "QWK", "chg_acc", "up_acc", "FAR"])
    for cc, t in tabs_cc.items():
        L.append(f"\n## {cc} 단독 상위 8\n")
        _md_table(L, t.sort_values("_score", ascending=False).head(8),
                  ["조합", "QWK", "chg_acc", "up_acc", "FAR"])
    L.append("\n## 부트스트랩(스윕 1위 vs v1.7 채택 동작점)\n")
    L.append(f"- 1위 조합: **{best_row['조합']}** — QWK차이 95% CI "
             f"[{bs['qwk_ci'][0]:+.3f}, {bs['qwk_ci'][1]:+.3f}] (P={bs['qwk_p']:.3f}), "
             f"chg_acc차이 CI [{bs['chg_ci'][0]:+.3f}, {bs['chg_ci'][1]:+.3f}] "
             f"(P={bs['chg_p']:.3f}), 비전환주 오류 {bs['steady_err'][0]}→"
             f"{bs['steady_err'][1]}건")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[combo_sweep] 리포트 → {path}")


if __name__ == "__main__":
    main()
