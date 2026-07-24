#!/usr/bin/env bash
# 외부 피드 수집 cron 래퍼 (2026-07-24, 피처 인벤토리 D단계 — 수집 상시화)
# 사용법: cron_collect_feeds.sh weekly|monthly
#   weekly (매주 토 09:10): 거래소 재고 증분(SHFE CU/NI·GFEX LI) + COT(금요일 발표분)
#   monthly(매월 6일 09:20): Comtrade 무역흐름·중국 PMI + 수요측(ISM·유로·부동산)
# 로그: komir/data_archive/cron_logs/feeds_<mode>_<YYYYMMDD>.log (보존 정책에 따라 삭제 금지)
set -uo pipefail
MODE="${1:?usage: cron_collect_feeds.sh weekly|monthly}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"          # → komir/
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/feeds_${MODE}_$(date +%Y%m%d).log"
cd "$ROOT/mineral_supply_risk"
export MSR_DB="$ROOT/warehouse/minerals.duckdb"
{
  echo "=== $(date '+%F %T') cron feeds [$MODE] 시작 ==="
  if [ "$MODE" = "weekly" ]; then
    python3 -m scripts.collect_exchange_inventory        # 증분(기본 8주)
    python3 -m scripts.collect_forecast_exog             # COT 전량 갱신(멱등)+WM
  else
    python3 -m scripts.collect_priority_feeds            # Comtrade+PMI(전량 멱등)
    python3 -m scripts.collect_demand_feeds              # ISM·유로·부동산
  fi
  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
