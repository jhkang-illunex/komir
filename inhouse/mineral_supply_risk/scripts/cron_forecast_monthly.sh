#!/usr/bin/env bash
# 12개월 수요량·단가 예측 파이프라인 — 월간(2026-08-19 신설).
# 등록: 독립 crontab 항목, 매월 첫째주 일요일 새벽(.env의 FORECAST_SCHEDULE_CRON=
# "0 1 1-7 * SUN" 설계값 그대로 — day-of-month 1-7 AND day-of-week SUN 조합으로
# "첫째주 일요일만"을 강제). ExtraTrees direct 다지평 + conformal 구간보정 + SHAP
# 설명까지 forecast_unit.run() 하나가 전부 수행 → out_import_forecast_unit·
# mart_forecast_method_log 적재.
#
# 전제: mart_monthly_forecast_input이 참조하는 fact_trade_monthly가 최신이어야 함 —
# raw_customs_* 자체를 갱신하는 cron이 아직 없다(관세청 DMZ 수집기 wiring 미완료,
# WORKLOG/메모리 next-tasks-komir 참고). 이 스크립트는 그 상태에서도 있는 데이터로
# 안전하게(멱등) 재적합만 수행한다 — 관세청 최신화는 별도 작업.
#
# 로그: data_archive/cron_logs/forecast_monthly_<YYYYMMDD>.log (삭제 금지 정책)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"   # → komir/
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/forecast_monthly_$(date +%Y%m%d).log"
LOCK=/tmp/komir_forecast_monthly.lock
cd "$ROOT/inhouse/mineral_supply_risk"
# cron은 .env를 자동으로 읽지 않는다 — 여기서 명시적으로 source(python-dotenv의
# load_dotenv()는 파이썬 프로세스 내부에서만 유효, 이 셸엔 안 보임). duckdb 파일경로로
# 폴백하지 않고(postgres 단일 정본), .env에 값이 없으면 명시적으로 실패한다.
set -a
source "$ROOT/inhouse/.env"
set +a
: "${MSR_DB:?MSR_DB가 설정되지 않음 — inhouse/.env의 postgres DSN을 확인할 것}"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 이미 실행 중(lock) — 종료" >> "$LOG"
  exit 0
fi

{
  echo "=== $(date '+%F %T') 12개월 수요량·단가 예측 시작 (MSR_DB=$MSR_DB) ==="
  # ExtraTrees(direct)+conformal+SHAP, 5광종×h1~12 전체 — 수 분 소요될 수 있음
  # (dashboards/streamlit_app.py·services/commodity_api 실측 기준 h1건 조회에도
  # conformal 3원점 재적합 포함 3분 내외).
  python3 -m msr.models.forecast_unit 2>&1 | tail -40
  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
