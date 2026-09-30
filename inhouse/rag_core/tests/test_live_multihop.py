import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from inhouse.rag_core.ragkit import live_multihop
from inhouse.rag_core.ragkit.action_contract import ActionPlan
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


class LiveMultiHopBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        live_multihop.clear_semantic_cache()

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

    def test_country_share_scope_normalizes_to_global_trade_scope(self):
        node = RequirementNode("country", Operator.RETRIEVE, args={"metric": "import_value", "scope": "country_share"})
        self.assertEqual(live_multihop._action_slots(node).trade_scope, "global")

    def test_filter_accepts_compact_string_predicate_without_runtime_error(self):
        factory = live_multihop.LiveOperatorFactory(
            message="가격 상승 광물", session_id="filter-test", profile="public",
            llm=object(), history=[],
        )
        source = TypedResult.success(
            ValueType.MINERAL_RANKING,
            [{"광종": "니켈", "pct_change": "12.5"}, {"광종": "리튬", "pct_change": "-2.0"}],
            entity=("니켈", "리튬"),
        )
        node = RequirementNode(
            "filtered", Operator.FILTER,
            args={"metric": "price_change_rate", "predicate": "greater_than", "value": 0},
        )

        result = factory._derive(node, {"rank": source})

        self.assertEqual(result.status.value, "success")
        self.assertEqual(result.value, [{"광종": "니켈", "pct_change": "12.5"}])

    def test_sort_keeps_rows_with_missing_metric_at_the_end(self):
        factory = live_multihop.LiveOperatorFactory(
            message="국가 순위", session_id="sort-test", profile="public", llm=object(), history=[],
        )
        source = TypedResult.success(
            ValueType.FACT_SET,
            [{"국가": "중국", "import_amount": None}, {"국가": "호주", "import_amount": 10}],
        )
        node = RequirementNode("sorted", Operator.SORT, args={"field": "import_amount", "order": "desc"})
        result = factory._derive(node, {"source": source})
        self.assertEqual([row["국가"] for row in result.value], ["호주", "중국"])

    def test_semantic_history_is_bounded_and_excludes_raw_result_payload(self):
        typed = TypedResult.success(
            ValueType.TRADE_SERIES,
            [{"월": "2026-01", "수입액": "999999999999999999999999"}],
            entity=("니켈",), metric="import_amount", provenance=("trade:fixture",),
        )
        turns = tuple(
            Turn(
                f"turn-{index}", "compact-session", UserUtterance("이전 질문"),
                semantic_program=SemanticProgram(
                    (RequirementNode("root", Operator.RETRIEVE, args={"metric": "import_amount"}),),
                    ("root",),
                ),
                result=ExecutionResult(f"pipe-{index}", ResultStatus.SUCCESS, {"root": typed}, ()),
            )
            for index in range(12)
        )
        payload = live_multihop._semantic_context_payload(ConversationContext("compact-session", turns))
        self.assertEqual(len(payload), 8)
        self.assertNotIn("수입액", str(payload))
        self.assertIn("operators", payload[-1]["ast"])
        self.assertIn("provenance", payload[-1]["results"][0])

    async def test_semantic_ast_cache_reuses_same_typed_context(self):
        class FakeLLM:
            model = "fake-gemma"
            calls = 0

            def invoke(self, **_kwargs):
                self.calls += 1
                return SimpleNamespace(output=live_multihop.ASTProgramModel.model_validate({
                    "nodes": [{"node_id": "root", "operator": "entity", "args": {"values": ["니켈"]}}],
                    "roots": ["root"],
                }))

        llm = FakeLLM()
        context = ConversationContext("cache-session")
        first = await live_multihop._parse_ast(llm, "니켈", context)
        second = await live_multihop._parse_ast(llm, "니켈", context)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(llm.calls, 1)
        self.assertEqual(live_multihop.semantic_cache_stats(), {"size": 1, "hits": 1, "misses": 1})

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
