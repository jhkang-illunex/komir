# -*- coding: utf-8 -*-
"""진단 Δ분류 챔피언 초과 탐색 R1 — 피처 2차 가공(다중스케일·스프레드·상호작용·
원시 이벤트 동역학) (2026-07-25, /goal "챔피언을 넘을 때까지 변형·탐색").

챔피언(넘어야 할 기준): Logistic + 채택동작점(NOLAG+INV+CNINV+PMI) —
QWK 0.8392 · 전환적중 0.1923 · FAR 0.1846 (CU SHFE 복구 상태).

가공 그룹(전부 as-of 안전 — 원천이 이미 as-of 조인된 값의 함수이거나 주간 원천):
  SPREAD : LME z52 − SHFE z52 (CU·NI) — "서로 다른 실물 재고의 스프레드"(NI 2축
           유의의 메커니즘)를 명시적 피처로.
  MHL    : 재고 수익률의 다중 반감기 EWMA(hl=2·8주) — MIDAS 감쇠 사전의 주간판.
  IX     : PMI 모멘텀 × 재고 모멘텀 상호작용(수요 회복+재고 감소 동시 신호).
  GSEV   : geo_event 원시 심각(sev≥2) 주간수의 다중 반감기 EWMA(hl2·hl8)와
           13주합 z — 지수로 압축되기 전의 이벤트 동역학.

실행: MSR_DB=<warehouse> python -m scripts.diag_refine1
산출: outputs/model_opt/diag_refine1.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import OUT                                                # noqa: E402
from scripts.diagnosis_retrain_answer import build_panel, GEO_ONLY_NO_LAG  # noqa: E402
from scripts.diagnosis_ylag_deep_review import (                          # noqa: E402
    add_dynamics, e2_delta_classifier,
)
from scripts.diagnosis_aux_features_eval import build_aux, INV_F, _asof_join  # noqa: E402
import scripts.diagnosis_exch_inventory_eval as exch                      # noqa: E402
from scripts.diagnosis_priority_feeds_eval import (                       # noqa: E402
    build_pmi, PMI_F, bootstrap_diff,
)

SPREAD_F = ["spr_z", "spr_chg13"]
MHL_F = ["inv_mhl2", "inv_mhl8", "cninv_mhl2", "cninv_mhl8"]
IX_F = ["ix_pmi_inv", "ix_pmi_cninv"]
GSEV_F = ["gsev_hl2", "gsev_hl8", "gsev_z13"]


def _z(s, w, mp):
    return (s - s.rolling(w, min_periods=mp).mean()) \
        / s.rolling(w, min_periods=mp).std().replace(0, np.nan)


def build_refined(db: str, panel: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(db, read_only=True)
    inv1 = con.execute("""SELECT commodity_code cc, CAST(obs_date AS DATE) AS d,
        CAST(val AS DOUBLE) v FROM fact_inventory ORDER BY 1,2""").df()
    inv2 = con.execute("""SELECT commodity_code cc, CAST(obs_date AS DATE) AS d,
        CAST(val AS DOUBLE) v FROM fact_inventory_exch
        WHERE src IN ('SHFE_99QH_W','GFEX_OFFICIAL_W') ORDER BY 1,2""").df()
    sev = con.execute("""SELECT commodity_code cc, CAST(obs_date AS DATE) AS d
        FROM geo_event WHERE severity >= 2 AND obs_date >= '2015-01-01'""").df()
    con.close()
    for d in (inv1, inv2, sev):
        d["d"] = pd.to_datetime(d["d"])
    panel = panel.copy()
    panel["obs_date"] = pd.to_datetime(panel["obs_date"]).astype("datetime64[ns]")

    # ── SPREAD·MHL: 재고 2축 주간 가공 ──
    frames = []
    for cc in ["CU", "NI", "LI"]:
        a = inv1[inv1["cc"] == cc].sort_values("d").set_index("d")["v"]
        b = inv2[inv2["cc"] == cc].sort_values("d").set_index("d")["v"]
        if len(b) == 0:
            continue
        idx = b.index if len(a) == 0 else a.index.union(b.index)
        f = pd.DataFrame(index=idx)
        if len(a):
            az = _z(a.reindex(idx).ffill(limit=2), 52, 20)
            f["inv_mhl2"] = a.reindex(idx).ffill(limit=2).pct_change() \
                .ewm(halflife=2).mean()
            f["inv_mhl8"] = a.reindex(idx).ffill(limit=2).pct_change() \
                .ewm(halflife=8).mean()
        else:
            az = pd.Series(np.nan, index=idx)
            f["inv_mhl2"] = np.nan; f["inv_mhl8"] = np.nan
        bz = _z(b.reindex(idx).ffill(limit=2), 52, 20)
        f["cninv_mhl2"] = b.reindex(idx).ffill(limit=2).pct_change() \
            .ewm(halflife=2).mean()
        f["cninv_mhl8"] = b.reindex(idx).ffill(limit=2).pct_change() \
            .ewm(halflife=8).mean()
        f["spr_z"] = az - bz
        f["spr_chg13"] = f["spr_z"].diff(13)
        f = f.reset_index()
        f = f.rename(columns={f.columns[0]: "obs_date"})  # 인덱스명 'd'/'index' 모두 대응
        f["commodity_code"] = cc
        f["avail_date"] = f["obs_date"] + pd.Timedelta(days=7)
        frames.append(f)
    allf = pd.concat(frames, ignore_index=True) \
        .replace([np.inf, -np.inf], np.nan)
    panel = _asof_join(panel, allf, SPREAD_F + MHL_F, by_commodity=True)

    # ── GSEV: 원시 심각 이벤트 주간수 다중스케일 ──
    gframes = []
    grid = pd.date_range(sev["d"].min(), sev["d"].max(), freq="W")
    for cc, g in sev.groupby("cc"):
        n = g.set_index("d").resample("W").size().reindex(grid, fill_value=0)
        f = pd.DataFrame({"obs_date": grid,
                          "gsev_hl2": n.ewm(halflife=2).mean().values,
                          "gsev_hl8": n.ewm(halflife=8).mean().values})
        f["gsev_z13"] = _z(pd.Series(n.rolling(13).sum().values), 52, 20).values
        f["commodity_code"] = cc
        f["avail_date"] = f["obs_date"] + pd.Timedelta(days=3)
        gframes.append(f)
    allg = pd.concat(gframes, ignore_index=True) \
        .replace([np.inf, -np.inf], np.nan)
    panel = _asof_join(panel, allg, GSEV_F, by_commodity=True)

    # ── IX: 상호작용(조인 완료된 as-of 값들의 곱) ──
    panel["ix_pmi_inv"] = panel["pmi_off_chg3"] * panel["inv_chg13"]
    panel["ix_pmi_cninv"] = panel["pmi_off_chg3"] * panel["cninv_chg13"]
    return panel


def main():
    db = os.environ["MSR_DB"]
    exch.SRC_MAP["CU"] = {"SHFE_99QH_W"}
    df = build_panel(db)
    print(f"패널 종점: {df['obs_date'].max().date()}")
    df = add_dynamics(df); df = build_aux(db, df)
    df = exch.build_cninv(db, df); df = build_pmi(db, df)
    df = build_refined(db, df)
    nolag = [f for f in GEO_ONLY_NO_LAG if df[f].notna().sum() > 50]
    ADOPTED = nolag + INV_F + exch.CNINV_F + PMI_F
    for c in SPREAD_F[:1] + GSEV_F[:1] + MHL_F[:1]:
        cov = df.groupby("commodity_code")[c].apply(
            lambda s: float(s.notna().mean()))
        print(f"{c} 커버리지: {cov[cov > 0].round(2).to_dict()}")

    variants = {
        "챔피언(채택동작점)": ADOPTED,
        "+SPREAD": ADOPTED + SPREAD_F,
        "+MHL": ADOPTED + MHL_F,
        "+IX": ADOPTED + IX_F,
        "+GSEV": ADOPTED + GSEV_F,
        "+SPREAD+GSEV": ADOPTED + SPREAD_F + GSEV_F,
        "+SPREAD+IX": ADOPTED + SPREAD_F + IX_F,
        "+전부": ADOPTED + SPREAD_F + MHL_F + IX_F + GSEV_F,
    }
    rows = {}
    for tag, feats in variants.items():
        r = e2_delta_classifier(df, feats, "Logistic")
        rows[tag] = (r, feats)
        print(f"{tag}: QWK {r['QWK']:.4f} chg {r['chg_acc']:.4f} "
              f"FAR {r['FAR']:.4f} Miss {r['Miss']:.4f}")

    champ = rows["챔피언(채택동작점)"][0]
    rng = np.random.default_rng(0)
    lines = []
    for tag, (r, feats) in rows.items():
        if tag == "챔피언(채택동작점)":
            continue
        # 파레토 후보(QWK 또는 chg 개선 & FAR 비악화 근접)만 부트스트랩
        if (r["QWK"] > champ["QWK"] - 0.005 and r["chg_acc"] >= champ["chg_acc"]) \
                or r["QWK"] > champ["QWK"] + 0.003:
            b = bootstrap_diff(df, rows["챔피언(채택동작점)"][1], feats, nolag, rng)
            line = (f"{tag} vs 챔피언: QWK CI [{b['qwk_ci'][0]:+.3f},"
                    f"{b['qwk_ci'][1]:+.3f}] P={b['qwk_p']:.3f} | chg CI "
                    f"[{b['chg_ci'][0]:+.3f},{b['chg_ci'][1]:+.3f}] "
                    f"P={b['chg_p']:.3f} | 비전환오류 {b['steady_err'][0]}→"
                    f"{b['steady_err'][1]}")
            lines.append(line)
            print(line)

    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "diag_refine1.md"), "w") as f:
        f.write("# 진단 R1 — 피처 2차 가공 탐색(2026-07-25)\n\n")
        f.write("| 구성 | QWK | chg | FAR | Miss |\n|---|---|---|---|---|\n")
        for tag, (r, _) in rows.items():
            f.write(f"| {tag} | {r['QWK']:.4f} | {r['chg_acc']:.4f} | "
                    f"{r['FAR']:.4f} | {r['Miss']:.4f} |\n")
        f.write("\n## 부트스트랩\n\n")
        for line in lines:
            f.write(f"- {line}\n")
    print("[diag_refine1] 리포트 저장")


if __name__ == "__main__":
    main()
