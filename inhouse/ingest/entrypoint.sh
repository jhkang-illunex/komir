#!/usr/bin/env bash
# ingest 컨테이너 진입점 — crontab 렌더링 + supercronic 기동.
# INGESTION_SCHEDULE_CRON은 inhouse/.env.example에 이미 예약된 변수를 그대로 재사용
# (CONTAINER_ARCHITECTURE.md §5-3, "정형+비정형+RAG 인덱스 전체, 매주 일요일" —
# 새 변수명을 만들지 않는다).
set -euo pipefail

: "${INGESTION_SCHEDULE_CRON:?INGESTION_SCHEDULE_CRON이 설정되지 않음 — inhouse/.env 확인}"

# .env 값이 따옴표를 포함한 채로 주입되는 compose 구현이 있을 수 있어 방어적으로
# 양끝 따옴표를 제거한다("0 0 * * SUN" 형태로 .env.example에 적혀 있음).
CRON_EXPR="${INGESTION_SCHEDULE_CRON%\"}"
CRON_EXPR="${CRON_EXPR#\"}"

printf '%s /komir/inhouse/ingest/cron_ingest_weekly.sh\n' "$CRON_EXPR" > /tmp/ingest.crontab
echo "[entrypoint] crontab: $(cat /tmp/ingest.crontab)"

exec supercronic -passthrough-logs /tmp/ingest.crontab
