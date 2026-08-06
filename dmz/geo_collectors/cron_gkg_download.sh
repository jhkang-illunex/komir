#!/usr/bin/env bash
# GKG 증분 다운로드 주간 cron (DMZ 몫 — 2026-08-06 inhouse/geo/cron_gkg_increment.sh에서 분할)
# 등록: 매주 토 06:30 (수집 feeds cron 09:10 이전에 종료되도록)
#
# 원래 in-house 스크립트의 [1/7][2/7] 단계(마스터리스트 갱신+증분 다운로드)만 담당한다.
# DMZ 존 원칙: LLM 없음 — 원본 다운로드 후 파일로 in-house에 전달만 한다. 전달(망연계
# 게이트웨이) 이후 단계는 이 스크립트가 신경 쓸 필요 없음 — 다운로드 결과를 로컬 산출
# 디렉토리($BULK)에 남기기만 하면 된다. 파싱·LLM 검증·지수 산출·publish는
# inhouse/geo/cron_gkg_increment.sh(같은 요일, 전달 이후 실행)가 이어받는다.
#
# 안전장치:
#   - flock으로 중복 실행 방지
# 로그: data_archive/cron_logs/gkg_weekly_download_<YYYYMMDD>.log (보존 정책 — 삭제 금지)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"              # → komir/
BULK=/mnt/nas2_team_ai/jhkang/광해공단/bulk/gdelt
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/gkg_weekly_download_$(date +%Y%m%d).log"
LOCK=/tmp/komir_gkg_download.lock
# 연말 경계 대비: 30일 전이 속한 연도부터 스캔
YEAR_FROM=$(date -d '30 days ago' +%Y)

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 이미 실행 중(lock) — 종료" >> "$LOG"
  exit 0
fi

{
  echo "=== $(date '+%F %T') GKG 증분 다운로드 cron 시작 (year-from=$YEAR_FROM) ==="
  cd "$ROOT/dmz"   # `python -m geo_collectors.xxx`는 geo_collectors 패키지의 부모
                    # 디렉토리에서 실행해야 함(engine/geo 이관 때와 동일 원리)

  echo "--- [1/2] 마스터리스트 갱신+증분 다운로드 ---"
  rm -f geo_collectors/_gkg_masterfilelist_cache.txt
  python3 -m geo_collectors.gkg_bulk_download --worker 0 --workers 1 \
    --dest "$BULK" --year-from "$YEAR_FROM" 2>&1 | tail -2

  echo "=== $(date '+%F %T') 종료 ==="
} >> "$LOG" 2>&1
