#!/usr/bin/env bash
# Test-container deployment: required local and live regression gates.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bash "$repo_root/inhouse/rag_chat/tests/verify_chatbot_changes.sh"
image_tag="${CHAT_IMAGE_TAG:-komir-rag-chat:$(date +%Y%m%d-%H%M%S)}"
docker build -f "$repo_root/inhouse/rag_chat/Containerfile" -t "$image_tag" "$repo_root/inhouse"
backup="komir-rag-chat-test-pre-$(date +%Y%m%d-%H%M%S)"
docker stop komir-rag-chat-test
if ! docker rename komir-rag-chat-test "$backup"; then
  docker start komir-rag-chat-test
  exit 1
fi
run_container() {
  docker run -d --name komir-rag-chat-test \
    --env-file "$repo_root/inhouse/.env" \
    -e "LLM_BASE_URL=${CHAT_LLM_BASE_URL:-http://host.docker.internal:52302/v1}" \
    --add-host host.docker.internal:host-gateway \
    -v "$repo_root/inhouse/data_lake/semi_structure/okf_documents:/app/data_lake/semi_structure/okf_documents:ro" \
    -v "$repo_root/inhouse/data_lake/semi_structure/pageindex_trees:/app/data_lake/semi_structure/pageindex_trees:ro" \
    -p 18002:8002 "$image_tag"
}
if ! run_container || ! python3 "$repo_root/inhouse/rag_chat/tests/verify_live_chatbot.py"; then
  docker stop komir-rag-chat-test 2>/dev/null || true
  docker rm komir-rag-chat-test 2>/dev/null || true
  docker rename "$backup" komir-rag-chat-test
  docker start komir-rag-chat-test
  echo "Live verification failed; restored $backup" >&2
  exit 1
fi
echo "Deployment verified; previous container retained as $backup"
