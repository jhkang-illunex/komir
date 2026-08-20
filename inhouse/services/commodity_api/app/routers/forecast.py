# -*- coding: utf-8 -*-
"""GET /commodities/{cc}/forecast — 12개월 수요량·단가 예측.

이식 원본: dashboards/streamlit_app.py의 load_forecast()(ExtraTrees direct
다지평 챔피언 + conformal 구간보정 + SHAP 기반 설명, forecast_backtest_snapshot.json
스냅샷 병행 노출). ExtraTrees 재적합(conformal 원점 3개마다 재계산)이 수 분
걸릴 수 있어 deps.cached()가 필수다(원본 docstring 참고)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from .. import deps
from ..model_loaders import load_backtest_snapshot, load_forecast
from ..serialize import df_records, json_safe

router = APIRouter(prefix="/commodities", tags=["forecast"])

_TABLE_COLS = [
    "h", "target_month", "pred_ton", "ton_lo", "ton_hi",
    "pred_unit_usd_per_ton", "unit_lo", "unit_hi",
    "pred_value_usd", "pred_value_lo", "pred_value_mid", "pred_value_hi",
    "reason",
]


@router.get("/{cc}/forecast")
def get_forecast(
    cc: str = Depends(deps.cc_path),
    h: int = Query(1, ge=1, le=12, description="설명(explain) 대상 호라이즌(1~12개월)"),
):
    fc, base_m, qt_pub, qu_pub = deps.cached("forecast", load_forecast)
    g = fc[fc["commodity_code"] == cc].sort_values("h")
    if g.empty:
        return {
            "commodity_code": cc, "base_month": json_safe(base_m),
            "conformal": {"q_ton": qt_pub, "q_unit": qu_pub},
            "horizons": [], "explain": None, "backtest": None,
        }

    row = g[g["h"] == h]
    explain = None
    if not row.empty:
        r = row.iloc[0]
        ex = json.loads(r["explain_json"])
        explain = {
            "h": h,
            "target_month": json_safe(r["target_month"]),
            "reason": r["reason"],
            "ton": {"local": ex["local"]["ton"], "global_top5": ex["global_top5"]["ton"]},
            "unit": {"local": ex["local"]["unit"], "global_top5": ex["global_top5"]["unit"]},
            "note": ex.get("note"),
        }

    snap = load_backtest_snapshot()
    backtest = None
    if snap is not None:
        metrics = [row for row in snap.get("champion_metrics", []) if row.get("commodity") == cc]
        pool = next(
            (row for row in snap.get("unit_pool_vs_depool", []) if row.get("commodity") == cc),
            None,
        )
        if metrics or pool:
            backtest = {
                "champion_metrics": metrics,
                "unit_pool_vs_depool": pool,
                "meta": snap.get("meta"),
            }

    return {
        "commodity_code": cc,
        "base_month": json_safe(base_m),
        "conformal": {"q_ton": round(float(qt_pub), 4), "q_unit": round(float(qu_pub), 4)},
        "horizons": df_records(g[_TABLE_COLS]),
        "explain": explain,
        "backtest": backtest,
    }
