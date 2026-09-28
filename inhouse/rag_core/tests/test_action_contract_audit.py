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
from rag_core.retrieval.weekly_trend import _publication_date  # noqa: E402
from rag_core.ragkit.mcp_client import _ProfileSession  # noqa: E402
from rag_core.ragkit.source_contract import SourceAssessment  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


def plan(*actions):
    return ActionPlan(actions=list(actions))


def call(requirement_id, action_id, **slots):
    return {"requirement_id": requirement_id, "action_id": action_id, "slots": slots}


class ActionContractAuditTest(unittest.TestCase):
    def test_verified_daily_news_bypasses_general_advisor(self):
        """발행·기간·검색조건을 SQL로 확정한 뉴스 표를 LLM 기권으로 버리지 않는다."""
        action = ActionCall(
            requirement_id="publication_search", action_id="document.retrieve",
            slots=ActionSlots(topic="중국 수출통제 뉴스", period=Period(
                kind="range", start="2026-07-01", end="2026-08-31", explicit=True,
            )), intent="document", role="content",
        )
        evidence = Evidence(
            kind="structured", source="public.ko_daynews_raw + 반정형 보고서",
            section="일일 자원뉴스",
            text=("| 날짜 | 제목 | 요약 |\n|---|---|---|\n"
                  "| 2026-07-28 | 중국 수출통제 | 발행 기사 |"),
            as_of="2026-07-28~2026-08-24", requirement_id="publication_search",
            action_id="document.retrieve", source_id="public.ko_daynews_raw + 반정형 보고서",
            observed_period="2026-07-28~2026-08-24",
        )
        route = graph.RetrievalRoute(resolved_query="중국 수출통제 뉴스", use_structured=False,
                                     use_dense=False, use_pageindex=False, use_news=True)
        result = graph._verify_node({
            "evidence": [evidence], "warnings": [], "action_call": action,
            "route": route, "history": [],
        }, None)
        self.assertTrue(result["sufficient"])

    def test_monthly_document_mineral_absence_has_specific_user_message(self):
        from rag_core.ragkit.chatbot import _resolve_abstain
        reason, text = _resolve_abstain(
            "2026년 5월 희소금속 월간동향에서 니켈 관련 내용 찾아줘",
            ["monthly_trend_mineral_not_mentioned:니켈", "advisor_rejected"], None,
        )
        self.assertEqual(reason, "content_not_mentioned")
        self.assertEqual(text, "해당 월간동향 문서에는 니켈에 대한 언급이 없습니다.")
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

    def test_current_price_words_bypass_planner_as_latest_observation(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("금일 가격 질의는 planner를 호출하면 안 됩니다")

        for question, mineral in (
            ("금일 니켈 가격 알려줘", "니켈"),
            ("금일자 니켈 시세는 얼마야?", "니켈"),
            ("오늘 니켈 가격", "니켈"),
            ("현재 텅스텐 가격은 얼마야?", "텅스텐"),
            ("지금 금 시세 알려줘", "금"),
            ("현재 아연 가격 알려줘", "아연"),
            ("니켈 가격 얼마야?", "니켈"),
        ):
            with self.subTest(question=question, mineral=mineral):
                candidate = extract_action_plan(question, MustNotRun())
                call = candidate.actions[0]
                self.assertEqual((call.action_id, call.slots.mineral), ("price.series", mineral))
                self.assertEqual(call.slots.period.kind, "latest")
                route = _route_from_action_call(call, question)
                self.assertIsNone(route.komis_start_period)
                self.assertIsNone(route.komis_end_period)
                self.assertEqual(route.komis_raw_limit, 2)

    def test_current_price_shortcut_does_not_capture_multi_mineral_request(self):
        class Planner:
            def invoke(self, **kwargs):
                return SimpleNamespace(output=IntentPlan(requirements=[IntentCall(
                    requirement_id="compare", intent="price_compare", role="data",
                    slots=ActionSlots(minerals=["니켈", "리튬"]),
                )]))

        candidate = extract_action_plan("현재 니켈과 리튬 가격 알려줘", Planner())

        self.assertEqual(candidate.actions[0].action_id, "price.compare")

    def test_composite_index_closed_forms_keep_hi001_and_typed_operation(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("닫힌 종합지수 문형은 planner를 호출하면 안 됩니다")

        cases = (
            ("오늘 광물 종합지수 얼마야?", "latest_delta", "latest"),
            ("최근 3개월 광물종합지수 추세 알려줘", "period_change", "trailing_months"),
            ("광물 종합지수 올해 고점/저점은?", "period_extrema", "calendar_year"),
        )
        for question, operation, period_kind in cases:
            with self.subTest(question=question):
                candidate = extract_action_plan(question, MustNotRun())
                call = candidate.actions[0]
                self.assertEqual(call.action_id, "indicator.series")
                self.assertEqual(call.slots.indicator, "composite_index")
                self.assertEqual(call.slots.indicator_variant, "composite")
                self.assertEqual(call.slots.indicator_operation, operation)
                self.assertEqual(call.slots.period.kind, period_kind)
                self.assertTrue(validate_action_plan(candidate).approved)
                route = _route_from_action_call(call, question)
                self.assertEqual(route.komis_index_type_code, "HI001")

    def test_composite_index_operation_rejects_mixed_or_missing_variant(self):
        candidate = plan(ActionCall(
            requirement_id="bad", action_id="indicator.series",
            slots=ActionSlots(indicator="composite_index", indicator_operation="latest_delta",
                              period=Period(kind="latest")),
        ))
        self.assertEqual(validate_action_plan(candidate).failure_reason, "slot_unresolved")

    def test_forecast_closed_forms_preserve_output_operation_and_are_available(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("가격예측 문형은 planner를 호출하면 안 됩니다")

        for question, operation in (
            ("다음달 구리 가격 전망을 알려줘", "next_month_value"),
            ("니켈 가격 앞으로 오를까 내릴까?", "direction"),
        ):
            with self.subTest(question=question):
                candidate = extract_action_plan(question, MustNotRun())
                self.assertEqual(candidate.actions[0].action_id, "forecast.price")
                self.assertEqual(candidate.actions[0].slots.forecast_operation, operation)
                self.assertTrue(validate_action_plan(candidate).approved)

    def test_weekly_trend_document_plan_uses_dated_publication_adapter(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("주간동향 단일 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("이번주 비철금속 주간 동향 요약해줘", MustNotRun())
        self.assertEqual(candidate.actions[0].action_id, "document.retrieve")
        route = _route_from_action_call(candidate.actions[0], "이번주 비철금속 주간 동향 요약해줘")
        self.assertTrue(route.use_weekly_trend)
        self.assertEqual(_publication_date("20260616_주간 경제 비철금속 시장 동향.pdf").isoformat(), "2026-06-16")
        self.assertEqual(_publication_date("2026-06-16_주간광물동향_KOMIS.hwp").isoformat(), "2026-06-16")
        self.assertIsNone(_publication_date("주간 경제 비철금속 시장 동향.pdf"))

    def test_dated_weekly_trend_evidence_is_not_removed_by_period_filter(self):
        call = extract_action_plan("2026년 6월 16일 주간 자원뉴스 요약해줘", type("No", (), {
            "invoke": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("planner called")),
        })()).actions[0]
        evidence = [Evidence(kind="structured", source="KOMIS", section="주간 광물동향 게시물",
                             text="| 게시일 | 보고서 제목 |\n|---|---|\n| 2026-06-16 | 주간동향 |",
                             as_of="2026-06-16")]
        self.assertEqual(graph._filter_document_evidence_to_trailing_period(evidence, call), evidence)

    def test_monthly_followup_validation_keeps_its_confirmed_parent_requirement(self):
        parent = ActionCall(requirement_id="monthly_trend", action_id="document.retrieve",
                            slots=ActionSlots(topic="2026년 6월 전략광종 월간동향"),
                            intent="document", role="content")
        followup = ActionCall(requirement_id="monthly_info_니켈", action_id="document.retrieve",
                              slots=ActionSlots(mineral="니켈", topic="니켈 기본 정보"),
                              intent="document", role="content", depends_on=["monthly_trend"])
        self.assertTrue(validate_action_plan(ActionPlan(actions=[parent, followup])).approved)

    def test_mineral_basic_info_route_uses_structured_adapter(self):
        call = ActionCall(requirement_id="info", action_id="document.retrieve",
                          slots=ActionSlots(mineral="니켈", topic="니켈 기본 정보"),
                          intent="document", role="content")
        self.assertTrue(_route_from_action_call(call, "니켈 기본 정보").use_mineral_info)

    def test_index_co_rise_plan_keeps_index_and_five_price_series(self):
        candidate = extract_action_plan("광물지수 오를때 같이 오른 광종은 뭐야?", type("No", (), {
            "invoke": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("planner called")),
        })())
        self.assertEqual([call.action_id for call in candidate.actions],
                         ["indicator.series", "price.series", "price.series", "price.series", "price.series", "price.series"])
        self.assertEqual([call.slots.mineral for call in candidate.actions[1:]],
                         ["구리", "니켈", "코발트", "리튬", "희토류"])
        self.assertTrue(all(call.depends_on == ["composite_index_trend"] for call in candidate.actions[1:]))

    def test_yearly_monthly_document_content_query_keeps_calendar_year(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("연도 지정 월간동향 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("2026년 희소금속 월간동향에서 리튬 관련 내용 찾아줘", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual(call.action_id, "document.retrieve")
        self.assertEqual(call.slots.period.calendar_year, 2026)
        self.assertTrue(_route_from_action_call(call, "2026년 희소금속 월간동향에서 리튬 관련 내용 찾아줘").use_monthly_trend)

    def test_year_month_monthly_document_query_keeps_single_month_range(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("연월 지정 월간동향 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("2026년 5월 희소금속 월간동향에서 리튬 관련 내용 찾아줘", MustNotRun())
        period = candidate.actions[0].slots.period
        self.assertEqual((period.start, period.end), ("2026-05-01", "2026-05-31"))

    def test_year_month_rare_monthly_prices_keeps_single_month_range(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("연월 지정 희소금속 월간동향 가격 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("2026년 5월 희소금속 월간동향에 나온 광종들 가격 어때?", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual(call.requirement_id, "monthly_rare_metals")
        self.assertEqual((call.slots.period.start, call.slots.period.end), ("2026-05-01", "2026-05-31"))

    def test_price_operation_questions_keep_typed_period_and_operation(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("닫힌 가격 집계 문형은 planner를 호출하면 안 됩니다")

        cases = (
            ("니켈 가격 최근 3개월 평균이랑 비교하면 어때?", "price.series", "니켈", "period_average_delta", "trailing_months", 3),
            ("니켈 가격 몇 개월째 오르고 있어?", "price.series", "니켈", "monthly_streak", "latest", None),
            ("니켈 연도별 평균 가격 알려줘", "price.series", "니켈", "yearly_average", "latest", None),
            ("니켈과 리튬 가격 같이 비교해줘", "price.compare", None, None, "trailing_months", 12),
        )
        for question, action_id, mineral, operation, period_kind, months in cases:
            with self.subTest(question=question):
                candidate = extract_action_plan(question, MustNotRun())
                action = candidate.actions[0]
                self.assertEqual(action.action_id, action_id)
                self.assertEqual(action.slots.mineral, mineral)
                self.assertEqual(action.slots.price_operation, operation)
                self.assertEqual(action.slots.period.kind, period_kind)
                self.assertEqual(action.slots.period.trailing_months, months)
                route = _route_from_action_call(action, question)
                self.assertEqual(
                    route.use_komis_price_time_aggregate,
                    operation in {"monthly_streak", "yearly_average"},
                )

    def test_user_qa_price_and_geography_variants_bypass_planner(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("닫힌 사용자 Q&A 문형은 planner를 호출하면 안 됩니다")

        cases = (
            ("니켈 수입 상위국이랑 현재가격 알려줘", ["trade.country_rank", "price.series"]),
            ("니켈은 어디에 쓰이고 지금 가격은 얼마야?", ["document.retrieve", "price.series"]),
            ("최근 니켈 가격 얼마야?", ["price.series"]),
            ("니켈 가격 년도별 평균 가격을 알려줘", ["price.series"]),
            ("니켈 텅스텐 가격 같이 비교해줘", ["price.compare"]),
        )
        for question, action_ids in cases:
            with self.subTest(question=question):
                candidate = extract_action_plan(question, MustNotRun())
                self.assertEqual([call.action_id for call in candidate.actions], action_ids)
                self.assertTrue(validate_action_plan(candidate).approved)
        latest = extract_action_plan("최근 니켈 가격 얼마야?", MustNotRun()).actions[0]
        self.assertEqual((latest.slots.mineral, latest.slots.period.kind), ("니켈", "latest"))
        yearly = extract_action_plan("니켈 가격 년도별 평균 가격을 알려줘", MustNotRun()).actions[0]
        self.assertEqual(yearly.slots.price_operation, "yearly_average")
        comparison = extract_action_plan("니켈 텅스텐 가격 같이 비교해줘", MustNotRun()).actions[0]
        self.assertEqual(comparison.slots.minerals, ["니켈", "텅스텐"])

    def test_price_volatility_route_does_not_duplicate_top_n(self):
        candidate = extract_action_plan(
            "이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘",
            type("MustNotRun", (), {"invoke": lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())})(),
        )
        route = _route_from_action_call(candidate.actions[0], "이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘")
        self.assertTrue(route.use_komis_price_volatility_ranking)
        self.assertEqual(route.komis_ranking_top_n, 5)

    def test_user_qa_period_defaults_bypass_planner(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("기간이 닫힌 사용자 Q&A 문형은 planner를 호출하면 안 됩니다")

        cases = (
            ("이번 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘", "price.volatility_rank", "range"),
            ("이번달 희소금속 월간 동향에 나온 광종들 가격 어때?", "document.retrieve", "range"),
            ("광물종합지수 구성 광종 중 상승 전망인 건 뭐야?", "document.retrieve", "trailing_months"),
            ("수입 의존도 높은 광종들 가격 전망 알려줘", "document.retrieve", "trailing_months"),
        )
        for question, action_id, period_kind in cases:
            with self.subTest(question=question):
                candidate = extract_action_plan(question, MustNotRun())
                self.assertEqual([call.action_id for call in candidate.actions], [action_id])
                self.assertEqual(candidate.actions[0].slots.period.kind, period_kind)
                self.assertTrue(validate_action_plan(candidate).approved)

    def test_price_operation_rejects_invalid_action_or_period(self):
        for action_id, operation, period in (
            ("price.compare", "monthly_streak", Period(kind="latest")),
            ("price.series", "monthly_streak", Period(kind="trailing_months", trailing_months=3)),
            ("price.series", "period_average_delta", Period(kind="latest")),
        ):
            with self.subTest(action_id=action_id, operation=operation):
                candidate = ActionPlan(actions=[ActionCall(
                    requirement_id="price", action_id=action_id,
                    slots=ActionSlots(mineral="니켈", period=period, price_operation=operation),
                )])
                self.assertFalse(validate_action_plan(candidate).approved)

    def test_raw_lookup_converts_iso_action_range_only_at_mcp_boundary(self):
        session = object.__new__(_ProfileSession)
        captured = {}
        session._call = lambda _name, args: (captured.update(args) or {"evidence": [], "warnings": []})
        session.call_komis_raw_lookup("price_base_metals", start_period="1900-01-01", end_period="2026-09-27")
        self.assertEqual((captured["start_period"], captured["end_period"]), ("19000101", "20260927"))

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
        # 월간동향에 실제로 언급된 광종을 원천에서 확인하기 전에는 "희소금속"을
        # 단일 가격 광종으로 추정하지 않는다. 최신 월간 문서 Action이 먼저다.
        self.assertEqual([call.action_id for call in price_followup.actions], ["document.retrieve"])

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

    def test_price_time_aggregate_resolves_every_requested_mineral_before_mcp_call(self):
        received: list[tuple[str, str]] = []

        class Session:
            def call_komis_resolve_mineral(self, name):
                return {"mineral_code": {"니켈": "MNRL0002", "구리": "MNRL0003"}[name],
                        "price_category": None, "warnings": []}

            def call_komis_price_time_aggregate(self, mineral_code, operation):
                received.append((mineral_code, operation))
                return [Evidence(kind="structured", source="KOMIS", section="연도별 평균 가격",
                                 text="| price_date | price | observation_months |\n|---|---|---|\n| 20250101 | 1 | 12 |")], []

        for mineral, expected_code in (("니켈", "MNRL0002"), ("구리", "MNRL0003")):
            with self.subTest(mineral=mineral):
                route = graph.RetrievalRoute(
                    resolved_query=f"{mineral} 연도별 평균 가격", use_structured=False,
                    use_dense=False, use_pageindex=False, use_komis_price_time_aggregate=True,
                    komis_price_operation="yearly_average", komis_mineral_name=mineral,
                )
                with patch.object(graph.mcp_client, "public", Session()):
                    result = graph._retrieve_node(
                        {"route": route, "question": route.resolved_query, "profile": "public", "warnings": [],
                         "action_assessment": graph.PlanAssessment(approved=True),
                         "source_assessment": SourceAssessment()}, dense_k=1, pageindex_k=1,
                    )
                self.assertEqual(len(result["evidence"]), 1)
                self.assertIn((expected_code, "yearly_average"), received)

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

    def test_explicit_year_country_dependency_does_not_request_period_clarification(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("명시 연도·국가 의존도는 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("2025년 한국 리튬 수입의 중국 의존도를 계산해줘", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual(call.action_id, "trade.indicator")
        self.assertEqual(call.slots.period.kind, "calendar_year")
        self.assertEqual(call.slots.period.calendar_year, 2025)
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_explicit_year_rca_preserves_all_required_slots_without_llm(self):
        class MustNotRun:
            def invoke(self, **kwargs):
                raise AssertionError("명시 연도 RCA는 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("2025년 한국 리튬의 현시비교우위지수 RCA를 계산해줘", MustNotRun())
        call = candidate.actions[0]
        self.assertEqual((call.action_id, call.slots.trade_metric), ("trade.indicator", "rca"))
        self.assertEqual(call.slots.reporter_country, "한국")
        self.assertEqual(call.slots.period.calendar_year, 2025)
        self.assertEqual(missing_trade_indicator_slots(call), ())

    def test_explicit_year_monthly_trade_overrides_untyped_trailing_period(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="monthly", intent="trade_monthly", role="data",
            slots=ActionSlots(mineral="리튬", period=Period(kind="trailing_months", trailing_months=12)),
        )]), "2025년 한국 리튬 수입금액 월별 추이")
        call = candidate.actions[0]
        self.assertEqual(call.action_id, "trade.monthly")
        self.assertEqual(call.slots.period.kind, "calendar_year")
        self.assertEqual(call.slots.period.calendar_year, 2025)
        route = _route_from_action_call(call, "2025년 한국 리튬 수입금액 월별 추이")
        self.assertEqual((route.komis_start_period, route.komis_end_period), ("2025", "2025"))

    def test_multi_year_monthly_trade_uses_closed_explicit_range(self):
        candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="monthly", intent="trade_monthly", role="data",
            slots=ActionSlots(mineral="리튬"),
        )]), "2024년과 2025년 한국 리튬 수입금액 월별 추이")
        period = candidate.actions[0].slots.period
        self.assertEqual((period.kind, period.start, period.end), ("range", "20240101", "20251231"))
        self.assertTrue(period.explicit)

    def test_explicit_monthly_trade_range_is_preserved(self):
        period = Period(kind="range", start="20250101", end="20251231", explicit=True)
        candidate = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="monthly", intent="trade_monthly", role="data",
            slots=ActionSlots(mineral="리튬", period=period),
        )]), "2025년 한국 리튬 수입금액 월별 추이")
        self.assertEqual(candidate.actions[0].slots.period, period)

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

    def test_price_trend_and_composite_index_are_routed_as_same_period_actions(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 복합 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan(
            "최근 6개월 니켈 가격 추이랑 광물 종합지수 추세 비교해주세요", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions], ["price.series", "indicator.series"])
        self.assertEqual(candidate.actions[0].slots.mineral, "니켈")
        self.assertEqual(candidate.actions[0].slots.period.trailing_months, 6)
        self.assertEqual(candidate.actions[1].slots.indicator, "composite_index")
        self.assertEqual(candidate.actions[1].slots.indicator_variant, "composite")
        self.assertEqual(candidate.actions[1].slots.indicator_operation, "period_change")
        self.assertEqual(candidate.actions[1].slots.period.trailing_months, 6)
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_export_control_country_share_starts_with_verified_news_only(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("기사 광종은 뉴스 근거에서 확인해야 합니다")

        candidate = extract_action_plan(
            "중국 수출통제 뉴스에 나온 광종 중국 수입 비중 알려줘", UnexpectedPlanner())
        self.assertEqual(len(candidate.actions), 1)
        self.assertEqual(candidate.actions[0].requirement_id, "export_control_news")
        self.assertEqual(candidate.actions[0].action_id, "document.retrieve")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_mineral_use_and_import_countries_are_two_actions(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 복합 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("망간 용도랑 주요 수입국 알려줘", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions], ["document.retrieve", "trade.country_rank"])
        self.assertEqual(candidate.actions[1].slots.trade_scope, "korea")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_current_price_and_next_month_forecast_are_two_actions(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 복합 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("니켈 현재 가격이랑 다음달 전망 같이 알려줘", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions], ["price.series", "forecast.price"])
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_forecast_and_recent_mineral_news_are_two_actions(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 복합 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan(
            "리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions],
                         ["forecast.price", "document.retrieve"])
        self.assertEqual(candidate.actions[0].slots.mineral, "리튬")
        self.assertEqual(candidate.actions[1].slots.topic, "최근 리튬 자원뉴스")
        self.assertEqual(candidate.actions[1].slots.period.trailing_months, 3)
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_significant_price_news_uses_configured_or_explicit_threshold(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 가격 변동 문형은 planner를 호출하면 안 됩니다")

        configured = extract_action_plan("니켈 가격 크게 오른 날 관련 뉴스 있어?", UnexpectedPlanner())
        self.assertEqual(configured.actions[0].slots.price_operation, "significant_daily_rise")
        self.assertEqual(configured.actions[0].slots.significant_change_pct, 5.0)
        explicit = extract_action_plan("니켈 가격 8% 이상 오른 날 관련 뉴스 있어?", UnexpectedPlanner())
        self.assertEqual(explicit.actions[0].slots.significant_change_pct, 8.0)

    def test_composite_index_down_week_starts_with_index_observations(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 지수 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions], ["indicator.series"])
        self.assertEqual(candidate.actions[0].slots.period.trailing_months, 3)
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_weekly_price_news_starts_with_volatility_rank(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 가격 변동 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("지난 주 가격 변동 큰 광종이랑 관련 뉴스 보여줘", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions], ["price.volatility_rank"])
        self.assertEqual(candidate.actions[0].slots.period.kind, "range")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_import_countries_and_price_forecast_are_two_actions(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 수입국·예측 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("리튬 주요 수입국이랑 가격 전망 같이 보여줘", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in candidate.actions], ["trade.country_rank", "forecast.price"])
        self.assertEqual(candidate.actions[0].slots.trade_scope, "korea")
        self.assertTrue(validate_action_plan(candidate).approved)

    def test_price_forecast_timeline_and_current_comparison_are_closed_plans(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("닫힌 가격·예측 문형은 planner를 호출하면 안 됩니다")

        timeline = extract_action_plan("니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘", UnexpectedPlanner())
        self.assertEqual([item.action_id for item in timeline.actions], ["price.series", "forecast.price"])
        self.assertEqual(timeline.actions[0].slots.period.trailing_months, 6)
        self.assertEqual(timeline.actions[1].slots.forecast_operation, "timeline")
        comparison = extract_action_plan("니켈 지금 가격이 전망치 보다 높은 편이야?", UnexpectedPlanner())
        self.assertEqual(comparison.actions[1].slots.forecast_operation, "compare_current")
        self.assertTrue(validate_action_plan(timeline).approved)
        self.assertTrue(validate_action_plan(comparison).approved)

    def test_battery_five_price_overview_uses_yaml_group(self):
        class UnexpectedPlanner:
            def invoke(self, **_kwargs):
                raise AssertionError("YAML 가격 그룹 문형은 planner를 호출하면 안 됩니다")

        candidate = extract_action_plan("2차전지 광물 5종 가격이랑 현황 한 번에 보여줘", UnexpectedPlanner())
        self.assertEqual(candidate.actions[0].action_id, "price.overview")
        self.assertEqual(candidate.actions[0].slots.strategic_price_groups, ["battery_five"])
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
