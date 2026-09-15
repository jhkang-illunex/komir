"""주간 스케줄러 — 두 가지 방식 중 하나로 붙인다.

1. 컨테이너 cron(권장, ingest와 동일 패턴): `entrypoint.sh`가 supercronic으로
   `cron_mnrl_report_weekly.sh`를 MNRL_REPORT_SCHEDULE_CRON에 맞춰 실행.
2. 상주 프로세스: 이 모듈의 `create_scheduler()`(APScheduler, report_gen과 동일
   패턴)를 다른 서비스가 import해 시작한다.

    python -m mnrl_report.scheduler   # 상주 실행(테스트용)
"""
from __future__ import annotations

import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import get_config, latest_monday
from .run import run

log = logging.getLogger("mnrl_report.scheduler")
JOB_ID = "mnrl_report.weekly"


def weekly_job() -> dict:
    base = latest_monday()
    log.info("주간 통합보고서 생성 시작 base_ymd=%s", base)
    res = run(base)
    log.info("완료: %s", res)
    return res


def create_scheduler() -> BackgroundScheduler:
    s = BackgroundScheduler(timezone="Asia/Seoul")
    s.add_job(weekly_job, CronTrigger.from_crontab(get_config().schedule_cron), id=JOB_ID,
              replace_existing=True, max_instances=1, coalesce=True, misfire_grace_time=3600)
    return s


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sched = create_scheduler()
    sched.start()
    log.info("스케줄 등록: %s (Asia/Seoul)", get_config().schedule_cron)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sched.shutdown()
