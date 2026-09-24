# -*- coding: utf-8 -*-
"""문서 Q&A의 terminal SSE 계약 회귀 검사."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_chat.app.routers import chat as chat_router  # noqa: E402
from rag_core.ragkit import chatbot  # noqa: E402
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots  # noqa: E402
from rag_core.ragkit.chatbot_events import ChatEvent  # noqa: E402


async def _collect_turn(**kwargs):
    return [event async for event in chatbot.chat_turn(**kwargs)]


class TerminalEventCoreTest(unittest.TestCase):
    def test_verified_action_plan_skips_followup_pre_gate(self):
        """복원된 typed action은 짧은 보충 문장으로 off_topic 처리하지 않는다."""
        stored = []

        async def immediate_to_thread(function, *args, **kwargs):
            return function(*args, **kwargs)

        async def retrieval_result(*_args, **_kwargs):
            yield "result", ([], ["source_audit:rdb:queried:1"]), {}

        plan = ActionPlan(actions=[ActionCall(
            requirement_id="trade_followup", action_id="trade.indicator",
            slots=ActionSlots(mineral="리튬", trade_metric="tsi",
                              reporter_country="한국"),
        )])
        with patch.object(chatbot, "get_or_create_session", return_value="hitl-session"), \
             patch.object(chatbot, "list_messages", return_value=[]), \
             patch.object(chatbot, "append_message", side_effect=lambda *args: stored.append(args)), \
             patch.object(chatbot, "_classify_pre_gate", side_effect=AssertionError("pre-gate 재분류 금지")), \
             patch.object(chatbot.asyncio, "to_thread", side_effect=immediate_to_thread), \
             patch.object(chatbot, "_run_with_status", side_effect=retrieval_result):
            events = asyncio.run(_collect_turn(
                message="한국, 2025년 기준으로 계산해주세요.", action_plan=plan,
                session_id="hitl-session", user_id="user", store_db_path="unused",
            ))

        self.assertEqual(sum(event.type == "done" for event in events), 1)

    def test_second_turn_pre_gate_finishes_once_and_persists_its_reason(self):
        """AC22: 같은 세션의 후속 턴도 pre-gate에서 스트림이 끊기지 않는다."""
        stored = []

        def append(*args):
            stored.append(args)

        async def immediate_to_thread(function, *args, **kwargs):
            return function(*args, **kwargs)

        async def retrieval_result(*_args, **_kwargs):
            # AC22는 첫 턴의 retrieval 결과와 둘째 턴 pre-gate terminal 계약만
            # 확인한다. executor 스레드·실제 MCP 상태에 의존하지 않는 fixture다.
            yield "result", ([], ["action_plan_failed:source_unavailable"]), {}

        common = {
            "session_id": "hitl-session",
            "user_id": "user",
            "store_db_path": "unused",
        }
        with patch.object(chatbot, "get_or_create_session", return_value="hitl-session"), \
             patch.object(chatbot, "list_messages", return_value=[]), \
             patch.object(chatbot, "append_message", side_effect=append), \
             patch.object(chatbot, "_classify_pre_gate", side_effect=[None, "off_topic"]), \
             patch.object(chatbot.asyncio, "to_thread", side_effect=immediate_to_thread), \
             patch.object(chatbot, "_run_with_status", side_effect=retrieval_result):
            first = asyncio.run(_collect_turn(message="무역 지수 조건을 확인해줘", **common))
            second = asyncio.run(_collect_turn(message="그런데 서울 날씨는 어때?", **common))

        self.assertEqual(sum(event.type == "done" for event in first), 1)
        self.assertEqual(sum(event.type == "done" for event in second), 1)
        self.assertEqual(second[-1].data["abstain_reason"], "off_topic")
        assistant_context = json.loads(stored[-1][3])
        self.assertEqual(assistant_context["rag_turn"]["abstain_reason"], "off_topic")

    def test_source_unavailable_exposes_resource_message_key(self):
        async def immediate_to_thread(function, *args, **kwargs):
            return function(*args, **kwargs)

        async def retrieval_result(*_args, **_kwargs):
            yield "result", ([], ["action_plan_failed:source_unavailable"]), {}

        with patch.object(chatbot, "get_or_create_session", return_value="source-session"), \
             patch.object(chatbot, "list_messages", return_value=[]), \
             patch.object(chatbot, "append_message"), \
             patch.object(chatbot, "_classify_pre_gate", return_value=None), \
             patch.object(chatbot.asyncio, "to_thread", side_effect=immediate_to_thread), \
             patch.object(chatbot, "_run_with_status", side_effect=retrieval_result):
            events = asyncio.run(_collect_turn(
                session_id="source-session", user_id="user", message="현재 수급위기 순위를 보여줘", store_db_path="unused",
            ))

        done = events[-1].data
        self.assertEqual(sum(event.type == "done" for event in events), 1)
        self.assertEqual(done["abstain_reason"], "source_unavailable")
        self.assertEqual(done["message_key"], "action_unavailable")


class TerminalEventRouterTest(unittest.TestCase):
    @staticmethod
    def _payloads(events):
        return [json.loads(event["data"]) for event in events]

    def test_unsupported_mineral_uses_public_reason_and_message_key(self):
        with patch.object(chat_router.session_store, "append_message"):
            payloads = self._payloads(list(chat_router._unsupported_mineral_response("s-1", "가상광물 가격")))

        self.assertEqual(sum(payload.get("done") is True for payload in payloads), 1)
        self.assertEqual(payloads[-1]["abstain_reason"], "unsupported_commodity")
        self.assertEqual(payloads[-1]["message_key"], "unsupported_commodity")

    def test_source_unavailable_action_plan_exposes_action_message_key(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="diagnosis", action_id="diagnosis.rank", slots=ActionSlots(),
        )])
        request = chat_router.ChatRequest(user_id="user", message="현재 수급위기 순위를 보여줘", mode="document")
        with patch.object(chat_router.session_store, "list_messages", return_value=[]), \
             patch.object(chat_router.session_store, "append_message"), \
             patch.object(chat_router, "extract_action_plan", return_value=plan):
            payloads = self._payloads(list(chat_router._run_chat_session(request, "public", "s-1")))

        self.assertEqual(sum(payload.get("done") is True for payload in payloads), 1)
        self.assertEqual(payloads[-1]["abstain_reason"], "source_unavailable")
        self.assertEqual(payloads[-1]["message_key"], "action_unavailable")

    def test_document_router_stops_after_one_done_and_recovers_from_exception(self):
        async def malformed_stream():
            yield ChatEvent(type="session", data={"session_id": "s-1"})
            yield ChatEvent(type="done", data={"done": True, "abstained": False})
            yield ChatEvent(type="delta", data={"delta": "must not be emitted"})

        async def broken_stream():
            yield ChatEvent(type="session", data={"session_id": "s-1"})
            raise RuntimeError("simulated core failure")

        request = chat_router.ChatRequest(user_id="user", message="리튬 수급 이슈", mode="document")
        dependencies = {
            "get_settings": SimpleNamespace(MSR_DB="unused"),
            "get_chat_client": object(),
        }
        with patch.object(chat_router, "get_settings", return_value=dependencies["get_settings"]), \
             patch.object(chat_router, "get_chat_client", return_value=dependencies["get_chat_client"]), \
             patch.object(chat_router, "chat_turn", return_value=malformed_stream()):
            terminal_payloads = self._payloads(list(chat_router._run_document_qa(request, "s-1", "public")))
        self.assertEqual(sum(payload.get("done") is True for payload in terminal_payloads), 1)
        self.assertNotIn("must not be emitted", "".join(payload.get("delta", "") for payload in terminal_payloads))

        with patch.object(chat_router, "get_settings", return_value=dependencies["get_settings"]), \
             patch.object(chat_router, "get_chat_client", return_value=dependencies["get_chat_client"]), \
             patch.object(chat_router, "chat_turn", return_value=broken_stream()):
            error_payloads = self._payloads(list(chat_router._run_document_qa(request, "s-1", "public")))
        done = error_payloads[-1]
        self.assertEqual(sum(payload.get("done") is True for payload in error_payloads), 1)
        self.assertEqual(done["abstain_reason"], "source_unavailable")
        self.assertEqual(done["message_key"], "action_unavailable")


if __name__ == "__main__":
    unittest.main()
