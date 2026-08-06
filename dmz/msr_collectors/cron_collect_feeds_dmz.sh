#!/usr/bin/env bash
# DMZ 측 외부 피드 수집 cron 래퍼 (2026-08-06 신설, dmz/inhouse 물리분리 리팩터)
# 원본: inhouse/mineral_supply_risk/scripts/cron_collect_feeds.sh(현 cron_collect_feeds_inhouse.sh)
#
# 이 스크립트는 원본 cron 중 "키가 필요한 직접 API 호출" 부분을 담당한다: msr.collectors
# (customs_api·ecos_api)와, 2026-08-06 추가로 collect_intl_agency_feeds.py의 Census·BPS
# (CENSUS_API_KEY·BPS_API_KEY 필요분)까지. 원본의 나머지 다수 항목(collect_exchange_inventory·
# collect_priority_feeds·collect_tier1/3_feeds·collect_intl_agency_feeds의 무키 8개 소스 등)은
# msr.collectors를 거치지 않는 직접 requests 수집이라 이번 리팩터 범위 밖 — 그대로 inhouse
# 쪽에 남아있다(cron_collect_feeds_inhouse.sh, 잔여 DMZ 경계 위반으로 별도 문서화됨).
# tier2_feeds·tier4_feeds 자체도 대부분 그런 직접수집이라 in-house에서 계속 도는데, 그 안의
# ECOS 하위 단계(collect_ecos/collect_ecos_ship)만 여기로 옮겨왔다 — in-house 쪽 tier2/tier4·
# intl_agency_feeds 실행 "전에" 이 스크립트가 먼저 돌아 parquet을 준비해둬야 한다.
#
# 사용법: cron_collect_feeds_dmz.sh weekly|monthly (weekly는 현재 대상 항목 없음 — no-op)
# 운영 순서: 1) 이 스크립트(DMZ) → 2) 산출물($MSR_COLLECT_OUT)을 inhouse로 전달
#            (공유마운트/rsync, dmz/collector/README.md 패턴 참고) → 3) inhouse cron
# 개발환경(단일 저장소, 물리분리 전)에서는 두 cron이 같은 $MSR_COLLECT_OUT 경로를
# 가리키므로 별도 전송 없이 바로 동작한다.
set -uo pipefail
MODE="${1:?usage: cron_collect_feeds_dmz.sh weekly|monthly}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"     # → komir/
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/feeds_dmz_${MODE}_$(date +%Y%m%d).log"
cd "$ROOT/dmz"
# 공유 산출물 루트 — 실운영에서는 dmz측 로컬 경로 + rsync/NAS로 inhouse에 전달되는 대상.
# 현재(단일 저장소) 개발환경에서는 inhouse cron과 동일 경로를 써서 전송 단계 없이 검증한다.
export MSR_COLLECT_OUT="${MSR_COLLECT_OUT:-$ROOT/msr_collect_out}"
{
  echo "=== $(date '+%F %T') cron feeds(DMZ) [$MODE] 시작 ==="
  if [ "$MODE" = "weekly" ]; then
    echo "(weekly: msr.collectors 경유 항목 없음 — no-op)"
  else
    # ECOS_API_KEY는 msr_collectors.config가 dmz/.env에서 자동 로드(2026-08-06 정리 —
    # 수동 grep 추출 방식은 인라인주석 함정에 취약해서 제거, python-dotenv로 대체)
    # collect_tier2_feeds.py collect_ecos()가 소비 — 전자부품·자동차·전기장비·1차금속 생산/재고
    python3 -m msr_collectors.scripts.collect_ecos \
        --jobs msr_collectors/data/ecos_jobs_tier2.json --out-subdir tier2
    # collect_tier4_feeds.py collect_ecos_ship()가 소비 — 전자부품·자동차 출하지수
    python3 -m msr_collectors.scripts.collect_ecos \
        --jobs msr_collectors/data/ecos_jobs_tier4_ship.json --out-subdir tier4_ship
    # collect_intl_agency_feeds.py의 Census·BPS(키필요분, 2026-08-06 이전) — CENSUS_API_KEY·
    # BPS_API_KEY도 msr_collectors.config가 dmz/.env에서 자동 로드
    python3 -m msr_collectors.scripts.collect_keyed_agency_feeds all
  fi
  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
