import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import (  # noqa: E402
    ActionCall, ActionPlan, ActionSlots, Period, extract_action_plan, validate_action_plan,
)
from rag_core.ragkit.chatbot_graph import retrieve_evidence  # noqa: E402
from rag_core.ragkit.composite_renderer import render_composite  # noqa: E402
from rag_core.retrieval.evidence import Evidence  # noqa: E402


class CrossRankWiringTest(unittest.TestCase):
    def test_question_types_use_single_cross_action(self):
        trade = extract_action_plan("중국 수입 비중 높은 광종 중 최근 가격 오른 건 뭐야?", None)
        resource = extract_action_plan("생산 1위국 비중이 높은 광종들 가격 변동 어때?", None)
        self.assertEqual(trade.actions[0].action_id, "trade.price_cross_rank")
        self.assertEqual(trade.actions[0].slots.partner_country, "중국")
        self.assertEqual(resource.actions[0].action_id, "resource.price_cross_rank")
        self.assertTrue(validate_action_plan(trade).approved)
        self.assertTrue(validate_action_plan(resource).approved)

    def test_country_renderer_excludes_price_declines(self):
        call = ActionCall(requirement_id="x", action_id="trade.price_cross_rank",
                          slots=ActionSlots(partner_country="중국", metric="import_amount"))
        evidence = Evidence(
            kind="structured", source="public.KO_CSTM_CMMRC", section="교차 순위",
            action_id=call.action_id,
            text=("| rank | country | mineral | share_pct | trade_start | trade_end | price_start | price_end | pct_change | price_criterion | price_currency_code | weight_unit_code | trade_metric |\n"
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                  "| 1 | 중국 | 리튬 | 60 | 2025-01-01 | 2025-12-31 | 2026-01-02 | 2026-09-25 | 12 | LME Cash | USD | 톤 | import_amount |\n"
                  "| 2 | 중국 | 니켈 | 30 | 2025-01-01 | 2025-12-31 | 2026-01-02 | 2026-09-25 | -4 | LME Cash | USD | 톤 | import_amount |"),
        )
        result = render_composite([evidence], ActionPlan(actions=[call]))
        self.assertIsNotNone(result)
        self.assertIn("리튬(+12%)", result[0])
        self.assertNotIn("니켈(-4%)", result[0].split("광물가격 :", 1)[1])

    def test_direct_adapter_bypasses_generic_retrieval(self):
        call = ActionCall(requirement_id="x", action_id="trade.price_cross_rank",
                          slots=ActionSlots(partner_country="중국", metric="import_amount",
                                            period=Period(kind="trailing_months", trailing_months=12)))
        evidence = Evidence(kind="structured", source="public.KO_CSTM_CMMRC", section="교차 순위",
                            text="| mineral | share_pct |\n|---|---|\n| 리튬 | 60 |")
        with patch("rag_core.ragkit.chatbot_graph.cross_rank.fetch_cross_rank_evidence",
                   return_value=([evidence], [])), \
             patch("rag_core.ragkit.chatbot_graph._retrieve_node",
                   side_effect=AssertionError("generic retrieval must not run")):
            result = retrieve_evidence("중국 수입 비중 높은 광종 중 가격 상승은?",
                                       llm=object(), action_plan=ActionPlan(actions=[call]),
                                       include_action_results=True)
        self.assertEqual(result.action_results[0].status, "success")
        self.assertEqual(result.evidence[0].action_id, call.action_id)


if __name__ == "__main__":
    unittest.main()
