import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.komis_raw import KomisRawDataRepository
from rag_core.ragkit.action_contract import ActionSlots, IntentCall, IntentPlan, action_plan_from_intent, extract_action_plan
from rag_core.ragkit.chatbot_graph import _route_from_action_call


class GlobalUnTradeWiringTest(unittest.TestCase):
    def test_non_korea_country_rank_defaults_to_un_global_scope(self):
        plan = extract_action_plan("니켈 주요 수출국을 알려줘", None)
        call = plan.actions[0]
        self.assertEqual(call.slots.trade_scope, "global")
        self.assertEqual(_route_from_action_call(call, "니켈 주요 수출국을 알려줘").komis_ranking_page, "map_global")

    def test_korea_country_rank_stays_customs_scope(self):
        plan = action_plan_from_intent(IntentPlan(requirements=[IntentCall(
            requirement_id="rank", intent="trade_rank", role="data",
            slots=ActionSlots(mineral="니켈", metric="import_amount", flow="import"),
        )]), "우리나라 니켈 주요 수입국을 알려줘")
        self.assertEqual(plan.actions[0].slots.trade_scope, "korea")

    def test_global_ranking_translates_hsk_to_un_hs6(self):
        captured = []
        def fake_read_sql(query):
            captured.append(query)
            import pandas as pd
            return pd.DataFrame([["Canada", 10, 1]], columns=["country", "total", "n"]) if "GROUP BY" in query else pd.DataFrame([[10, "20170101", "20170101"]], columns=["grand_total", "period_start", "period_end"])
        with patch("common.komis_raw.read_sql_pg", side_effect=fake_read_sql):
            result = KomisRawDataRepository().fetch_country_ranking(page_id="map_global", hs_codes=["7501100000"], metric="export_amount", start_period=None, end_period=None)
        self.assertEqual(result.rows[0]["country"], "Canada")
        self.assertIn("'750110'", captured[0])
        self.assertNotIn("'7501100000'", captured[0])

    def test_country_rank_share_label_names_the_metric(self):
        import pandas as pd
        with patch("common.komis_raw.read_sql_pg", side_effect=[
            pd.DataFrame([["Australia", 100, 2]], columns=["country", "total", "n"]),
            pd.DataFrame([[100, "20260601", "20260909"]],
                         columns=["grand_total", "period_start", "period_end"]),
        ]):
            result = KomisRawDataRepository().fetch_country_ranking(
                page_id="map_korea", hs_codes=["2836910000"], metric="import_amount",
                start_period="20260601", end_period="20260909",
            )
        self.assertEqual(
            result.column_labels["share_pct"],
            "수입금액 비중(%, 2026-06-01~2026-09-09 조회 품목 전체 국가 합계 대비)",
        )


if __name__ == "__main__":
    unittest.main()
