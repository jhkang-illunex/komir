# -*- coding: utf-8 -*-
"""AI 종합분석 및 관련뉴스 — `GET /api/v1/dashboard/comprehensive`.

기존 `/api/v1/analysis/*`(5종, `analysis.py`)와 경로를 분리했다 — 그쪽은
"page_id + 광종 1개" 계약이 이미 검증·고정됐고(2026-08-13 실데이터 검증
완료), 이 엔드포인트는 파라미터 없이 5광종 통합 현황을 한 번에 돌려주는
다른 모양의 계약이라 같은 prefix 아래 묶을 이유가 없다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ..analysis.comprehensive_models import ComprehensiveDashboardResponse

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/comprehensive", response_model=ComprehensiveDashboardResponse)
def get_comprehensive_analysis(request: Request) -> ComprehensiveDashboardResponse:
    """대시보드 최상단 "AI 종합분석 및 관련뉴스"(화면기획 ver.1.3 11p)."""

    service = getattr(request.app.state, "comprehensive_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Comprehensive analysis service is not configured.",
        )
    try:
        with request.app.state.analysis_lock:
            return service.build_dashboard()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
