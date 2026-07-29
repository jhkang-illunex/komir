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
    python3 -m scripts.collect_tier1_feeds --skip-comtrade  # CO/LI COT·IDR·중국 OI(주간)
    # 해외기관 정책 공고(2026-07-28 발주처 확장 요청): MOFCOM 수출통제·FedReg·HTS.
    # MOFCOM 목록은 최신 ~15건만 반환 → 주간 폴링으로 놓침 없이 축적(url upsert)
    python3 -m scripts.collect_intl_agency_feeds policy
  else
    python3 -m scripts.collect_priority_feeds            # Comtrade+PMI(전량 멱등)
    python3 -m scripts.collect_demand_feeds              # ISM·유로·부동산
    python3 -m scripts.collect_tier1_feeds               # 공급국 흐름 포함 풀 수집(월간)
    # Tier2(2026-07-25): 칠레 생산·CO LME재고(USGS)·WSTS 반도체·ECOS 세부업종 —
    # 진단·예측 채택은 0건이나 축적 가치(KINV 방향긍정 등)로 수집 지속.
    # ECOS 키만 루트 .env에서 추출(전체 source는 인라인주석 함정 회피)
    ECOS_API_KEY="$(grep '^ECOS_API_KEY=' "$ROOT/.env" | cut -d= -f2-)" \
      python3 -m scripts.collect_tier2_feeds
    # Tier3(2026-07-25): 칠레·아르헨 LI, 필리핀 NI, 말레이 REE, 일본 NI수입,
    # USGS 구리 MIS(광산생산·미국/COMEX 재고) — 축적 목적, 검정은 별도
    python3 -m scripts.collect_tier3_feeds
    # Tier4(2026-07-25 최종 스윕): Comtrade 10흐름(이어받기 가드)·EIA·Eurostat·
    # akshare 전력/탄소·ECOS 출하·ICSG(축적형)·OECD CLI
    ECOS_API_KEY="$(grep '^ECOS_API_KEY=' "$ROOT/.env" | cut -d= -f2-)" \
      python3 -m scripts.collect_tier4_feeds
    # GFEX 레이트리밋으로 남은 LI 공백(2025-08~2026-04)을 매월 조금씩 자가 치유 —
    # skip_dates 멱등이라 이미 채워진 주는 재호출하지 않음(공백 소진 후엔 사실상 no-op)
    python3 -m scripts.collect_exchange_inventory --backfill
    # 해외기관 직접 무역통계(2026-07-28~29 발주처 확장 요청): 페루 BCRP·호주 ABS·
    # 필리핀 PSA·중국 GACC 영문월보(무키) + 미 Census·인니 BPS(키 필요, 07-29
    # 사용자 발급) + 아르헨 ARCA(최근 4개월 증분). 월간 전량 멱등(계열 한정 DELETE)
    CENSUS_API_KEY="$(grep '^CENSUS_API_KEY=' "$ROOT/.env" | cut -d= -f2-)" \
    BPS_API_KEY="$(grep '^BPS_API_KEY=' "$ROOT/.env" | cut -d= -f2-)" \
      python3 -m scripts.collect_intl_agency_feeds trade
  fi
  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
