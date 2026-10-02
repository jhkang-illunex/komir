import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode, ValueType
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult
from inhouse.rag_core.ragkit.semantic_ir import SemanticProgram
from inhouse.rag_core.retrieval.evidence import Evidence


class LiveAuditSafetyTests(unittest.IsolatedAsyncioTestCase):
    def factory(self):
        return live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])

    def test_price_metric_without_redundant_domain_is_not_document_lookup(self):
        self.assertEqual(live._action_id(RequirementNode("price", Operator.RETRIEVE,
            args={"metric": "price", "price_criterion_serial": 502})), "price.series")

    def test_document_root_renders_validated_evidence_text(self):
        ev = Evidence("pageindex", "fixture", "usage", "Synthetic usage fact")
        root = TypedResult.success(ValueType.DOCUMENT_EVIDENCE, [ev], evidence=(ev,))
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=root)))
        self.assertIn("Synthetic usage fact", str([e.data for e in events]))
        self.assertFalse(events[-1].data["abstained"])

    async def test_runtime_keeps_semantic_ids_with_langgraph_reserved_characters(self):
        from inhouse.rag_core.ragkit.pipe_runtime import Pipe, PipeRuntime, FunctionStep
        first = FunctionStep("entity:nickel", "entity", lambda c, i: TypedResult.success(ValueType.MINERAL_SET, ["nickel"]))
        second = FunctionStep("price:latest", "project", lambda c, i: i["entity:nickel"], dependencies=("entity:nickel",))
        result = await PipeRuntime().execute(Pipe("reserved-ids", (first, second)))
        self.assertEqual(result.results["price:latest"].value, ["nickel"])

    def test_history_materialization_preserves_original_typed_snapshot(self):
        source = TypedResult(ValueType.TIME_SERIES, [{"price": 10}], status=ResultStatus.PARTIAL,
            entity=("nickel",), period={"year": 2024}, unit="USD/t",
            evidence=(Evidence("structured", "fixture", "fixture", "price=10"),))
        turn = Turn("old", "fixture", UserUtterance("previous"),
            semantic_program=SemanticProgram((RequirementNode("root", Operator.ENTITY),), ("root",)),
            result=ExecutionResult("pipe", ResultStatus.PARTIAL, {"root": source}, ()))
        context = ConversationContext("fixture", (turn,))
        factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None,
                                          history=[], context=context)
        payload = {"nodes": [{"node_id": "next", "operator": "project",
            "inputs": [{"node_id": "previous"}], "args": {"fields": ["price"]}}], "roots": ["next"]}
        program = SemanticProgram.from_dict(live._normalize_history_aliases(payload, context))
        restored = factory._entity(program.nodes[0])
        self.assertIs(restored, source)
        self.assertEqual(factory._derive(program.nodes[1], {"previous": restored}).status, ResultStatus.PARTIAL)

    def test_localized_result_alias_resolves_to_latest_root_snapshot(self):
        source = TypedResult(ValueType.TIME_SERIES, [{"price": 10}], status=ResultStatus.PARTIAL,
            entity=("nickel",), evidence=(Evidence("structured", "fixture", "fixture", "price=10"),))
        turn = Turn("old", "fixture", UserUtterance("previous"),
            semantic_program=SemanticProgram((RequirementNode("root", Operator.ENTITY),), ("root",)),
            result=ExecutionResult("pipe", ResultStatus.PARTIAL, {"root": source}, ()))
        context = ConversationContext("fixture", (turn,))
        alias = f"result:{live._history_node_id('history:old:root')}"
        payload = {"nodes": [{"node_id": "next", "operator": "project",
            "inputs": [{"node_id": alias}], "args": {"fields": ["price"]}}], "roots": ["next"]}
        normalized = live._normalize_history_aliases(payload, context)
        self.assertEqual(normalized["nodes"][1]["inputs"][0]["node_id"], live._history_node_id(alias))

    def test_legacy_single_root_result_alias_resolves_for_followup(self):
        source = TypedResult.success(ValueType.TIME_SERIES, [{"price": 10}], entity=("nickel",))
        turn = Turn("old", "fixture", UserUtterance("previous"),
                    semantic_program=None,
                    result=ExecutionResult("pipe", ResultStatus.SUCCESS, {"legacy": source}, ()),
                    result_id="old-result")
        context = ConversationContext("fixture", (turn,))
        alias = "result:old:legacy"
        payload = {"nodes": [{"node_id": "next", "operator": "project",
            "inputs": [{"node_id": alias}], "args": {"fields": ["price"]}}],
                   "roots": ["next"]}
        normalized = live._normalize_history_aliases(payload, context)
        self.assertEqual(normalized["nodes"][0]["operator"], "entity")

    def test_followup_ignores_in_progress_turn_without_result(self):
        source = TypedResult.success(ValueType.TIME_SERIES, [{"price": 10}], entity=("nickel",))
        previous = Turn("old", "fixture", UserUtterance("previous"),
                        semantic_program=None,
                        result=ExecutionResult("pipe", ResultStatus.SUCCESS, {"legacy": source}, ()),
                        result_id="old-result")
        current = Turn("current", "fixture", UserUtterance("followup"), result=None)
        context = ConversationContext("fixture", (previous, current))
        payload = {"nodes": [{"node_id": "next", "operator": "project",
            "inputs": [{"node_id": "result:old:legacy"}], "args": {"fields": ["price"]}}],
                   "roots": ["next"]}
        normalized = live._normalize_history_aliases(payload, context)
        self.assertEqual(normalized["nodes"][0]["operator"], "entity")

    def test_legacy_compatibility_alias_maps_only_to_latest_single_root(self):
        source = TypedResult.success(ValueType.TIME_SERIES, [{"price": 10}], entity=("nickel",))
        turn = Turn("old", "fixture", UserUtterance("previous"),
                    semantic_program=None,
                    result=ExecutionResult("pipe", ResultStatus.SUCCESS, {"current_price": source}, ()))
        context = ConversationContext("fixture", (turn,))
        payload = {"nodes": [{"node_id": "next", "operator": "project",
            "inputs": [{"node_id": "result:old:legacy"}], "args": {"fields": ["price"]}}],
                   "roots": ["next"]}
        normalized = live._normalize_history_aliases(payload, context)
        self.assertEqual(normalized["nodes"][0]["operator"], "entity")

    def test_simple_legacy_delegation_does_not_construct_empty_plan(self):
        from unittest.mock import patch
        from inhouse.rag_core.ragkit import action_contract
        sentinel = object()
        with patch.dict("os.environ", {"MULTIHOP_ORCHESTRATOR_MODE": "enabled", "SEMANTIC_INTENT_MODE": "off"}), \
             patch.object(action_contract, "_extract_action_plan_legacy", return_value=sentinel):
            self.assertIs(action_contract.extract_action_plan("query", None), sentinel)

    def test_aggregate_executes_instead_of_returning_input_rows(self):
        source = TypedResult.success(ValueType.FACT_SET, [{"price": 10}, {"price": 20}], unit="USD/t")
        result = self.factory()._derive(RequirementNode("sum", Operator.AGGREGATE,
            args={"field": "price", "aggregation": "sum"}), {"source": source})
        self.assertEqual(result.value, [{"price": 30}])
        self.assertEqual(result.unit, "USD/t")

    def test_unimplemented_calculation_does_not_claim_success(self):
        source = TypedResult.success(ValueType.FACT_SET, [{"price": 10}])
        for operator in (Operator.CALCULATE, Operator.JOIN, Operator.COMPARE):
            with self.subTest(operator=operator):
                result = self.factory()._derive(RequirementNode("op", operator), {"source": source})
                self.assertNotEqual(result.status, ResultStatus.SUCCESS)

    def test_multi_root_sse_contains_values_and_one_completion(self):
        price = TypedResult.success(ValueType.TIME_SERIES, [{"price": 20}], source=("price-source",))
        root = TypedResult(ValueType.COMPOSITE, {"price": price,
            "usage": TypedResult.empty(ValueType.DOCUMENT_EVIDENCE, "no_data")}, status=ResultStatus.PARTIAL)
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=root)))
        self.assertEqual(sum(e.type == "done" for e in events), 1)
        self.assertTrue(any(e.type == "table" and "20" in str(e.data) for e in events))
        self.assertIn("no_data", str([e.data for e in events]))

    def test_explicit_series_composite_keeps_all_observations(self):
        root = TypedResult.success(ValueType.COMPOSITE, [{"mineral": "nickel", "status": "success",
            "output": "time_series", "result_type": "time_series", "metric": "price",
            "value": [{"date": "2020-01-01", "price": 10}, {"date": "2020-02-01", "price": 20}]}])
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=root)))
        tables = [event.data for event in events if event.type == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tables[0]["rows"]), 2)


    def test_action_slots_preserve_explicit_typed_constraints(self):
        node = RequirementNode("price", Operator.RETRIEVE, args={
            "domain": "price", "mineral": "nickel", "price_criterion_serial": 502,
            "reporter_country": "KR", "partner_country": "CL"})
        slots = live._action_slots(node)
        self.assertEqual(slots.price_criterion_serial, 502)
        self.assertEqual(slots.reporter_country, "KR")
        self.assertEqual(slots.partner_country, "CL")

    def test_null_equality_filter_does_not_evaluate_ordering(self):
        source = TypedResult.success(ValueType.FACT_SET, [{"value": None}, {"value": 10}])
        node = RequirementNode("filter", Operator.FILTER, args={
            "predicate": {"field": "value", "operator": "equals", "value": None}})
        self.assertEqual(self.factory()._derive(node, {"source": source}).value, [{"value": None}])

    def test_projection_preserves_partial_metadata_and_blocks_aggregate(self):
        source = TypedResult(ValueType.FACT_SET, [{"price": 10}], status=ResultStatus.PARTIAL,
                            period={"year": 2024}, unit="USD/t", warnings=("missing entity",))
        projected = self.factory()._derive(RequirementNode("project", Operator.PROJECT,
            args={"fields": ["price"]}), {"source": source})
        self.assertEqual(projected.status, ResultStatus.PARTIAL)
        self.assertEqual(projected.period, source.period)
        self.assertEqual(projected.unit, source.unit)
        self.assertEqual(projected.warnings, source.warnings)
        total = self.factory()._derive(RequirementNode("sum", Operator.AGGREGATE), {"source": projected})
        self.assertEqual(total.failure_reason, "incomplete_population")

    async def test_multi_mineral_trade_binds_each_entity(self):
        factory = self.factory()
        factory._call_action = AsyncMock(return_value=TypedResult.empty(ValueType.FACT_SET, "no_data"))
        await factory._retrieve(RequirementNode("trade", Operator.RETRIEVE,
            args={"domain": "trade", "metric": "import_amount", "minerals": ["nickel", "lithium"]}), {})
        self.assertEqual([call.kwargs["mineral"] for call in factory._call_action.call_args_list],
                         ["nickel", "lithium"])

    def test_history_does_not_retarget_unknown_reference_or_remove_validation(self):
        previous = Turn("old", "session", UserUtterance("previous"),
                        semantic_program=SemanticProgram((RequirementNode("root", Operator.ENTITY),), ("root",)),
                        result=ExecutionResult("pipe", ResultStatus.SUCCESS,
                                               {"root": TypedResult.success(ValueType.MINERAL_SET, ["A"])}, ()))
        payload = {"nodes": [{"node_id": "guard", "operator": "validate_evidence",
                               "inputs": [{"node_id": "history:missing:root"}]}], "roots": ["guard"]}
        normalized = live._normalize_history_aliases(payload, ConversationContext("session", (previous,)))
        self.assertEqual(normalized, payload)

    def test_document_list_column_preserves_individual_entities(self):
        self.assertEqual(live._entity_values([{"광종 목록": "니켈, 리튬", "문서": "동향"}]), ["니켈", "리튬"])

    def test_document_projection_preserves_list_and_provenance(self):
        factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
        ev = Evidence("pageindex", "fixture", "fixture", "mineral_list")
        source = TypedResult.success(ValueType.DOCUMENT_EVIDENCE, [{"광종 목록": "니켈, 리튬"}], evidence=(ev,), provenance=("doc:fixture",))
        node = RequirementNode("minerals", Operator.PROJECT, args={"field": "minerals"})
        result = factory._derive(node, {"doc": source})
        self.assertEqual(result.result_type, ValueType.MINERAL_SET)
        self.assertEqual(result.entity, ("니켈", "리튬"))
        self.assertEqual(result.evidence, source.evidence)
        self.assertEqual(result.provenance, source.provenance)

    async def test_document_title_does_not_establish_mineral_membership(self):
        factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
        factory._call_action = AsyncMock()
        ev = Evidence("pageindex", "fixture", "fixture", "월간동향 목차")
        node = RequirementNode("each", Operator.FOR_EACH, args={"domain": "price"})
        result = await factory._foreach(node, {"source": TypedResult.success(ValueType.DOCUMENT_EVIDENCE, [ev], evidence=(ev,))})
        self.assertEqual(result.status, ResultStatus.EMPTY)
        factory._call_action.assert_not_called()

    def test_partial_population_cannot_be_aggregated(self):
        factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
        partial = TypedResult(ValueType.FACT_SET, [{"price": 1}], status=ResultStatus.PARTIAL)
        result = factory._derive(RequirementNode("sum", Operator.AGGREGATE), {"source": partial})
        self.assertEqual(result.failure_reason, "incomplete_population")

    def test_null_grounding_reason_does_not_change_rejection(self):
        from inhouse.rag_core.ragkit.chatbot_graph import GroundingCheck
        result = GroundingCheck.model_validate({"sufficient": False, "reason": None, "supported_evidence_indices": []})
        self.assertFalse(result.sufficient)
        self.assertEqual(result.supported_evidence_indices, [])

    def test_rejected_document_is_not_promoted_to_success(self):
        call = live.ActionCall(requirement_id="doc", action_id="document.retrieve",
                               slots=live.ActionSlots(topic="report"))
        ev = Evidence("pageindex", "fixture", "fixture", "Index only")
        raw = RetrievalResult(live.ActionPlan(actions=[call]), [
            ActionResult("doc", call.action_id, call.slots, "validation_failed", [ev])], [ev])
        result = live._typed_from_retrieval(raw, call, input_entities=[])
        self.assertNotEqual(result.status, ResultStatus.SUCCESS)
        self.assertFalse(result.sufficient)

    async def test_foreach_isolates_tool_failure_and_reports_partial(self):
        factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
        ev = Evidence("structured", "fixture", "fixture", "price=10")
        factory._call_action = AsyncMock(side_effect=[
            TypedResult.success(ValueType.TIME_SERIES, [{"price": 10}], evidence=(ev,)),
            RuntimeError("tool failed"),
            TypedResult.empty(ValueType.TIME_SERIES, "no_data")])
        node = RequirementNode("each", Operator.FOR_EACH, args={"domain": "price", "metric": "price"})
        source = TypedResult.success(ValueType.MINERAL_SET, ["A", "B", "C"], entity=("A", "B", "C"))
        result = await factory._foreach(node, {"source": source})
        self.assertEqual(result.status, ResultStatus.PARTIAL)
        self.assertEqual([r["status"] for r in result.value], ["success", "failed", "empty"])
        self.assertEqual(factory._call_action.await_count, 3)

    async def test_foreach_all_empty_does_not_succeed(self):
        factory = live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
        factory._call_action = AsyncMock(return_value=TypedResult.empty(ValueType.TIME_SERIES, "no_data"))
        node = RequirementNode("each", Operator.FOR_EACH, args={"domain": "price", "metric": "price"})
        result = await factory._foreach(node, {"source": TypedResult.success(ValueType.MINERAL_SET, ["A"], entity=("A",))})
        self.assertNotEqual(result.status, ResultStatus.SUCCESS)
        self.assertEqual(len(result.value), 1)

    def test_empty_composite_presentation_cannot_report_success(self):
        result = TypedResult.success(ValueType.COMPOSITE, [{"mineral": "A", "status": "success", "value": []}])
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=result)))
        self.assertTrue(events[-1].data["abstained"])

    def test_price_criterion_is_not_a_price_observation(self):
        result = TypedResult.success(ValueType.COMPOSITE, [{"mineral": "A", "status": "success", "value": [{"가격기준": 502}]}])
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=result)))
        self.assertTrue(events[-1].data["abstained"])

    def test_price_unit_metadata_is_not_rendered_as_unit_text(self):
        result = TypedResult.success(ValueType.COMPOSITE, [{"mineral": "A", "status": "success",
            "unit": "가격기준=[DEV_DUMMY] spot; 통화코드=USD; 중량단위코드=TON", "value": [{"price": 10}]}])
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=result)))
        self.assertIn("USD/", events[0].data["delta"])
        self.assertNotIn("DEV_DUMMY", events[0].data["delta"])

    def test_latest_price_is_not_first_row_and_keeps_item_source_unit(self):
        result = TypedResult.success(ValueType.COMPOSITE, [{"mineral": "A", "status": "success", "unit": "USD/t", "source": ["price-source"],
            "value": [{"date": "2020-01-01", "price": 10}, {"date": "2020-02-01", "price": 20}]}], source=("doc-source", "price-source"))
        events = live.live_run_events(SimpleNamespace(orchestration=SimpleNamespace(root_result=result)))
        self.assertIn("20 USD/t", events[0].data["delta"])
        table = next(event.data for event in events if event.type == "table")
        self.assertEqual(table["source_index"], 2)
