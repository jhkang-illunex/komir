# -*- coding: utf-8 -*-
"""경보 계열2(시설·수송, dimension∈{ops,corridor}) 트리거 후보 백테스트
(피드백기반_수정플랜 2026-07-16 A-2 — Codex 최우선 지적 대응).

동기: override_backtest.py(2026-07-16)가 "③ 지정학 고신뢰"(모든 고신뢰 supply_down 이벤트,
event_type 무관)를 폐지 판정한 바 있다(674주 상시발화·FAR 폭증). A-2는 event_type을
event_type→dimension(ops/corridor/trade/input/policy, geo/dimension.py) 으로 정규화해
"진짜 시설·수송 차질"(ops/corridor)만 걸러낸 좁은 트리거를 새로 만든다 — 이게 옛 광역
트리거와 달리 순기여를 갖는지 동일 방법론(override_backtest.py)으로 재검증한다.

방법: override_backtest.py 를 그대로 재사용(4구성 프레임 대신 "d_full(현행, geo off)"과
"e_c2(신규 후보, ops/corridor severity>=2 하나만 On)"를 비교) — compute_alerts 순수함수
무수정, geo_sev 딕셔너리만 다르게 구성해 입력 마스킹으로 순효과를 분리한다.

실행: MSR_DB=<warehouse> python -m scripts.dimension_c2_backtest
산출: outputs/model_opt/dimension_c2_backtest.md
"""
from __future__ import annotations
import os, sys

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr.config import DB_PATH, OUT                                    # noqa: E402
from msr.models.alert import compute_alerts, Q_CUT                     # noqa: E402
from msr.models.diagnosis_opt import ANCHOR_SPAN                       # noqa: E402
from scripts.override_backtest import (                                # noqa: E402
    teacher_actual, qwk, far_miss, vol_fwd_weekly, prec_recall,
)

HORIZON = 3
C2_SEV_THR = 2 / 3.0   # severity>=2(0~3 스케일) 정규화, OV_GEO_SEV(0.85, ≈severity3)보다 완화


def load_inputs(db: str):
    con = duckdb.connect(db, read_only=True)
    df = con.execute("""SELECT commodity_code,obs_date,teacher_supply_demand,volatility_12w,import_hhi
        FROM mart_weekly_diagnosis
        WHERE obs_date>='2020-01-01' AND teacher_supply_demand IS NOT NULL""").df()
    nc = con.execute("SELECT commodity_code, month, ci_pred AS ci_model FROM mart_diagnosis_nowcast").df()
    nc["month"] = pd.to_datetime(nc["month"])
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["month"] = df["obs_date"].values.astype("datetime64[M]")
    df = df.merge(nc, on=["commodity_code", "month"], how="left").drop(columns=["month"])

    # 신규 후보: dimension in (ops, corridor) 전용(광의 소스 필터는 기존과 동일 유지)
    geo_c2 = con.execute("""SELECT commodity_code, obs_date, severity FROM geo_event
        WHERE commodity_code IS NOT NULL AND direction='supply_down'
          AND dimension IN ('ops','corridor')
          AND source IN ('US_FederalRegister','CN_MOFCOM','WoodMac','IEA','KOMIS',
                         'Argus','PPS','AsianMetal','EU_SCRREEN')""").df()
    # 비교용 구 광역 트리거(override_backtest.py와 동일 조건, dimension 무관)
    geo_broad = con.execute("""SELECT commodity_code, obs_date, severity FROM geo_event
        WHERE commodity_code IS NOT NULL AND direction='supply_down'
          AND source IN ('US_FederalRegister','CN_MOFCOM','WoodMac','IEA','KOMIS',
                         'Argus','PPS','AsianMetal','EU_SCRREEN')""").df()
    proxy = con.execute("""SELECT commodity_code, CAST(month AS DATE) AS month, vol_spike
        FROM mart_proxy_label""").df()
    con.close()

    def sev_map(geo_df, thr):
        sev = {}
        if len(geo_df):
            g = geo_df.dropna(subset=["obs_date"]).copy()
            g["m"] = pd.to_datetime(g["obs_date"]).values.astype("datetime64[M]")
            gs = g.groupby(["commodity_code", "m"])["severity"].max()
            gsmap = {(cc, pd.Timestamp(m)): float(s) / 3.0 for (cc, m), s in gs.items()}
            sev = {(cc, d): gsmap.get((cc, pd.Timestamp(d).replace(day=1)))
                   for cc, d in zip(df.commodity_code, df.obs_date)}
        return sev

    return df, sev_map(geo_c2, C2_SEV_THR), sev_map(geo_broad, C2_SEV_THR), proxy, len(geo_c2), len(geo_broad)


