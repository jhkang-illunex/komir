#!/usr/bin/env bash
# Run before every rag_chat image build. A failure blocks deployment.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$repo_root"
export PYTHONPATH="$repo_root/inhouse${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest inhouse/rag_core/tests/test_mine_ranking_action.py
python3 -m unittest \
  inhouse/common/tests/test_langfuse_tracing.py \
  inhouse/common/tests/test_komis_raw_aggregation.py \
  inhouse/rag_core/tests/test_komis_raw_period_limit.py \
  inhouse/rag_core/tests/test_action_contract.py \
  inhouse/rag_core/tests/test_source_contract.py \
  inhouse/rag_core/tests/test_okf_action_contract.py
python3 -m unittest \
  inhouse.rag_core.tests.test_internal_knowledge_route.SourceFooterTest.test_selected_price_unit_is_added_and_false_missing_unit_sentence_is_removed \
  inhouse.rag_core.tests.test_internal_knowledge_route.SourceFooterTest.test_selected_price_unit_is_not_duplicated_when_generator_includes_it \
  inhouse.rag_core.tests.test_internal_knowledge_route.SourceFooterTest.test_single_selected_price_series_uses_observed_period_only \
  inhouse.rag_core.tests.test_internal_knowledge_route.SourceFooterTest.test_price_scope_answer_does_not_override_price_only_evidence_from_mixed_plan \
  inhouse.rag_core.tests.test_internal_knowledge_route.InternalKnowledgeTurnTest.test_document_retrieve_keeps_question_when_typed_minerals_refine_topic \
  inhouse.rag_core.tests.test_internal_knowledge_route.InternalKnowledgeTurnTest.test_q15_rare_earth_and_nd_use_two_public_usgs_body_rows
python3 -m unittest inhouse/rag_chat/tests/test_mine_aggregate.py inhouse/rag_chat/tests/test_menu_path_policy.py
python3 -m unittest inhouse/rag_chat/tests/test_langfuse_chat_trace.py
python3 inhouse/rag_chat/tests/smoke_chat_routing.py
python3 inhouse/rag_chat/tests/smoke_page_recommend.py
