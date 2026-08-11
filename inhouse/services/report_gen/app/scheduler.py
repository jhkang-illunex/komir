# -*- coding: utf-8 -*-
"""주기 실행(`REPORT_SCHEDULE_CRON`) → `generator.generate_and_store()` → `out_report`.

2026-08-11 구현. 설계(CONTAINER_ARCHITECTURE.md §6) 그대로 APScheduler cron 1개가
5광종 브리프를 순회 생성한다. 적재는 `generator.store_report()`가
`services/shared/db.write_df_msr`(=dbio.write_df)로 수행 — 이 파일이 DB를 직접
건드리지 않는다.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.config import get_settings  # noqa: E402

from .generator import VALID_COMMODITIES, generate_and_store  # noqa: E402

logger = logging.getLogger(__name__)

JOB_ID = "report_gen.weekly_brief"


def run_all_commodities() -> list[dict]:
    """5광종 브리프를 생성해 `out_report`에 적재한다(한 광종이 실패해도 계속)."""

    results: list[dict] = []
    for code in VALID_COMMODITIES:
        try:
            report = generate_and_store(code)
            logger.info("리포트 생성 완료: %s (%s)", report["report_id"], code)
            results.append(
                {
                    "commodity_code": code,
                    "report_id": report["report_id"],
                    "stored_rows": report["stored_rows"],
                }
            )
        except Exception as exc:  # noqa: BLE001 — 한 광종 실패가 배치 전체를 막지 않게
            logger.exception("리포트 생성 실패: %s", code)
            results.append({"commodity_code": code, "error": str(exc)})
    return results


def create_scheduler() -> BackgroundScheduler:
    """`.env`의 `REPORT_SCHEDULE_CRON`(기본 '0 6 * * MON')으로 작업 1개를 등록한다."""

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_all_commodities,
        CronTrigger.from_crontab(get_settings().REPORT_SCHEDULE_CRON),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
