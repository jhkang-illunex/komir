#!/usr/bin/env bash
# build_images.sh 이후 실행 — tar 아카이브로 묶어 반입 매체로 옮길 준비.
# 설계 단계 스켈레톤(docs/CONTAINER_ARCHITECTURE.md §7·§8) — 실제 실행은 다음 세션.
set -euo pipefail
OUT_DIR="${1:-./airgap_images}"
mkdir -p "$OUT_DIR"

echo "[save] qdrant"
podman save -o "${OUT_DIR}/qdrant.tar" "docker.io/qdrant/qdrant:latest"

for svc in commodity_api rag_chat report_gen; do
  echo "[save] ${svc}"
  podman save -o "${OUT_DIR}/komir-${svc}.tar" "komir/${svc}:latest"
done

echo "저장 완료 → ${OUT_DIR} — 이 디렉토리를 반입망으로 물리 이동할 것"
