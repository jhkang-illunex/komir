# -*- coding: utf-8 -*-
"""분석요약 라우터 공용 실행부.

`routers/analysis.py`(`/api/v1/analysis/*`, page_id 기반, 발주처 프론트 계약이라
경로 고정)와 `routers/report_data.py`(`/api/v1/prices`·`/indicators`·`/maps`,
2026-08-26 신규 — REST 명명규칙으로 재배치한 price/idx/map 3계열)가 같은
`AnalysisSummaryService.analyze()` 호출·응답 조립을 쓴다. 원래 `analysis.py`
안에 `_run_summary`로 있던 것을 여기로 옮겼다 — 두 라우터가 각자 복제하면
응답 계약이 어긋날 수 있어서다.

**2026-08-26 응답 계약 전면 교체**(사용자 지시): "보고서는 DB에 저장하지
않고 MD 형태로 풍부한 표현력을 가진 텍스트로 바로 response에 작성",
"response에 status(정상/오류코드)", "요청당 20초 초과 금지". 그 결과:

1. `analyze_and_store()`(`analysis/store.py`, `out_report`/MSR_DB 적재) 호출을
   `service.analyze()` 직접 호출로 교체 — DB 저장을 안 한다. `store.py` 파일
   자체는 지우지 않았다(다른 경로에서 여전히 쓸 수 있어, 호출부만 뗀 것 —
   이전 두 턴의 "DB 조회 코드는 주석 보존" 원칙과 같은 결로 유지).
2. 반환 타입이 `AnalysisSummaryResponse`(구조화 JSON) → `AnalysisReportResponse`
   (`status`+`report`, `models.py` 참고)로 바뀌었다. `status`는 성공 시 `"ok"`,
   실패 시 오류 코드 문자열 하나로 성공/실패를 겸한다 — 코드 3종:
   `NO_DATA`(옛 `DataSourceError`/422에 대응, 대개 observations 누락)·
   `TIMEOUT`(20초 초과)·`INTERNAL_ERROR`(그 밖의 예외, 서버 로그에 상세 기록).
3. **HTTP 상태 코드는 9종 전부 항상 200**이다 — 성공/실패 구분은 바디의
   `status`로만 한다(더 이상 HTTPException을 던지지 않는다). 이건 기존
   422/503 HTTPException 매핑을 없애는 변경이라 해석 지점으로 남긴다.
4. **20초 타임아웃**: `ThreadPoolExecutor.submit(...).result(timeout=20)`으로
   감싼다. ⚠ 알려진 제약 — `analysis_lock`을 쥔 채로 실행되는 백그라운드
   스레드는 타임아웃 후에도 인터럽트되지 않고 계속 LLM 응답을 기다린다
   (LLM 클라이언트가 요청 중간 취소를 지원하지 않는다). 2026-08-27 skeptic
   감사(SC-002)에서 실측: 느린 LLM 응답 1건이 lock을 쥐면 뒤이은 규칙기반
   요청(ms 단위)까지 전부 TIMEOUT을 맞고, lock을 기다리던 워커는 취소되지
   않아 해제 후에도 한 건씩 순서대로 풀리며 각각이 다시 LLM을 태운다. vLLM이
   죽었을 때만이 아니라 응답이 20초만 넘어도 생기는 경로다. 그래서 두 가지로
   연쇄 반경을 묶었다 — (a) `main.py`가 report_gen용 LLM 클라이언트의
   timeout·retries를 요청 예산 규모로 줄여 lock 점유 시간 자체를 바운드하고,
   (b) 여기서 `analysis_lock.acquire(timeout=)`로 예산 안에 lock을 못 잡은
   워커는 즉시 포기해 스레드풀에 쌓이지 않게 한다.

5. **요청 조립도 이 안에서**(2026-08-27, skeptic 감사 SC-001): 라우터가
   `AnalysisSummaryRequest(page_id=..., **payload.model_dump())`를 라우트 본문에서
   직접 만들면, 페이지 전용 필드(예: `trade_direction`)를 다른 page_id에 보냈을 때
   `models.py`의 검증기가 던지는 pydantic `ValidationError`가 라우트 밖으로 새어
   **HTTP 500 평문**으로 나가 위 3번 계약이 깨졌다(실측). 그래서 조립을 여기로
   옮기고 `ValidationError`도 `NO_DATA`로 매핑한다 — 라우터는 `page_id`와 검증된
   payload만 넘긴다.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from fastapi import Request
from pydantic import BaseModel, ValidationError

from ..analysis.budget import ANALYSIS_LLM_RETRIES, ANALYSIS_LLM_TIMEOUT_SECONDS, REQUEST_BUDGET_SECONDS
from ..analysis.data_sources import DataSourceError
from ..analysis.models import AnalysisReportResponse, AnalysisSummaryRequest, SummaryPageId
from ..analysis.report_render import render_markdown_report

_LOG = logging.getLogger(__name__)
_TIMEOUT_SECONDS = REQUEST_BUDGET_SECONDS
# ANALYSIS_LLM_TIMEOUT_SECONDS/RETRIES는 `analysis/budget.py`가 소유한다(요청 예산과
# LLM 호출 상한을 `_refine_with_llm`도 같이 봐야 해서 — Pass 3 R3-F1). main.py 호환을
# 위해 여기서 재노출한다. 12s는 "호출 1회 상한"이고, 요청 전체(20s)는 `_refine_
# with_llm`이 호출 전마다 남은 예산을 확인해 지킨다.
# 9종 엔드포인트가 공유하는 실행 풀 — 요청마다 새 스레드를 만들지 않는다.
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="analysis-summary")


class _LockTimeout(Exception):
    """요청 예산 안에 `analysis_lock`을 잡지 못했다(앞 요청의 LLM 호출이 길어짐)."""


def run_summary(
    page_id: SummaryPageId,
    payload: BaseModel,
    request: Request,
) -> AnalysisReportResponse:
    """라우터가 검증한 payload를 `AnalysisSummaryRequest`로 조립해 공용 서비스로
    태우고, MD 보고서 응답으로 감싼다(모듈 docstring 5번)."""

    service = getattr(request.app.state, "analysis_summary_service", None)
    if service is None:
        _LOG.error("analysis_summary_service가 조립되지 않았다 — INTERNAL_ERROR로 응답")
        return AnalysisReportResponse(status="INTERNAL_ERROR")

    try:
        summary_request = AnalysisSummaryRequest(page_id=page_id, **payload.model_dump())
    except ValidationError as exc:
        _LOG.info("%s: NO_DATA — 요청 필드가 페이지 계약과 맞지 않는다: %s", page_id, exc.errors()[0].get("msg") if exc.errors() else exc)
        return AnalysisReportResponse(status="NO_DATA")

    # 요청 예산은 submit 시점부터 센다 — 풀(8워커)이 꽉 차 큐에서 기다리다 뒤늦게
    # 슬롯을 받은 _call이 자기만의 20초를 새로 시작하면, 클라이언트는 이미
    # TIMEOUT을 받았는데 lock을 잡아 아무도 읽지 않는 LLM 호출을 실행한다(2026-08-27
    # skeptic 감사 Pass 3에서 실측한 zombie). 그래서 deadline 하나를 공유하고,
    # 타임아웃 시 아직 시작 안 한 future는 cancel()로 큐에서 뺀다.
    deadline = time.monotonic() + _TIMEOUT_SECONDS

    def _call():
        # 동기 엔드포인트는 스레드풀에서 돌아 동시 진입이 가능하다 — 원본
        # ApiRuntime.analysis_lock과 같은 이유로 직렬화한다. 예산 안에 lock을
        # 못 잡으면 포기한다(모듈 docstring 4-(b)).
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _LockTimeout()
        lock = request.app.state.analysis_lock
        if not lock.acquire(timeout=remaining):
            raise _LockTimeout()
        try:
            # Pass 3 라운드 2 R2-F2: 예산 안에 lock을 잡았어도 남은 시간이 LLM
            # 호출 1회분보다 짧으면 어차피 클라이언트는 TIMEOUT을 받고, 이 스레드는
            # 아무도 안 읽는 LLM 호출로 lock을 자기 deadline 너머까지 쥔다 —
            # LLM이 배선된 서비스면 여기서 포기한다(규칙기반만이면 ms라 계속).
            if getattr(service, "uses_llm", False) and (deadline - time.monotonic()) < ANALYSIS_LLM_TIMEOUT_SECONDS:
                raise _LockTimeout()
            return service.analyze(summary_request, deadline=deadline)
        finally:
            lock.release()

    future = _EXECUTOR.submit(_call)
    try:
        response = future.result(timeout=max(0.0, deadline - time.monotonic()))
    except (FutureTimeoutError, _LockTimeout):
        future.cancel()  # 큐에서 아직 시작 안 했으면 여기서 제거된다(시작했으면 no-op)
        _LOG.warning("%s: 분석요약이 %d초 내 완료되지 않아 TIMEOUT 응답", page_id, _TIMEOUT_SECONDS)
        return AnalysisReportResponse(status="TIMEOUT")
    except DataSourceError as exc:
        _LOG.info("%s: NO_DATA — %s", page_id, exc)
        return AnalysisReportResponse(status="NO_DATA")
    except Exception:  # noqa: BLE001 — 클라이언트에는 코드만, 상세는 서버 로그에
        _LOG.exception("%s: 분석요약 처리 중 예외 발생 — INTERNAL_ERROR로 응답", page_id)
        return AnalysisReportResponse(status="INTERNAL_ERROR")

    return AnalysisReportResponse(status="ok", report=render_markdown_report(response))


__all__ = ["ANALYSIS_LLM_RETRIES", "ANALYSIS_LLM_TIMEOUT_SECONDS", "run_summary"]
