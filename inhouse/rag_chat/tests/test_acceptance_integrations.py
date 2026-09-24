import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook

from rag_chat.tests import acceptance_integrations as integration


class RequiredChecksTest(unittest.TestCase):
    def test_duplicate_check_is_rejected_and_skipped_cannot_pass(self):
        ledger = integration._CheckLedger("AC40")
        ledger.record("fixed_doc_filter", "PASS")
        with self.assertRaises(AssertionError):
            ledger.record("fixed_doc_filter", "PASS")
        status, _, detail = ledger.finish([])
        self.assertEqual(status, "FAIL")
        self.assertEqual([item["id"] for item in detail["required_checks"]],
                         list(integration.REQUIRED_CHECK_IDS["AC40"]))
        self.assertEqual([item["status"] for item in detail["required_checks"]],
                         ["PASS", "SKIPPED", "SKIPPED"])


class RawFormatRelationshipTest(unittest.TestCase):
    def test_hwp_facts_on_other_commodity_row_fail(self):
        spec = {"context_anchor": "니켈", "original_facts": ["추가 하락 전망", "가격 추가 하락"]}
        rows = ["니켈 | 전망 없음", "구리 | 추가 하락 전망 | 가격 추가 하락"]
        with patch.object(integration, "_hwp_text_and_rows", return_value=(" ".join(rows), rows, None)):
            status, evidence, _ = integration._verify_hwp_original(Path("unused.hwp"), spec)
        self.assertEqual(status, "FAIL")
        self.assertEqual(evidence["matched_row_count"], 0)

    def test_excel_values_moved_to_unrelated_cells_fail(self):
        spec = integration.fixture("AC30")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Ni_Weda Bay_2025_Prod_AR_260814.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = spec["sheet"]
            sheet["B4"] = spec["unit"]
            sheet["D3"] = "광석"
            sheet["L3"] = "최종 금속량"
            sheet["D8"] = 41875
            sheet["L9"] = 303.7481341598289
            book.save(path)
            status, _, _ = integration._verify_excel_original(path, spec)
        self.assertEqual(status, "FAIL")

    def test_excel_okf_values_swapped_between_columns_fail(self):
        spec = integration.fixture("AC30")
        body = "\n".join([
            "| col1 | col2 | 광석 | 최종 금속량 |",
            "|---|---|---|---|",
            "| 광석 생산량(kwmt) | Saprolite+Limonite | 303.748134 | 41875 |",
        ])
        ok, evidence = integration._verify_excel_okf_table(body, spec)
        self.assertFalse(ok)
        self.assertFalse(all(item["matched"] for item in evidence["comparisons"]))

    def test_confirmed_source_hash_failure_wins_over_parser_blocked(self):
        spec = dict(integration.fixture("AC29"))
        spec["resource"] = "sample.hwp"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / spec["resource"]).write_bytes(b"wrong source bytes")
            page = SimpleNamespace(OKF_DOCUMENTS_ROOT=root)
            real_fixture = integration.fixture
            with patch.object(integration, "REPO_ROOT", root), \
                 patch.object(integration, "fixture", side_effect=lambda case_id: spec if case_id == "AC29" else real_fixture(case_id)), \
                 patch.object(integration, "_verify_hwp_original", return_value=("BLOCKED_ENV", {}, "parser unavailable")), \
                 patch.object(integration, "_dense_search", side_effect=OSError("model unavailable")):
                _, _, detail = integration._verify_document_case("AC29", [], page, object(), object())
        check = next(item for item in detail["required_checks"] if item["id"] == "original_metadata_provenance")
        self.assertEqual(check["status"], "FAIL")


class DenseContractTest(unittest.TestCase):
    def test_closed_db_client_is_environment_block(self):
        self.assertEqual(integration._exception_status(
            RuntimeError("Cannot send a request, as the client has been closed.")),
            "BLOCKED_ENV")

    def _hit(self, *, source_group="생산매장량_USGS"):
        spec = integration.fixture("AC39")
        return SimpleNamespace(
            dense_rank=1, chunk_id="chunk", doc_id=integration._vector_doc_id(spec["doc_id"]),
            source_path=spec["resource"], week=source_group, title="USGS 2026",
            section_heading="Lithium", text=spec["okf_fact"], score=0.9,
        )

    def test_normalized_vector_id_and_exact_fact_pass(self):
        spec = integration.fixture("AC39")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            okf = root / spec["okf_path"]
            okf.parent.mkdir(parents=True)
            okf.write_text(spec["okf_fact"], encoding="utf-8")
            tree = {"doc_id": spec["doc_id"], "resource": spec["resource"], "okf_path": spec["okf_path"]}
            with patch.object(integration, "_dense_search", return_value=[self._hit()]):
                status, _, detail = integration.verify_dense_fixture("AC39", tree=tree, okf_root=root)
        self.assertEqual(status, "PASS")
        self.assertEqual(detail["expected_doc_ranks"], [1])

    def test_public_private_source_result_is_rejected(self):
        spec = integration.fixture("AC39")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            okf = root / spec["okf_path"]
            okf.parent.mkdir(parents=True)
            okf.write_text(spec["okf_fact"], encoding="utf-8")
            tree = {"doc_id": spec["doc_id"], "resource": spec["resource"], "okf_path": spec["okf_path"]}
            with patch.object(integration, "_dense_search", return_value=[self._hit(source_group="Argus_비철금속_일일")]):
                status, _, _ = integration.verify_dense_fixture("AC39", tree=tree, okf_root=root)
        self.assertEqual(status, "FAIL")


