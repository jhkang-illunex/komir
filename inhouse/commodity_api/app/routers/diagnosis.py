# -*- coding: utf-8 -*-
"""GET /commodities/{cc}/diagnosis — 수급위기 진단.

이식 원본: dashboards/streamlit_app.py의 load_diagnosis_level()+
load_diagnosis_alert()+load_delta_ew()(Ridge 챔피언 재적합 + alert.py 규칙엔진/
히스테리시스 + 보조 Δ 조기경보 앙상블, §1 표 참고)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from .. import deps
from ..model_loaders import load_delta_ew, load_diagnosis_alert, load_diagnosis_level
from ..serialize import df_records, json_safe

router = APIRouter(prefix="/commodities", tags=["diagnosis"])

_SERIES_COLS = ["month", "ci_pred", "ci_teacher", "stage", "stage_name"]


@router.get("/{cc}/diagnosis")
def get_diagnosis(
    cc: str = Depends(deps.cc_path),
    months: int = Query(0, ge=0, description="최근 N개월만 series에 반환(0=전체)"),
    include_early_warning: bool = Query(True, description="보조 Δ 조기경보 앙상블 포함 여부"),
):
    lvl, feats = deps.cached("diagnosis_level", load_diagnosis_level)
    # lvl을 넘겨 load_diagnosis_alert가 Ridge를 다시 재적합하지 않게 한다(중복 계산 방지).
    alert_res = deps.cached("diagnosis_alert", lambda: load_diagnosis_alert(lvl))

    g = lvl[lvl["commodity_code"] == cc].sort_values("month")
    ga = alert_res[alert_res["commodity_code"] == cc].sort_values("obs_date")

    if g.empty:
        return {
            "commodity_code": cc,
            "latest_model": None,
            "latest_alert": None,
            "series": [],
            "early_warning": None,
            "features": feats,
        }

    latest = g.iloc[-1]
    latest_model = {
        "month": json_safe(latest["month"]),
        "ci_pred": json_safe(latest["ci_pred"]),
        "ci_teacher": json_safe(latest["ci_teacher"]),
        "stage": json_safe(latest["stage"]),
        "stage_name": latest["stage_name"],
        "probs": json_safe(latest["probs"]),
        "contrib": json_safe(latest["contrib"]),
    }

    latest_alert = None
    if not ga.empty:
        la = ga.iloc[-1]
        evidence = json.loads(la["evidence_json"]) if la.get("evidence_json") else {}
        latest_alert = {
            "obs_date": json_safe(la["obs_date"]),
            "alert_name": la["alert_name"],
            "alert_level": json_safe(la.get("alert_level")),
            "crisis_index": json_safe(la.get("crisis_index")),
            "ci_source": la.get("ci_source"),
            "triggers": la.get("triggers") or None,
            "reason": la["reason"],
            "override_applied": evidence.get("override_applied"),
            "hysteresis_applied": evidence.get("hysteresis_applied"),
            "evidence": json_safe(evidence),
        }

    series_df = g[_SERIES_COLS]
    if months > 0:
        series_df = series_df.tail(months)

    early_warning = None
    if include_early_warning:
        ew, gimp = deps.cached("delta_ew", load_delta_ew)
        e = ew[ew["commodity_code"] == cc]
        if not e.empty:
            r = e.iloc[0]
            early_warning = {
                "obs_date": json_safe(r["obs_date"]),
                "direction": r["direction"],
                "trigger": json_safe(r["trigger"]),
                "p_down": json_safe(r["p_down"]),
                "p_stay": json_safe(r["p_stay"]),
                "p_up": json_safe(r["p_up"]),
                "global_importance": {
                    tag: [[feat, json_safe(val)] for feat, val in rank]
                    for tag, rank in gimp.items()
                },
            }

    return {
        "commodity_code": cc,
        "latest_model": latest_model,
        "latest_alert": latest_alert,
        "series": df_records(series_df),
        "early_warning": early_warning,
        "features": feats,
    }
