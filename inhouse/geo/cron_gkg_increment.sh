#!/usr/bin/env bash
# GKG 증분 전처리→DB화 주간 cron (2026-07-24 확립 절차의 자동화)
# 등록: 매주 토 06:30 (수집 feeds cron 09:10 이전에 종료되도록 — 전체 ~1h)
# 2026-08-06 DMZ/in-house 물리 분리로 다운로드 단계([1/7][2/7])는
# dmz/geo_collectors/cron_gkg_download.sh로 분리됐다 — 이 스크립트는 그 다운로드 결과(망연계
# 게이트웨이로 전달된 GKG 벌크 파일)가 $BULK에 이미 도착해있다는 전제로 파싱부터 시작한다.
#
# 순서가 중요(2026-07-24 실측 함정 — WORKLOG 최신⑮):
#   파싱 → LLM 전량 검증(--limit 0) → **샤드 병합 → 기각 제거** → 지수/확률/발행
#   (샤드 병합 전에 기각 제거만 하면 publish에서 기각분이 샤드 경유로 부활)
# 안전장치:
#   - LLM 헬스체크 실패 시 파싱까지만 하고 중단(미검증 이벤트가 발행되지 않도록
#     이후 단계 전부 스킵 — 다음 주 실행이 state 기반으로 이어서 처리)
#   - flock으로 중복 실행 방지
# 로그: data_archive/cron_logs/gkg_weekly_<YYYYMMDD>.log (보존 정책 — 삭제 금지)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"              # → komir/ (2026-08-05 engine/ 편입으로 한 단 깊어짐)
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
  cd "$ROOT/inhouse"   # 2026-08-06 DMZ/in-house 분리 반영 — `python -m geo`는 geo 패키지의
                       # 부모 디렉토리에서 실행해야 함(komir/inhouse/geo가 아니라 komir/inhouse/)

  echo "--- [1/5] 파싱(state 증분) ---"
  python3 -m geo gkg-parse --bulk-root "$BULK" --year-from "$YEAR_FROM" 2>&1 | tail -3

  echo "--- LLM 헬스체크 ---"
  if ! curl -sf --max-time 10 "$LLM_URL" > /dev/null; then
    echo "$(date '+%F %T') LLM 서버 미응답 — 검증·발행 스킵(파싱분은 다음 실행에서 검증)"
    exit 0
  fi

  echo "--- [2/5] LLM 재검증 전량 ---"
  python3 -m geo.gkg_verify --bulk-root "$BULK" --provider openai_compat --limit 0 2>&1 | tail -2

  echo "--- [3/5] 샤드 병합(기각 제거보다 먼저!) ---"
  python3 - <<'PY'
import sys, os
sys.path.insert(0, os.getcwd())
from geo import store
n = store.compact_event_shards()
print(f"샤드 {n if n else 0}개 병합")
PY

  echo "--- [4/5] 기각분 실삭제 ---"
  python3 -m geo.gkg_verify --bulk-root "$BULK" --compact-rejections 2>&1 | tail -1

  echo "--- [5/5] 지수·확률 재산출 + publish ---"
  python3 -m geo index 2>&1 | tail -1
  python3 -m geo prob 2>&1 | tail -1
  python3 -m geo publish --db "$ROOT/inhouse/data_lake/db/minerals.duckdb" --what all 2>&1 | tail -3

  echo "=== $(date '+%F %T') 종료 ==="
} >> "$LOG" 2>&1
