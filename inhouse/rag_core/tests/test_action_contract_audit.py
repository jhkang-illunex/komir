# -*- coding: utf-8 -*-
"""설계 문서와 기존 챗봇 요구를 기준으로 한 독립 action 계약 검수."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import (  # noqa: E402
    ActionCall, ActionPlan, IntentCall, IntentPlan, ActionSlots, Period, action_plan_from_intent,
    extract_action_plan, missing_trade_indicator_slots, validate_action_plan,
)
from rag_core.ragkit.chatbot_graph import _route_from_action_plan, _route_from_action_call  # noqa: E402
from rag_core.ragkit import chatbot_graph as graph  # noqa: E402
from rag_core.ragkit.mcp_client import _ProfileSession  # noqa: E402
from rag_core.ragkit.source_contract import SourceAssessment  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


def plan(*actions):
    return ActionPlan(actions=list(actions))


def call(requirement_id, action_id, **slots):
    return {"requirement_id": requirement_id, "action_id": action_id, "slots": slots}


class ActionContractAuditTest(unittest.TestCase):
    def test_world_trade_rank_routes_to_global_source_without_korea_substitution(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="rank", intent="trade_rank", role="data",
            slots=ActionSlots(mineral="리튬", flow="export", metric="export_amount"),
        )]), "세계 리튬 수출 상위국은 어디야?")
        call = candidate.actions[0]
        self.assertEqual(call.slots.trade_scope, "global")
        route = _route_from_action_call(call, "세계 리튬 수출 상위국은 어디야?")
        self.assertEqual(route.komis_ranking_page, "map_global")
        self.assertEqual(route.komis_ranking_metric, "export_amount")

    def test_korea_trade_rank_keeps_korea_source(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="rank", intent="trade_rank", role="data",
            slots=ActionSlots(mineral="리튬", flow="import", metric="import_amount"),
        )]), "우리나라 리튬 수입 상위국은 어디야?")
        route = _route_from_action_call(candidate.actions[0], "우리나라 리튬 수입 상위국은 어디야?")
        self.assertEqual(route.komis_ranking_page, "map_korea")

    def test_country_share_without_world_overrides_planner_global_scope(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="rank", intent="trade_rank", role="data",
            slots=ActionSlots(mineral="리튬", flow="import", metric="import_amount",
                              trade_scope="global"),
        )]), "리튬 수입 상위 5개국과 국가별 비중을 알려줘")
        call = candidate.actions[0]
        self.assertEqual(call.slots.trade_scope, "korea")
        self.assertEqual(
            _route_from_action_call(call, "리튬 수입 상위 5개국과 국가별 비중을 알려줘").komis_ranking_page,
            "map_korea",
        )

    def test_trade_rank_followup_preserves_inherited_global_scope(self):
        for question in (
            "같은 순위를 최근 2년으로 다시 보여줘",
            "최근 2년으로 바꿔줘",
            "그럼 최근 6개월은?",
            "표로 보여줘",
        ):
            with self.subTest(question=question):
                candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
                    requirement_id="rank", intent="trade_rank", role="data",
                    slots=ActionSlots(mineral="리튬", flow="export", metric="export_amount",
                                      trade_scope="global"),
                )]), question)
                self.assertEqual(candidate.actions[0].slots.trade_scope, "global")

    def test_future_actual_price_is_deterministically_source_unavailable(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("future actual-price query must not call the planner")

        candidate = extract_action_plan(
            "2030년 리튬 실제 월별 가격을 차트로 보여줘. 아직 없는 실측 자료라면 없다고 알려줘.",
            MustNotRun(),
        )
        self.assertEqual(candidate.actions[0].action_id, "price.series")
        self.assertEqual(candidate.actions[0].slots.period.kind, "future_horizon")
        self.assertEqual(validate_action_plan(candidate).failure_reason, "source_unavailable")

    def test_mine_yoy_rank_is_deterministic_before_planner(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("완결된 광산 YoY 순위는 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("구리 광산 생산량 최근 YoY 증가 상위 5개를 보여줘", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual((call.action_id, call.slots.mineral, call.slots.mine_metric,
                          call.slots.mine_order, call.slots.top_n),
                         ("mine.rank", "구리", "production", "yoy_increase", 5))
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_standalone_monthly_and_news_queries_bypass_llm_as_document_actions(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("publication query must not call the planner")

        cases = (
            ("이번 달 전략광종 월간동향 요약해줘", "range"),
            ("오늘 자원뉴스 뭐 있어?", "range"),
            ("이번 주 주간자원뉴스 요약해줘", "range"),
            ("최근 중국 수출통제 관련 뉴스 있어?", "trailing_months"),
            ("최근 3개월 월간동향에서 리튬 관련 내용 찾아줘", "trailing_months"),
        )
        for question, period_kind in cases:
            with self.subTest(question=question):
                candidate = extract_action_plan(question, MustNotRun())
                self.assertEqual([call.action_id for call in candidate.actions], ["document.retrieve"])
                self.assertEqual(candidate.actions[0].slots.period.kind, period_kind)

    def test_dated_publication_content_bypasses_planner_as_explicit_lookup(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("발행일이 적힌 단일 문서 확인은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan(
            "2026년 6월 16일 주간 경제 비철금속 시장 동향 내용을 알려줘", MustNotRun(),
        )
        self.assertEqual([call.action_id for call in candidate.actions], ["document.lookup"])
        self.assertEqual(candidate.actions[0].slots.topic,
                         "2026년 6월 16일 주간 경제 비철금속 시장 동향 내용을 알려줘")

    def test_publication_shortcut_preserves_compound_and_navigation_requests(self):
        class Planner:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=IntentPlan(requirements=[IntentCall(
                    requirement_id="price", intent="price_series", role="data",
                    slots=ActionSlots(mineral="니켈"),
                )]))

        compound = extract_action_plan("월간동향 요약하고 니켈 현재 가격 알려줘", Planner())
        self.assertEqual([call.action_id for call in compound.actions], ["price.series"])
        navigation = extract_action_plan("월간동향 게시판으로 이동해줘", Planner())
        self.assertEqual([call.action_id for call in navigation.actions], ["price.series"])
        price_followup = extract_action_plan(
            "이번 달 희소금속 월간동향에 나온 광종들 가격 어때?", Planner(),
        )
        self.assertEqual([call.action_id for call in price_followup.actions], ["price.series"])

    def test_publication_shortcut_preserves_year_periods(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("publication query must not call the planner")

        recent = extract_action_plan("최근 1년 월간동향 요약해줘", MustNotRun())
        self.assertEqual(recent.actions[0].slots.period.trailing_months, 12)
        annual = extract_action_plan("2025년 월간동향 요약해줘", MustNotRun())
        self.assertEqual(annual.actions[0].slots.period.calendar_year, 2025)
        latest = extract_action_plan("최근 희소금속 월간동향 보고서 제목 알려줘", MustNotRun())
        self.assertIsNone(latest.actions[0].slots.period)

    def test_mixed_world_resource_and_korea_trade_requires_requirement_scope(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[
            IntentCall(requirement_id="world", intent="resource_rank", role="data",
                       slots=ActionSlots(mineral="코발트", metric="production")),
            IntentCall(requirement_id="korea", intent="trade_rank", role="data",
                       slots=ActionSlots(mineral="코발트", flow="import", metric="import_amount")),
        ]), "코발트 세계 생산국이랑 우리나라 수입국 비교해줘")
        trade = next(call for call in candidate.actions if call.action_id == "trade.country_rank")
        self.assertIsNone(trade.slots.trade_scope)
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_unresolved")
        trade.slots.trade_scope = "korea"
        self.assertTrue(validate_action_plan(candidate).approved)
        self.assertEqual(_route_from_action_call(trade, "질문").komis_ranking_page, "map_korea")

    def test_mixed_korea_monthly_and_world_rank_does_not_inherit_korea(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[
            IntentCall(requirement_id="monthly", intent="trade_monthly", role="data",
                       slots=ActionSlots(mineral="니켈", metric="import_amount")),
            IntentCall(requirement_id="world", intent="trade_rank", role="data",
                       slots=ActionSlots(mineral="리튬", flow="export", metric="export_amount")),
        ]), "한국 니켈 수입금액 월별 추이와 세계 리튬 수출 상위국을 보여줘")
        trade = next(call for call in candidate.actions if call.action_id == "trade.country_rank")
        self.assertIsNone(trade.slots.trade_scope)
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_unresolved")

    def test_two_trade_rank_requirements_need_requirement_level_scopes(self):
        candidate = ActionPlan(actions=[
            ActionCall(requirement_id="world", action_id="trade.country_rank",
                       slots=ActionSlots(mineral="리튬", flow="export", metric="export_amount")),
            ActionCall(requirement_id="korea", action_id="trade.country_rank",
                       slots=ActionSlots(mineral="니켈", flow="import", metric="import_amount")),
        ])
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_unresolved")

    def test_complex_publication_periods_are_left_to_planner(self):
        class Planner:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=IntentPlan(requirements=[IntentCall(
                    requirement_id="doc", intent="document", role="content",
                    slots=ActionSlots(topic=kwargs["payload"]["question"]),
                )]))

        for question in (
            "2025년 1월부터 3월까지 월간동향 요약해줘",
            "지난달 전략광종 월간동향 요약해줘",
        ):
            with self.subTest(question=question):
                candidate = extract_action_plan(question, Planner())
                self.assertEqual(candidate.actions[0].slots.topic, question)

    def test_explicit_document_range_filters_old_and_unknown_dates(self):
        action = plan(call("news", "document.retrieve", topic="오늘 자원뉴스",
                           period={"kind": "range", "start": "2026-09-27",
                                   "end": "2026-09-27", "explicit": True})).actions[0]
        today = Evidence(kind="pageindex", source="today", section="뉴스", text="내용",
                         as_of="2026-09-27")
        old = Evidence(kind="pageindex", source="old", section="뉴스", text="내용",
                       as_of="2025-06-10")
        unknown = Evidence(kind="pageindex", source="unknown", section="뉴스", text="내용")
        self.assertEqual(graph._filter_document_evidence_to_trailing_period(
            [today, old, unknown], action), [today])

    def test_statistical_year_does_not_filter_by_document_publication_year(self):
        action = plan(call("analysis", "document.retrieve", topic="2025년 리튬 생산량 설명",
                           period={"kind": "calendar_year", "calendar_year": 2025,
                                   "explicit": True})).actions[0]
        published_later = Evidence(kind="pageindex", source="USGS_2026", section="리튬",
                                   text="2025년 생산량", as_of="2026-01-31")
        self.assertEqual(graph._filter_document_evidence_to_trailing_period(
            [published_later], action), [published_later])

    def test_requested_monthly_frequency_is_preserved_without_misreading_monthly_news(self):
        intent_plan = IntentPlan(requirements=[IntentCall(
            requirement_id="r1", intent="price_series", role="data",
            slots=ActionSlots(mineral="리튬", period=Period(
                kind="trailing_months", trailing_months=12, explicit=True,
            )),
        )])
        monthly = action_plan_from_intent(intent_plan, "최근 1년 리튬 가격 월별 추이")
        self.assertEqual(monthly.actions[0].slots.period.frequency, "monthly")

        news_plan = IntentPlan(requirements=[IntentCall(
            requirement_id="r1", intent="price_series", role="data",
            slots=ActionSlots(mineral="리튬", period=Period(
                kind="trailing_months", trailing_months=12, explicit=True,
            )),
        )])
        news = action_plan_from_intent(news_plan, "최근 월간동향에서 리튬 가격 관련 내용")
        self.assertIsNone(news.actions[0].slots.period.frequency)

    def test_requested_period_rejects_out_of_year_and_disjoint_same_year_evidence(self):
        action = plan(call("r1", "price.series", mineral="니켈", period=Period(
            kind="calendar_year", calendar_year=2025, explicit=True,
        ))).actions[0]
        def evidence(period):
            return Evidence(kind="structured", source="public.KO_MNRL_PRC", section="니켈",
                            text="| date | price |\n| --- | --- |\n| 2025-01-01 | 1 |",
                            observed_period=period, requirement_id="r1", action_id="price.series")

        self.assertTrue(graph._evidence_matches_required_period(
            [evidence("2025-07-01~2025-12-31")], action,
        ))
        self.assertFalse(graph._evidence_matches_required_period(
            [evidence("2025-07-01~2026-02-01")], action,
        ))
        range_action = plan(call("r1", "price.series", mineral="니켈", period=Period(
            kind="range", start="2025-01-01", end="2025-03-31", explicit=True,
        ))).actions[0]
        self.assertFalse(graph._evidence_matches_required_period(
            [evidence("2025-07-01~2025-09-30")], range_action,
        ))

    def test_unverified_komis_evidence_is_fail_closed_but_dummy_is_returned(self):
        action = plan(call("r1", "price.series", mineral="니켈")).actions[0]
        for caveat in (graph.KOMIS_RAW_DUMMY_CAVEAT, graph.KOMIS_RAW_UNVERIFIED_CAVEAT):
            evidence = Evidence(kind="structured", source="public.KO_MNRL_PRC", section="가격",
                                text="| date | price |\n| --- | --- |\n| 2026-01-01 | 1 |",
                                caveat=caveat, menu_page_id="price_base_metals")
            with self.subTest(caveat=caveat), patch.object(
                graph, "_retrieve_node", return_value={"evidence": [evidence], "warnings": []},
            ), patch.object(
                graph, "_verify_node", return_value={"sufficient": True, "evidence": [evidence], "warnings": []},
            ):
                retrieved, warnings = graph.retrieve_evidence(
                    "니켈 가격 알려줘", action_plan=plan(action), llm=object(),
                )
            if caveat == graph.KOMIS_RAW_DUMMY_CAVEAT:
                self.assertTrue(retrieved)
                self.assertNotIn("source_unavailable:komis_data_provenance_unverified", warnings)
            else:
                self.assertEqual(retrieved, [])
                self.assertIn("source_unavailable:komis_data_provenance_unverified", warnings)

    def test_frequency_contract_accepts_finer_data_and_rejects_coarser_data(self):
        action = plan(call("r1", "price.series", mineral="리튬", period=Period(
            kind="trailing_months", trailing_months=12, frequency="monthly", explicit=True,
        ))).actions[0]
        daily = Evidence(kind="structured", source="public.KO_MNRL_PRC", section="리튬",
                         text="| crtr_ymd(기준일자) | cmerc_prc(통상가격) |\n| --- | --- |\n"
                              "| 20260701 | 1 |\n| 20260702 | 2 |")
        yearly = Evidence(kind="structured", source="public.KO_MNRL_PRC", section="리튬",
                          text="| year(연도) | cmerc_prc(통상가격) |\n| --- | --- |\n| 2025 | 1 |")
        self.assertTrue(graph._evidence_matches_requested_frequency([daily], action))
        self.assertFalse(graph._evidence_matches_requested_frequency([yearly], action))

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
            denominator_scope="reporter_product_trade",
            period={"kind": "calendar_year", "calendar_year": 2025, "explicit": True},
        ))
        self.assertTrue(validate_action_plan(candidate).approved)
        route = _route_from_action_plan(candidate, "2025년 한국의 중국산 리튬 수입 의존도")
        self.assertTrue(route.use_komis_trade_indicator)
        self.assertEqual(route.komis_trade_metric, "country_dependency")
        self.assertEqual(route.komis_partner_country, "중국")

    def test_trailing_country_dependency_forwards_range_and_denominator_to_mcp(self):
        received: dict[str, object] = {}

        class Session:
            def call_komis_resolve_mineral(self, _name):
                return {"mineral_code": "MNRL0005", "price_category": None, "warnings": []}

            def call_komis_trade_indicator(self, **kwargs):
                received.update(kwargs)
                return [Evidence(kind="structured", source="KOMIS", section="의존도", text="근거")], []

        route = graph.RetrievalRoute(
            resolved_query="흑연 중국 수입 비중", use_structured=False, use_dense=False, use_pageindex=False,
            use_komis_trade_indicator=True, komis_trade_metric="country_dependency",
            komis_reporter_country="한국", komis_partner_country="중국", komis_trade_flow="import",
            komis_dependency_denominator="reporter_product_trade", komis_mineral_name="흑연",
            komis_relative_months=3,
        )
        with patch.object(graph.mcp_client, "public", Session()):
            result = graph._retrieve_node({"route": route, "question": "흑연 수입 중 중국 비중 최근 3개월",
                                           "profile": "public", "warnings": [],
                                           "action_assessment": graph.PlanAssessment(approved=True),
                                           "source_assessment": SourceAssessment()},
                                          dense_k=1, pageindex_k=1)
        self.assertEqual(len(result["evidence"]), 1)
        self.assertEqual(received["denominator_scope"], "reporter_product_trade")
        self.assertEqual(received["mineral_code"], "MNRL0005")
        self.assertRegex(str(received["start_period"]), r"^\d{8}$")
        self.assertRegex(str(received["end_period"]), r"^\d{8}$")
        self.assertNotIn("calendar_year", received)

    def test_fallback_country_share_question_fills_dependency_slots_without_llm(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("specific-country share must use deterministic trade plan")

        candidate = extract_action_plan("흑연 수입 중 중국 비중 얼마야?", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual(call.action_id, "trade.indicator")
        self.assertEqual(call.slots.trade_metric, "country_dependency")
        self.assertEqual(call.slots.reporter_country, "한국")
        self.assertEqual(call.slots.partner_country, "중국")
        self.assertEqual(call.slots.flow, "import")
        self.assertEqual(call.slots.period.trailing_months, 12)
        self.assertEqual(call.slots.denominator_scope, "reporter_product_trade")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_strategic_price_overview_uses_closed_yaml_group_action_without_llm(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("전략광종 단일 가격 현황은 LLM을 호출하면 안 됩니다.")

        candidate = extract_action_plan("전략광종 가격 현황 한눈에 보여줘", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual(call.action_id, "price.overview")
        self.assertEqual(call.slots.strategic_price_groups, ["strategic_six", "strategic_ten"])
        self.assertTrue(validate_action_plan(candidate).approved)
        route = _route_from_action_plan(candidate, "전략광종 가격 현황 한눈에 보여줘")
        self.assertTrue(route.use_komis_strategic_price_overview)
        self.assertEqual(route.komis_strategic_price_groups, ["strategic_six", "strategic_ten"])

    def test_strategic_price_overview_rejects_duplicate_or_mineral_override(self):
        candidate = plan(call("overview", "price.overview", strategic_price_groups=["strategic_six", "strategic_six"]))
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_unresolved")
        overridden = plan(call("overview", "price.overview", strategic_price_groups=["strategic_six"], mineral="니켈"))
        self.assertEqual(validate_action_plan(overridden).failure_reason, "slot_unresolved")

    def test_country_share_shortcut_does_not_capture_rank_or_compound_question(self):
        class RecordingLlm:
            def __init__(self):
                self.calls = 0

            def invoke(self, **kwargs):
                self.calls += 1
                return SimpleNamespace(output=IntentPlan(requirements=[IntentCall(
                    requirement_id="rank", intent="trade_rank", role="data",
                    slots=ActionSlots(mineral="리튬", flow="import"),
                )]))

        llm = RecordingLlm()
        candidate = extract_action_plan("한국의 리튬 수입 상위국과 국가별 비중", llm)
        self.assertEqual(llm.calls, 1)
        self.assertEqual(candidate.actions[0].action_id, "trade.country_rank")

    def test_country_share_shortcut_rejects_non_single_partner_tokens(self):
        class RecordingLlm:
            def __init__(self):
                self.calls = 0

            def invoke(self, **kwargs):
                self.calls += 1
                return SimpleNamespace(output=IntentPlan(requirements=[IntentCall(
                    requirement_id="rank", intent="trade_rank", role="data",
                    slots=ActionSlots(mineral="흑연", flow="import"),
                )]))

        llm = RecordingLlm()
        for question in (
            "흑연 수입 중 국가별 비중 알려줘",
            "흑연 수입 중 중국과 미국 비중 알려줘",
        ):
            with self.subTest(question=question):
                candidate = extract_action_plan(question, llm)
                self.assertEqual(candidate.actions[0].action_id, "trade.country_rank")
        self.assertEqual(llm.calls, 2)

    def test_legacy_country_dependency_defaults_denominator_without_new_hitl(self):
        candidate = plan(call(
            "legacy", "trade.indicator", trade_metric="country_dependency", mineral="리튬",
            reporter_country="한국", partner_country="중국", flow="import",
            period={"kind": "calendar_year", "calendar_year": 2025, "explicit": True},
        ))
        self.assertTrue(validate_action_plan(candidate).approved)
        self.assertEqual(candidate.actions[0].slots.denominator_scope, "reporter_product_trade")

    def test_non_dependency_trailing_period_remains_hitl(self):
        candidate = plan(call(
            "tsi", "trade.indicator", trade_metric="tsi", mineral="리튬", reporter_country="한국",
            period={"kind": "trailing_months", "trailing_months": 3, "explicit": True},
        ))
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_required")

    def test_specific_country_dependency_normalizes_from_typed_concentration_to_indicator(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="r1", intent="trade_concentration", role="data",
            slots=ActionSlots(mineral="리튬"),
        )])
        candidate = action_plan_from_intent(
            intents, "2025년 한국 리튬 수입의 중국 의존도를 계산해줘",
        )
        self.assertEqual(len(candidate.actions), 1)
        call = candidate.actions[0]
        self.assertEqual(call.action_id, "trade.indicator")
        self.assertEqual(call.slots.trade_metric, "country_dependency")
        self.assertEqual(call.slots.partner_country, "중국")
        self.assertEqual(call.slots.flow, "import")
        self.assertEqual(call.slots.reporter_country, "한국")
        self.assertEqual(call.slots.period.calendar_year, 2025)
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_hhi_concentration_without_partner_remains_concentration(self):
        intents = IntentPlan(requirements=[IntentCall(
            requirement_id="r1", intent="trade_concentration", role="data",
            slots=ActionSlots(mineral="리튬", flow="import"),
        )])
        candidate = action_plan_from_intent(intents, "2025년 한국 리튬 수입 집중도 HHI를 계산해줘")
        self.assertEqual(candidate.actions[0].action_id, "trade.concentration")
        self.assertIsNone(candidate.actions[0].slots.partner_country)

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

    def test_composite_metric_contract_uses_two_scalar_actions(self):
        """metrics[]가 아니라 requirement별 scalar metric이 공개 계약이다."""
        class Planner:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=IntentPlan(requirements=[
                    IntentCall(requirement_id="production", intent="resource_rank", role="data",
                               slots=ActionSlots(mineral="희토류", metric="production", top_n=5)),
                    IntentCall(requirement_id="reserves", intent="resource_rank", role="data",
                               slots=ActionSlots(mineral="희토류", metric="reserves", top_n=5)),
                ]))

        candidate = extract_action_plan("희토류 생산량과 매장량 상위 5개국을 알려줘", Planner())
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
