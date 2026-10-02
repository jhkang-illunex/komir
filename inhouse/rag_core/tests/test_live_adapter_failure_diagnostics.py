"""Empty adapter contracts must not be reported as advisor judgements."""
from pathlib import Path
import asyncio
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rag_core.ragkit import chatbot_graph as graph
from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from common.komis_raw import KomisRawDataRepository, RawDataset, RawDataAccessError
import pandas as pd


class AdapterFailureDiagnosticsTests(unittest.TestCase):
    def run_empty(self, action, warning):
        with patch.object(graph, "_retrieve_node", return_value={"evidence": [], "warnings": [warning]}), \
                patch.object(graph, "_verify_node", wraps=graph._verify_node) as verify:
            result = graph.retrieve_evidence("", action_plan=ActionPlan(actions=[action]), llm=object(), include_action_results=True)
        return result.action_results[0], verify.call_count

    def test_reserves_category_failure_not_advisor_rejection(self):
        call = ActionCall(requirement_id="reserves", action_id="resource.rank", slots=ActionSlots(
            mineral="구리", metric="reserves", resource_population="all", period=Period(kind="calendar_year", calendar_year=2024)))
        result, count = self.run_empty(call, "resource_population_unresolved_category")
        self.assertEqual(result.failure_reason, "resource_population_unresolved_category")
        self.assertEqual(result.status, "failed")
        self.assertEqual(count, 0)
        self.assertNotIn("advisor_rejected", result.warnings)

    def test_price_selection_is_preserved_not_invented_missing_data(self):
        call = ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="텅스텐"))
        marker = "price_criterion_selection_required:TEST:1=criterion A; 2=criterion B"
        result, count = self.run_empty(call, marker)
        self.assertEqual(result.failure_reason, marker)
        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(count, 0)
        self.assertNotIn("advisor_rejected", result.warnings)

    def test_missing_price_mapping_not_asserted_absent_observations(self):
        call = ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="리튬"))
        marker = "price_criterion_mapping_missing:TEST"
        result, count = self.run_empty(call, marker)
        self.assertEqual(result.failure_reason, marker)
        self.assertEqual(result.status, "failed")
        self.assertEqual(count, 0)

    def test_known_development_reserve_rows_are_excluded_from_population(self):
        rows = [{"ntn_eng_cd": "CL", "crtr_yr": "2024", "se_cd": kind,
                 "mass_unit_cd": unit, "rsrc_invt_cd": inventory, "burudg_quty_ton": value}
                for kind, unit, inventory, value in [
                    ("-", "WT003", "RI001", 190000000),
                    ("DEV", "TON", "DEV", 13677),
                ]]
        data = RawDataset(source_table="KO_RSRC_BURUDG_QUTY", columns=list(rows[0]), row_count=2, rows=rows)
        with patch.object(KomisRawDataRepository, "_fetch_dataset", return_value=data), \
                patch("common.komis_raw.read_sql_pg", return_value=pd.DataFrame([("CL", "칠레", "Chile")], columns=["ntn_cd", "ntn_nm_ko", "ntn_nm_en"])):
            result = KomisRawDataRepository().fetch_mineral_country_ranking(
                metric="reserves", mineral_code="TEST", start_period="2024", end_period="2024", top_n=None)
        self.assertEqual(result.row_count, 1)
        self.assertEqual(result.rows[0]["country_code"], "CL")
        self.assertEqual(result.rows[0]["total"], 190000000)

    def test_unknown_resource_category_still_fails_closed(self):
        rows = [{"ntn_eng_cd": "CL", "crtr_yr": "2024", "se_cd": "GRADE_A",
                 "mass_unit_cd": "WT003", "rsrc_invt_cd": "RI001", "burudg_quty_ton": 190000000}]
        data = RawDataset(source_table="KO_RSRC_BURUDG_QUTY", columns=list(rows[0]), row_count=1, rows=rows)
        with patch.object(KomisRawDataRepository, "_fetch_dataset", return_value=data), \
                patch("common.komis_raw.read_sql_pg", return_value=pd.DataFrame([("CL", "칠레", "Chile")], columns=["ntn_cd", "ntn_nm_ko", "ntn_nm_en"])):
            with self.assertRaisesRegex(RawDataAccessError, "resource_population_unresolved_category"):
                KomisRawDataRepository().fetch_mineral_country_ranking(
                    metric="reserves", mineral_code="TEST", start_period="2024", end_period="2024", top_n=None)

    def test_actual_price_tool_exposes_missing_mapping_without_fetch_or_llm(self):
        from mcp.server.fastmcp import FastMCP
        from rag_core.ragkit import _mcp_tools_common as tools
        server = FastMCP("adapter-diagnostic-test")
        tools.register_common_tools(server)
        repo = Mock(spec=KomisRawDataRepository)
        repo.resolve_price_criterion_serials.return_value = []
        with patch.object(tools, "KomisRawDataRepository", return_value=repo):
            result = asyncio.run(server._tool_manager.get_tool("komis_raw_lookup").run(
                {"page_id": "price_minor_metals", "mineral_code": "TEST"}))
        self.assertEqual(result["evidence"], [])
        self.assertIn("price_criterion_mapping_missing:TEST", result["warnings"])
        repo.fetch.assert_not_called()
        repo.fetch_complete.assert_not_called()

    def test_source_policy_failure_has_priority_over_selection(self):
        call = ActionCall(requirement_id="price", action_id="price.series", slots=ActionSlots(mineral="텅스텐"))
        warnings = ["price_criterion_selection_required:TEST:1=A;2=B", "source_unavailable:unverified"]
        with patch.object(graph, "_retrieve_node", return_value={"evidence": [], "warnings": warnings}):
            result = graph.retrieve_evidence("", action_plan=ActionPlan(actions=[call]), llm=object(), include_action_results=True)
        self.assertEqual(result.action_results[0].status, "source_unavailable")
        self.assertEqual(result.action_results[0].failure_reason, "source_unavailable:unverified")


if __name__ == "__main__":
    unittest.main()
