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