class AC41MutationTest(unittest.TestCase):
    def _run(self, mutation=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        docs, trees = [], []
        for index in range(3):
            fact = f"fact-{index}"
            doc = {"resource": f"source/{index}.pdf", "doc_id": f"doc_{index:024x}",
                   "okf_path": f"group/{index}.md", "query": f"query-{index}", "fact": fact,
                   "line_start": 2, "line_end": 2}
            path = root / doc["okf_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"---\ndoc_id: {doc['doc_id']}\n---\n\n# Root\n{fact}\n", encoding="utf-8")
            doc["body_sha256"] = integration._body_sha256(path)
            tree = {"doc_id": doc["doc_id"], "resource": doc["resource"], "okf_path": doc["okf_path"],
                    "body_line_offset": integration._body_line_offset(path), "okf_body_sha256": doc["body_sha256"],
                    "structure": [{"node_id": "0000", "line_num": 1, "title": "Root", "nodes": []}]}
            docs.append(doc)
            trees.append(tree)
        if mutation == "tree_sha":
            trees[0]["okf_body_sha256"] = "STALE"
        if mutation == "tree_offset":
            trees[0]["body_line_offset"] += 1

        class FakePageIndex:
            OKF_DOCUMENTS_ROOT = root

            @staticmethod
            def search_nodes(query, *, doc, node_limit, exclude_source_groups):
                tree = next(item for item in trees if item["doc_id"] == doc)
                hit = {"doc_id": tree["doc_id"], "resource": tree["resource"], "okf_path": tree["okf_path"],
                       "body_line_offset": tree["body_line_offset"], "node_id": "0000", "line_num": 1}
                if doc == docs[0]["doc_id"]:
                    if mutation == "path": hit["okf_path"] = "forged.md"
                    if mutation == "resource": hit["resource"] = "forged.pdf"
                    if mutation == "hit_offset": hit["body_line_offset"] += 1
                    if mutation == "line": hit["line_num"] = 999999
                return [hit]

            @staticmethod
            def read_node_text(hit):
                if mutation == "read_text" and hit["doc_id"] == docs[0]["doc_id"]:
                    return docs[0]["fact"]
                tree = next(item for item in trees if item["doc_id"] == hit["doc_id"])
                return integration._independent_node_text(tree, hit, root / tree["okf_path"])[0]

        by_id = {doc["doc_id"]: doc for doc in docs}

        def fake_chunks(connect, settings, *, doc_id, source_path):
            doc = by_id[doc_id]
            text = integration._body_text(root / doc["okf_path"])
            return "PASS", [{"text": text, "dimension": 384}], None

        def expected_chunks(path):
            return {integration._body_text(path)}

        real_fixture = integration.fixture
        with patch.object(integration, "fixture", side_effect=lambda case_id: {"documents": docs} if case_id == "AC41" else real_fixture(case_id)), \
             patch.object(integration, "_fetch_chunks", side_effect=fake_chunks), \
             patch.object(integration, "_expected_chunk_texts", side_effect=expected_chunks):
            result = integration._verify_ac41(trees, FakePageIndex, object(), object())
        temp.cleanup()
        return result

    def test_valid_control_passes_with_complete_unique_checks(self):
        status, errors, detail = self._run()
        self.assertEqual((status, errors), ("PASS", []))
        checks = detail["required_checks"]
        self.assertEqual([item["id"] for item in checks], list(integration.REQUIRED_CHECK_IDS["AC41"]))
        self.assertTrue(all(item["status"] == "PASS" for item in checks))

    def test_each_single_forgery_fails(self):
        for mutation in ("tree_sha", "path", "resource", "tree_offset", "hit_offset", "line", "read_text"):
            with self.subTest(mutation=mutation):
                status, _, _ = self._run(mutation)
                self.assertEqual(status, "FAIL")


class AC40AdversarialTest(unittest.TestCase):
    def test_stale_tree_and_forged_hit_cannot_pass_on_fake_read_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "doc.md"
            path.write_text("---\ndoc_id: doc_test\n---\n\n# Root\nfixed fact\n", encoding="utf-8")
            digest = integration._body_sha256(path)
            spec = {"resource": "source.pdf", "doc_id": "doc_test", "okf_path": "doc.md", "query": "q",
                    "fact": "fixed fact", "line_start": 2, "line_end": 2, "body_sha256": digest}
            tree = {"resource": "source.pdf", "doc_id": "doc_test", "okf_path": "doc.md", "okf_body_sha256": "STALE",
                    "body_line_offset": integration._body_line_offset(path),
                    "structure": [{"node_id": "n", "line_num": 1, "nodes": []}]}
            page = SimpleNamespace(
                OKF_DOCUMENTS_ROOT=root,
                search_nodes=lambda *args, **kwargs: [{"resource": "wrong.pdf", "doc_id": "doc_test", "okf_path": "wrong.md",
                                                        "body_line_offset": 999, "node_id": "n", "line_num": 999999}],
                read_node_text=lambda hit: "fixed fact",
            )
            real_fixture = integration.fixture
            with patch.object(integration, "fixture", side_effect=lambda case_id: spec if case_id == "AC40" else real_fixture(case_id)):
                status, _, detail = integration._verify_ac40([tree], page)
        self.assertEqual(status, "FAIL")
        self.assertEqual([item["id"] for item in detail["required_checks"]], list(integration.REQUIRED_CHECK_IDS["AC40"]))


if __name__ == "__main__":
    unittest.main()
