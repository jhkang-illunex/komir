# -*- coding: utf-8 -*-
"""Report 생성 API 엔트리 — 2026-08-11 구현(CONTAINER_ARCHITECTURE.md §6).

- `POST /reports/{template}/generate` — 수동 트리거(주기 대기 없이 즉시 생성).
  `store=false`면 조립 결과만 돌려주고 `out_report`에 쓰지 않는다(미리보기).
- `GET /reports/{report_id}` — 적재된 리포트 본문 조회.
- `POST /api/v1/analysis/{market-indicator,supply-indicator,composite-index,
  mineral-map,price-forecast}` — KOMIS 분석요약 5종(2026-08-13 추가,
  `routers/analysis.py`). 외부 저장소 komis-report-generator-main의 실물 엔진을
  `app/analysis/`로 이식해 배선한 것이다.
- `POST /api/v1/analysis/{prices,domestic-trade,global-trade}` — 나머지 3종
  (2026-08-19 추가). 외부repo도 501 스텁이라 참고할 구현이 없어 komir가 자체로
  짰다(`analysis/data_sources/extra.py`+`analysis/komir_summary.py`).
- `POST /api/v1/{prices,indicators,maps}/...` — 보고서 요약 템플릿용 REST
  엔드포인트(2026-08-26 신규, `routers/report_data.py`). 위 `/api/v1/analysis/*`
  8종과 같은 서비스를 재사용하되 price/idx/map 3계열로 재배치했다. `/prices/
  {base-metals,minor-metals}`도 나머지와 동일하게 `page_id="price"`로 위임한다
  (그룹 검증 없는 단순 별칭 — 상세는 그 라우터 모듈 docstring 참고).
- **2026-08-26 DB 조회 → 요청 바디 입력 전환**: 위 분석요약 8종은 이제
  `public.KO_*`를 직접 조회하지 않는다 — "이 서버는 prompt/template를 제외하고는
  DB에서 값을 로딩하지 않는다"는 원칙에 따라, 계산에 쓰는 원자료(observations)를
  각 요청 바디로 받는다(`analysis/models.py::AnalysisSummaryRequest`의
  `observations`/`mineral_name`/`unit`/`price_unit` 등). DB 조회 코드는 삭제하지
  않고 `build_analysis_summary_service()`·`analysis/summary.py`에서 호출부만
  주석 처리해 남겨 뒀다(복원 가능). 상세는 `documents/meta/WORKLOG.md`
  2026-08-26 항목 참고.
- `GET /api/v1/dashboard/comprehensive` — AI 종합분석 및 관련뉴스(2026-08-13
  신규, `routers/comprehensive.py`+`analysis/comprehensive.py`). 화면기획안
  ver.1.3(11p) 대응 — 5광종 통합 위기지수·리스크태그·대응전략+광종별 주간
  뉴스카드 5개를 komir 자체 산출물(geo_index·out_diagnosis_alert·geo_event)만으로
  조립한다(위 5종과 달리 `public.KO_*` 의존 없음). ⚠ 2026-08-19~20 별도 세션이
  화면기획 §13(같은 요구사항)을 `out_ai_dashboard_summary`+
  `report_gen/app/dashboard_summary.py`(배치·LLM 서술·postgres 저장)로 독립
  구현 — 이 라우터(on-demand·규칙기반 카탈로그)와 기능이 겹친다. 어느 쪽을
  정본으로 할지 아직 미정, WORKLOG 참고.
- 앱 기동 시 `scheduler.create_scheduler()`(APScheduler, `REPORT_SCHEDULE_CRON`)를
  등록하고 종료 시 내린다.
- `POST /admin/prompts/reload` — 분석요약 LLM 프롬프트(`ai_cfg.cfg_prompt`, PostgreSQL·PG_DSN)
  캐시를 다시 읽는다(2026-08-26 신규, `analysis/prompt_store.py`). 앱 기동
  시에도 1회 자동 로드하고, 이후엔 이 엔드포인트가 호출될 때만 다시 읽는다 —
  DB 행을 갱신한 뒤 이걸 호출하면 서버 재시동 없이 다음 보고서 생성부터 새
  프롬프트가 반영된다.

`analysis/scaffold.py`(원천데이터 미리보기)는 여전히 API로 노출하지 않는다 —
외부repo `main` 브랜치에서도 `analyze()`가 `analysis=None` 스텁이라 노출할 결과물이
없다(2026-08-13 재확인). 분석요약 5종은 그와 **별개 경로**이며 실물이다.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import read_sql_msr  # noqa: E402

from .analysis import prompt_store  # noqa: E402
from .analysis.models import AnalysisReportResponse  # noqa: E402
from .generator import DEFAULT_TEMPLATE, ReportGenerationError, generate_and_store, render_report  # noqa: E402
from .routers.analysis import router as analysis_router  # noqa: E402
from .routers.comprehensive import router as comprehensive_router  # noqa: E402
from .routers.report_data import (  # noqa: E402
    indicators_router,
    maps_router,
    prices_router,
)
from .routers._common import ANALYSIS_LLM_RETRIES, ANALYSIS_LLM_TIMEOUT_SECONDS  # noqa: E402
from .scheduler import create_scheduler  # noqa: E402


def build_analysis_summary_service():
    """분석요약 8종 서비스를 조립한다(외부repo `api/app.py`의 동명 함수 대응).

    원본은 자체 psycopg 커넥션 팩토리(`PostgresRawDataRepository(PostgresSettings)`)와
    자체 LLM 클라이언트(`OpenAICompatibleJsonLLM`)를 썼다. 여기서는 komir의
    `services/shared/llm_client.KomirJsonLLM`을 쓴다.

    **2026-08-26: DB 조회 경로 비활성화** — "이 서버는 prompt/template를 제외하고는
    DB에서 값을 로딩하지 않는다"는 원칙에 따라, 8종 전부 `public.KO_*` 직접
    조회(`KomisRawDataRepository`+`Database*DataSource`)를 멈췄다. 이제
    `AnalysisSummaryService`의 각 `_analyze_*`가 요청 바디의 `observations`로
    Series를 직접 조립한다(`analysis/summary.py` 참고) — 그래서 DataSource
    인자는 전부 `None`으로 넘긴다. 복원하려면 아래 주석 블록을 해제하고
    `None` 대신 다시 인스턴스를 넘기면 된다(DataSource 클래스 정의 자체는
    `data_sources/`에 그대로 남아 있다 — 삭제하지 않았다).
    """

    from shared.config import get_settings

    # from .analysis.data_sources import (
    #     DatabaseCompositeIndexDataSource,
    #     DatabaseDomesticTradeDataSource,
    #     DatabaseGlobalTradeDataSource,
    #     DatabaseIndicatorDataSource,
    #     DatabaseMineralMapDataSource,
    #     DatabasePriceDataSource,
    #     DatabasePriceForecastDataSource,
    # )
    # from .analysis.scaffold import KomisRawDataRepository
    from .analysis.summary import AnalysisSummaryService

    # PG_DSN 가드는 예전엔 "DataSource가 DB에 붙을 수 있는지"의 대리 지표였다.
    # 이제 analyze() 자체는 DB가 필요 없지만, 프롬프트 캐시(ai_cfg.cfg_prompt)는
    # 여전히 PG_DSN이 필요해(§lifespan의 prompt_store.reload()) 이 가드를
    # 일단 유지한다 — PG_DSN 없이도 분석요약 8종을 규칙기반으로라도 띄우고
    # 싶다면 이 줄을 지우면 된다(열린 결정, WORKLOG 참고).
    if not get_settings().PG_DSN:
        return None
    # repository = KomisRawDataRepository()
    llm = None
    try:
        from shared.llm_client import KomirJsonLLM

        # 2026-08-27 skeptic 감사 SC-002: 기본 cfg(LLM_TIMEOUT_SECONDS=120, retries 3)
        # 그대로 쓰면 느린 LLM 응답 1건이 `routers/_common.py`의 analysis_lock을
        # 수 분(전송 실패 경로 ≈372s) 쥐고 뒤 요청 전부를 TIMEOUT시킨다(실측).
        # 요청당 예산이 20초이므로 report_gen용 클라이언트만 timeout·retries를
        # 그 규모로 줄여 lock 점유를 바운드한다 — LLM 자체를 20초 안에 "맞추는"
        # 게 아니라 연쇄 반경을 줄이는 것(vLLM 장애 시 폴백은 그대로 규칙기반).
        llm = KomirJsonLLM(
            {
                **get_settings().llm_cfg(),
                "timeout": ANALYSIS_LLM_TIMEOUT_SECONDS,
                "retries": ANALYSIS_LLM_RETRIES,
            }
        )
    except Exception:  # noqa: BLE001 — LLM 없이도 규칙기반 요약은 나와야 한다
        llm = None
    return AnalysisSummaryService(
        None,  # DatabaseIndicatorDataSource(repository) — 2026-08-26 비활성화
        composite_source=None,  # DatabaseCompositeIndexDataSource(repository)
        mineral_map_source=None,  # DatabaseMineralMapDataSource(repository)
        price_forecast_source=None,  # DatabasePriceForecastDataSource(repository)
        # 아래 3개는 komir 자체 추가(2026-08-19) — `/prices`·`/domestic-trade`·
        # `/global-trade`, §routers/analysis.py 모듈 docstring 참고.
        price_source=None,  # DatabasePriceDataSource(repository)
        domestic_trade_source=None,  # DatabaseDomesticTradeDataSource(repository)
        global_trade_source=None,  # DatabaseGlobalTradeDataSource(repository)
        llm=llm,
    )


def build_comprehensive_service():
    """"AI 종합분석 및 관련뉴스" 서비스를 조립한다(2026-08-13, `analysis/
    comprehensive.py`). 분석요약 5종과 달리 komir 자체 산출물(MSR_DB=DuckDB)만
    읽어 PG(`KomisRawDataRepository`)가 필요 없다 — LLM 실패 시에도 규칙기반
    폴백이 있어 None을 돌려주지 않는다(LLM 없이도 서비스 자체는 항상 뜬다)."""

    from .analysis.comprehensive import ComprehensiveAnalysisService

    llm = None
    try:
        from shared.llm_client import KomirJsonLLM

        llm = KomirJsonLLM()
    except Exception:  # noqa: BLE001 — LLM 없이도 규칙기반 결과는 나와야 한다
        llm = None
    return ComprehensiveAnalysisService(llm=llm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    loaded = prompt_store.reload()
    logging.getLogger(__name__).info("cfg_prompt에서 프롬프트 %d건 로드(없으면 하드코드 기본값 사용)", loaded)
    try:
        app.state.analysis_summary_service = build_analysis_summary_service()
    except Exception:  # noqa: BLE001 — 분석요약이 못 떠도 리포트 생성은 살려둔다
        # 로그를 남기지 않으면 설정 실수가 "그냥 503"으로만 보여 원인 추적이 안 된다.
        logging.getLogger(__name__).exception("분석요약 서비스 조립 실패 — 5종 API는 503으로 응답한다")
        app.state.analysis_summary_service = None
    try:
        app.state.comprehensive_service = build_comprehensive_service()
    except Exception:  # noqa: BLE001 — 종합분석이 못 떠도 나머지 API는 살려둔다
        logging.getLogger(__name__).exception("AI 종합분석 서비스 조립 실패 — /api/v1/dashboard/comprehensive는 503으로 응답한다")
        app.state.comprehensive_service = None
    app.state.analysis_lock = Lock()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        service = getattr(app.state, "analysis_summary_service", None)
        if service is not None:
            service.close()
        comprehensive_service = getattr(app.state, "comprehensive_service", None)
        if comprehensive_service is not None:
            comprehensive_service.close()


app = FastAPI(title="komir report_gen", lifespan=lifespan)
app.include_router(analysis_router)
app.include_router(comprehensive_router)
app.include_router(prices_router)
app.include_router(indicators_router)
app.include_router(maps_router)

#: 분석요약 API 프리픽스 — 이 아래 경로만 "HTTP 항상 200 + 바디 status" 계약이다.
_ANALYSIS_API_PREFIXES = ("/api/v1/analysis/", "/api/v1/prices/", "/api/v1/indicators/", "/api/v1/maps/")


@app.exception_handler(RequestValidationError)
async def _analysis_request_validation_to_no_data(request: Request, exc: RequestValidationError):
    """분석요약 라우트의 요청 스키마 위반(알 수 없는 필드, start>end 등)도 422가
    아니라 200 + `NO_DATA`로 돌려준다 — 2026-08-27 skeptic 감사 Pass 3에서 "항상
    200" 계약이 라우터 스키마를 통과한 바디에만 적용되던 간극을 지적. 그 밖의
    경로(`/reports/*`, `/api/v1/dashboard/*`)는 FastAPI 기본 422 그대로다."""

    if request.url.path.startswith(_ANALYSIS_API_PREFIXES):
        logging.getLogger(__name__).info(
            "%s: NO_DATA — 요청 스키마 위반: %s", request.url.path, exc.errors()[0].get("msg") if exc.errors() else exc
        )
        return JSONResponse(status_code=200, content=AnalysisReportResponse(status="NO_DATA").model_dump())
    return await request_validation_exception_handler(request, exc)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/admin/prompts/reload")
def reload_prompts() -> dict:
    """`cfg_prompt`를 다시 읽어 프롬프트 캐시를 교체한다(서버 재시동 불필요).
    이후 생성되는 보고서부터 새 프롬프트를 쓴다 — 진행 중인 호출에는 영향 없다."""

    return {"reloaded_prompt_count": prompt_store.reload()}


@app.post("/reports/{template}/generate")
def generate(
    template: str,
    commodity_code: str = Query(..., description="CU|NI|CO|LI|REE"),
    store: bool = Query(True, description="false면 out_report에 적재하지 않고 본문만 반환"),
) -> dict:
    """템플릿×정형데이터로 리포트 1건을 생성한다(기본은 `out_report` 적재까지)."""

    name = template if template.endswith(".j2") else f"{template}.md.j2"
    try:
        if store:
            return generate_and_store(commodity_code, template=name)
        return render_report(commodity_code, template=name)
    except ReportGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"리포트 생성 실패: {exc}") from exc


@app.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    """적재된 리포트 1건을 돌려준다."""

    if not report_id.replace("_", "").isalnum() or len(report_id) > 32:
        raise HTTPException(status_code=400, detail="잘못된 report_id")
    frame = read_sql_msr(
        f"""
        SELECT report_id, commodity_code, period, kind, title, body, generated_at
        FROM out_report
        WHERE report_id = '{report_id}'
        LIMIT 1
        """
    )
    if not len(frame):
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없음")
    return {k: (str(v) if k == "generated_at" else v) for k, v in frame.iloc[0].to_dict().items()}


@app.get("/reports")
def list_reports(limit: int = Query(20, ge=1, le=100)) -> list[dict]:
    """최근 생성된 리포트 목록(본문 제외)."""

    frame = read_sql_msr(
        f"""
        SELECT report_id, commodity_code, period, kind, title, generated_at
        FROM out_report
        ORDER BY generated_at DESC
        LIMIT {int(limit)}
        """
    )
    return [
        {k: (str(v) if k == "generated_at" else v) for k, v in row.items()}
        for row in frame.to_dict("records")
    ]


__all__ = ["app", "DEFAULT_TEMPLATE"]
