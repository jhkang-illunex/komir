# -*- coding: utf-8 -*-
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from rag_core.ragkit.action_results import ActionResult
from rag_core.ragkit.multi_action_state import (
    decode_multi_action_state, decode_price_context, encode_citation_envelope,
    merge_multi_action_followup, price_context_from_action_results, state_from_action_results,
    is_non_carry_payload,
)
from rag_core.retrieval.evidence import Evidence
from rag_chat.app.routers import chat as chat_router
from rag_chat.app.streaming import sse_event


def _plan():
    return ActionPlan(actions=[
        ActionCall(requirement_id="production", action_id="resource.rank", slots=ActionSlots(
            mineral="구리", metric="production", country_scope="world",
            period=Period(kind="calendar_year", calendar_year=2024, explicit=True),
        )),
        ActionCall(requirement_id="reserves", action_id="resource.rank", slots=ActionSlots(
            mineral="구리", metric="reserves", country_scope="world",
            period=Period(kind="calendar_year", calendar_year=2024, explicit=True),
        )),
    ])


class MultiActionStateTest(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()
        self.state = state_from_action_results(
            self.plan,
            [ActionResult("production", "resource.rank", self.plan.actions[0].slots, "success"),
             ActionResult("reserves", "resource.rank", self.plan.actions[1].slots, "success")],
            profile="public",
        )
        self.assertIsNotNone(self.state)

    def test_round_trip_preserves_only_whitelisted_slots(self):
        encoded = encode_citation_envelope([{"index": 1}], self.state)
        payload = json.loads(encoded)
        restored = decode_multi_action_state(payload, profile="public")
        self.assertEqual(payload["citations"], [{"index": 1}])
        self.assertEqual([item.slots.metric for item in restored.actions], ["production", "reserves"])
        self.assertFalse(hasattr(restored.actions[0].slots, "topic"))

    def test_legacy_or_wrong_profile_has_no_state(self):
        self.assertIsNone(decode_multi_action_state([], profile="public"))
        payload = json.loads(encode_citation_envelope([], self.state))
        self.assertIsNone(decode_multi_action_state(payload, profile="private"))
        payload["rag_turn"]["multi_action_v1"]["unexpected"] = True
        self.assertIsNone(decode_multi_action_state(payload, profile="public"))

    def test_explicit_mineral_keeps_two_metrics_and_period(self):
        result = merge_multi_action_followup(self.state, "그럼 니켈로 보여줘")
        self.assertEqual(result.status, "merged")
        self.assertEqual([item.slots.mineral for item in result.plan.actions], ["니켈", "니켈"])
        self.assertEqual([item.slots.metric for item in result.plan.actions], ["production", "reserves"])
        self.assertEqual([item.slots.period.calendar_year for item in result.plan.actions], [2024, 2024])

    def test_explicit_period_wins_and_ambiguous_metric_change_closes(self):
        result = merge_multi_action_followup(self.state, "그럼 2023년으로 보여줘")
        self.assertEqual(result.status, "merged")
        self.assertEqual([item.slots.period.calendar_year for item in result.plan.actions], [2023, 2023])
        self.assertEqual(merge_multi_action_followup(self.state, "그럼 생산량만 보여줘").status, "ambiguous")

    def test_complete_new_question_does_not_inherit(self):
        self.assertEqual(merge_multi_action_followup(self.state, "2025년 리튬 생산량 순위를 보여줘").status,
                         "not_candidate")

    def test_new_price_intent_after_reference_is_not_merged(self):
        self.assertEqual(merge_multi_action_followup(
            self.state, "그럼 2025년 리튬 가격을 보여줘",
        ).status, "not_candidate")

    def test_top_n_is_explicit_and_same_period_requires_observed_range(self):
        result = merge_multi_action_followup(self.state, "그럼 상위 10개로 보여줘")
        self.assertEqual(result.status, "merged")
        self.assertEqual([call.slots.top_n for call in result.plan.actions], [10, 10])
        self.assertEqual(merge_multi_action_followup(self.state, "그럼 상위 101개로 보여줘").status,
                         "ambiguous")
        self.assertEqual(merge_multi_action_followup(self.state, "그럼 같은 기간 니켈로 보여줘").status,
                         "ambiguous")

        evidence = [Evidence(kind="structured", source="test", section="test", text="x",
                             observed_period="2024-01-01~2024-12-31")]
        observed = state_from_action_results(
            self.plan,
            [ActionResult("production", "resource.rank", self.plan.actions[0].slots, "success", evidence),
             ActionResult("reserves", "resource.rank", self.plan.actions[1].slots, "success", evidence)],
            profile="public",
        )
        merged = merge_multi_action_followup(observed, "그럼 같은 기간 니켈로 보여줘")
        self.assertEqual(merged.status, "merged")
        self.assertEqual(merged.plan.actions[0].slots.period.start, "2024-01-01")
        explicit = merge_multi_action_followup(observed, "그럼 같은 기간 2023년으로 보여줘")
        self.assertEqual(explicit.plan.actions[0].slots.period.calendar_year, 2023)

    def test_oversized_state_is_marked_non_carry_not_silently_dropped(self):
        self.state.actions[0].slots.mineral = "구리" * 3000
        payload = json.loads(encode_citation_envelope([{"source": "x" * 5000}], self.state))
        self.assertTrue(payload["citations_truncated"])
        self.assertTrue(is_non_carry_payload(payload, profile="public"))

    def test_oversized_citations_without_state_are_always_bounded(self):
        encoded = encode_citation_envelope([{"source": "x" * 1000} for _ in range(100)], None)
        self.assertLessEqual(len(encoded.encode("utf-8")), 3800)

    def test_single_price_context_round_trip_is_separate_from_multi_state(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price_니켈", action_id="price.series",
            slots=ActionSlots(mineral="니켈", period=Period(kind="range", start="2026-09-24", end="2026-09-30")),
        )])
        context = price_context_from_action_results(
            plan, [ActionResult("price_니켈", "price.series", plan.actions[0].slots, "success")],
            profile="public",
        )
        self.assertIsNotNone(context)
        payload = json.loads(encode_citation_envelope([], None, context))
        restored = decode_price_context(payload, profile="public")
        self.assertEqual(restored.action.slots.mineral, "니켈")
        self.assertIsNone(decode_multi_action_state(payload, profile="public"))

    def test_router_uses_typed_state_without_replanning(self):
        stored = {"role": "assistant", "citations_json": encode_citation_envelope([], self.state)}
        received = []

        def fake_document(request, session_id, profile, action_plan=None):
            received.append(action_plan)
            yield sse_event({"done": True, "abstained": False}, event="done")

        with (patch.object(chat_router.session_store, "list_messages", return_value=[stored]),
              patch.object(chat_router, "extract_action_plan") as planner,
              patch.object(chat_router, "_run_document_qa", side_effect=fake_document)):
            list(chat_router._run_chat_session(
                chat_router.ChatRequest(user_id="state-test", message="그럼 2023년으로 보여줘"),
                "public", "session-state",
            ))
        planner.assert_not_called()
        self.assertEqual([call.slots.period.calendar_year for call in received[0].actions], [2023, 2023])


if __name__ == "__main__":
    unittest.main()
