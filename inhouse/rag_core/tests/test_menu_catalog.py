import unittest

from rag_core.ragkit.chatbot import _citation_sources, _evidence_source_label
from rag_core.ragkit.menu_catalog import menu_catalog, menu_source
from rag_core.retrieval.evidence import Evidence


class MenuCatalogTest(unittest.TestCase):
    def test_report_gen_catalog_has_three_menus_and_eleven_pages(self):
        catalog = menu_catalog()
        self.assertEqual(len(catalog), 11)
        self.assertEqual(menu_source("map_korea")["source_label"], "KOMIS 핵심광물지도 > 수급지도 > 대한민국")

    def test_only_menu_bound_rdb_evidence_uses_menu_source(self):
        rdb = Evidence(kind="structured", source="public.KO_CSTM_CMMRC", section="원천", text="x", menu_page_id="map_korea")
        document = Evidence(kind="pageindex", source="보고서.pdf", section="본문", text="x")
        self.assertTrue(_evidence_source_label(rdb).startswith("KOMIS 핵심광물지도"))
        self.assertEqual(_evidence_source_label(document), "보고서.pdf · 본문")
        citations = _citation_sources({1, 2}, [rdb, document])
        self.assertEqual(citations[0]["menu_source"]["page_id"], "map_korea")
        self.assertIsNone(citations[1]["menu_source"])


if __name__ == "__main__":
    unittest.main()
