#!/usr/bin/env bash
# 연결망에서 1회 실행 — 3개 서비스 이미지를 빌드 + qdrant 공식 이미지를 pull한다.
# 설계 단계 스켈레톤(docs/CONTAINER_ARCHITECTURE.md §7·§8) — 실제 빌드는 다음 세션.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "[pull] qdrant (공식 이미지, komir이 직접 소유·기동 — build 대상 아님)"
podman pull docker.io/qdrant/qdrant:latest

for svc in commodity_api rag_chat report_gen; do
  echo "[build] ${svc}"
  podman build -f "services/${svc}/Containerfile" -t "komir/${svc}:latest" .
done

echo "TODO: rag_chat 이미지에 임베딩 모델 가중치 사전 다운로드 단계가 포함됐는지 확인"
echo "TODO: HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE, QDRANT__TELEMETRY_DISABLED 설정 확인(airgap 필수, §7)"
