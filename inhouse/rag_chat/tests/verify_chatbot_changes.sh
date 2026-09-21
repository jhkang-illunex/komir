#!/usr/bin/env bash
# Run before every rag_chat image build. A failure blocks deployment.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/inhouse${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest inhouse/rag_core/tests/test_mine_ranking_action.py
python3 -m unittest inhouse/rag_chat/tests/test_mine_aggregate.py inhouse/rag_chat/tests/test_menu_path_policy.py
python3 inhouse/rag_chat/tests/smoke_chat_routing.py
python3 inhouse/rag_chat/tests/smoke_page_recommend.py
