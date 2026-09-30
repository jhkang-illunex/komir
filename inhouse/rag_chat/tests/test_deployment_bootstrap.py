import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import deployment_bootstrap as bootstrap


class FakeInspector:
    def __init__(self):
        self.tables = {
            ("ai_chatbot", "multihop_semantic_turn"): {"columns": ["session_id"], "row_count": 1},
            ("ai_chatbot", "schema_migration"): {"columns": ["component", "version"], "row_count": 1},
            ("public", "ai_mnrl_mst"): {"columns": ["mnrknd_unq_cd", "mnrl_nm_ko"], "row_count": 2},
            ("public", "ko_cstm_cmmrc"): {"columns": ["crtr_ymd", "incm_amt", "incm_weig"], "row_count": 10},
            ("public", "ko_mnrl_prc"): {"columns": ["crtr_ymd", "cmerc_prc"], "row_count": 10},
            ("public", "ko_rsrc_prdctn_quty"): {"columns": ["crtr_yr", "prdctn_quty_ton"], "row_count": 10},
            ("mineral_risk", "doc_chunk"): {"columns": ["chunk_id", "embedding"], "row_count": 10},
        }

    def close(self):
        return None

    def schema_exists(self, schema):
        return schema in {"public", "mineral_risk", "ai_chatbot"}

    def table_info(self, schema, table):
        value = self.tables.get((schema, table))
        return None if value is None else {"schema": schema, "table": table, **value}

    def migration_version(self, schema, component):
        return 1 if schema == "ai_chatbot" and component == "multihop_history" else None

    def entity_values(self, schema, table):
        return {"NI", "니켈"}


class DeploymentBootstrapTests(unittest.TestCase):
    def test_path_discovery_records_count_and_representative(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "one.tree.json").write_text("{}", encoding="utf-8")
            result = bootstrap._readable_path(str(path), ("*.tree.json",))
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["count"], 1)
            self.assertTrue(result["representative_readable"])

    def test_missing_vector_metadata_is_not_treated_as_compatible(self):
        result = bootstrap._vector_check(FakeInspector())
        self.assertEqual(result["status"], "REINDEX_REQUIRED")
        self.assertFalse(result["compatible"])
        self.assertIn("metadata", result["reason"])

    def test_manifest_is_degraded_without_destructive_or_guessed_vector_reuse(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "PG_DSN": "postgresql://fixture/db",
            "LLM_BASE_URL": "http://llm.fixture",
            "INGEST_DATA_LAKE_DIR": root,
            "MULTIHOP_HISTORY_SCHEMA": "ai_chatbot",
            "BOOTSTRAP_ENTITY_BINDINGS_JSON": "{}",
        }, clear=False), patch.object(bootstrap, "PostgresInspector", return_value=FakeInspector()), patch.object(
            bootstrap, "_probe_url", return_value={"available": True, "status_code": 200}
        ):
            data = Path(root)
            (data / "pageindex_trees").mkdir()
            (data / "pageindex_trees" / "a.tree.json").write_text("{}", encoding="utf-8")
            (data / "okf_documents").mkdir()
            (data / "okf_documents" / "a.md").write_text("fixture", encoding="utf-8")
            manifest = bootstrap.run()

        self.assertEqual(manifest["postgresql"]["history_store"]["migration_version"], 1)
        self.assertEqual(manifest["vector"]["status"], "REINDEX_REQUIRED")
        self.assertEqual(manifest["overall"]["status"], "DEGRADED")

    def test_entity_binding_reports_source_alias_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            pageindex = Path(root) / "trees"
            pageindex.mkdir()
            (pageindex / "nickel.tree.json").write_text("{}", encoding="utf-8")
            result = bootstrap._binding_check(
                {"니켈": {"postgres": ["NI"], "pageindex": ["nickel"], "okf": ["nickel"]}},
                {"NI"},
                {"pageindex": str(pageindex), "okf": str(Path(root) / "missing")},
            )
            self.assertEqual(result["status"], "MISMATCH")
            self.assertEqual({item["source"] for item in result["mismatches"]}, {"okf"})


if __name__ == "__main__":
    unittest.main()
