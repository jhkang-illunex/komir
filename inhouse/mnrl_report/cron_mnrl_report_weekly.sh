#!/usr/bin/env bash
# 통합보고서 주간 규칙 엔진 — 컨테이너에선 supercronic이 호출(env는 env_file 주입),
# 호스트 수동 실행 시엔 inhouse/.env를 직접 source한다(ingest/cron_ingest_weekly.sh와
# 같은 구조: set -uo pipefail·flock·필수 env 강제).
set -uo pipefail
INHOUSE="$(cd "$(dirname "$0")/.." && pwd)"    # → inhouse/ (컨테이너: /komir/inhouse)
cd "$INHOUSE"

if [ -f "$INHOUSE/.env" ]; then
  set -a
  source "$INHOUSE/.env"
  set +a
fi
: "${PG_DSN:?PG_DSN이 설정되지 않음 — inhouse/.env 확인}"

LOCK=/tmp/komir_mnrl_report_weekly.lock
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 이미 실행 중(lock) — 종료"
  exit 0
fi

echo "$(date '+%F %T') mnrl_report 주간 실행 시작"
python -m mnrl_report.run "$@"
rc=$?
echo "$(date '+%F %T') mnrl_report 종료 rc=$rc"
exit $rc
