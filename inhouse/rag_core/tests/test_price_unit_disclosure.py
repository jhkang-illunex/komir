# -*- coding: utf-8 -*-
"""가격 원천 내부 코드가 본문과 인용 메타데이터로 새지 않는지 검사한다."""
import unittest
from types import SimpleNamespace

from rag_core.ragkit import chatbot
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from rag_core.retrieval.evidence import Evidence


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
        scope = chatbot._price_series_scope_answer([evidence], plan)
        assert scope is not None
        answer, cited = scope
        self.assertNotIn("가격 기준은 [DEV_DUMMY]", answer)
        self.assertIn("개발용 더미", chatbot._dummy_data_notice(cited, [evidence]))

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
        scope = chatbot._price_series_scope_answer([evidence], plan)
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

        scope = chatbot._price_series_scope_answer([evidence], plan)

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

        scope = chatbot._price_series_scope_answer([evidence], plan)

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
        scope = chatbot._price_series_scope_answer([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "2026-09-08 기준 니켈 가격은 105 USD/톤입니다. 전일 대비 +5(+5.00%) 변동했습니다.")

    def test_latest_price_table_hides_prior_observation_used_for_change(self):
        table = chatbot.extract_markdown_tables(
            "| crtr_ymd | price |\n| --- | --- |\n| 20260907 | 100 |\n| 20260908 | 105 |",
        )[0]
        displayed = chatbot._latest_price_display_table(table)
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
        scope = chatbot._price_series_scope_answer([evidence], plan)
        assert scope is not None
        self.assertEqual(scope[0], "2026-09-08 기준 구리 가격은 105 (원천 단위 미확인)입니다. 전일 대비 +5(+5.00%) 변동했습니다.")

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


if __name__ == "__main__":
    unittest.main()