def build_configs(df, sev_c2, sev_broad):
    def mask():
        d = df.copy(); d["volatility_12w"] = np.nan; d["import_hhi"] = np.nan
        return d
    os.environ["ALERT_OVERRIDE_GEO"] = "on"
    configs = {
        "a_model_only": compute_alerts(mask(), None),
        "e_c2_only":    compute_alerts(mask(), sev_c2),
        "f_broad_only": compute_alerts(mask(), sev_broad),   # 참고용: 옛 광역 트리거 재현
    }
    os.environ.pop("ALERT_OVERRIDE_GEO", None)
    return configs


def _fmt(x, p=3):
    return "—" if (x is None or (isinstance(x, float) and np.isnan(x))) else f"{x:.{p}f}"


def main():
    db = os.environ.get("MSR_DB", DB_PATH)
    df, sev_c2, sev_broad, proxy, n_c2_events, n_broad_events = load_inputs(db)
    df = df.reset_index(drop=True)
    configs = build_configs(df, sev_c2, sev_broad)

    def align(res):
        return res.set_index(["commodity_code", "obs_date"]).reindex(
            pd.MultiIndex.from_frame(df[["commodity_code", "obs_date"]])).reset_index()
    configs = {k: align(v) for k, v in configs.items()}

    actual = teacher_actual(df)
    y_vol = vol_fwd_weekly(proxy, df)
    base_lv = configs["a_model_only"]["base_level"].values

    rows = []
    for k, res in configs.items():
        al = res["alert_level"].values
        far, miss, ncalm, ncris = far_miss(actual.values, al)
        raised = int((al > base_lv).sum())
        flag = al > base_lv
        pr = prec_recall(flag, y_vol)
        rows.append(dict(cfg=k, qwk=qwk(actual.values, al), FAR=far, Miss=miss,
                          raised=raised, **pr))
    tab = pd.DataFrame(rows)

    out_dir = os.path.join(str(OUT), "model_opt")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dimension_c2_backtest.md")
    L = []
    L.append("# 경보 계열2(시설·수송, dimension∈{ops,corridor}) 트리거 후보 백테스트\n")
    L.append("피드백기반_수정플랜(260716) A-2 — Codex 최우선 지적(3계열 구조·시설수송 계열 구축) "
             "대응. dimension 백필(geo/dimension.py, event_type 32,398종 정규화) 후 '진짜 "
             "시설·수송 차질'(ops/corridor)만으로 좁힌 신규 후보 트리거를, 2026-07-16 폐지된 "
             "구 광역 '지정학 고신뢰' 트리거와 동일 방법론(override_backtest.py)으로 비교한다.\n")
    L.append(f"- 패널: {df['obs_date'].min().date()}~{df['obs_date'].max().date()} 주간 × "
             f"광종 {df['commodity_code'].nunique()}종, 총 {len(df):,}주\n")
    L.append(f"- 소스 이벤트 수(2020+, direction=supply_down, 고신뢰소스): 신규 c2(ops/corridor) "
             f"{n_c2_events:,}건 vs 구 광역(dimension 무관) {n_broad_events:,}건 "
             f"({n_c2_events/max(n_broad_events,1)*100:.1f}%로 축소)\n")
    L.append("- severity 임계는 구 트리거와 동일(정규화 severity>=0.667, 원척도 2/3)\n")

    L.append("\n## 구성별 비교\n")
    L.append("| 구성 | QWK | FAR | Miss | 격상주수 | 격상주 실현율 | 비격상주 실현율(대조) | lift |")
    L.append("|---|---|---|---|---|---|---|---|")
    label = {"a_model_only": "(a) 모델 단계만(기준)", "e_c2_only": "(e) 신규 c2(ops/corridor)",
             "f_broad_only": "(f) 구 광역(참고, 폐지됨)"}
    for _, r in tab.iterrows():
        lift = (r["precision"] / r["neg_rate"]) if (r["neg_rate"] and r["neg_rate"] > 0
                                                      and not np.isnan(r["neg_rate"])) else float("nan")
        L.append(f"| {label[r['cfg']]} | {_fmt(r['qwk'])} | {_fmt(r['FAR'])} | {_fmt(r['Miss'])} | "
                 f"{int(r['raised'])} | {_fmt(r['precision'])} | {_fmt(r['neg_rate'])} | {_fmt(lift,1)} |")

    a = tab.set_index("cfg")
    q0, qe, qf = a.loc["a_model_only", "qwk"], a.loc["e_c2_only", "qwk"], a.loc["f_broad_only", "qwk"]
    far0, fare, farf = a.loc["a_model_only", "FAR"], a.loc["e_c2_only", "FAR"], a.loc["f_broad_only", "FAR"]
    raised_e = int(a.loc["e_c2_only", "raised"])
    prec_e, neg_e = a.loc["e_c2_only", "precision"], a.loc["e_c2_only", "neg_rate"]
    lift_e = (prec_e / neg_e) if (neg_e and neg_e > 0 and not np.isnan(neg_e)) else float("nan")

    L.append("\n## 판정\n")
    if raised_e == 0:
        verdict = "폐지(무효)"
        reason = "발화·격상 0주 — 임계 완화(severity>=1?) 재검토 필요, 현 임계로는 신호 없음"
    elif (not np.isnan(lift_e) and lift_e >= 1.5) and (fare - far0) < 0.05:
        verdict = "채택 후보(alert.py 반영 권고)"
        reason = f"lift ×{lift_e:.1f}·FAR 증가 {fare-far0:+.3f}(≤0.05, 구 광역의 폭증과 대비적으로 억제)"
    elif (not np.isnan(lift_e) and lift_e >= 1.2):
        verdict = "임계 조정 후 재평가"
        reason = f"lift ×{lift_e:.1f}로 약한 신호 — 최소단계(관심)로 제한하거나 severity 임계 상향 검토"
    else:
        verdict = "폐지"
        reason = f"lift ×{_fmt(lift_e,1)}(기저 근접) — dimension 좁히기로도 신호 회복 안 됨, 구 광역과 동일 결론"
    L.append(f"- **{verdict}** — {reason}\n")
    L.append(f"- 참고(구 광역 재현): QWK {q0:.3f}→{qf:.3f}({qf-q0:+.3f}), FAR {far0:.3f}→{farf:.3f}"
             f"({farf-far0:+.3f}) — 2026-07-16 override_backtest.py 결론(폐지)과 방향 일치 확인(재현성 점검).\n")
    L.append(f"- 신규 c2 후보: QWK {q0:.3f}→{qe:.3f}({qe-q0:+.3f}), FAR {far0:.3f}→{fare:.3f}"
             f"({fare-far0:+.3f}), 격상 {raised_e}주.\n")

    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"[dimension_c2_backtest] 리포트 → {path}")
    print(tab.to_string(index=False))
    print("판정:", verdict, "-", reason)


if __name__ == "__main__":
    main()
