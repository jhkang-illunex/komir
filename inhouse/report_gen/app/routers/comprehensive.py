# -*- coding: utf-8 -*-
"""AI 종합분석 및 관련뉴스 — `GET /api/v1/dashboard/comprehensive`.

기존 `/api/v1/analysis/*`(5종, `analysis.py`)와 경로를 분리했다 — 그쪽은
"page_id + 광종 1개" 계약이 이미 검증·고정됐고(2026-08-13 실데이터 검증
완료), 이 엔드포인트는 파라미터 없이 5광종 통합 현황을 한 번에 돌려주는
다른 모양의 계약이라 같은 prefix 아래 묶을 이유가 없다.

**2026-08-28 skeptic 감사(HIGH)**: `analysis_lock`은 `/api/v1/analysis/*`
11종(`routers/_common.py::run_summary`)과 이 엔드포인트가 공유한다.
`run_summary`는 2026-08-27 SC-002 감사로 `lock.acquire(timeout=)`(예산 안에서만
대기)로 고쳐졌는데 이 엔드포인트는 `with ...analysis_lock:`(무제한 대기)를
그대로 쓰고 있어, 느린 LLM 응답 1건이 이 엔드포인트를 통해 lock을 수 분
점유하면 SC-002가 막으려던 캐스케이드(다른 11종 전부 TIMEOUT)가 이 경로로는
여전히 뚫려 있었다 — 같은 `acquire(timeout=)` 패턴으로 고친다(`main.py::
build_comprehensive_service()`의 LLM timeout/retries 축소와 세트, 부수
발견이던 기본 cfg 미적용 문제도 그쪽에서 같이 고쳤다)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ..analysis.budget import REQUEST_BUDGET_SECONDS
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
    lock = request.app.state.analysis_lock
    # `/api/v1/analysis/*`(run_summary)와 같은 예산으로 대기를 바운드한다 —
    # §모듈 docstring 2026-08-28 skeptic 감사.
    if not lock.acquire(timeout=REQUEST_BUDGET_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{REQUEST_BUDGET_SECONDS}초 안에 analysis_lock을 잡지 못했다 — 다른 요청이 오래 점유 중이다.",
        )
    try:
        return service.build_dashboard()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    finally:
        lock.release()
