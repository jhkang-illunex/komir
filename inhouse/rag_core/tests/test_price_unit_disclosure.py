# -*- coding: utf-8 -*-
"""가격 원천 내부 코드가 본문과 인용 메타데이터로 새지 않는지 검사한다."""
import unittest
from types import SimpleNamespace

from rag_core.ragkit import chatbot
from rag_core.ragkit.renderers.price import (
    latest_price_display_table,
    render_price_comparison,
    render_price_series,
)
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from rag_core.retrieval.evidence import Evidence


def _render_price_series(evidence, action_plan):
    return render_price_series(evidence, action_plan)


class PriceUnitDisclosureTest(unittest.TestCase):
    def test_dummy_price_status_is_not_rendered_as_price_basis(self):
        evidence = Evidence(
            kind="structured", source="public.KO_MNRL_PRC", section="가격",
            text="| date | price |\n| --- | --- |\n| 2026-01-01 | 1 |",
            unit="가격기준=[DEV_DUMMY]", observed_period="2026-01-01~2026-01-02",
            action_id="price.series", caveat="개발용 더미 데이터이며 실제 값이 아닙니다.",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈"),
        )])
        scope = _render_price_series([evidence], plan)
        assert scope is not None
        answer, cited = scope
        self.assertNotIn("가격 기준은 [DEV_DUMMY]", answer)
        self.assertEqual(chatbot._dummy_data_notice(cited, [evidence]), "")

    def test_dummy_prefix_is_removed_but_actual_basis_is_kept(self):
        self.assertEqual(
            chatbot._natural_price_basis("가격기준=[DEV_DUMMY] spot"),
            "가격 기준은 spot입니다.",
        )

    def test_dummy_prefix_is_also_removed_from_citation_unit(self):
        evidence = Evidence(kind="structured", source="public.KO_MNRL_PRC", section="가격", text="x",
                            unit="가격기준=[DEV_DUMMY] spot", caveat="개발용 더미 데이터")
        citation = chatbot._citation_sources({1}, [evidence])[0]
        self.assertEqual(citation["unit"], "가격기준=spot")
        self.assertNotIn("DEV_DUMMY", citation["unit"])
    def test_compound_raw_unit_keeps_criterion_and_hides_opaque_codes(self):
        unit = "가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002"
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열",
            text="| date | price |\n| --- | --- |\n| 2025-12-31 | 100 |",
            unit=unit, observed_period="2025-01-01~2025-12-31", action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series", slots=ActionSlots(),
        )])

        disclosure = chatbot._price_unit_disclosure(
            f"가격 흐름입니다. 단위는 {unit}입니다. [1]", [evidence],
        )
        scope = _render_price_series([evidence], plan)
        citations = chatbot._citation_sources({1}, [evidence])

        self.assertIn("가격기준=LME CASH", disclosure)
        self.assertNotIn("PR001", disclosure)
        self.assertNotIn("WT002", disclosure)
        assert scope is not None
        self.assertIn("가격 기준은 LME CASH이며, 통화는 USD이며, 중량 단위는 톤입니다.", scope[0])
        self.assertIn("최신 보유 관측일(2025-12-31) 가격 요약입니다.", scope[0])
        self.assertIn("최신 가격은 100 (2025-12-31)", scope[0])
        self.assertNotIn("관측 기간", scope[0])
        self.assertNotIn("PR001;", scope[0])
        self.assertNotIn("WT002;", scope[0])
        self.assertEqual(citations[0]["unit"], "가격기준=LME CASH")
        self.assertEqual(chatbot._price_display_unit(unit), "USD/톤")

    def test_latest_observation_heading_uses_table_date_not_range_status(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열",
            text="| date | price |\n| --- | --- |\n| 2026-09-08 | 10 |\n| 2026-09-09 | 11 |",
            unit="가격기준=LME CASH; 통화=USD; 중량=톤",
            observed_period=("2026-09-08~2026-09-09, 최신순 2건만, "
                             "최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음)"),
            action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈"),
        )])

        scope = _render_price_series([evidence], plan)

        assert scope is not None
        self.assertIn("최신 보유 관측일(2026-09-09) 가격 요약입니다.", scope[0])
        self.assertNotIn("최신순 2건", scope[0])

    def test_single_latest_price_is_not_described_as_a_chart_or_trend(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열",
            text="| date | price |\n| --- | --- |\n| 2026-09-08 | 16745.53 |",
            unit="가격기준=LME CASH; 통화=USD; 중량=톤", observed_period="2026-09-08",
            action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈"),
        )])

        scope = _render_price_series([evidence], plan)

        assert scope is not None
        self.assertIn("최신 가격은 16,745.53 (2026-09-08)입니다.", scope[0])
        self.assertIn("표에는 최신 관측값 1건", scope[0])
        self.assertNotIn("차트", scope[0])
        self.assertNotIn("추세", scope[0])

    def test_latest_price_uses_requested_date_price_unit_and_prior_change(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열",
            text="| date | price |\n| --- | --- |\n| 2026-09-07 | 100 |\n| 2026-09-08 | 105 |",
            unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002",
            observed_period="2026-09-07~2026-09-08", action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series",
            slots=ActionSlots(mineral="니켈", period=Period(kind="latest")),
        )])
        scope = _render_price_series([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "2026-09-08 기준 니켈 가격은 105 USD/톤입니다. 전일 대비 +5(+5.00%) 변동했습니다.")

    def test_latest_price_table_hides_prior_observation_used_for_change(self):
        table = chatbot.extract_markdown_tables(
            "| crtr_ymd | price |\n| --- | --- |\n| 20260907 | 100 |\n| 20260908 | 105 |",
        )[0]
        displayed = latest_price_display_table(table)
        self.assertEqual(displayed["rows"], [["20260908", "105"]])

    def test_latest_price_marks_missing_source_unit_without_guessing(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열",
            text="| date | price |\n| --- | --- |\n| 2026-09-07 | 100 |\n| 2026-09-08 | 105 |",
            unit="가격기준=[DEV_DUMMY]", observed_period="2026-09-07~2026-09-08", action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series",
            slots=ActionSlots(mineral="구리", period=Period(kind="latest")),
        )])
        scope = _render_price_series([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "2026-09-08 기준 구리 가격은 105 (원천 단위 미확인)입니다. 전일 대비 +5(+5.00%) 변동했습니다.")

    def test_price_operation_renderers_are_deterministic(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="가격 시계열",
            text=("| date | price |\n| --- | --- |\n| 2026-01-02 | 100 |\n"
                  "| 2026-02-02 | 110 |\n| 2026-03-02 | 121 |"),
            unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002",
            observed_period="2026-01-02~2026-03-02", action_id="price.series",
        )
        cases = (
            ("period_average_delta", Period(kind="trailing_months", trailing_months=3),
             "2026-03-02 기준 니켈 가격은 121 USD/톤입니다. 최근 3개월 평균 대비 +9.67%입니다."),
            ("monthly_streak", Period(kind="range", start="1900-01-01", end="2026-03-02"),
             "2026-03 기준 니켈 월평균 가격은 121 USD/톤입니다. 2개월째 상승세이며, 상승 구간 시작은 2026-01입니다. 현재 월평균 가격은 121 USD/톤(+21.00%)입니다."),
            ("yearly_average", Period(kind="range", start="1900-01-01", end="2026-03-02"),
             "니켈 연도별 평균 가격은 [2026 YTD 110.33]입니다. 단위: USD/톤"),
        )
        for operation, period, expected in cases:
            with self.subTest(operation=operation):
                plan = ActionPlan(actions=[ActionCall(
                    requirement_id="price", action_id="price.series",
                    slots=ActionSlots(mineral="니켈", period=period, price_operation=operation),
                )])
                scope = _render_price_series([evidence], plan)
                assert scope is not None
                self.assertEqual(scope[0], expected)

    def test_two_mineral_comparison_renderer_discloses_different_price_bases(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="동일 기간 가격 변동률",
            text=("| mineral | start_date | pct_change | price_criterion | price_currency_code | weight_unit_code |\n"
                  "| --- | --- | --- | --- | --- | --- |\n"
                  "| 니켈 | 2025-09-01 | 10.25 | LME CASH | PR001 | WT002 |\n"
                  "| 리튬 | 2025-09-01 | -3.5 | 탄산리튬 | PR001 | WT001 |"),
            unit=None,
            observed_period="2025-09-01~2026-09-01", action_id="price.compare",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="compare", action_id="price.compare",
            slots=ActionSlots(minerals=["니켈", "리튬"], period=Period(kind="trailing_months", trailing_months=12)),
        )])
        scope = render_price_comparison([evidence], plan)
        assert scope is not None
        self.assertIn("니켈 +10.25%", scope[0])
        self.assertIn("리튬 -3.50%", scope[0])
        self.assertIn("가격기준=LME CASH", scope[0])
        self.assertIn("단순 비교", scope[0])

    def test_yearly_average_marks_partial_historical_year_as_ytd(self):
        evidence = Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC", section="연도별 평균",
            text="| price_date | price | observation_months |\n| --- | --- | --- |\n| 20250101 | 110 | 6 |",
            unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002",
            observed_period="2025-01-01~2025-06-01", action_id="price.series",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="price", action_id="price.series",
            slots=ActionSlots(mineral="니켈", period=Period(kind="latest"), price_operation="yearly_average"),
        )])
        scope = _render_price_series([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "니켈 연도별 평균 가격은 [2025 YTD 110]입니다. 단위: USD/톤")

    def test_verified_human_units_are_preserved(self):
        unit = "가격기준=LME CASH; 통화=USD; 중량=톤"
        evidence = SimpleNamespace(
            kind="aggregated", source="price", section="series", as_of=None, unit=unit,
            requirement_id=None, action_id="price.series", source_id=None, observed_period=None,
            menu_page_id=None,
        )
        disclosure = chatbot._price_unit_disclosure("가격 흐름입니다. [1]", [evidence])
        citations = chatbot._citation_sources({1}, [evidence])

        self.assertIn(unit, disclosure)
        self.assertEqual(citations[0]["unit"], unit)

    def test_composite_index_answers_follow_private_output_contract(self):
        evidence = Evidence(
            kind="structured", source="private.KO_MNRL_SNTHS_INDX", section="광물종합지수",
            text=("| INDX_SE_CD | CRTR_YMD | INDX |\n| --- | --- | --- |\n"
                  "| HI001 | 20260925 | 120 |\n| HI001 | 20260926 | 123 |"),
            observed_period="2026-09-25~2026-09-26", action_id="indicator.series",
        )
        latest = ActionPlan(actions=[ActionCall(
            requirement_id="index", action_id="indicator.series",
            slots=ActionSlots(indicator="composite_index", indicator_variant="composite",
                              indicator_operation="latest_delta", period=Period(kind="latest")),
        )])
        trend = ActionPlan(actions=[ActionCall(
            requirement_id="index", action_id="indicator.series",
            slots=ActionSlots(indicator="composite_index", indicator_variant="composite",
                              indicator_operation="period_change",
                              period=Period(kind="trailing_months", trailing_months=3)),
        )])
        self.assertEqual(
            chatbot._composite_index_scope_answer([evidence], latest)[0],
            "2026-09-26 광물종합지수는 123으로 전일 대비 +3.00(+2.50%) 변동했습니다.",
        )
        self.assertEqual(
            chatbot._composite_index_scope_answer([evidence], trend)[0],
            "2026-09-25~2026-09-26 광물종합지수는 120에서 123으로 +2.50% 상승했습니다.",
        )

    def test_future_forecast_output_contract_requires_normalized_adapter_columns(self):
        evidence = Evidence(
            kind="structured", source="private.forecast", section="가격예측",
            text=("| forecast_date | predicted_price | current_price | unit |\n| --- | --- | --- | --- |\n"
                  "| 2026-10 | 110 | 100 | USD/톤 |"),
            action_id="forecast.price",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="forecast", action_id="forecast.price",
            slots=ActionSlots(mineral="구리", period=Period(kind="future_horizon", future_horizon=1)),
        )])
        scope = chatbot._forecast_price_scope_answer([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "2026-10 구리 가격 전망치는 110 USD/톤로, 현재 대비 +10.00% 상승 전망입니다. 전망치는 참고용입니다.")

    def test_future_forecast_direction_contract_requires_adapter_period(self):
        evidence = Evidence(
            kind="structured", source="private.forecast", section="가격예측",
            text=("| forecast_date | forecast_period | predicted_price | current_price | unit |\n"
                  "| --- | --- | --- | --- | --- |\n| 2026-10 | 2026-10~2026-12 | 90 | 100 | USD/톤 |"),
            action_id="forecast.price",
        )
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="forecast", action_id="forecast.price",
            slots=ActionSlots(mineral="니켈", forecast_operation="direction"),
        )])
        scope = chatbot._forecast_price_scope_answer([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "2026-10~2026-12 니켈 가격 전망 방향은 하락입니다. 현재가 100 USD/톤, 전망치는 90 USD/톤 기준입니다.")


if __name__ == "__main__":
    unittest.main()
