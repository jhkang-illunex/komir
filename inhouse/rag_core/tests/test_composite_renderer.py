import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period  # noqa: E402
from rag_core.ragkit.composite_renderer import _document_summary_text, _hhi_risk_label, render_composite  # noqa: E402
from rag_core.ragkit.action_results import ActionResult  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


class CompositeRendererTest(unittest.TestCase):
    def test_monthly_summary_uses_summary_cell_without_source_path_or_metadata(self):
        item = Evidence(
            kind="structured", source="전략광종 월간동향", section="2026년 6월호",
            text=("| 월호 | 게시월 | 원문 | 광종목록 | 요약 |\n|---|---|---|---|---|\n"
                  "| 6월호 | 2026-06 | /srv/private/monthly/file.md | 구리, 니켈 | "
                  "구리와 니켈의 시장 동향을 다룹니다. |"),
        )

        summary = _document_summary_text(item)

        self.assertEqual(summary, "구리와 니켈의 시장 동향을 다룹니다.")
        self.assertNotIn("/srv/private", summary)
        self.assertNotIn("file.md", summary)

    def test_production_and_reserves_rankings_get_a_grounded_joint_summary(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="production_req", action_id="resource.rank",
                       slots=ActionSlots(mineral="희토류", metric="production", top_n=5)),
            ActionCall(requirement_id="reserves_req", action_id="resource.rank",
                       slots=ActionSlots(mineral="희토류", metric="reserves", top_n=5)),
        ])
        # Evidence 순서를 뒤집어도 requirement_id로 각 지표를 정확히 결합해야 한다.
        evidence = [
            Evidence(kind="structured", source="KOMIS", section="희토류 매장량", action_id="resource.rank",
                     requirement_id="reserves_req", as_of="2025~2025",
                     text=("집계 기준: 분모는 공식 세계 합계 1000 톤입니다.\n\n"
                           "| country | share_pct |\n|---|---:|\n| 중국 | 36.4 |\n| 베트남 | 21.6 |")),
            Evidence(kind="structured", source="KOMIS", section="희토류 생산량", action_id="resource.rank",
                     requirement_id="production_req", as_of="2026~2026",
                     text=("집계 기준: 분모는 공식 세계 합계 1000 톤입니다.\n\n"
                           "| country | share_pct |\n|---|---:|\n| 중국 | 60.5 |\n| 호주 | 20.5 |")),
        ]

        result = render_composite(evidence, plan)

        self.assertIsNotNone(result)
        answer, cited = result
        self.assertIn("희토류 생산량은 2026년 기준 1위 중국(60.5%), 2위 호주(20.5%)", answer)
        self.assertIn("분모는 공식 세계 생산량 총량입니다", answer)
        self.assertIn("희토류 매장량은 2025년 기준 상위 2개국이 중국(36.4%) 및 베트남(21.6%)", answer)
        self.assertIn("합산 비중은 58%", answer)
        self.assertNotIn("req_001", answer)
        self.assertNotIn("다음과 같습니다", answer)
        self.assertEqual(cited, {1, 2})

    def test_production_reserves_pair_reports_only_the_successful_metric(self):
        production = ActionCall(requirement_id="production_req", action_id="resource.rank",
                                slots=ActionSlots(mineral="희토류", metric="production"))
        reserves = ActionCall(requirement_id="reserves_req", action_id="resource.rank",
                              slots=ActionSlots(mineral="희토류", metric="reserves"))
        plan = ActionPlan(actions=[production, reserves])
        evidence = [Evidence(
            kind="structured", source="KOMIS", section="희토류 생산량", action_id="resource.rank",
            requirement_id="production_req", as_of="2026~2026",
            text=("집계 기준: 분모는 조회 대상 국가별 합계 1000 톤입니다.\n\n"
                  "| country | share_pct |\n|---|---:|\n| 중국 | 60.5 |")),
        ]
        outcomes = [
            ActionResult("production_req", "resource.rank", production.slots, "success", evidence),
            ActionResult("reserves_req", "resource.rank", reserves.slots, "no_data"),
        ]

        result = render_composite(evidence, plan, outcomes)

        self.assertIsNotNone(result)
        self.assertIn("1위가 중국(60.5%)", result[0])
        self.assertIn("분모는 조회된 국가별 생산량 합계입니다", result[0])
        self.assertNotIn("공식 세계 생산량 총량입니다", result[0])
        self.assertIn("매장량 자료는 확인되지 않았습니다", result[0])
        self.assertEqual(result[1], {1})

        no_data = render_composite([], plan, [
            ActionResult("production_req", "resource.rank", production.slots, "no_data"),
            ActionResult("reserves_req", "resource.rank", reserves.slots, "no_data"),
        ])
        self.assertEqual(no_data[0], "희토류 생산량·매장량 상위 국가 자료를 확인하지 못했습니다.")
        self.assertEqual(no_data[1], set())

    def test_composite_index_year_range_reports_actual_partial_coverage(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="index", action_id="indicator.series",
            slots=ActionSlots(
                indicator="composite_index", indicator_variant="composite",
                indicator_operation="period_change",
                period=Period(kind="range", start="2010-01-01", end="2011-12-31", explicit=True),
            ),
        )])
        evidence = [Evidence(
            kind="structured", source="KOMIS", section="광물종합지수", action_id="indicator.series",
            text=("| date | index |\n|---|---:|\n"
                  "| 2011-01-03 | 100 |\n| 2011-12-30 | 110 |"),
        )]

        result = render_composite(evidence, plan)

        self.assertIsNotNone(result)
        self.assertIn("요청하신 2010~2011년 중 확인된 자료 2011-01-03~2011-12-30", result[0])
        self.assertIn("100에서 110까지 10% 상승", result[0])
        self.assertEqual(result[1], {1})

    def test_hhi_risk_threshold_boundaries(self):
        self.assertEqual(_hhi_risk_label(5999.99), "주의 필요")
        self.assertEqual(_hhi_risk_label(6000), "높은 위험")
        self.assertEqual(_hhi_risk_label(7999.99), "높은 위험")
        self.assertEqual(_hhi_risk_label(8000), "매우 높은 위험")
        self.assertEqual(_hhi_risk_label(10000), "매우 높은 위험")
        self.assertIsNone(_hhi_risk_label(10000.01))

    def test_import_concentration_has_summary_and_hhi_interpretation(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="hhi", action_id="trade.concentration",
            slots=ActionSlots(mineral="리튬"),
        )])
        evidence = [Evidence(
            kind="structured", source="public.KO_CSTM_CMMRC",
            section="수입금액 집중도(HHI=2333.77, 전체합계=2500000, formula)",
            action_id="trade.concentration",
            text=("집계 기준: 같은 기간·조건의 전체 국가 합계 2500000 USD를 분모로 사용.\n\n"
                  "| country | total | share_pct |\n|---|---:|---:|\n"
                  "| 호주 | 940000 | 37.6 |\n| 중국 | 657500 | 26.3 |"),
        )]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("호주(37.6%)와 중국(26.3%)이 전체의 63.9%", result[0])
        self.assertIn("HHI 2,333.77은 국가별 수입 비중을 제곱해 합산한 집중도 지수", result[0])
        self.assertIn("'주의 필요' 구간입니다", result[0])
        self.assertIn("지정학적 위험 자체를 직접 측정하는 값은 아닙니다", result[0])

    def test_import_concentration_suppresses_hhi_below_amount_floor(self):
        plan = ActionPlan(actions=[ActionCall(
            requirement_id="hhi", action_id="trade.concentration",
            slots=ActionSlots(mineral="리튬"),
        )])
        evidence = [Evidence(
            kind="structured", source="public.KO_CSTM_CMMRC",
            section="수입금액 집중도(HHI 미표시: 수입액 100만 USD 기준 미달)",
            action_id="trade.concentration",
            text=("집계 기준: 전체 국가 합계 800000 USD를 분모로 사용.\n\n"
                  "| country | total | share_pct |\n|---|---:|---:|\n"
                  "| 호주 | 300800 | 37.6 |\n| 중국 | 210400 | 26.3 |"),
        )]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("HHI 수치와 집중도 등급은 표시하지 않습니다", result[0])
        self.assertNotIn("2,333.77", result[0])

    def test_price_is_retained_when_forecast_action_has_no_data(self):
        price_call = ActionCall(requirement_id="price", action_id="price.series",
                                slots=ActionSlots(mineral="리튬"))
        forecast_call = ActionCall(requirement_id="forecast", action_id="forecast.price",
                                   slots=ActionSlots(mineral="리튬"))
        plan = ActionPlan(actions=[price_call, forecast_call])
        evidence = [Evidence(
            kind="table", source="price", section="price", requirement_id="price",
            action_id="price.series", unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002",
            text="| date | price |\n|---|---|\n| 2026-09-08 | 100 |",
        )]
        outcomes = [
            ActionResult("price", "price.series", price_call.slots, "success", evidence),
            ActionResult("forecast", "forecast.price", forecast_call.slots, "no_data"),
        ]
        result = render_composite(evidence, plan, outcomes)
        self.assertIsNotNone(result)
        self.assertIn("2026-09-08 리튬 가격 100.00 USD/톤", result[0])
        self.assertIn("전망 자료가 없어", result[0])
        self.assertEqual(result[1], {1})

    def test_five_battery_mineral_ranks_are_joined_by_requirement_not_evidence_position(self):
        minerals = [("li", "리튬", "호주"), ("ni", "니켈", "인도네시아"),
                    ("co", "코발트", "콩고민주공화국"), ("mn", "망간", "미국"),
                    ("gr", "흑연", "중국")]
        actions = [ActionCall(requirement_id=req, action_id="trade.country_rank",
                              slots=ActionSlots(mineral=mineral))
                   for req, mineral, _country in minerals]
        plan = ActionPlan(actions=actions)
        evidence = []
        for req, _mineral, country in minerals:
            for _ in range(2):
                evidence.append(Evidence(
                    kind="table", source="KOMIS", section="수입 순위", requirement_id=req,
                    action_id="trade.country_rank", observed_period="2026-06-01~2026-09-09",
                    text=f"| country | share_pct |\n|---|---|\n| {country} | 25 |",
                ))
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        for _req, mineral, country in minerals:
            self.assertIn(f"{mineral} : {country} (25%)", result[0])
        self.assertIn("2026-06-01~2026-09-09", result[0])
        self.assertEqual(len(result[1]), 5)

    def test_latest_price_and_import_rank_select_evidence_by_requirement(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(
                mineral="니켈", period=Period(kind="latest"))),
            ActionCall(requirement_id="imports", action_id="trade.country_rank", slots=ActionSlots(
                mineral="니켈", metric="import_amount", top_n=5)),
        ])
        evidence = [
            Evidence(kind="table", source="price", section="price", requirement_id="price",
                     action_id="price.series",
                     text="| date | price |\n|---|---|\n| 2026-08-01 | 100 |\n| 2026-09-01 | 110 |"),
            Evidence(kind="table", source="KOMIS", section="unrelated", requirement_id="other",
                     action_id="trade.country_rank",
                     text="| country | share_pct |\n|---|---|\n| 중국 | 99 |"),
            Evidence(kind="table", source="KOMIS", section="imports", requirement_id="imports",
                     action_id="trade.country_rank",
                     text="| country | share_pct |\n|---|---|\n| 인도네시아 | 37.1 |"),
        ]
        result = render_composite(evidence, plan)
        self.assertIsNotNone(result)
        self.assertIn("인도네시아(37.1%)", result[0])
        self.assertIn("2026-09-01 가격 110", result[0])
        self.assertNotIn("중국", result[0])
        self.assertEqual(result[1], {1, 3})

    def test_latest_price_and_import_rank_survive_missing_previous_month_average(self):
        price_call = ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(
            mineral="니켈", period=Period(kind="latest")))
        import_call = ActionCall(requirement_id="imports", action_id="trade.country_rank", slots=ActionSlots(
            mineral="니켈", metric="import_amount", top_n=5))
        plan = ActionPlan(actions=[import_call, price_call])
        evidence = [
            Evidence(kind="table", source="KOMIS", section="imports", requirement_id="imports", action_id="trade.country_rank",
                     text="| country | share_pct |\n|---|---:|\n| 인도네시아 | 37.12 |"),
            Evidence(kind="table", source="KOMIS", section="price", requirement_id="price", action_id="price.series",
                     unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002",
                     text="| crtr_ymd | cmerc_prc |\n|---|---:|\n| 20260908 | 16745.53 |"),
        ]

        result = render_composite(evidence, plan)

        self.assertIsNotNone(result)
        answer, cited = result
        self.assertIn("2026-09-08 기준 최근 가격 16,745.53 USD/톤", answer)
        self.assertIn("전월 평균 비교 자료는 확인되지 않았습니다", answer)
        self.assertIn("수입 상위국 인도네시아(37.12%)", answer)
        self.assertNotIn("데이터 없음", answer)
        self.assertEqual(cited, {1, 2})

    def test_price_trend_and_import_rank_report_single_observation_without_fake_change(self):
        plan = ActionPlan(actions=[
            ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(
                mineral="니켈", period=Period(kind="range", start="2025-09-29", end="2026-09-29"))),
            ActionCall(requirement_id="imports", action_id="trade.country_rank", slots=ActionSlots(
                mineral="니켈", metric="import_amount", top_n=5)),
        ])
        evidence = [
            Evidence(kind="table", source="KOMIS", section="price", requirement_id="price", action_id="price.series",
                     unit="가격기준=LME CASH; 통화코드=PR001; 중량단위코드=WT002",
                     text="| crtr_ymd | cmerc_prc |\n|---|---:|\n| 20260908 | 16745.53 |"),
            Evidence(kind="table", source="KOMIS", section="imports", requirement_id="imports", action_id="trade.country_rank",
                     text="| country | share_pct |\n|---|---:|\n| 인도네시아 | 37.12 |"),
        ]

        result = render_composite(evidence, plan)

        self.assertIsNotNone(result)
        answer, cited = result
        self.assertIn("2026-09-08 기준 최근 확인 가격 16,745.53 USD/톤", answer)
        self.assertIn("가격 관측치가 1건이라 기간 변동률과 추세는 계산할 수 없습니다", answer)
        self.assertIn("인도네시아(37.12%)", answer)
        self.assertNotIn("데이터 없음", answer)
        self.assertEqual(cited, {1, 2})

    def test_monthly_summary_is_rendered_without_internal_ids_when_index_action_fails(self):
        index_call = ActionCall(requirement_id="monthly_composite_index", action_id="indicator.series",
                                slots=ActionSlots(indicator="composite_index", indicator_variant="composite",
                                                  indicator_operation="period_change"))
        document_call = ActionCall(requirement_id="monthly_trend", action_id="document.retrieve",
                                   slots=ActionSlots(topic="월간동향"))
        plan = ActionPlan(actions=[index_call, document_call])
        evidence = [Evidence(
            kind="document", source="전략광종 월간동향", section="2026년 6월호 전략광종 월간동향",
            requirement_id="monthly_trend", action_id="document.retrieve",
            text="2026년 6월호 주요 내용은 동과 니켈의 시장 동향입니다.",
        )]
        outcomes = [
            ActionResult("monthly_composite_index", "indicator.series", index_call.slots,
                         "validation_failed", failure_reason="advisor_rejected"),
            ActionResult("monthly_trend", "document.retrieve", document_call.slots, "success", evidence),
        ]

        result = render_composite(evidence, plan, outcomes)

        self.assertIsNotNone(result)
        answer, cited = result
        self.assertIn("광물종합지수 : 요청 기간의 변동 자료를 확인하지 못했습니다", answer)
        self.assertIn("월간동향 : 2026년 6월호 전략광종 월간동향 주요 내용", answer)
        self.assertIn("동과 니켈의 시장 동향", answer)
        self.assertNotIn("monthly_composite_index", answer)
        self.assertNotIn("monthly_trend", answer)
        self.assertNotIn("advisor_rejected", answer)
        self.assertEqual(cited, {1})

    def test_price_timeline_keeps_actual_range_when_forecast_is_missing(self):
        price_call = ActionCall(requirement_id="price", action_id="price.series",
                                slots=ActionSlots(mineral="니켈"))
        forecast_call = ActionCall(requirement_id="forecast", action_id="forecast.price",
                                   slots=ActionSlots(mineral="니켈", forecast_operation="timeline"))
        plan = ActionPlan(actions=[price_call, forecast_call])
        evidence = [Evidence(
            kind="table", source="price", section="price", requirement_id="price",
            action_id="price.series",
            text=("| date | price |\n|---|---|\n| 2026-03-01 | 100 |\n"
                  "| 2026-09-01 | 110 |"),
        )]
        outcomes = [
            ActionResult("price", "price.series", price_call.slots, "success", evidence),
            ActionResult("forecast", "forecast.price", forecast_call.slots, "source_unavailable"),
        ]
        result = render_composite(evidence, plan, outcomes)
        self.assertIsNotNone(result)
        self.assertIn("실제 관측 구간 2026-03-01~2026-09-01", result[0])
        self.assertIn("전망 구간은 표시하지 않습니다", result[0])
        self.assertEqual(result[1], {1})

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

    def test_significant_price_rise_keeps_price_when_same_day_news_is_missing(self):
        price_call = ActionCall(requirement_id="rise", action_id="price.series", slots=ActionSlots(
            mineral="니켈", price_operation="significant_daily_rise", significant_change_pct=5.0,
        ))
        news_call = ActionCall(requirement_id="news", action_id="document.retrieve", slots=ActionSlots(
            mineral="니켈", topic="니켈 자원뉴스",
        ), depends_on=["rise"])
        plan = ActionPlan(actions=[price_call, news_call])
        evidence = [Evidence(
            kind="structured", source="KOMIS", section="니켈 가격",
            text="| date | price |\n|---|---:|\n| 2026-09-20 | 100 |\n| 2026-09-21 | 108 |",
            action_id="price.series", requirement_id="rise",
        )]
        results = [
            ActionResult("rise", "price.series", price_call.slots, "success", evidence),
            ActionResult("news", "document.retrieve", news_call.slots, "no_data"),
        ]

        rendered = render_composite(evidence, plan, results)

        self.assertIsNotNone(rendered)
        self.assertIn("2026-09-21 니켈 전일 대비 +8.00% 상승", rendered[0])
        self.assertIn("해당 날짜의 관련 뉴스를 찾지 못했습니다", rendered[0])
        self.assertEqual(rendered[1], {1})

    def test_significant_price_rise_rejects_news_from_a_different_date(self):
        news = Evidence(
            kind="structured", source="news", section="자원뉴스",
            text="| 날짜 | 제목 |\n|---|---|\n| 2026-09-20 | 전날 기사 |",
            action_id="document.retrieve",
        )
        from rag_core.ragkit.composite_renderer import _news_titles
        self.assertEqual(_news_titles(news, expected_date="2026-09-21"), [])

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
