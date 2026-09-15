#!/usr/bin/env bash
# mnrl_report 컨테이너 진입점 — crontab 렌더링 + supercronic 기동(ingest/entrypoint.sh와 동일 패턴).
set -euo pipefail

CRON_EXPR="${MNRL_REPORT_SCHEDULE_CRON:-0 7 * * TUE}"
CRON_EXPR="${CRON_EXPR%\"}"
CRON_EXPR="${CRON_EXPR#\"}"

printf '%s /komir/inhouse/mnrl_report/cron_mnrl_report_weekly.sh\n' "$CRON_EXPR" > /tmp/mnrl_report.crontab
echo "[entrypoint] crontab: $(cat /tmp/mnrl_report.crontab)"

exec supercronic -passthrough-logs /tmp/mnrl_report.crontab
