# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import (
    ActionCall, ActionPlan, ActionSlots, IntentCall, IntentPlan, Period,
    _has_source_unavailable_predecessor, _intent_plan_semantic_failure, action_plan_from_intent, validate_action_plan,
)
from rag_core.ragkit import chatbot_graph as graph
from rag_core.ragkit import chatbot
from rag_core.retrieval.evidence import Evidence


class ActionContractTest(unittest.TestCase):
    def test_price_slots_map_without_question_regex(self):
        plan = ActionPlan(actions=[ActionCall(requirement_id="r1", action_id="price.series",
            slots=ActionSlots(mineral="텅스텐", period=Period(kind="trailing_months", trailing_months=12),
                             requested_outputs={"table", "chart"}))])
        checked = validate_action_plan(plan)
        self.assertTrue(checked.approved)
        route = graph._route_from_action_plan(plan, "표현이 달라도 planner가 준 plan을 사용")
        self.assertTrue(route.use_komis_raw)
        self.assertEqual(route.komis_mineral_name, "텅스텐")
        self.assertEqual(route.komis_relative_months, 12)

    def test_unavailable_and_unverified_combo_are_closed_before_adapter(self):
        unavailable = ActionPlan(actions=[ActionCall(requirement_id="r1", action_id="diagnosis.rank", slots=ActionSlots())])
        self.assertEqual(validate_action_plan(unavailable).failure_reason, "source_unavailable")
        mixed = ActionPlan(actions=[
            ActionCall(requirement_id="r1", action_id="price.series", slots=ActionSlots(mineral="니켈")),
            ActionCall(requirement_id="r2", action_id="document.retrieve", slots=ActionSlots(topic="원인")),
        ])
        checked = validate_action_plan(mixed)
        self.assertEqual(checked.failure_reason, "unsupported_combination")
        result = graph._retrieve_node({"action_assessment": checked}, dense_k=1, pageindex_k=1)
        self.assertEqual(result["evidence"], [])
        self.assertIn("action_plan_failed:unsupported_combination", result["warnings"])

    def test_market_outlook_observations_and_documented_impact_are_a_supported_pair(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="mechanism", action_id="document.retrieve",
                       slots=ActionSlots(topic="전기차 수요 둔화가 광종에 미치는 영향")),
            ActionCall(requirement_id="observed", action_id="indicator.series",
                       slots=ActionSlots(indicator="market_outlook", minerals=["리튬", "니켈", "코발트"])),
        ])
        self.assertTrue(validate_action_plan(plan).approved)
        # supply stability 등 다른 indicator/document 조합은 허용 범위 밖이다.
        plan.actions[1].slots.indicator = "supply_stability"
        self.assertEqual(validate_action_plan(plan).failure_reason, "unsupported_combination")

    def test_advisor_runs_before_generation_for_structured_evidence(self):
        class Advisor:
            def __init__(self): self.called = False
            def invoke(self, **kwargs):
                self.called = True
                return SimpleNamespace(output=graph.GroundingCheck(sufficient=True, supported_evidence_indices=[1]))
        advisor = Advisor()
        result = graph._verify_node({"evidence": [Evidence(kind="structured", source="KOMIS", section="가격", text="x")],
                                     "warnings": [], "route": graph.RetrievalRoute(resolved_query="q", use_structured=False, use_dense=False, use_pageindex=False),
                                     "history": []}, advisor)
        self.assertTrue(advisor.called)
        self.assertTrue(result["sufficient"])

    def test_period_conflict_and_dependency_cycle_are_rejected(self):
        conflict = ActionPlan(actions=[ActionCall(requirement_id="r1", action_id="price.series",
            slots=ActionSlots(mineral="니켈", period=Period(kind="latest", future_horizon=3)))])
        self.assertFalse(validate_action_plan(conflict).approved)
        cycle = ActionPlan(actions=[
            ActionCall(requirement_id="r1", action_id="trade.monthly", depends_on=["r2"], slots=ActionSlots(mineral="니켈")),
            ActionCall(requirement_id="r2", action_id="trade.monthly", depends_on=["r1"], slots=ActionSlots(mineral="니켈")),
        ])
        self.assertFalse(validate_action_plan(cycle).approved)

    def test_mineral_specific_composite_index_is_closed(self):
        plan = ActionPlan(actions=[ActionCall(requirement_id="r1", action_id="indicator.series",
            slots=ActionSlots(indicator="composite_index", mineral="코발트"))])
        self.assertEqual(validate_action_plan(plan).failure_reason, "source_unavailable")

    def test_unavailable_predecessor_keeps_source_reason_for_follow_up(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="prior", action_id="diagnosis.series", slots=ActionSlots()),
            ActionCall(requirement_id="follow_up", action_id="price.series", depends_on=["prior"],
                       slots=ActionSlots()),
        ])
        self.assertEqual(validate_action_plan(plan).failure_reason, "source_unavailable")

    def test_static_methodology_evidence_is_limited_to_documented_q17_alternative(self):
        intent_plan = IntentPlan(requirements=[IntentCall(
            requirement_id="q17", intent="document", role="content", slots=ActionSlots(
                topic="리튬 재고와 목표의 부족분, 비축일 계산에 필요한 입력값"))])
        q17_plan = action_plan_from_intent(intent_plan)
        self.assertEqual(q17_plan.actions[0].action_id, "stockpile.methodology")
        self.assertTrue(validate_action_plan(q17_plan).approved)
        self.assertTrue(validate_action_plan(ActionPlan(actions=[ActionCall(
            requirement_id="q17-empty", action_id="stockpile.methodology", slots=ActionSlots())])).approved)
        q17 = ActionCall(requirement_id="q17", action_id="stockpile.methodology", slots=ActionSlots(
            topic="리튬 비축 현황과 목표 대비 부족량, 비축일수"))
        unrelated = ActionCall(requirement_id="other", action_id="document.retrieve", slots=ActionSlots(
            topic="니켈 가격의 전망"))
        evidence = graph._internal_methodology_evidence(q17)[0]
        self.assertEqual(evidence.source, "rag_core/ragkit/static_docs/stockpile_calculation_methodology.md")
        self.assertIn("max(목표재고−현재재고, 0)", evidence.text)
        methodology = Path(__file__).resolve().parents[1] / "ragkit/static_docs/stockpile_calculation_methodology.md"
        self.assertIn("거래소 재고 / 일평균 소비", methodology.read_text())
        self.assertEqual(graph._internal_methodology_evidence(unrelated), [])

    def test_stockpile_methodology_bypasses_observation_advisor_only_after_contract_checks(self):
        action = ActionCall(requirement_id="q17", action_id="stockpile.methodology", slots=ActionSlots(
            topic="비축 부족량과 비축일수 계산"))
        evidence = graph._internal_methodology_evidence(action)
        for item in evidence:
            item.requirement_id, item.action_id, item.source_id, item.observed_period = (
                action.requirement_id, action.action_id, item.source, item.as_of)
        result = graph._verify_node({"evidence": evidence, "warnings": [], "action_call": action,
            "route": graph.RetrievalRoute(resolved_query=action.slots.topic, use_structured=False,
                                              use_dense=False, use_pageindex=False), "history": []}, None)
        self.assertTrue(result["sufficient"])
        answer = chatbot._stockpile_methodology_answer(evidence)
        self.assertIn("실제 비축 현황, 부족량, 비축일수는 산출할 수 없습니다", answer)
        self.assertIn("max(목표재고 − 현재재고, 0)", answer)
        self.assertIn("[1] rag_core/ragkit/static_docs/stockpile_calculation_methodology.md", answer)

    def test_claim_uses_adapter_calculated_change_not_question_text(self):
        evidence = Evidence(kind="aggregated", source="KOMIS", section="가격 비교",
            text="| mineral | pct_change |\n| --- | --- |\n| 니켈 | 301.0 |")
        self.assertTrue(graph._claim_matches_comparison([evidence], 300, "greater_than", "니켈"))
        self.assertFalse(graph._claim_matches_comparison([evidence], 400, "greater_than", "니켈"))
        mixed = Evidence(kind="aggregated", source="KOMIS", section="가격 비교",
            text="| mineral | pct_change |\n| --- | --- |\n| 니켈 | 10 |\n| 리튬 | 500 |")
        self.assertFalse(graph._claim_matches_comparison([mixed], 300, "greater_than", "니켈"))

    def test_typed_normalization_for_resource_compare_and_country_default(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="r1", action_id="resource.rank", slots=ActionSlots(minerals=["희토류"], metric="production")),
            ActionCall(requirement_id="r2", action_id="resource.rank", slots=ActionSlots(minerals=["희토류"], metric="reserves")),
        ])
        self.assertTrue(validate_action_plan(plan).approved)
        self.assertEqual(plan.actions[0].slots.mineral, "희토류")
        rank = ActionPlan(actions=[ActionCall(requirement_id="r1", action_id="trade.country_rank",
            slots=ActionSlots(mineral="리튬", flow="import"))])
        self.assertTrue(validate_action_plan(rank).approved)
        self.assertEqual(rank.actions[0].slots.metric, "import_amount")

    def test_price_metadata_and_diagnosis_content_do_not_become_unsupported_combinations(self):
        price_metadata = IntentPlan(requirements=[
            IntentCall(requirement_id="price", intent="price_compare", role="data", slots=ActionSlots(
                minerals=["리튬"], windows=[3, 6, 12])),
            IntentCall(requirement_id="basis", intent="concept", role="content", slots=ActionSlots(
                topic="가격 기준과 등락률 계산 기준일")),
        ])
        normalized = action_plan_from_intent(price_metadata)
        self.assertEqual([call.action_id for call in normalized.actions], ["price.compare"])
        self.assertTrue(validate_action_plan(normalized).approved)
        diagnosis = IntentPlan(requirements=[
            IntentCall(requirement_id="price", intent="price_series", role="data", slots=ActionSlots(mineral="리튬")),
            IntentCall(requirement_id="risk", intent="concept", role="content", slots=ActionSlots(
                topic="수급위기 위험과 가격 하락의 관계")),
        ])
        self.assertEqual(validate_action_plan(action_plan_from_intent(diagnosis)).failure_reason, "source_unavailable")

    def test_off_topic_is_a_zero_tool_stable_plan(self):
        plan = ActionPlan(actions=[ActionCall(requirement_id="r1", action_id="off_topic", slots=ActionSlots())])
        self.assertEqual(validate_action_plan(plan).failure_reason, "out_of_scope")

    def test_metadata_before_data_is_absorbed_without_a_second_action(self):
        plan = action_plan_from_intent(IntentPlan(requirements=[
            IntentCall(requirement_id="basis", intent="price_series", role="metadata",
                       slots=ActionSlots(mineral="니켈", requested_outputs={"text"})),
            IntentCall(requirement_id="series", intent="price_series", role="data",
                       slots=ActionSlots(mineral="니켈", period=Period(
                           kind="trailing_months", trailing_months=12),
                           requested_outputs={"table", "chart"})),
        ]))
        self.assertEqual([call.action_id for call in plan.actions], ["price.series"])
        self.assertTrue(validate_action_plan(plan).approved)

    def test_multi_mineral_price_series_is_normalized_to_compare(self):
        plan = action_plan_from_intent(IntentPlan(requirements=[
            IntentCall(requirement_id="prices", intent="price_series", role="data",
                       slots=ActionSlots(minerals=["구리", "니켈", "코발트"],
                                         period=Period(kind="trailing_months", trailing_months=12))),
            IntentCall(requirement_id="basis", intent="concept", role="content",
                       slots=ActionSlots(topic="가격 단위가 다를 때 비교 방법")),
        ]))
        self.assertEqual([call.action_id for call in plan.actions], ["price.compare"])
        self.assertTrue(validate_action_plan(plan).approved)

    def test_claim_false_keeps_typed_comparison_evidence_when_advisor_rejects(self):
        action = ActionCall(requirement_id="claim", action_id="price.verify_claim",
                            slots=ActionSlots(mineral="니켈", claimed_change_pct=300,
                                              comparator="equals"))
        evidence = Evidence(kind="aggregated", source="KOMIS", source_id="komis_price",
                            requirement_id="claim", action_id="price.verify_claim",
                            section="가격 비교", unit="USD/톤",
                            text="| mineral | pct_change |\n| --- | --- |\n| 니켈 | -3.27 |")
        class RejectingAdvisor:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=graph.GroundingCheck(
                    sufficient=False, supported_evidence_indices=[]))
        result = graph._verify_node({
            "evidence": [evidence], "warnings": [], "action_call": action,
            "route": graph.RetrievalRoute(resolved_query="가격 전제 검증", use_structured=False,
                                          use_dense=False, use_pageindex=False), "history": [],
        }, RejectingAdvisor())
        self.assertTrue(result["sufficient"])
        self.assertEqual(result["evidence"], [evidence])

    def test_month_only_range_is_normalized_for_trade_adapter(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="trade", action_id="trade.monthly",
            slots=ActionSlots(mineral="리튬", metric="import_amount",
                              period=Period(kind="range", start="2026-01", end="2026-12")),
        )])
        self.assertTrue(validate_action_plan(plan).approved)
        self.assertEqual(plan.actions[0].slots.period.start, "2026-01-01")
        self.assertEqual(plan.actions[0].slots.period.end, "2026-12-31")

    def test_current_range_end_is_accepted_for_observed_trade(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="trade", action_id="trade.monthly",
            slots=ActionSlots(mineral="리튬", metric="import_amount",
                              period=Period(kind="range", start="2026-01", end="현재")),
        )])
        self.assertTrue(validate_action_plan(plan).approved)
        self.assertEqual(plan.actions[0].slots.period.start, "2026-01-01")

    def test_current_observed_range_needs_no_intent_repair(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="trade", intent="trade_monthly", role="data",
            slots=ActionSlots(mineral="리튬", metric="import_amount",
                              period=Period(kind="range", start="2026-01", end="현재")),
        )])
        self.assertIsNone(_intent_plan_semantic_failure(intents))

    def test_diagnosis_content_preserves_unavailable_source_boundary(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="diagnosis", intent="diagnosis", role="content",
            slots=ActionSlots(mineral="니켈", topic="최근 8주 위기진단 점수"),
        )])
        self.assertIsNone(_intent_plan_semantic_failure(intents))
        self.assertEqual(validate_action_plan(action_plan_from_intent(intents)).failure_reason,
                         "source_unavailable")

    def test_follow_up_price_slot_inherits_structured_source_failure_only(self):
        follow_up = ActionPlan(actions=[ActionCall(
            requirement_id="follow", action_id="price.compare", slots=ActionSlots(),
        )])
        history = [{"role": "assistant", "content": "기권 문구와 무관",
                    "abstain_reason": "source_unavailable", "action_ids": ["price.compare"]}]
        self.assertTrue(_has_source_unavailable_predecessor(history, follow_up))
        follow_up.predecessor_source_unavailable = True
        self.assertEqual(validate_action_plan(follow_up).failure_reason, "source_unavailable")

    def test_dummy_or_incomplete_comparison_and_monthly_evidence_are_blocked(self):
        dummy = Evidence(kind="aggregated", source="KOMIS", section="KO_MNRL_PRC(구리)",
                         text="| mineral | price |\n| --- | --- |\n| 구리 | 1 |",
                         as_of="2026-07-07~2026-09-08", caveat="개발용 더미 데이터")
        compare = ActionCall(requirement_id="prices", action_id="price.compare", slots=ActionSlots(
            minerals=["구리", "니켈", "코발트"], period=Period(kind="trailing_months", trailing_months=12)))
        self.assertFalse(graph._comparison_or_monthly_source_is_usable([dummy], compare))
        monthly = ActionCall(requirement_id="trade", action_id="trade.monthly", slots=ActionSlots(
            mineral="리튬", metric="import_amount"))
        self.assertFalse(graph._comparison_or_monthly_source_is_usable([dummy], monthly))


if __name__ == "__main__":
    unittest.main()
