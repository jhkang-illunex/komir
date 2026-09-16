#!/usr/bin/env bash
# ingest 주간 체인 — 호스트 crontab 호환 래퍼(2026-09-16부터 본체는 `python -m ingest.run_chain`).
# 컨테이너 supercronic도 같은 명령을 부른다(entrypoint.sh). 단계 순서·flock·로그·실패 처리는
# run_chain.py에 있다(이 파일에 단계를 다시 적지 말 것 — 예전엔 여기 하드코딩돼 있었다).
#
# 호스트 crontab 예:
#   0 0 * * SUN  /path/komir/inhouse/ingest/cron_ingest_weekly.sh >> /var/log/komir_ingest.log 2>&1
# 컨테이너(docker compose)에서 호스트 crontab으로 돌릴 때:
#   0 0 * * SUN  cd /path/komir/deploy && docker compose run --rm ingestion python3 -m ingest.run_chain --trigger cron
set -uo pipefail
INHOUSE="$(cd "$(dirname "$0")/.." && pwd)"    # → inhouse/ (컨테이너: /komir/inhouse)
cd "$INHOUSE"

if [ -f "$INHOUSE/.env" ]; then
  set -a
  source "$INHOUSE/.env"
  set +a
fi
: "${PG_DSN:?PG_DSN이 설정되지 않음 — inhouse/.env 확인}"

exec python3 -m ingest.run_chain --trigger cron "$@"
