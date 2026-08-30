# -*- coding: utf-8 -*-
"""보고서 템플릿용 price/idx/map REST 엔드포인트 — 2026-08-26 신규.

`routers/analysis.py`(`/api/v1/analysis/*`)는 KOMIS 원본 계약(page_id를 경로에
그대로 노출)이라 발주처 프론트를 위해 경로를 고정해뒀다. 이 라우터는 그와
별개로, 보고서 요약 템플릿이 데이터를 가져올 때 쓸 3개 리소스군(가격·지표·지도)을
REST 명명규칙(kebab-case·복수 컬렉션명·자원 세그먼트, `/api/v1` 프리픽스는
`analysis.py`와 동일하게 맞춤)으로 다시 노출한다. 8종 전부 `/api/v1/analysis/*`와
동일 page_id로 같은 서비스 호출을 그대로 위임하는 얇은 별칭이다(계산 로직 복제
없음, 요청 스키마도 `routers/analysis.py`의 것을 그대로 재사용). `idx/general`
(사용자 최초 가칭)은 KOMIS 내부 용어(`indicator_composite`, "광물종합지수")에
맞춰 `composite`로 정했다.

`/api/v1/prices/{base-metals,minor-metals}`는 처음엔 신규 page_id(`price_
base_metals`/`price_minor_metals`)로 "요청 광종이 그 그룹에 속하는지" 검증까지
넣었었는데(2026-08-26 1차), 사용자 확인 결과 이 보고서 메뉴는 입력을 그대로
템플릿에 꽂아 넣을 뿐 복잡한 처리가 없어 그 가드가 불필요하다고 판단해
제거했다(같은 날 2차) — 그 뒤로는 둘 다 `page_id="price"` 하나로 위임했다.

**2026-08-27**: 사용자가 실제 KOMIS 사이트맵을 확인해 "광물자원가격"이 진짜로
서브메뉴 2개(비철금속/희소금속)라는 걸 확인 → `page_id`를 다시 쪼갰다(이번엔
그룹 검증 가드 없이, 이름만 원래 1차 시도와 같은 `price_base_metals`/
`price_minor_metals`로 되돌림 — `routers/analysis.py`의 `/api/v1/analysis/
prices/{base-metals,minor-metals}`도 같은 날 같은 2개 page_id로 분리했다). URL은
그대로라 이 라우터의 두 엔드포인트 경로 자체는 바뀌지 않았고, 내부적으로 어느
page_id로 위임하는지만 바뀌었다.

가격예측(`forecast_price`)은 사용자가 1차 범위에서 의도적으로 제외했다
("우선 price/idx/map 세 개로 분리") — 필요해지면 `/api/v1/prices/forecast`로
추가.

응답은 `routers/analysis.py`와 동일하게 `AnalysisReportResponse`(`status`+
Markdown `report`, 2026-08-26)다 — 상세는 `routers/_common.py` 모듈 docstring
참고.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..analysis.models import AnalysisReportResponse
from ._common import run_summary
from .analysis import (
    CompositeIndexSummaryRequest,
    DomesticTradeSummaryRequest,
    GlobalTradeSummaryRequest,
    IndicatorSummaryRequest,
    MineralMapSummaryRequest,
    PriceSummaryRequest,
)

prices_router = APIRouter(prefix="/api/v1/prices", tags=["prices"])
indicators_router = APIRouter(prefix="/api/v1/indicators", tags=["indicators"])
maps_router = APIRouter(prefix="/api/v1/maps", tags=["maps"])


@prices_router.post("/base-metals", response_model=AnalysisReportResponse)
def summarize_base_metal_price(
    payload: PriceSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """비철금속(LME, 니켈·동·아연·알루미늄·연·주석) 가격 분석요약
    (`/api/v1/analysis/prices/base-metals`와 동일 위임 — 그룹 검증 없음, §모듈
    docstring)."""

    return run_summary("price_base_metals", payload, request)


@prices_router.post("/minor-metals", response_model=AnalysisReportResponse)
def summarize_minor_metal_price(
    payload: PriceSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """희소금속(리튬·코발트·희토류 등) 가격 분석요약
    (`/api/v1/analysis/prices/minor-metals`와 동일 위임 — 그룹 검증 없음, §모듈
    docstring)."""

    return run_summary("price_minor_metals", payload, request)


@indicators_router.post("/market", response_model=AnalysisReportResponse)
def summarize_market_indicator(
    payload: IndicatorSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """시장동향지표 분석요약(`/api/v1/analysis/market-indicator`와 동일 위임)."""

    return run_summary("indicator_market", payload, request)


@indicators_router.post("/supply", response_model=AnalysisReportResponse)
def summarize_supply_indicator(
    payload: IndicatorSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """수급동향지표 분석요약(`/api/v1/analysis/supply-indicator`와 동일 위임)."""

    return run_summary("indicator_supply", payload, request)


@indicators_router.post("/composite", response_model=AnalysisReportResponse)
def summarize_composite_indicator(
    payload: CompositeIndexSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """광물종합지수 분석요약(`/api/v1/analysis/composite-index`와 동일 위임)."""

    return run_summary("indicator_composite", payload, request)


@maps_router.post("/korea", response_model=AnalysisReportResponse)
def summarize_korea_map(
    payload: DomesticTradeSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """국내 수급지도 분석요약(`/api/v1/analysis/domestic-trade`와 동일 위임)."""

    return run_summary("map_korea", payload, request)


@maps_router.post("/global", response_model=AnalysisReportResponse)
def summarize_global_map(
    payload: GlobalTradeSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """글로벌 수급지도 분석요약(`/api/v1/analysis/global-trade`와 동일 위임)."""

    return run_summary("map_global", payload, request)


@maps_router.post("/mineral", response_model=AnalysisReportResponse)
def summarize_mineral_map(
    payload: MineralMapSummaryRequest,
    request: Request,
) -> AnalysisReportResponse:
    """광물지도(매장량/생산량) 분석요약(`/api/v1/analysis/mineral-map`와 동일 위임)."""

    return run_summary("map_mineral", payload, request)


__all__ = ["prices_router", "indicators_router", "maps_router"]
