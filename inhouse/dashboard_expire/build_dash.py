# -*- coding: utf-8 -*-
"""수급위기 진단 대시보드 재생성 (2026-07-25 스크립트화 — 기존엔 WORKLOG 쿼리 수동).

template의 __DATA__를 warehouse 스냅샷(JSON)으로 치환해 자체완결 HTML 생성.
2026-07-25 추가 노출: 보조 조기경보(out_aux_early_warning)·지정학 급증확률
적응형(geo_prob.p_burst_adapt) — 신챔피언 운영 반영(v1.19) 소비자측 마감.

실행: MSR_DB=<warehouse> python3 dashboard_expire/build_dash.py
"""
from __future__ import annotations
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mineral_supply_risk"))
from db.dbio import connect_ro  # noqa: E402

DB = os.environ.get("MSR_DB",
                    "/home/nuri/dev/git/ws/mine_ws/komir/inhouse/data_lake/db/minerals.duckdb")
LVL = {"정상": 0, "관심": 1, "주의": 2, "경계": 3, "심각": 4}
CCS = ["CU", "NI", "LI", "CO", "REE"]


def build_data() -> dict:
    con = connect_ro(DB)
    alerts = {}
    al = con.execute("""SELECT commodity_code cc, CAST(obs_date AS DATE) d,
            risk_score, alert_level, reason FROM out_diagnosis_alert
        WHERE obs_date >= '2020-01-01' ORDER BY 1, 2""").df()
    for cc, g in al.groupby("cc"):
        alerts[cc] = [[str(r.d)[:10], round(float(r.risk_score), 1),
                       LVL.get(r.alert_level, 0), r.reason or ""]
                      for r in g.itertuples()]
    xai = {}
    nc = con.execute("""SELECT commodity_code cc, month, ci_pred, stage_name,
            stage_probs, contrib FROM mart_diagnosis_nowcast
        WHERE month = (SELECT max(month) FROM mart_diagnosis_nowcast)""").df()
    for r in nc.itertuples():
        xai[r.cc] = {"month": str(r.month)[:7], "ci": round(float(r.ci_pred), 1),
                     "stage": r.stage_name, "probs": json.loads(r.stage_probs),
                     "contrib": json.loads(r.contrib)}
    geo = {}
    gi = con.execute("""SELECT commodity_code cc, CAST(period AS DATE) d,
            CAST(idx_value AS DOUBLE PRECISION) v FROM geo_index
        WHERE freq='W' AND period >= '2020-01-01' ORDER BY 1, 2""").df()
    # 주간 지수는 일요일 앵커 — 경보(월요일 앵커)와 정확일치 조인되도록 +1일 보정
    # (geo_prob DB 발행과 동일 규약; 미보정 시 차트 오버레이가 전부 미매칭)
    gi["d"] = pd.to_datetime(gi["d"]) + pd.Timedelta(days=1)
    for cc, g in gi.groupby("cc"):
        geo[cc] = [[str(r.d)[:10], round(float(r.v), 1)] for r in g.itertuples()]
    aux = {}
    try:
        ax = con.execute("""SELECT commodity_code cc, CAST(obs_date AS DATE) d,
                delta_pred, trigger, p_down, p_stay, p_up
            FROM out_aux_early_warning
            WHERE obs_date = (SELECT max(obs_date) FROM out_aux_early_warning)""").df()
        for r in ax.itertuples():
            aux[r.cc] = {"date": str(r.d)[:10], "delta": int(r.delta_pred),
                         "trigger": bool(r.trigger),
                         "p_down": round(float(r.p_down), 3),
                         "p_stay": round(float(r.p_stay), 3),
                         "p_up": round(float(r.p_up), 3)}
    except Exception as e:
        print(f"  [warn] aux 조기경보 없음({e}) — 카드만 발행")
    burst = {}
    try:
        gp = con.execute("""SELECT commodity_code cc, period,
                p_burst_next, p_burst_adapt, burst_k_adapt, burst_threshold
            FROM geo_prob
            WHERE period = (SELECT max(period) FROM geo_prob)""").df()
        for r in gp.itertuples():
            burst[r.cc] = {"date": str(r.period)[:10],
                           "p_fixed": round(float(r.p_burst_next), 4),
                           "p_adapt": round(float(r.p_burst_adapt), 4),
                           "k_adapt": int(r.burst_k_adapt),
                           "k_fixed": int(r.burst_threshold)}
    except Exception as e:
        print(f"  [warn] p_burst_adapt 없음({e})")
    con.close()
    return {"alerts": alerts, "xai": xai, "geo": geo, "aux": aux, "burst": burst,
            "generated": str(pd.Timestamp.now().date()),
            "versionBoundary": "2026-07-24", "versionLabel": "지수 재앵커(v3)"}


def main() -> None:
    data = build_data()
    tpl = open(os.path.join(HERE, "mineral_crisis_dash.template.html"),
               encoding="utf-8").read()
    assert "__DATA__" in tpl, "template에 __DATA__ 플레이스홀더 없음"
    html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    out = os.path.join(HERE, "mineral_crisis_dash.html")
    open(out, "w", encoding="utf-8").write(html)
    n_alert = sum(len(v) for v in data["alerts"].values())
    print(f"[build_dash] {out} 생성 — alerts {n_alert}행·aux {len(data['aux'])}광종·"
          f"burst {len(data['burst'])}광종·최신주 {data['alerts']['CU'][-1][0]}")


if __name__ == "__main__":
    main()
