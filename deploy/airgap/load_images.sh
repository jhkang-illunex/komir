#!/usr/bin/env bash
# 반입망(airgap)에서 실행 — save_images.sh가 만든 tar를 podman에 적재.
# 설계 단계 스켈레톤(docs/CONTAINER_ARCHITECTURE.md §7·§8) — 실제 실행은 다음 세션.
set -euo pipefail
IN_DIR="${1:-./airgap_images}"

for f in "${IN_DIR}"/qdrant.tar "${IN_DIR}"/komir-*.tar; do
  echo "[load] ${f}"
  podman load -i "$f"
done

echo "적재 완료 — deploy/podman-compose.yml + deploy/.env로 기동 (.env는 airgap 환경의 실제 " \
     "Postgres/LLM 접속정보로 별도 채울 것, .env.example을 커밋하지 말 것. qdrant는 komir이 " \
     "직접 소유하므로 podman-compose가 자체 기동함 — 별도 접속정보 불필요)"
