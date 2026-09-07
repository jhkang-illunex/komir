# -*- coding: utf-8 -*-
"""GET /commodities/{cc}/geo-index — 지정학 위기지수.

이식 원본: dashboards/streamlit_app.py의 load_geo()(geo_index/geo_prob 최신값
조회, 연산 없음 — 산식 기반이라 모델 재적합 불필요). 그래서 이 라우터만 캐시가
없어도 무리 없지만, 다른 두 라우터와 동일하게 deps.cached()를 거쳐 DB 재조회
왕복을 줄인다(비용이 싸므로 실질 효과는 크지 않음)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .. import deps
from ..model_loaders import load_geo
from ..serialize import df_records, json_safe

router = APIRouter(prefix="/commodities", tags=["geo-index"])


@router.get("/{cc}/geo-index")
def get_geo_index(
    cc: str = Depends(deps.cc_path),
    weeks: int = Query(0, ge=0, description="최근 N주만 series에 반환(0=전체)"),
):
    idx_w, prob = deps.cached("geo", load_geo)
    g = idx_w[idx_w["commodity_code"] == cc].sort_values("week")
    p = prob[prob["commodity_code"] == cc].sort_values("period")

    if g.empty:
        return {
            "commodity_code": cc,
            "latest": None,
            "prob_latest": None,
            "series": [],
            "prob_series_tail": [],
        }

    if weeks > 0:
        g = g.tail(weeks)
    latest = g.iloc[-1]
    prob_latest = json_safe(p.iloc[-1].to_dict()) if not p.empty else None

    return {
        "commodity_code": cc,
        "latest": {
            "week": json_safe(latest["week"]),
            "idx_value": json_safe(latest["idx_value"]),
            "n_events": json_safe(latest["n_events"]),
        },
        "prob_latest": prob_latest,
        "series": df_records(g[["week", "idx_value", "n_events"]]),
        "prob_series_tail": (
            df_records(p.tail(8)[["period", "p_burst_next", "p_severe_next", "p_burst_adapt", "family"]])
            if not p.empty else []
        ),
    }
