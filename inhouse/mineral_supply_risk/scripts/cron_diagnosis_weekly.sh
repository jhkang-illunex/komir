#!/usr/bin/env bash
# 수급위기 진단 파이프라인 — 주간(2026-08-19 신설).
# 등록 방식: 독립 crontab 항목이 아니라 inhouse/geo/cron_gkg_increment.sh 끝에서
# 직접 호출되는 "이벤트 체이닝"이다(.env의 DIAGNOSIS_TRIGGER=after_geo_index 설계값
# 그대로 구현 — 지정학위기지수(geo_index/geo_prob)가 그 주의 최신값으로 publish된
# *직후*에만 돌아야, 이번 주 mart_weekly_diagnosis.geopolitical_risk가 최신 지수를
# 반영한다. geo 쪽이 LLM 미응답 등으로 조기 종료(exit 0)하면 이 스크립트 자체가
# 호출되지 않으므로 별도 가드 불필요).
#
# 순서(schedule.py weekly()의 진단 부분 그대로 재사용 — 재구현 아님, 다만 그 파일은
# 2026-08-06 DMZ/inhouse 분리 이전의 geo 호출까지 섞여 있어 stale, 이 스크립트는
# 진단 부분만 분리해 현재 코드와 시그니처 일치시킨 것):
#   normalize(raw_customs_* → fact_trade_*, 멱등) → weekly_mart(마트 재생성)
#   → nowcast(Ridge 재적합 → mart_diagnosis_nowcast) → alert(경보 4단계 → out_diagnosis_alert)
#   → dashboard_summary(2026-08-19 추가 — out_diagnosis_alert가 이번 주 최신값으로
#     막 갱신된 직후에만 돌아야 "텍스트 보고서" 화면 데이터가 최신 경보를 반영함)
#
# 로그: data_archive/cron_logs/diagnosis_weekly_<YYYYMMDD>.log (삭제 금지 정책)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"   # → komir/
LOGDIR="$ROOT/data_archive/cron_logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/diagnosis_weekly_$(date +%Y%m%d).log"
cd "$ROOT/inhouse/mineral_supply_risk"
export MSR_DB="${MSR_DB:-$ROOT/inhouse/data_lake/db/minerals.duckdb}"

{
  echo "=== $(date '+%F %T') 수급위기 진단 파이프라인 시작 (MSR_DB=$MSR_DB) ==="

  echo "--- [1/4] 정규화(raw_customs_* → fact_trade_*, 멱등) ---"
  python3 -m msr.features.normalize 2>&1 | tail -3

  echo "--- [2/4] 주간 마트 재생성(mart_weekly_diagnosis) ---"
  python3 -m msr.features.weekly_mart 2>&1 | tail -3

  echo "--- [3/4] 진단 nowcast(Ridge 재적합 → mart_diagnosis_nowcast) ---"
  python3 -m msr.models.nowcast 2>&1 | tail -5

  echo "--- [4/5] 경보 발행(규칙엔진+히스테리시스 → out_diagnosis_alert) ---"
  python3 -m msr.models.alert 2>&1 | tail -10

  echo "--- [5/5] 텍스트 보고서 화면 데이터 생성(out_ai_dashboard_summary, LLM 서술) ---"
  ( cd "$ROOT/inhouse/services/report_gen" && python3 -m app.dashboard_summary 2>&1 | tail -5 )

  echo "=== $(date '+%F %T') 종료(exit=$?) ==="
} >> "$LOG" 2>&1
