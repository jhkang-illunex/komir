#!/usr/bin/env bash
# GKG 증분 수집→전처리→DB화 주간 cron (2026-07-24 확립 절차의 자동화)
# 등록: 매주 토 06:30 (수집 feeds cron 09:10 이전에 종료되도록 — 전체 ~1h)
#
# 순서가 중요(2026-07-24 실측 함정 — WORKLOG 최신⑮):
#   다운로드 → 파싱 → LLM 전량 검증(--limit 0) → **샤드 병합 → 기각 제거** → 지수/확률/발행
#   (샤드 병합 전에 기각 제거만 하면 publish에서 기각분이 샤드 경유로 부활)
# 안전장치:
#   - LLM 헬스체크 실패 시 파싱까지만 하고 중단(미검증 이벤트가 발행되지 않도록
#     이후 단계 전부 스킵 — 다음 주 실행이 state 기반으로 이어서 처리)
#   - flock으로 중복 실행 방지
# 로그: data_archive/cron_logs/gkg_weekly_<YYYYMMDD>.log (보존 정책 — 삭제 금지)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"                 # → komir/
BULK=/mnt/nas2_team_ai/jhkang/광해공단/bulk/gdelt
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/gkg_weekly_$(date +%Y%m%d).log"
LOCK=/tmp/komir_gkg_increment.lock
LLM_URL="http://localhost:52302/v1/models"
# 연말 경계 대비: 30일 전이 속한 연도부터 스캔
YEAR_FROM=$(date -d '30 days ago' +%Y)

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 이미 실행 중(lock) — 종료" >> "$LOG"
  exit 0
fi

{
  echo "=== $(date '+%F %T') GKG 증분 cron 시작 (year-from=$YEAR_FROM) ==="
  cd "$ROOT"

  echo "--- [1/7] 마스터리스트 갱신+증분 다운로드 ---"
  rm -f geo/collectors/_gkg_masterfilelist_cache.txt
  python3 -m geo.collectors.gkg_bulk_download --worker 0 --workers 1 \
    --year-from "$YEAR_FROM" 2>&1 | tail -2

  echo "--- [2/7] 파싱(state 증분) ---"
  python3 -m geo gkg-parse --bulk-root "$BULK" --year-from "$YEAR_FROM" 2>&1 | tail -3

  echo "--- LLM 헬스체크 ---"
  if ! curl -sf --max-time 10 "$LLM_URL" > /dev/null; then
    echo "$(date '+%F %T') LLM 서버 미응답 — 검증·발행 스킵(파싱분은 다음 실행에서 검증)"
    exit 0
  fi

  echo "--- [3/7] LLM 재검증 전량 ---"
  python3 -m geo.gkg_verify --bulk-root "$BULK" --provider openai_compat --limit 0 2>&1 | tail -2

  echo "--- [4/7] 샤드 병합(기각 제거보다 먼저!) ---"
  python3 - <<'PY'
import sys, os
sys.path.insert(0, os.getcwd())
from geo import store
n = store.compact_event_shards()
print(f"샤드 {n if n else 0}개 병합")
PY

  echo "--- [5/7] 기각분 실삭제 ---"
  python3 -m geo.gkg_verify --bulk-root "$BULK" --compact-rejections 2>&1 | tail -1

  echo "--- [6/7] 지수·확률 재산출 ---"
  python3 -m geo index 2>&1 | tail -1
  python3 -m geo prob 2>&1 | tail -1

  echo "--- [7/7] publish ---"
  python3 -m geo publish --db "$ROOT/warehouse/minerals.duckdb" --what all 2>&1 | tail -3

  echo "=== $(date '+%F %T') 종료 ==="
} >> "$LOG" 2>&1
