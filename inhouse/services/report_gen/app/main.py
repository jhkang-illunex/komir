# -*- coding: utf-8 -*-
"""Report 생성 API 엔트리 — 2026-08-11 구현(CONTAINER_ARCHITECTURE.md §6).

- `POST /reports/{template}/generate` — 수동 트리거(주기 대기 없이 즉시 생성).
  `store=false`면 조립 결과만 돌려주고 `out_report`에 쓰지 않는다(미리보기).
- `GET /reports/{report_id}` — 적재된 리포트 본문 조회.
- 앱 기동 시 `scheduler.create_scheduler()`(APScheduler, `REPORT_SCHEDULE_CRON`)를
  등록하고 종료 시 내린다.

`analysis/` 이식본(외부 저장소 komis-report-generator-main)의 원천 미리보기
엔드포인트는 붙이지 않았다 — 그쪽 `AnalysisScaffoldService.analyze()`가 아직
스텁(계산·서술 없음)이라 API로 노출할 만한 결과물이 아니다(`analysis/__init__.py` 참고).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from ._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import read_sql_msr  # noqa: E402

from .generator import DEFAULT_TEMPLATE, ReportGenerationError, generate_and_store, render_report  # noqa: E402
from .scheduler import create_scheduler  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="komir report_gen", lifespan=lifespan)


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
