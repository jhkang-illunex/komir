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

`analysis/scaffold.py`(원천데이터 미리보기)는 여전히 API로 노출하지 않는다 —
외부repo `main` 브랜치에서도 `analyze()`가 `analysis=None` 스텁이라 노출할 결과물이
없다(2026-08-13 재확인). 분석요약 5종은 그와 **별개 경로**이며 실물이다.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Query

from ._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import read_sql_msr  # noqa: E402

from .generator import (  # noqa: E402
    DEFAULT_TEMPLATE,
    ReportGenerationError,
    generate_and_store,
    render_report,
)
from .routers.analysis import router as analysis_router  # noqa: E402
from .routers.comprehensive import router as comprehensive_router  # noqa: E402
from .scheduler import create_scheduler  # noqa: E402


def build_analysis_summary_service():
    """분석요약 5종 서비스를 조립한다(외부repo `api/app.py`의 동명 함수 대응).

    원본은 자체 psycopg 커넥션 팩토리(`PostgresRawDataRepository(PostgresSettings)`)와
    자체 LLM 클라이언트(`OpenAICompatibleJsonLLM`)를 썼다. 여기서는 komir의
    `services/shared/komis_raw.KomisRawDataRepository`(→ `shared/db.read_sql_pg`)와
    `services/shared/llm_client.KomirJsonLLM`을 쓴다 — 접속·LLM 클라이언트를 2벌
    만들지 않는다.

    설정이 없거나 조립에 실패하면 None을 돌려주고, 라우터가 503으로 응답한다
    (원본 `build_analysis_summary_service()`도 None 반환 규약이다).
    """

    from shared.config import get_settings

    from .analysis.data_sources import (
        DatabaseCompositeIndexDataSource,
        DatabaseDomesticTradeDataSource,
        DatabaseGlobalTradeDataSource,
        DatabaseIndicatorDataSource,
        DatabaseMineralMapDataSource,
        DatabasePriceDataSource,
        DatabasePriceForecastDataSource,
    )
    from .analysis.scaffold import KomisRawDataRepository
    from .analysis.summary import AnalysisSummaryService

    if not get_settings().PG_DSN:
        return None
    repository = KomisRawDataRepository()
    llm = None
    try:
        from shared.llm_client import KomirJsonLLM

        llm = KomirJsonLLM()
    except Exception:  # noqa: BLE001 — LLM 없이도 규칙기반 요약은 나와야 한다
        llm = None
    return AnalysisSummaryService(
        DatabaseIndicatorDataSource(repository),
        composite_source=DatabaseCompositeIndexDataSource(repository),
        mineral_map_source=DatabaseMineralMapDataSource(repository),
        price_forecast_source=DatabasePriceForecastDataSource(repository),
        # 아래 3개는 komir 자체 추가(2026-08-19) — `/prices`·`/domestic-trade`·
        # `/global-trade`, §routers/analysis.py 모듈 docstring 참고.
        price_source=DatabasePriceDataSource(repository),
        domestic_trade_source=DatabaseDomesticTradeDataSource(repository),
        global_trade_source=DatabaseGlobalTradeDataSource(repository),
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


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


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
