"""복합 Action의 부분 성공과 근거 귀속 회귀 검사."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit import chatbot_graph as graph  # noqa: E402
from rag_core.ragkit import chatbot  # noqa: E402
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots  # noqa: E402
from rag_core.ragkit.action_results import ActionResult, RetrievalResult  # noqa: E402
from rag_core.ragkit.answer_composer import AnswerComposer  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


class ActionResultCompositionTest(unittest.TestCase):
    def setUp(self):
        self.plan = ActionPlan(actions=[
            ActionCall(requirement_id="price_context", action_id="document.retrieve",
                       slots=ActionSlots(topic="니켈 가격 동향")),
            ActionCall(requirement_id="news_context", action_id="document.retrieve",
                       slots=ActionSlots(topic="니켈 월간동향")),
        ])

    def _retrieve(self, state, **kwargs):
        call = state["action_call"]
        if call.requirement_id == "news_context":
            return {"evidence": [], "warnings": []}
        return {"evidence": [Evidence(kind="pageindex", source="가격 문서",
            section="가격", text="니켈 가격 동향 원문")], "warnings": []}

    def _verify(self, state, llm):
        evidence = state["evidence"]
        return {"sufficient": bool(evidence), "evidence": evidence, "warnings": []}

    def test_successful_action_survives_later_failure_and_legacy_pair(self):
        with patch.object(graph, "_retrieve_node", side_effect=self._retrieve), \
             patch.object(graph, "_verify_node", side_effect=self._verify):
            result = graph.retrieve_evidence(
                "니켈 가격과 월간동향을 알려줘", action_plan=self.plan,
                llm=object(), include_action_results=True,
            )
        self.assertIsInstance(result, RetrievalResult)
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].requirement_id, "price_context")
        self.assertEqual([item.status for item in result.action_results], ["success", "no_data"])
        self.assertIn("action_failed:news_context:document.retrieve:no_data", result.warnings)
        instruction = AnswerComposer().instruction(result)
        self.assertIn("requirement_id=price_context; action_id=document.retrieve", instruction)
        self.assertIn("사용 가능한 근거=[1]", instruction)
        self.assertIn("requirement_id=news_context; action_id=document.retrieve", instruction)
        self.assertIn("사용 가능한 근거=없음", instruction)
        self.assertIn("문서 내용: 조회한 조건에 해당하는 데이터를 찾지 못했습니다.",
                      AnswerComposer().failure_notice(result))

        with patch.object(graph, "_retrieve_node", side_effect=self._retrieve), \
             patch.object(graph, "_verify_node", side_effect=self._verify):
            evidence, warnings = graph.retrieve_evidence(
                "니켈 가격과 월간동향을 알려줘", action_plan=self.plan, llm=object(),
            )
        self.assertEqual(len(evidence), 1)
        self.assertIn("action_failed:news_context:document.retrieve:no_data", warnings)

    def test_failed_dependency_blocks_only_dependent_action(self):
        dependent = ActionCall(requirement_id="dependent", action_id="document.retrieve",
                               slots=ActionSlots(topic="후속 설명"), depends_on=["news_context"])
        plan = ActionPlan(actions=[dependent, *self.plan.actions])
        observed = []

        def retrieve(state, **kwargs):
            observed.append(state["action_call"].requirement_id)
            return self._retrieve(state, **kwargs)

        with patch.object(graph, "_retrieve_node", side_effect=retrieve), \
             patch.object(graph, "_verify_node", side_effect=self._verify):
            result = graph.retrieve_evidence("니켈 동향과 후속 설명", action_plan=plan,
                                             llm=object(), include_action_results=True)
        self.assertEqual(observed, ["news_context", "price_context"])
        self.assertEqual({item.requirement_id: item.status for item in result.action_results}, {
            "dependent": "blocked", "price_context": "success", "news_context": "no_data",
        })
        self.assertEqual(len(result.evidence), 1)

    def test_later_adapter_exception_does_not_drop_earlier_evidence(self):
        def retrieve(state, **kwargs):
            if state["action_call"].requirement_id == "news_context":
                raise RuntimeError("adapter unavailable")
            return self._retrieve(state, **kwargs)

        with patch.object(graph, "_retrieve_node", side_effect=retrieve), \
             patch.object(graph, "_verify_node", side_effect=self._verify), \
             patch.object(graph._logger, "exception"):
            result = graph.retrieve_evidence("니켈 가격과 월간동향", action_plan=self.plan,
                                             llm=object(), include_action_results=True)
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual([item.status for item in result.action_results], ["success", "failed"])
        self.assertEqual(result.action_results[1].failure_reason, "retrieve_failed")

    def test_chat_turn_keeps_one_done_and_one_saved_answer_for_partial_result(self):
        class Chat:
            prompt = None

            def complete_stream(self, system, user, max_tokens):
                self.prompt = user
                yield "니켈 가격 동향은 근거에서 확인됩니다. [1]"

        evidence = Evidence(kind="pageindex", source="가격 문서", section="가격",
                            text="니켈 가격 동향 원문", requirement_id="price_context",
                            action_id="document.retrieve")
        result = RetrievalResult(action_plan=self.plan, evidence=[evidence],
            action_results=[
                ActionResult(requirement_id="price_context", action_id="document.retrieve",
                             slots=self.plan.actions[0].slots, status="success", evidence=[evidence]),
                ActionResult(requirement_id="news_context", action_id="document.retrieve",
                             slots=self.plan.actions[1].slots, status="no_data", failure_reason="no_data"),
            ], warnings=["action_failed:news_context:document.retrieve:no_data"])
        chat = Chat()

        async def collect():
            return [event async for event in chatbot.chat_turn(
                session_id=None, user_id="test", message="니켈 가격과 월간동향을 알려줘",
                action_plan=self.plan, chat=chat, store_db_path="unused",
            )]

        with patch.object(chatbot, "get_or_create_session", return_value="session"), \
             patch.object(chatbot, "list_messages", return_value=[]), \
             patch.object(chatbot, "append_message") as save, \
             patch.object(chatbot, "retrieve_evidence", return_value=result):
            events = asyncio.run(collect())
        self.assertEqual(sum(event.type == "done" for event in events), 1)
        self.assertEqual(sum(call.args[1] == "assistant" for call in save.call_args_list), 1)
        self.assertIn("requirement_id=price_context", chat.prompt)
        self.assertIn("requirement_id=news_context", chat.prompt)
        self.assertIn("문서 내용: 조회한 조건에 해당하는 데이터를 찾지 못했습니다.",
                      "".join(event.data.get("delta", "") for event in events if event.type == "delta"))


if __name__ == "__main__":
    unittest.main()
