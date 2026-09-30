import unittest
from unittest.mock import AsyncMock, patch

from inhouse.rag_core.ragkit import live_multihop
from inhouse.rag_core.ragkit.action_contract import ActionPlan
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


class LiveMultiHopBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_history_alias_is_materialized_from_latest_typed_root(self):
        typed = TypedResult.success(ValueType.MINERAL_SET, [{"광종": "니켈"}], entity=("니켈",))
        previous = Turn(
            "turn-1",
            "session-1",
            UserUtterance("니켈 가격"),
            semantic_program=SemanticProgram(
                (RequirementNode("root", Operator.ENTITY, args={"values": ["니켈"]}),),
                ("root",),
            ),
            result=ExecutionResult("pipe-1", ResultStatus.SUCCESS, {"root": typed}, ()),
        )
        payload = {
            "nodes": [{"node_id": "next", "operator": "retrieve", "inputs": [{"node_id": "previous"}]}],
            "roots": ["next"],
        }

        normalized = live_multihop._normalize_history_aliases(payload, ConversationContext("session-1", (previous,)))
        program = SemanticProgram.from_dict(normalized)

        next_node = next(node for node in program.nodes if node.node_id == "next")
        self.assertEqual(next_node.inputs[0].node_id, "ctx_history_turn_1_root")
        self.assertTrue(any(node.node_id == "ctx_history_turn_1_root" and node.operator == Operator.ENTITY for node in program.nodes))

    def test_parser_root_is_normalized_to_terminal_dependency_node(self):
        program = SemanticProgram.from_dict({
            "nodes": [
                {"node_id": "rank", "operator": "rank"},
                {"node_id": "top", "operator": "top_k", "inputs": [{"node_id": "rank"}]},
                {"node_id": "answer", "operator": "arg_max", "inputs": [{"node_id": "top"}]},
            ],
            "roots": ["rank"],
        })

        self.assertEqual(program.roots, ("answer",))

    def test_source_unavailable_result_maps_to_empty_without_contract_error(self):
        call = live_multihop.ActionCall(
            requirement_id="r1",
            action_id="price.series",
            slots=live_multihop.ActionSlots(mineral="니켈"),
        )
        evidence = Evidence("structured", "fixture", "fixture", "| 상태 | 값 |\n| --- | --- |\n| unavailable | - |")
        raw = RetrievalResult(
            ActionPlan(actions=[call]),
            [ActionResult("r1", "price.series", call.slots, "source_unavailable", [evidence])],
            [evidence],
            [],
        )

        result = live_multihop._typed_from_retrieval(raw, call, input_entities=[])

        self.assertEqual(result.status.value, "empty")
        self.assertEqual(result.failure_reason, "retrieval unavailable: source_unavailable")

    def test_semantic_metrics_lower_to_existing_actions_without_domain(self):
        price = RequirementNode(
            "price",
            Operator.RETRIEVE,
            args={"metric": "price_change_rate"},
            expected_type=ValueType.MINERAL_RANKING,
        )
        imports = RequirementNode(
            "imports",
            Operator.RETRIEVE,
            args={"metric": "import_value"},
            expected_type=ValueType.TRADE_SERIES,
        )

        self.assertEqual(live_multihop._action_id(price), "price.volatility_rank")
        self.assertEqual(live_multihop._action_id(imports), "trade.monthly")
        self.assertIsNone(live_multihop._action_slots(price).metric)
        self.assertEqual(live_multihop._action_slots(imports).metric, "import_amount")
        self.assertEqual(live_multihop._action_slots(price, mineral="nickel").mineral, "니켈")
        self.assertIsNone(live_multihop._action_slots(RequirementNode("price_query", Operator.RETRIEVE, args={"metric": "price"})).metric)

    async def test_real_bridge_uses_existing_action_executor_and_sse_blocks(self):
        program = SemanticProgram(
            nodes=(
                RequirementNode("rank", Operator.RANK, args={"domain": "price", "metric": "price_change", "top_n": 3}, expected_type=ValueType.MINERAL_RANKING),
                RequirementNode("top", Operator.TOP_K, (InputRef("rank"),), {"k": 2}, ValueType.MINERAL_SET),
                RequirementNode("imports", Operator.RETRIEVE, (InputRef("top"),), {"domain": "trade", "metric": "country_share", "scope": "KR"}, ValueType.COUNTRY_SHARE),
                RequirementNode("answer", Operator.ARG_MAX, (InputRef("imports"),), {"field": "import_amount"}, ValueType.SCALAR_METRIC),
            ),
            roots=("answer",),
        )

        def fake_retrieve(_question, *, action_plan, **_kwargs):
            call = action_plan.actions[0]
            if call.action_id == "price.volatility_rank":
                text = "| 광종 | 변동률(%) |\n| --- | --- |\n| 니켈 | 20 |\n| 리튬 | 10 |\n| 구리 | 5 |"
            else:
                text = "| 국가 | import_amount(USD) |\n| --- | --- |\n| 중국 | 90 |"
            evidence = Evidence("structured", "KOMIS fixture", "fixture", text, unit="USD")
            action_result = ActionResult(call.requirement_id, call.action_id, call.slots, "success", [evidence])
            return RetrievalResult(action_plan, [action_result], [evidence], [])

        with patch.object(live_multihop, "_parse_ast", new=AsyncMock(return_value=program)), \
             patch.object(live_multihop, "retrieve_evidence", side_effect=fake_retrieve):
            run = await live_multihop.run_live_multihop(
                message="가격 상승률 상위 3개 중 수입액이 가장 큰 광물",
                session_id="live-test-session",
                profile="public",
                llm=object(),
                history=[],
            )

        self.assertEqual(run.orchestration.root_result.status.value, "success")
        self.assertEqual(run.orchestration.root_result.value[0]["국가"], "중국")
        event_types = [event.type for event in live_multihop.live_run_events(run)]
        self.assertIn("delta", event_types)
        self.assertIn("table", event_types)
        self.assertEqual(event_types[-1], "done")
