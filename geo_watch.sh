#!/usr/bin/env bash
# geo_data/inbox 감시 → 파일 업로드 감지 시 geo 파이프라인 자동 실행:
#   ingest → extract → index → OKF 번들 → warehouse geo_index publish
# ingest가 파일을 archive로 옮겨 inbox를 비우므로, "inbox 비어있지 않음"이 곧 트리거.
# 사용: ./geo_watch.sh   (또는 make geo-watch). 백그라운드: nohup ./geo_watch.sh &>geo_watch.log &
set -uo pipefail
cd "$(dirname "$0")"
INBOX="geo_data/inbox"
INTERVAL="${GEO_WATCH_INTERVAL:-10}"
mkdir -p "$INBOX"
echo "[geo-watch] '$INBOX' 감시 시작 (${INTERVAL}s 간격). Ctrl-C로 중지."
while true; do
  if [ -n "$(ls -A "$INBOX" 2>/dev/null)" ]; then
    echo "[geo-watch] $(date '+%F %T') 새 파일 감지 → 파이프라인 실행"
    if docker compose run --rm geo && docker compose run --rm geo-publish; then
      echo "[geo-watch] 완료 → OKF: geo_data/okf/ · 지수: warehouse geo_index"
    else
      echo "[geo-watch] ⚠️ 파이프라인 실패(로그 확인). 다음 주기에 재시도."
    fi
  fi
  sleep "$INTERVAL"
done
