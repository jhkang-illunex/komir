"""Complete country retrieval: actual Action/MCP/repository over isolated SQL."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common import komis_raw
from rag_core.ragkit.action_contract import ActionCall, ActionSlots, Period
from rag_core.ragkit.chatbot_graph import _route_from_action_call
from rag_core.ragkit import chatbot_graph, mcp_client
from rag_core.ragkit import _mcp_tools_common as tools
from mcp.server.fastmcp import FastMCP


class ResourcePopulationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE ai_ntn_mst (ntn_cd TEXT, ntn_nm_ko TEXT, ntn_nm_en TEXT)")
        self.db.executemany("INSERT INTO ai_ntn_mst VALUES (?,?,?)", [
            ("CL", "칠레", "Chile"), ("PE", "페루", "Peru"), ("AU", "호주", "Australia"),
            ("C001", "국가001", "Country001"), ("C002", None, "Country002")])
        self.db.execute("CREATE TABLE ko_rsrc_prdctn_quty (mnrknd_unq_cd TEXT, crtr_yr TEXT, ntn_eng_cd TEXT, mass_unit_cd TEXT, prdctn_quty REAL, se_cd TEXT, prdctn_quty_ton REAL)")
        rows = [("TEST", "2024", f"C{i:03}", "WT002", i * 1000, "-", i) for i in range(1, 131)]
        rows += [("TEST", "2024", c, "WT002", 999999, "-", 999999) for c in ("SU", "OT")]
        rows += [("TEST", "2023", "C001", "WT002", 999999, "-", 999999)]
        self.db.executemany("INSERT INTO ko_rsrc_prdctn_quty VALUES (?,?,?,?,?,?,?)", rows)
        self.db.commit()
        self.queries = []
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(komis_raw, "read_sql_pg", side_effect=self.query))
        self.stack.enter_context(patch.object(komis_raw, "_column_comments", return_value={}))
        self.addCleanup(self.stack.close)
        self.addCleanup(self.db.close)

    def query(self, sql):
        self.queries.append(sql)
        return pd.read_sql_query(sql.replace("public.", ""), self.db)

    def fetch(self, **kwargs):
        return komis_raw.KomisRawDataRepository().fetch_mineral_country_ranking(
            metric="production", mineral_code="TEST", start_period="2024", end_period="2024", top_n=None, **kwargs)

    def test_complete_more_than_100_no_limit_summary_exclusion_and_unit(self):
        result = self.fetch()
        self.assertEqual(result.row_count, 130)
        self.assertEqual(sum(r["total"] for r in result.rows), 8515)
        self.assertNotIn("LIMIT", self.queries[0].upper())
        self.assertEqual(result.metadata["excluded_summary_codes"], {"SU": 1, "OT": 1})
        self.assertEqual(result.metadata["unit_basis"], "PRDCTN_QUTY_TON")
        self.assertEqual(result.unit, "톤")
        self.assertEqual({r["year"] for r in result.rows}, {"2024"})

    def test_unbounded_population_ignores_later_development_slice(self):
        self.db.executemany(
            "INSERT INTO ko_rsrc_prdctn_quty VALUES (?,?,?,?,?,?,?)",
            [("TEST", "2026", code, "TON", 100, "DEV", 100)
             for code in ("C001", "C002")],
        )
        result = komis_raw.KomisRawDataRepository().fetch_mineral_country_ranking(
            metric="production", mineral_code="TEST", start_period=None, end_period=None, top_n=None)
        self.assertEqual(result.row_count, 130)
        self.assertEqual({r["year"] for r in result.rows}, {"2024"})

    def test_zero_and_null_not_fabricated_or_dropped(self):
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET prdctn_quty_ton=NULL WHERE ntn_eng_cd='C001'")
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET prdctn_quty_ton=0 WHERE ntn_eng_cd='C002'")
        result = {r["country_code"]: r["total"] for r in self.fetch().rows}
        self.assertIsNone(result["C001"])
        self.assertEqual(result["C002"], 0)
        self.assertEqual(len(result), 130)

    def test_duplicate_country_year_rejected(self):
        self.db.execute("INSERT INTO ko_rsrc_prdctn_quty SELECT * FROM ko_rsrc_prdctn_quty WHERE ntn_eng_cd='C003'")
        with self.assertRaisesRegex(komis_raw.RawDataAccessError, "duplicate_country_year"):
            self.fetch()

    def test_unresolved_category_rejected(self):
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET se_cd='component' WHERE ntn_eng_cd='C003'")
        with self.assertRaisesRegex(komis_raw.RawDataAccessError, "unresolved_category"):
            self.fetch()

    def test_missing_unit_rejected_not_assumed(self):
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET mass_unit_cd=NULL WHERE ntn_eng_cd='C003'")
        with self.assertRaisesRegex(komis_raw.RawDataAccessError, "unit_unverified"):
            self.fetch()

    def test_negative_normalized_quantity_rejected(self):
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET prdctn_quty_ton=-1 WHERE ntn_eng_cd='C003'")
        with self.assertRaisesRegex(komis_raw.RawDataAccessError, "invalid_normalized_tonnes"):
            self.fetch()

    def route(self, **kwargs):
        return _route_from_action_call(ActionCall(requirement_id="resource", action_id="resource.rank",
            slots=ActionSlots(mineral="구리", metric="production", period=Period(kind="calendar_year", calendar_year=2024), **kwargs)), "")

    def test_typed_all_and_existing_aggregate_route(self):
        self.assertEqual(self.route(resource_population="all").komis_resource_population, "all")
        self.assertEqual(self.route(resource_operation="sum").komis_resource_population, "all")
        self.assertEqual(self.route(resource_operation="count").komis_resource_population, "all")
        self.assertIsNone(self.route().komis_resource_population)

    def test_explicit_top_n_is_preserved_and_all_conflict_rejected(self):
        route = self.route(resource_operation="sum", top_n=3)
        self.assertEqual(route.komis_ranking_top_n, 3)
        self.assertIsNone(route.komis_resource_population)
        with self.assertRaisesRegex(ValueError, "resource_population_conflict"):
            self.route(resource_population="all", top_n=3)

    def test_real_mcp_schema_and_tool_preserve_all_rows(self):
        server = FastMCP("population-test")
        tools.register_common_tools(server)
        tool = server._tool_manager.get_tool("komis_mineral_ranking")
        self.assertIn({"type": "null"}, tool.parameters["properties"]["top_n"]["anyOf"])
        with patch.object(komis_raw.KomisRawDataRepository, "resolve_mineral_meta", return_value=("구리", "KOMIS_SAMPLE")):
            result = asyncio.run(tool.run({"mineral_code": "TEST", "metric": "production", "start_period": "2024", "end_period": "2024", "top_n": None}))
        self.assertTrue(result["evidence"])
        text = result["evidence"][0]["text"]
        self.assertIn("C130", text)
        self.assertIn("C001", text)
        self.assertIn("population_complete: True", text)
        self.assertEqual(result["evidence"][0]["unit"], "톤")
        conflict = asyncio.run(tool.run({"mineral_code": "TEST", "metric": "production", "top_n": None, "share_only": True}))
        self.assertFalse(conflict["evidence"])
        self.assertIn("resource_population_conflict", conflict["warnings"][0])

    def test_graph_to_real_client_tool_and_sql_preserves_null_limit(self):
        server = FastMCP("adapter-population-test")
        tools.register_common_tools(server)
        tool = server._tool_manager.get_tool("komis_mineral_ranking")
        session = mcp_client._ProfileSession("public")
        calls = []
        def local_transport(name, args):
            calls.append((name, args))
            self.assertEqual(name, "komis_mineral_ranking")
            return asyncio.run(tool.run(args))
        with patch.object(session, "_call", side_effect=local_transport), \
                patch.object(session, "call_komis_resolve_mineral", return_value={"mineral_code": "TEST", "warnings": []}), \
                patch.object(mcp_client, "public", session), \
                patch.object(komis_raw.KomisRawDataRepository, "resolve_mineral_meta", return_value=("구리", "KOMIS_SAMPLE")):
            result = chatbot_graph._retrieve_node(
                {"route": self.route(resource_population="all"), "question": "", "profile": "public",
                 "source_assessment": SimpleNamespace(blocked=False)}, dense_k=1, pageindex_k=1)
        self.assertEqual(len(calls), 1)  # no dense/pageindex fallback
        self.assertIsNone(calls[0][1]["top_n"])
        self.assertEqual(calls[0][1]["start_period"], "2024")
        self.assertTrue(result["evidence"])
        self.assertIn("C130", result["evidence"][0].text)

    def test_reserves_complete_is_single_end_year_snapshot(self):
        self.db.execute("CREATE TABLE ko_rsrc_burudg_quty AS SELECT mnrknd_unq_cd,crtr_yr,ntn_eng_cd,mass_unit_cd,'RI001' rsrc_invt_cd,prdctn_quty burudg_quty,se_cd,prdctn_quty_ton burudg_quty_ton FROM ko_rsrc_prdctn_quty")
        result = komis_raw.KomisRawDataRepository().fetch_mineral_country_ranking(
            metric="reserves", mineral_code="TEST", start_period="2023", end_period="2024", top_n=None)
        self.assertEqual(result.row_count, 130)
        self.assertEqual({r["year"] for r in result.rows}, {"2024"})
        self.assertEqual(result.metadata["unit_basis"], "BURUDG_QUTY_TON")

    def test_master_name_and_code_both_preserved_with_unmapped_fallback(self):
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET ntn_eng_cd='CL' WHERE ntn_eng_cd='C003'")
        rows = self.fetch().rows
        chile = [r for r in rows if r["country"] == "칠레"]
        self.assertEqual([(r["country_code"], r["total"]) for r in chile], [("CL", 3)])
        by_code = {r["country_code"]: r for r in rows}
        self.assertEqual(by_code["C001"]["country"], "국가001")
        self.assertEqual(by_code["C002"]["country"], "C002")  # null master name
        self.assertEqual(by_code["C130"]["country"], "C130")  # absent master row
        self.assertEqual(len(rows), 130)
        self.assertEqual(sum(r["total"] for r in rows), 8515)

    def test_master_join_does_not_multiply_rows_and_conflicts_fail_closed(self):
        self.db.execute("INSERT INTO ai_ntn_mst VALUES ('C001','국가001','Country001')")
        self.assertEqual(self.fetch().row_count, 130)
        self.db.execute("INSERT INTO ai_ntn_mst VALUES ('C001','다른국가','Country001')")
        with self.assertRaisesRegex(komis_raw.RawDataAccessError, "ambiguous_country_master"):
            self.fetch()

    def test_named_country_survives_legacy_renderer_and_live_typed_adapter(self):
        from rag_core.retrieval.evidence import from_komis_aggregate
        from rag_core.ragkit.renderers.resource_rank import render_resource_operation
        from rag_core.ragkit.live_multihop import _typed_from_retrieval
        self.db.execute("UPDATE ko_rsrc_prdctn_quty SET ntn_eng_cd='CL' WHERE ntn_eng_cd='C003'")
        evidence = from_komis_aggregate(self.fetch(), label="전체 국가")
        action = ActionCall(requirement_id="resource", action_id="resource.rank", slots=ActionSlots(
            mineral="구리", metric="production", resource_population="all", resource_operation="country_value", resource_country="칠레"))
        rendered = render_resource_operation(evidence, SimpleNamespace(actions=[action]))
        self.assertIsNotNone(rendered)
        self.assertIn("칠레", rendered[0])
        typed = _typed_from_retrieval(SimpleNamespace(evidence=evidence, action_results=[]), action, input_entities=["구리"])
        chile = [r for r in typed.value if r["country"] == "칠레"]
        self.assertEqual(len(chile), 1)
        self.assertEqual(chile[0]["country_code"], "CL")
        self.assertEqual(chile[0]["country_name_en"], "Chile")
        # Markdown cells retain their textual representation until calculation.
        self.assertEqual(float(chile[0]["production_volume"]), 3)

    def test_multi_year_identity_remains_country_code_and_year(self):
        result = komis_raw.KomisRawDataRepository().fetch_mineral_country_ranking(
            metric="production", mineral_code="TEST", start_period="2023", end_period="2024", top_n=None)
        same_country = [r for r in result.rows if r["country"] == "국가001"]
        self.assertEqual({(r["country_code"], r["year"], r["total"]) for r in same_country},
                         {("C001", "2023", 999999), ("C001", "2024", 1)})
        self.assertEqual(result.row_count, 131)
        self.assertTrue(result.metadata["population_complete"])

    def test_english_master_names_multiple_countries_and_missing_names(self):
        for old, code in (("C003", "CL"), ("C004", "PE"), ("C005", "AU")):
            self.db.execute("UPDATE ko_rsrc_prdctn_quty SET ntn_eng_cd=? WHERE ntn_eng_cd=?", (code, old))
        self.db.execute("INSERT INTO ai_ntn_mst VALUES ('C006','국가006','   ')")
        rows = self.fetch().rows
        mapped = {r["country_code"]: r for r in rows}
        for code, ko, en in (("CL", "칠레", "Chile"), ("PE", "페루", "Peru"), ("AU", "호주", "Australia")):
            with self.subTest(code=code):
                self.assertEqual((mapped[code]["country"], mapped[code]["country_name_en"]), (ko, en))
        self.assertEqual(mapped["C002"]["country"], "C002")
        self.assertEqual(mapped["C002"]["country_name_en"], "Country002")
        self.assertIsNone(mapped["C006"]["country_name_en"])
        self.assertIsNone(mapped["C130"]["country_name_en"])
        self.assertEqual(len(rows), 130)
        self.assertEqual(sum(r["total"] for r in rows), 8515)

    def test_conflicting_english_master_name_is_rejected(self):
        self.db.execute("INSERT INTO ai_ntn_mst VALUES ('C001','국가001','Different Country')")
        with self.assertRaisesRegex(komis_raw.RawDataAccessError, "ambiguous_country_master"):
            self.fetch()


if __name__ == "__main__":
    unittest.main()
