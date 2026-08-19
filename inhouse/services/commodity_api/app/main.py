# -*- coding: utf-8 -*-
"""광종 리스트 API 엔트리 — CONTAINER_ARCHITECTURE.md §8 3단계 구현.

`dashboards/streamlit_app.py`의 load_geo/load_diagnosis_level/load_diagnosis_alert/
load_delta_ew/load_forecast 로직을 `model_loaders.py`로 그대로 이식하고, 3개
라우터(geo-index/diagnosis/forecast)로 서빙한다. st.cache_data가 하던 "DB mtime
기준 캐시"는 `deps.cached()`(in-memory, 요청 간 공유)로 대체했다 — 예측 조회는
conformal 보정 포함 시 수 분 걸리므로 캐시 없이는 매 요청이 그 비용을 문다.

성공 기준(CONTAINER_ARCHITECTURE.md §8): 기존 Streamlit 데모와 동일 광종·동일
시점 조회 시 수치 일치(회귀 없음) — model_loaders.py가 원본 함수를 그대로
옮긴 것이므로 입력 DB가 같으면 결과도 같다."""
from __future__ import annotations

from fastapi import FastAPI

from . import deps  # noqa: F401 — import 시점에 sys.path 부트스트랩(CCS 등도 여기서)
from .routers.diagnosis import router as diagnosis_router
from .routers.forecast import router as forecast_router
from .routers.geo_index import router as geo_index_router

from msr.config import CORE_COMMODITIES  # noqa: E402

app = FastAPI(title="komir commodity_api")
app.include_router(geo_index_router)
app.include_router(diagnosis_router)
app.include_router(forecast_router)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/commodities")
def list_commodities() -> list[dict]:
    """대상 5광종 목록(코드·한글명·영문명) — 다른 3개 엔드포인트가 받는 `cc` 값의 사전."""

    return [
        {"commodity_code": cc, "name_ko": CORE_COMMODITIES[cc]["ko"], "name_en": CORE_COMMODITIES[cc]["en"]}
        for cc in deps.CCS
    ]


@app.post("/admin/cache/clear")
def clear_cache() -> dict:
    """모델 재적합 캐시를 비운다(streamlit 데모의 "모델 다시 적합" 버튼과 동일).
    다음 요청부터 다시 재적합하므로 무겁다 — 운영 배치 갱신 직후 등 필요할 때만 호출."""

    return {"cleared_entries": deps.clear_cache()}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):  # noqa: ANN001
    # HTTPException(우리 라우터가 던지는 404/500)은 FastAPI 기본 핸들러가 먼저
    # 잡는다(MRO상 더 구체적인 핸들러 우선) — 여기 도달하는 건 진짜 예기치 않은
    # 예외뿐이다.
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=500, content={"detail": f"예기치 않은 오류: {exc}"})


__all__ = ["app"]
