import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period  # noqa: E402
from rag_core.ragkit.composite_renderer import render_composite  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


class CompositeRendererTest(unittest.TestCase):
    def test_single_weekly_report_is_rendered_without_generation(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="weekly_news", action_id="document.retrieve",
                       slots=ActionSlots(topic="2026년 6월 16일 주간동향")),
        ])
        evidence = [Evidence(
            kind="structured", source="KOMIS·조달청 주간 광물동향", section="주간 광물동향 게시물",
            text=("| 게시일 | 출처 | 보고서 제목 | 원문 |\n| --- | --- | --- | --- |\n"
                  "| 2026-06-16 | 조달청 주간시장동향 | 주간 경제 비철금속 시장 동향 | 게시판 |"),
            action_id="document.retrieve",
        )]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("주간 자원뉴스", result[0])
        self.assertIn("2026-06-16", result[0])

    def test_monthly_minerals_and_info_are_rendered_from_separate_adapters(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="monthly_trend", action_id="document.retrieve",
                       slots=ActionSlots(topic="2026년 6월 전략광종 월간동향")),
            ActionCall(requirement_id="monthly_info_니켈", action_id="document.retrieve",
                       slots=ActionSlots(mineral="니켈", topic="니켈 기본 정보")),
        ])
        evidence = [
            Evidence(kind="structured", source="전략광종 월간동향", section="2026년 6월호",
                     text="| 월호 | 광종목록 |\n|---|---|\n| 2026년 6월호 | 니켈 |", action_id="document.retrieve"),
            Evidence(kind="structured", source="Royal Society of Chemistry", section="광물정보",
                     text="| 광종 | 속성 | 값 |\n|---|---|---|\n| 니켈 | uses | 합금 |\n| 니켈 | characteristics | 내식성 |",
                     action_id="document.retrieve"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("광물정보", result[0])
        self.assertIn("니켈: uses: 합금", result[0])

    def test_monthly_minerals_and_import_ranks_are_rendered_from_separate_adapters(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="monthly_trend", action_id="document.retrieve",
                       slots=ActionSlots(topic="2026년 6월 전략광종 월간동향")),
            ActionCall(requirement_id="monthly_import_니켈", action_id="trade.country_rank",
                       slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="전략광종 월간동향", section="2026년 6월호",
                     text="| 월호 | 광종목록 |\n|---|---|\n| 2026년 6월호 | 니켈 |", action_id="document.retrieve"),
            Evidence(kind="structured", source="수급지도", section="한국 수입",
                     text="| country | share_pct |\n|---|---|\n| 인도네시아 | 61.2 |", action_id="trade.country_rank"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("한국 수입 1위국", result[0])
        self.assertIn("니켈: 인도네시아 (61.2%)", result[0])
    def test_single_news_document_is_rendered_without_generation(self):
        """확인된 ai_news 표는 생성 기권으로 버리지 않는다."""
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="news", action_id="document.retrieve",
                       slots=ActionSlots(topic="최근 자원 뉴스")),
        ])
        evidence = [
            Evidence(kind="structured", source="public.ai_news", section="자원뉴스",
                     text=("| 날짜 | 광종 | 제목 | 요약 |\n|---|---|---|---|\n"
                           "| 2026-09-28 | 니켈 | 니켈 자원 뉴스 | 시장 동향 |"),
                     action_id="document.retrieve"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("최근 자원뉴스", result[0])
        self.assertIn("니켈 자원 뉴스", result[0])
        self.assertEqual(result[1], {1})

    def test_price_index_comparison(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="p", action_id="price.series", slots=ActionSlots(
                mineral="니켈", period=Period(kind="trailing_months", trailing_months=6))),
            ActionCall(requirement_id="i", action_id="indicator.series", slots=ActionSlots(
                indicator="composite_index", indicator_variant="composite")),
        ])
        evidence = [
            Evidence(kind="table", source="price", section="price", text="| date | price |\n|---|---|\n| 2026-01-01 | 100 |\n| 2026-06-01 | 110 |", action_id="price.series"),
            Evidence(kind="table", source="index", section="index", text="| date | index |\n|---|---|\n| 2026-01-01 | 200 |\n| 2026-06-01 | 190 |", action_id="indicator.series"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("니켈 가격 +10.00%", result[0])
        self.assertIn("광물 종합지수 -5.00%", result[0])
        self.assertEqual(result[1], {1, 2})

    def test_index_co_rise_renders_only_same_direction_minerals(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="index", action_id="indicator.series", slots=ActionSlots()),
            ActionCall(requirement_id="cu", action_id="price.series", slots=ActionSlots(mineral="구리")),
            ActionCall(requirement_id="ni", action_id="price.series", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="index", section="지수",
                     text="| date | index |\n|---|---|\n| 2026-07-02 | 100 |\n| 2026-08-30 | 110 |", action_id="indicator.series"),
            Evidence(kind="structured", source="price", section="가격",
                     text="| date | price |\n|---|---|\n| 2026-07-02 | 100 |\n| 2026-08-30 | 108 |", action_id="price.series"),
            Evidence(kind="structured", source="price", section="가격",
                     text="| date | price |\n|---|---|\n| 2026-07-02 | 100 |\n| 2026-08-30 | 90 |", action_id="price.series"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("구리(+8.00%)", result[0])
        self.assertNotIn("니켈(-10.00%)", result[0])

    def test_latest_trade_requires_previous_month(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="p", action_id="price.series", slots=ActionSlots(
                mineral="리튬", period=Period(kind="latest"))),
            ActionCall(requirement_id="t", action_id="trade.country_rank", slots=ActionSlots(
                mineral="리튬", metric="import_amount")),
        ])
        evidence = [
            Evidence(kind="table", source="price", section="price", text="| date | price |\n|---|---|\n| 2026-06-01 | 110 |", action_id="price.series"),
            Evidence(kind="table", source="trade", section="trade", text="| country | share_pct |\n|---|---|\n| 호주 | 50 |", action_id="trade.country_rank"),
        ]
        self.assertIsNone(render_composite(evidence, plan))

    def test_mineral_usage_and_price(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="info", action_id="document.retrieve", slots=ActionSlots(topic="니켈 용도")),
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="document", source="info", section="광물정보", text="니켈의 주요 용도는 스테인리스강과 배터리입니다.", action_id="document.retrieve"),
            Evidence(kind="table", source="price", section="price", text="| date | price |\n|---|---|\n| 2026-09-25 | 100 |\n| 2026-09-26 | 110 |", action_id="price.series"),
        ]
        result = render_composite(evidence, plan)
        self.assertIn("광물정보 : 주요 용도", result[0])
        self.assertIn("광물가격 : 2026-09-26", result[0])

    def test_yaml_mineral_info_uses_and_price(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="info", action_id="document.retrieve", slots=ActionSlots(topic="니켈 용도")),
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="RSC", section="광물정보",
                     text="| 광종 | 속성 | 값 |\n|---|---|---|\n| 니켈 | uses | 스테인리스강·합금, 충전식 배터리 |",
                     action_id="document.retrieve"),
            Evidence(kind="table", source="price", section="price",
                     text="| date | price |\n|---|---|\n| 2026-09-25 | 100 |\n| 2026-09-26 | 110 |",
                     action_id="price.series"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("광물정보 : 주요 용도 : 스테인리스강·합금, 충전식 배터리", result[0])

    def test_mineral_usage_and_price_displays_human_price_unit(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="info", action_id="document.retrieve", slots=ActionSlots(topic="니켈 용도")),
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="RSC", section="광물정보",
                     text="| 광종 | 속성 | 값 |\n|---|---|---|\n| 니켈 | uses | 스테인리스강 |",
                     action_id="document.retrieve"),
            Evidence(kind="table", source="price", section="price",
                     text="| date | price |\n|---|---|\n| 2026-09-25 | 100 |\n| 2026-09-26 | 110 |",
                     action_id="price.series",
                     unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("가격 110 USD/톤", result[0])
        self.assertNotIn("통화코드", result[0])

    def test_monthly_trend_and_prices(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="trend", action_id="document.retrieve", slots=ActionSlots(topic="희소금속 월간동향")),
            ActionCall(requirement_id="p1", action_id="price.series", slots=ActionSlots(mineral="리튬")),
            ActionCall(requirement_id="p2", action_id="price.series", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="document", source="trend", section="2026년 9월호", text="희소금속 월간동향 광종별 가격 동향", action_id="document.retrieve"),
            Evidence(kind="table", source="price", section="price", text="| date | price |\n|---|---|\n| 2026-09-25 | 100 |\n| 2026-09-26 | 110 |", action_id="price.series"),
            Evidence(kind="table", source="price", section="price", text="| date | price |\n|---|---|\n| 2026-09-25 | 200 |\n| 2026-09-26 | 190 |", action_id="price.series"),
        ]
        result = render_composite(evidence, plan)
        self.assertIn("월간동향 : 2026년 9월호", result[0])
        self.assertIn("리튬", result[0])
        self.assertIn("니켈", result[0])

    def test_export_control_news_and_china_import_shares(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="news", action_id="document.retrieve", slots=ActionSlots(topic="수출통제 뉴스")),
            ActionCall(requirement_id="ni", action_id="trade.indicator", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="news", section="자원뉴스",
                     text="| 날짜 | 광종 | 제목 | 요약 |\n|---|---|---|---|\n| 2026-09-01 | 니켈 | 중국 수출통제 | 니켈 규제 |",
                     action_id="document.retrieve"),
            Evidence(kind="structured", source="trade", section="수급지도",
                     text="| period | dependency_pct |\n|---|---|\n| 2026-01-01~2026-09-01 | 72.5 |",
                     action_id="trade.indicator"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("니켈 중국 수입 점유율 72.5%", result[0])
        self.assertEqual(result[1], {1, 2})

    def test_mineral_uses_and_import_countries(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="info", action_id="document.retrieve", slots=ActionSlots(topic="니켈 용도")),
            ActionCall(requirement_id="trade", action_id="trade.country_rank", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="info", section="광물정보",
                     text="| 광종 | 속성 | 값 |\n|---|---|---|\n| 니켈 | uses | 스테인리스강·합금 |",
                     action_id="document.retrieve"),
            Evidence(kind="structured", source="trade", section="수급지도",
                     text="| country | share_pct |\n|---|---|\n| 인도네시아 | 60.1 |",
                     action_id="trade.country_rank"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("수입 상위국 인도네시아(60.1%)", result[0])

    def test_current_price_and_forecast(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="니켈")),
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral="니켈")),
        ])
        evidence = [
            Evidence(kind="structured", source="price", section="가격",
                     text="| date | price |\n|---|---|\n| 2026-09-01 | 100 |",
                     action_id="price.series", unit="USD/톤"),
            Evidence(kind="structured", source="forecast", section="예측",
                     text="| forecast_date | forecast_period | current_price | predicted_price | unit |\n|---|---|---|---|---|\n| 2026-10-01 | 월간 | 100 | 110 | USD/톤 |",
                     action_id="forecast.price"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("가격예측 : 2026-10-01 월간 전망치 110 USD/톤", result[0])

    def test_forecast_and_recent_news(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral="리튬")),
            ActionCall(requirement_id="news", action_id="document.retrieve",
                       slots=ActionSlots(mineral="리튬", topic="최근 리튬 자원뉴스")),
        ])
        evidence = [
            Evidence(kind="structured", source="forecast", section="예측",
                     text="| forecast_date | forecast_period | current_price | predicted_price | unit |\n|---|---|---|---|---|\n| 2026-10-01 | 월간 | 100 | 110 | USD/톤 |",
                     action_id="forecast.price"),
            Evidence(kind="structured", source="news", section="자원뉴스",
                     text="| 날짜 | 제목 | 요약 |\n|---|---|---|\n| 2026-09-25 | 리튬 공급 동향 | 요약 |\n| 2026-09-20 | 리튬 수요 동향 | 요약 |",
                     action_id="document.retrieve"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("가격예측 : 월간 리튬 전망 방향 상승 (+10.00%)", result[0])
        self.assertIn("- 리튬 공급 동향 (2026-09-25)", result[0])

    def test_significant_price_rise_and_same_day_news(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="rise", action_id="price.series", slots=ActionSlots(
                mineral="니켈", price_operation="significant_daily_rise", significant_change_pct=5.0)),
            ActionCall(requirement_id="news", action_id="document.retrieve", slots=ActionSlots(
                mineral="니켈", topic="니켈 자원뉴스")),
        ])
        evidence = [
            Evidence(kind="structured", source="price", section="가격",
                     text="| date | price |\n|---|---|\n| 2026-09-20 | 100 |\n| 2026-09-21 | 108 |",
                     action_id="price.series"),
            Evidence(kind="structured", source="news", section="자원뉴스",
                     text="| 날짜 | 제목 | 요약 |\n|---|---|---|\n| 2026-09-21 | 니켈 시장 동향 | 요약 |",
                     action_id="document.retrieve"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("2026-09-21 니켈 전일 대비 +8.00% 상승", result[0])
        self.assertIn("- 니켈 시장 동향 (2026-09-21)", result[0])

    def test_composite_index_decline_week_and_news(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="index", action_id="indicator.series", slots=ActionSlots(
                indicator="composite_index", indicator_variant="composite")),
            ActionCall(requirement_id="news", action_id="document.retrieve", slots=ActionSlots(
                topic="광물종합지수 하락 주간 자원뉴스")),
        ])
        evidence = [
            Evidence(kind="structured", source="index", section="광물종합지수",
                     text="| date | index |\n|---|---|\n| 2026-09-14 | 100 |\n| 2026-09-18 | 94 |",
                     action_id="indicator.series"),
            Evidence(kind="structured", source="news", section="자원뉴스",
                     text="| 날짜 | 제목 | 요약 |\n|---|---|---|\n| 2026-09-17 | 주요 광물 동향 | 요약 |",
                     action_id="document.retrieve"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("2026-09-14 주 -6.00% 하락", result[0])
        self.assertIn("- 주요 광물 동향 (2026-09-17)", result[0])

    def test_weekly_volatility_and_ranked_mineral_news(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="rank", action_id="price.volatility_rank", slots=ActionSlots()),
            ActionCall(requirement_id="news", action_id="document.retrieve", slots=ActionSlots(
                minerals=["니켈", "리튬"], topic="니켈, 리튬 자원뉴스")),
        ])
        evidence = [
            Evidence(kind="structured", source="price", section="가격",
                     text="| mineral | pct_change |\n|---|---|\n| 니켈 | 8.5 |\n| 리튬 | -6.0 |",
                     action_id="price.volatility_rank"),
            Evidence(kind="structured", source="news", section="자원뉴스",
                     text="| 날짜 | 광종 | 제목 | 요약 |\n|---|---|---|---|\n| 2026-09-21 | 니켈 | 니켈 시장 동향 | 요약 |",
                     action_id="document.retrieve"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("니켈 (+8.50%)", result[0])
        self.assertIn("- 니켈 시장 동향 (2026-09-21)", result[0])

    def test_import_countries_and_forecast(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="imports", action_id="trade.country_rank", slots=ActionSlots(mineral="리튬")),
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral="리튬")),
        ])
        evidence = [
            Evidence(kind="structured", source="trade", section="수급지도",
                     text="| country | share_pct |\n|---|---|\n| 호주 | 65.2 |\n| 칠레 | 20.1 |",
                     action_id="trade.country_rank"),
            Evidence(kind="structured", source="forecast", section="예측",
                     text="| forecast_date | forecast_period | current_price | predicted_price | unit |\n|---|---|---|---|---|\n| 2026-10-01 | 월간 | 100 | 110 | USD/톤 |",
                     action_id="forecast.price"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("수입 상위국 호주 (65.2%), 칠레 (20.1%)", result[0])
        self.assertIn("2026-10-01 리튬 전망치 110 USD/톤 (현재 대비 +10.00%)", result[0])

    def test_price_forecast_timeline_and_current_comparison(self):
        def evidence():
            return [
                Evidence(kind="structured", source="price", section="가격",
                         text="| date | price |\n|---|---|\n| 2026-04-01 | 100 |\n| 2026-09-01 | 120 |",
                         action_id="price.series", unit="통화코드=PR001; 중량단위코드=WT002"),
                Evidence(kind="structured", source="forecast", section="예측",
                         text="| forecast_date | forecast_period | current_price | predicted_price | unit |\n|---|---|---|---|---|\n| 2026-10-01 | 월간 | 100 | 110 | PR001 |",
                         action_id="forecast.price"),
            ]
        timeline = ActionPlan(actions=[
            ActionCall(requirement_id="actual", action_id="price.series", slots=ActionSlots(mineral="니켈")),
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral="니켈", forecast_operation="timeline")),
        ])
        result = render_composite(evidence(), timeline)
        self.assertIn("실적 구간과 전망 구간을 구분", result[0])
        comparison = ActionPlan(actions=[
            ActionCall(requirement_id="actual", action_id="price.series", slots=ActionSlots(mineral="니켈")),
            ActionCall(requirement_id="forecast", action_id="forecast.price", slots=ActionSlots(mineral="니켈", forecast_operation="compare_current")),
        ])
        result = render_composite(evidence(), comparison)
        self.assertIn("현재가가 전망치 대비 10 (+9.09%) 높습니다", result[0])


if __name__ == "__main__":
    unittest.main()
