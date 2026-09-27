import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period  # noqa: E402
from rag_core.ragkit.composite_renderer import render_composite  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


class CompositeRendererTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
