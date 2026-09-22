# -*- coding: utf-8 -*-
"""설계 문서와 기존 챗봇 요구를 기준으로 한 독립 action 계약 검수."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import (  # noqa: E402
    ActionPlan, IntentCall, IntentPlan, ActionSlots, action_plan_from_intent,
    missing_trade_indicator_slots, validate_action_plan,
)
from rag_core.ragkit.chatbot_graph import _route_from_action_plan, _route_from_action_call  # noqa: E402
from rag_core.ragkit import chatbot_graph as graph  # noqa: E402
from rag_core.ragkit.mcp_client import _ProfileSession  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


def plan(*actions):
    return ActionPlan(actions=list(actions))


def call(requirement_id, action_id, **slots):
    return {"requirement_id": requirement_id, "action_id": action_id, "slots": slots}


class ActionContractAuditTest(unittest.TestCase):
    def test_trade_indicator_missing_slots_is_hitl_only(self):
        candidate = plan(call("r1", "trade.indicator", trade_metric="country_dependency"))
        self.assertEqual(
            missing_trade_indicator_slots(candidate.actions[0]),
            ("reporter_country", "period", "mineral_or_hs_code", "flow", "partner_country"),
        )
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_required")

    def test_complete_trade_indicator_routes_to_dedicated_mcp_path(self):
        candidate = plan(call(
            "r1", "trade.indicator", trade_metric="country_dependency", mineral="리튬",
            reporter_country="한국", partner_country="중국", flow="import",
            period={"kind": "calendar_year", "calendar_year": 2025, "explicit": True},
        ))
        self.assertTrue(validate_action_plan(candidate).approved)
        route = _route_from_action_plan(candidate, "2025년 한국의 중국산 리튬 수입 의존도")
        self.assertTrue(route.use_komis_trade_indicator)
        self.assertEqual(route.komis_trade_metric, "country_dependency")
        self.assertEqual(route.komis_partner_country, "중국")

    @staticmethod
    def _verify_rejected_claim(action, evidence):
        class RejectingLLM:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=graph.GroundingCheck(
                    sufficient=False, reason="주장과 관측값 불일치", supported_evidence_indices=[]))

        return graph._verify_node({
            "evidence": [evidence], "warnings": [], "action_call": action,
            "route": graph.RetrievalRoute(resolved_query="니켈 가격 주장 검증",
                                          use_structured=False, use_dense=False,
                                          use_pageindex=False), "history": [],
        }, RejectingLLM())

    def test_false_price_claim_preserves_only_matching_typed_evidence(self):
        action = plan(call("claim", "price.verify_claim", mineral="니켈",
                           claimed_change_pct=300, comparator="equals",
                           currency="USD", period={"kind": "calendar_year",
                                                   "calendar_year": 2025, "explicit": True})).actions[0]
        common = dict(kind="aggregated", source="public.KO_MNRL_PRC", section="가격 비교",
                      source_id="public.KO_MNRL_PRC", requirement_id="claim",
                      action_id="price.verify_claim")
        valid = Evidence(**common, unit="USD/톤", observed_period="2025-01-02~2025-12-31",
                         text="| mineral(광종) | pct_change(변동률(%)) |\n| --- | --- |\n| 니켈 | -3.27 |")
        self.assertTrue(self._verify_rejected_claim(action, valid)["sufficient"])
        invalid = (
            Evidence(**common, unit="USD/톤", observed_period="2025-01-02~2025-12-31",
                     text="| mineral | pct_change |\n| --- | --- |\n| 코발트 | -3.27 |"),
            Evidence(**common, unit="USD/톤", observed_period="2023-01-02~2023-12-31",
                     text="| mineral | pct_change |\n| --- | --- |\n| 니켈 | -3.27 |"),
            Evidence(**common, unit="CNY/kg", observed_period="2025-01-02~2025-12-31",
                     text="| mineral | pct_change |\n| --- | --- |\n| 니켈 | -3.27 |"),
            Evidence(**common, unit="USD/톤", observed_period="2025-01-02~2025-12-31",
                     text="| mineral | price |\n| --- | --- |\n| 니켈 | 15010 |"),
        )
        for evidence in invalid:
            with self.subTest(text=evidence.text, unit=evidence.unit,
                              observed_period=evidence.observed_period):
                self.assertFalse(self._verify_rejected_claim(action, evidence)["sufficient"])

    def test_intent_plan_preserves_independent_requirements(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="production", intent="resource_rank",
                       slots=ActionSlots(mineral="희토류", metric="production", top_n=5)),
            IntentCall(requirement_id="reserves", intent="resource_rank",
                       slots=ActionSlots(mineral="희토류", metric="reserves", top_n=5)),
        ])
        candidate = action_plan_from_intent(intents)
        self.assertEqual([item.requirement_id for item in candidate.actions], ["production", "reserves"])
        self.assertEqual([item.slots.metric for item in candidate.actions], ["production", "reserves"])
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_mineral_concept_is_document_action(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="concept", intent="concept",
            slots=ActionSlots(topic="핵심광물 공급망 다변화에서 재활용의 역할과 한계"),
        )])
        candidate = action_plan_from_intent(intents)
        self.assertEqual(candidate.actions[0].action_id, "document.retrieve")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_non_geopolitical_issue_is_normalized_to_document_search(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="issue", intent="geopolitics_articles", role="content",
            slots=ActionSlots(mineral="리튬", topic="수요 관련 이슈"),
        )])
        candidate = action_plan_from_intent(intents)
        self.assertEqual([item.action_id for item in candidate.actions], ["document.retrieve"])
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_issue_report_is_document_search_but_dated_report_stays_explicit_lookup(self):
        issue = IntentPlan(requirements=[IntentCall(
            requirement_id="issue", intent="okf_lookup", role="content",
            slots=ActionSlots(topic="리튬 수급 이슈 보고서"),
        )])
        self.assertEqual(action_plan_from_intent(issue).actions[0].action_id, "document.retrieve")
        dated = IntentPlan(requirements=[IntentCall(
            requirement_id="dated", intent="okf_lookup", role="content",
            slots=ActionSlots(topic="2026년 6월 16일 조달청 주간 경제 비철금속 시장 동향 보고서"),
        )])
        self.assertEqual(action_plan_from_intent(dated).actions[0].action_id, "document.lookup")

    def test_document_search_uses_original_question_when_topic_is_missing(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="issue", intent="document", role="content",
            slots=ActionSlots(mineral="리튬"),
        )])
        candidate = action_plan_from_intent(intents, "6개월 이내 리튬 수요 관련 이슈를 보여주세요")
        self.assertEqual(candidate.actions[0].slots.topic, "6개월 이내 리튬 수요 관련 이슈를 보여주세요")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_recent_document_evidence_keeps_only_confirmed_file_dates_in_window(self):
        action = plan(call("issue", "document.retrieve", topic="리튬 수요", mineral="리튬",
                           period={"kind": "trailing_months", "trailing_months": 6,
                                   "explicit": True})).actions[0]
        recent = Evidence(kind="dense", source="20260616.pdf", section="리튬", text="배터리 설치량",
                          as_of="2026-06-16")
        old = Evidence(kind="dense", source="20230523.pdf", section="리튬", text="수요 전망",
                       as_of="2023-05-23")
        unknown = Evidence(kind="pageindex", source="unknown", section="리튬", text="수요")
        self.assertEqual(graph._filter_document_evidence_to_trailing_period(
            [recent, old, unknown], action), [recent])

    def test_document_action_builds_dense_and_pageindex_route(self):
        candidate = plan(call("concept", "document.retrieve", topic="핵심광물 재활용의 역할과 한계"))
        self.assertTrue(validate_action_plan(candidate).approved)
        route = _route_from_action_call(candidate.actions[0], "개념 질문")
        self.assertEqual(route.resolved_query, "핵심광물 재활용의 역할과 한계")
        self.assertTrue(route.use_dense)
        self.assertTrue(route.use_pageindex)
        self.assertFalse(route.use_komis_raw)

    def test_data_result_absorbs_only_its_metadata(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="price", intent="price_series",
                       slots=ActionSlots(mineral="니켈")),
            IntentCall(requirement_id="unit", intent="concept",
                       slots=ActionSlots(topic="가격 기준과 단위")),
        ])
        candidate = action_plan_from_intent(intents)
        self.assertEqual([item.action_id for item in candidate.actions], ["price.series"])
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_independent_document_content_is_not_dropped_from_price_claim(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="claim", intent="price_claim",
                       slots=ActionSlots(mineral="니켈", claimed_change_pct=300,
                                         period={"kind": "calendar_year", "calendar_year": 2025})),
            IntentCall(requirement_id="cause", intent="document",
                       slots=ActionSlots(topic="2025년 니켈 가격 상승의 원인")),
        ])
        candidate = action_plan_from_intent(intents)
        self.assertEqual([item.action_id for item in candidate.actions],
                         ["price.verify_claim", "document.retrieve"])
        self.assertEqual(validate_action_plan(candidate).failure_reason, "unsupported_combination")

    def test_diagnosis_content_is_not_dropped_from_price_result(self):
        intents = IntentPlan(requirements=[
            IntentCall(requirement_id="price", intent="price_series", role="data",
                       slots=ActionSlots(mineral="니켈")),
            IntentCall(requirement_id="diagnosis", intent="diagnosis", role="content",
                       slots=ActionSlots(mineral="니켈", topic="수급위기 진단과 가격의 관계")),
        ])
        candidate = action_plan_from_intent(intents)
        self.assertEqual([item.action_id for item in candidate.actions],
                         ["price.series", "diagnosis.rank"])
        self.assertEqual(validate_action_plan(candidate).failure_reason, "source_unavailable")

    def test_future_quantity_forecast_is_not_relabelled_as_observed_trade(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="forecast", intent="forecast_quantity", role="data",
            slots=ActionSlots(mineral="리튬", metric="import_amount",
                              period={"kind": "future_horizon", "future_horizon": 12}),
        )])
        candidate = action_plan_from_intent(intents)
        self.assertEqual([item.action_id for item in candidate.actions], ["forecast.quantity"])
        self.assertEqual(validate_action_plan(candidate).failure_reason, "source_unavailable")

    @staticmethod
    def _verify_with_approving_llm(action, evidence):
        class ApprovingLLM:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=graph.GroundingCheck(
                    sufficient=True, supported_evidence_indices=[1]))

        return graph._verify_node({
            "evidence": [evidence], "warnings": [], "action_call": action,
            "route": graph.RetrievalRoute(resolved_query="검수 질문",
                                          use_structured=False, use_dense=False,
                                          use_pageindex=False), "history": [],
        }, ApprovingLLM())

    def test_mineral_specific_composite_index_is_rejected_before_adapter(self):
        candidate = plan(call("r1", "indicator.series", indicator="composite_index", mineral="코발트"))
        self.assertEqual(validate_action_plan(candidate).failure_reason, "source_unavailable")

    def test_period_kinds_are_mutually_exclusive(self):
        candidate = plan(call("r1", "price.series", mineral="니켈",
                              period={"kind": "trailing_months", "trailing_months": 12, "future_horizon": 3}))
        self.assertFalse(validate_action_plan(candidate).approved)

    def test_month_range_expands_to_calendar_bounds_and_rejects_invalid_order(self):
        valid = plan(call("r1", "trade.monthly", mineral="리튬", metric="import_amount",
                          period={"kind": "range", "start": "2024-02", "end": "2024-02", "explicit": True}))
        self.assertTrue(validate_action_plan(valid).approved)
        self.assertEqual(valid.actions[0].slots.period.start, "2024-02-01")
        self.assertEqual(valid.actions[0].slots.period.end, "2024-02-29")
        for start, end in (("2026-13", "2026-13"), ("2026-12", "2026-01")):
            with self.subTest(start=start, end=end):
                invalid = plan(call("r1", "trade.monthly", mineral="리튬", metric="import_amount",
                                    period={"kind": "range", "start": start, "end": end, "explicit": True}))
                self.assertEqual(validate_action_plan(invalid).failure_reason, "slot_unresolved")

    def test_monthly_trade_mcp_boundary_uses_compact_day_dates(self):
        session = _ProfileSession("public")
        with patch.object(session, "_call", return_value={"evidence": [], "warnings": []}) as tool:
            session.call_komis_monthly_trade_summary(
                mineral_code="MNRL0001", start_period="2026-01-01",
                end_period="2026-12-31", metric="import_amount")
        payload = tool.call_args.args[1]
        self.assertEqual(payload["start_period"], "20260101")
        self.assertEqual(payload["end_period"], "20261231")
        self.assertEqual(payload["metric"], "import_amount")

    def test_price_comparison_mcp_boundary_uses_compact_day_dates(self):
        session = _ProfileSession("public")
        with patch.object(session, "_call", return_value={"evidence": [], "warnings": []}) as tool:
            session.call_komis_price_comparison(
                ["니켈", "코발트"], start_period="2026-06-17", end_period="2026-09-08")
        payload = tool.call_args.args[1]
        self.assertEqual(payload["start_period"], "20260617")
        self.assertEqual(payload["end_period"], "20260908")

    def test_dependency_graph_rejects_cycle(self):
        candidate = plan(
            {**call("r1", "price.series", mineral="니켈"), "depends_on": ["r2"]},
            {**call("r2", "price.series", mineral="구리"), "depends_on": ["r1"]},
        )
        self.assertFalse(validate_action_plan(candidate).approved)

    def test_price_windows_reach_existing_adapter_route(self):
        candidate = plan(call("r1", "price.compare", minerals=["리튬"], windows=[3, 6, 12]))
        self.assertTrue(validate_action_plan(candidate).approved)
        route = _route_from_action_plan(candidate, "문구에 의존하지 않는 비교")
        self.assertEqual(route.komis_price_windows_months, [3, 6, 12])

    def test_menu_and_full_dataset_have_live_capability(self):
        for action, slots in (
            ("menu.navigate", {"target_page": "광물지도"}),
            ("dataset.navigate", {"dataset": "supply_stability", "mineral": "NI"}),
        ):
            with self.subTest(action=action):
                self.assertTrue(validate_action_plan(plan(call("r1", action, **slots))).approved)

    def test_claim_threshold_is_not_dropped_at_adapter(self):
        candidate = plan(call("r1", "price.verify_claim", mineral="니켈",
                              period={"kind": "calendar_year", "calendar_year": 2025},
                              claimed_change_pct=300, comparator="equals"))
        self.assertTrue(validate_action_plan(candidate).approved)
        route = _route_from_action_plan(candidate, "주장 300%")
        self.assertEqual(getattr(route, "komis_claimed_change_pct", None), 300)

    def test_advisor_rejects_explicit_period_mismatch_even_if_llm_approves(self):
        action = plan(call("r1", "price.series", mineral="니켈",
                           period={"kind": "calendar_year", "calendar_year": 2025, "explicit": True})).actions[0]
        evidence = Evidence(kind="aggregated", source="KOMIS", section="가격",
                            text="| date | price |\n| --- | --- |\n| 2023-01-01 | 1 |",
                            observed_period="2023-01-01~2023-12-31", unit="USD/톤",
                            requirement_id="r1", action_id="price.series")
        result = self._verify_with_approving_llm(action, evidence)
        self.assertFalse(result["sufficient"])

    def test_advisor_allows_partial_range_with_observed_period(self):
        action = plan(call("r1", "price.series", mineral="니켈",
                           period={"kind": "range", "start": "2025-01-01",
                                   "end": "2025-12-31", "explicit": True})).actions[0]
        evidence = Evidence(kind="aggregated", source="KOMIS", section="가격",
                            text="| date | price |\n| --- | --- |\n| 2025-06-01 | 1 |",
                            observed_period="2025-06-01~2025-07-31", unit="USD/톤",
                            source_id="komis_price", requirement_id="r1", action_id="price.series")
        result = self._verify_with_approving_llm(action, evidence)
        self.assertTrue(result["sufficient"])

    def test_advisor_rejects_incompatible_unit(self):
        action = plan(call("r1", "price.series", mineral="니켈", currency="USD",
                           weight_unit="톤")).actions[0]
        evidence = Evidence(kind="aggregated", source="KOMIS", section="가격",
                            text="| mineral | price |\n| --- | --- |\n| 니켈 | 1 |",
                            observed_period="2025-01-01", unit="CNY/kg",
                            source_id="komis_price", requirement_id="r1", action_id="price.series")
        result = self._verify_with_approving_llm(action, evidence)
        self.assertFalse(result["sufficient"])

    def test_advisor_rejects_wrong_mineral(self):
        action = plan(call("r1", "price.series", mineral="니켈")).actions[0]
        evidence = Evidence(kind="aggregated", source="KOMIS", section="가격",
                            text="| mineral | price |\n| --- | --- |\n| 코발트 | 1 |",
                            observed_period="2025-01-01", unit="USD/톤",
                            source_id="komis_price", requirement_id="r1", action_id="price.series")
        result = self._verify_with_approving_llm(action, evidence)
        self.assertFalse(result["sufficient"])

    def test_advisor_rejects_import_weight_as_import_amount(self):
        action = plan(call("r1", "trade.monthly", mineral="코발트",
                           metric="import_amount", flow="import")).actions[0]
        evidence = Evidence(kind="aggregated", source="KOMIS", section="월별 한국 수입중량",
                            text="| month | import_weight_kg |\n| --- | --- |\n| 2026-06 | 5572 |",
                            observed_period="2026-06-01~2026-09-09", unit="kg",
                            source_id="public.KO_CSTM_CMMRC", requirement_id="r1",
                            action_id="trade.monthly")
        result = self._verify_with_approving_llm(action, evidence)
        self.assertFalse(result["sufficient"])


if __name__ == "__main__":
    unittest.main()
