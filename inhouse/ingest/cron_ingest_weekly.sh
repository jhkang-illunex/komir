#!/usr/bin/env bash
# ingest 주간 체인 — 컨테이너에선 supercronic이 호출(env는 env_file 주입), 호스트
# 수동 실행 시엔 .env를 직접 source한다(기존 cron 래퍼 관례 — geo/cron_gkg_increment.sh·
# mineral_supply_risk/scripts/cron_collect_feeds_inhouse.sh와 동일 구조: set -uo pipefail·
# flock·필수 env 강제·순서 체이닝).
set -uo pipefail
INHOUSE="$(cd "$(dirname "$0")/.." && pwd)"    # → inhouse/ (컨테이너: /komir/inhouse)
cd "$INHOUSE"

if [ -f "$INHOUSE/.env" ]; then
  set -a
  source "$INHOUSE/.env"
  set +a
fi
: "${PG_DSN:?PG_DSN이 설정되지 않음 — inhouse/.env 확인}"
: "${LLM_BASE_URL:?LLM_BASE_URL이 설정되지 않음 — inhouse/.env 확인}"

# .env의 PDF_MAXPAGES=40은 geo GKG 뉴스용 기본값이라, 그대로 두면 build_okf_documents.py
# 자체의 setdefault(500)를 무력화해 대용량 PDF가 40쪽까지만 잘려나가는 회귀가 재현된다
# (build_okf_documents.py 헤더에 실측 기록된 함정과 동일 — 2026-08-11, USGS_2026 226쪽
# 중 40쪽만 추출됨). 여기서 명시적으로 상향한다.
export PDF_MAXPAGES=500 OCR_MAXPAGES=60
# status.pipeline_run()이 이 값으로 trigger='cron'을 기록한다(9개 모듈 어디에도 별도
# CLI 플래그 없이 이 env var 하나로 균일 적용).
export INGEST_TRIGGERED_BY=cron

LOCK=/tmp/komir_ingest_weekly.lock
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date '+%F %T') 이미 실행 중(lock) — 종료"
  exit 0
fi

echo "=== $(date '+%F %T') ingest 주간 체인 시작 ==="

echo "--- [1/7] 외부공개 PDF 정제(shareable) ---"
python3 -m ingest.extract.pdf_extract_shareable

echo "--- [2/7] 비축월보(restricted, 진단모델 전용) 정제 ---"
python3 -m ingest.extract.pdf_extract_restricted

echo "--- [3/7] 문서-OKF ---"
python3 -m ingest.okf.build_okf_documents --what all 2>&1 | tail -20

echo "--- LLM 헬스체크(cron_gkg_increment.sh 선례 — 미응답 시 pageindex만 스킵) ---"
if python3 - <<'PY'
import os, sys, urllib.request
try:
    urllib.request.urlopen(os.environ["LLM_BASE_URL"].rstrip("/") + "/models", timeout=10)
except Exception:
    sys.exit(1)
PY
then
  echo "--- [4/7] PageIndex 트리(증분) ---"
  python3 -m ingest.pageindex.build_pageindex_trees 2>&1 | tail -5
else
  echo "LLM 미응답 — pageindex 스킵(증분이라 다음 주 실행이 이어서 처리)"
fi

echo "--- [5/7] pgvector 전량 재적재(반드시 okf보다 먼저 — README 불변식) ---"
python3 -m ingest.vectorize.build_pgvector_index 2>&1 | tail -5

echo "--- [6/7] pgvector OKF 갈래(src 단위) ---"
python3 -m ingest.vectorize.build_pgvector_okf 2>&1 | tail -5

echo "--- [7/7] pub_date 백필 ---"
python3 -m ingest.vectorize.backfill_doc_chunk_pub_date

echo "=== $(date '+%F %T') 종료 ==="
