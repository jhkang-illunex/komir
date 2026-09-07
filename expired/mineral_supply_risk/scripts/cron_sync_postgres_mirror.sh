#!/usr/bin/env bash
# minerals.duckdb -> postgres(komis_demo, mineral_risk 스키마) 정기 동기화 (2026-08-19 신설).
#
# 배경: RAG 챗봇의 structured.py가 read_sql_msr(duckdb)에서 read_sql_pg(mineral_risk
# 스키마)로 전환됐는데(같은 날), PG 쪽은 2026-08-10 1회성 이관 이후 정기 동기화가 없어
# geo_index가 라이브 대비 약 1주 stale해져 있던 걸 실측으로 발견 — 이 스크립트가 그
# 재발 방지책이다. scripts/migrate_duckdb_to_postgres.py(기존 1회성 이관 스크립트, 재사용 —
# 신규 작성 아님) 그대로 호출한다 — DROP+CREATE TABLE AS SELECT 전체 재적재라 멱등하고,
# 원본 duckdb는 read_only로 열어 라이브 프로세스(cron·streamlit)와 충돌하지 않는다.
#
# 등록: 매일 05:00(토요일 geo cron 07:00·feeds cron 09:10/09:20보다 앞선 조용한 시간대,
# 겹침 없음). out_diagnosis_alert/out_import_forecast는 수동 재학습이라 cron 주기와 무관하게
# 갱신될 수 있으므로, 갱신 직후 사람이 이 스크립트를 수동 재실행해도 안전(멱등)하다.
#
# 로그: komir/data_archive/cron_logs/pg_sync_<YYYYMMDD>.log (보존 정책, 삭제 금지)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"   # → komir/
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/pg_sync_$(date +%Y%m%d).log"
LOCK=/tmp/komir_pg_sync.lock
cd "$ROOT/inhouse/mineral_supply_risk"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 이미 실행 중(lock) — 종료" >> "$LOG"
  exit 0
fi

{
  echo "=== $(date '+%F %T') postgres 동기화 시작 ==="
  python3 -m scripts.migrate_duckdb_to_postgres
  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
