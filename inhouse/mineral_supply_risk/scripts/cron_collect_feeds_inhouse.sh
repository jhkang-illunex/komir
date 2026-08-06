#!/usr/bin/env bash
# 외부 피드 수집 cron 래퍼 — inhouse 측 (2026-07-24 최초 작성, 2026-08-06 dmz/inhouse
# 물리분리로 cron_collect_feeds.sh에서 분리+개명)
# 사용법: cron_collect_feeds_inhouse.sh weekly|monthly
#   weekly (매주 토 09:10): 거래소 재고 증분(SHFE CU/NI·GFEX LI) + COT(금요일 발표분)
#   monthly(매월 6일 09:20): Comtrade 무역흐름·중국 PMI + 수요측(ISM·유로·부동산)
# 로그: komir/data_archive/cron_logs/feeds_<mode>_<YYYYMMDD>.log (보존 정책에 따라 삭제 금지)
#
# ⚠️ 실행 순서: monthly는 collect_tier2_feeds·collect_tier4_feeds의 ECOS 하위단계가
# DMZ 산출물(parquet)을 읽는다 — dmz/msr_collectors/cron_collect_feeds_dmz.sh monthly를
# 먼저 실행(및 산출물 전달)해 둘 것. 나머지 항목(collect_exchange_inventory 등 다수)은
# msr.collectors를 거치지 않는 직접 수집이라 예전처럼 이 스크립트에서 그대로 라이브 수집한다.
set -uo pipefail
MODE="${1:?usage: cron_collect_feeds_inhouse.sh weekly|monthly}"
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"       # → komir/
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/feeds_${MODE}_$(date +%Y%m%d).log"
cd "$ROOT/inhouse/mineral_supply_risk"   # 2026-08-06 dmz/inhouse 물리분리 반영
export MSR_DB="$ROOT/inhouse/data_lake/db/minerals.duckdb"   # 2026-08-06 신 경로(별도 이관중)
# DMZ가 만든 parquet 산출물 위치 — dmz측 cron과 같은 경로를 가리켜야 함(현재 단일 저장소
# 개발환경 전제, 실운영에서는 rsync/NAS로 이 경로에 사본을 채워둘 것)
export MSR_COLLECT_OUT="${MSR_COLLECT_OUT:-$ROOT/msr_collect_out}"
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
    # ECOS_API_KEY 불필요(2026-08-06) — collect_tier2_feeds의 ECOS 하위단계는 이제
    # dmz/msr_collectors/cron_collect_feeds_dmz.sh가 만든 parquet을 읽는다(사전 실행 필요).
    python3 -m scripts.collect_tier2_feeds
    # Tier3(2026-07-25): 칠레·아르헨 LI, 필리핀 NI, 말레이 REE, 일본 NI수입,
    # USGS 구리 MIS(광산생산·미국/COMEX 재고) — 축적 목적, 검정은 별도
    python3 -m scripts.collect_tier3_feeds
    # Tier4(2026-07-25 최종 스윕): Comtrade 10흐름(이어받기 가드)·EIA·Eurostat·
    # akshare 전력/탄소·ECOS 출하·ICSG(축적형)·OECD CLI — ECOS_API_KEY 불필요 이유는 위와 동일
    python3 -m scripts.collect_tier4_feeds
    # GFEX 레이트리밋으로 남은 LI 공백(2025-08~2026-04)을 매월 조금씩 자가 치유 —
    # skip_dates 멱등이라 이미 채워진 주는 재호출하지 않음(공백 소진 후엔 사실상 no-op)
    python3 -m scripts.collect_exchange_inventory --backfill
    # 해외기관 직접 무역통계(2026-07-28~29 발주처 확장 요청): 페루 BCRP·호주 ABS·
    # 필리핀 PSA·중국 GACC 영문월보(무키, 여전히 in-house 직접수집 — 잔여 DMZ 경계
    # 위반, 별도 사이클 필요) + 미 Census·인니 BPS(키 필요, 2026-08-06부로 dmz/
    # msr_collectors/scripts/collect_keyed_agency_feeds.py로 이동 — 여기선 그 parquet만
    # 읽음, CENSUS_API_KEY/BPS_API_KEY 더 이상 불필요) + 아르헨 ARCA(무키, 최근 4개월 증분).
    # 월간 전량 멱등(계열 한정 DELETE). ⚠️ DMZ 쪽 collect_keyed_agency_feeds.py를
    # 먼저 실행해 산출물을 전달해둘 것.
    python3 -m scripts.collect_intl_agency_feeds trade
  fi
  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
