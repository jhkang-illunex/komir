import unittest

from rag_core.ragkit.chatbot import _citation_sources, _source_footer
from rag_core.ragkit.official_sources import official_source_url
from rag_core.ragkit.renderers.citation import citation_sources
from rag_core.retrieval.evidence import Evidence


class OfficialSourceUrlTest(unittest.TestCase):
    def test_allowed_sources_resolve_to_their_official_landing_urls(self):
        cases = {
            "생산매장량_USGS/USGS_2026.md": "usgs.gov",
            "조달청보고서/20260616_주간_시장동향.md": "pps.go.kr",
            "KOTRA 국가정보": "kotra.or.kr",
            "IEA Global Critical Minerals Outlook 2025": "iea.org",
            "SCRREEN lithium factsheet": "scrreen.eu",
        }
        for source, domain in cases.items():
            with self.subTest(source=source):
                self.assertIn(domain, official_source_url(source))

    def test_unknown_source_does_not_receive_an_invented_url(self):
        self.assertIsNone(official_source_url("내부 산출물/검토 메모.md"))
        self.assertIsNone(official_source_url("내부/apps/report.md"))
        self.assertIsNone(official_source_url("검토 메모"))

    def test_citation_and_footer_expose_official_url_without_internal_path_contract(self):
        evidence = [Evidence(
            kind="pageindex", source="생산매장량_USGS/USGS_2026.md",
            section="리튬 생산량", text="원문", as_of="2026",
        )]
        citations = _citation_sources({1}, evidence)
        self.assertIn("official_url", citations[0])
        self.assertIn("usgs.gov", citations[0]["official_url"])
        self.assertEqual(citations[0]["source"], "USGS Mineral Commodity Summaries")
        self.assertNotIn("USGS_2026.md", citations[0]["source"])
        self.assertIn("공식 URL:", _source_footer({1}, evidence))

    def test_internal_database_source_is_replaced_in_user_citation(self):
        evidence = [Evidence(kind="structured", source="public.KO_MNRL_PRC", section="가격", text="표")]
        citation = _citation_sources({1}, evidence)[0]
        self.assertEqual(citation["source"], "KOMIS 공식 데이터")
        self.assertNotIn("source_id", citation)
        self.assertNotIn("public.KO_", _source_footer({1}, evidence))

    def test_structured_block_source_label_hides_internal_source(self):
        from rag_core.ragkit.chatbot import _evidence_source_label
        evidence = Evidence(kind="structured", source="public.KO_MNRL_PRC", section="가격", text="표")
        self.assertEqual(_evidence_source_label(evidence), "KOMIS 공식 데이터 · 가격")

    def test_menu_citation_uses_public_label_without_source_table_names(self):
        evidence = Evidence(
            kind="structured", source="public.KO_MNRL_PRC",
            section="KOMIS 원천 · KO_MNRL_PRC(니켈)", text="표",
            menu_page_id="price_base_metals",
        )
        citation = _citation_sources({1}, [evidence])[0]
        self.assertIn("광물자원가격", citation["section"])
        self.assertNotIn("source_tables", citation["menu_source"])
        self.assertNotIn("KO_MNRL_PRC", str(citation))
        self.assertNotIn("KO_MNRL_PRC", _source_footer({1}, [evidence]))

    def test_price_citation_uses_menu_and_hides_observation_period(self):
        evidence = [Evidence(
            kind="aggregated", source="public.KO_MNRL_PRC",
            section="KOMIS 원천 · KO_MNRL_PRC(니켈)", text="표",
            menu_page_id="price_base_metals", action_id="price.series",
            as_of="2025-09-29~2026-09-08, 지정 기간 내 관측 247건 전체",
            observed_period="2025-09-29~2026-09-08",
        )]
        citation = _citation_sources({1}, evidence)[0]
        shared_citation = citation_sources({1}, evidence)[0]
        self.assertIn("KOMIS 광물자원가격 > 비철금속", citation["section"])
        self.assertIsNone(citation["as_of"])
        self.assertIsNone(citation["observed_period"])
        self.assertEqual(shared_citation["section"], citation["section"])
        self.assertIsNone(shared_citation["as_of"])
        self.assertIsNone(shared_citation["observed_period"])
        self.assertNotIn("KO_MNRL_PRC", str(citation))
        self.assertNotIn("247건", str(citation))
        self.assertIn("KOMIS 광물자원가격 > 비철금속", _source_footer({1}, evidence))
        self.assertNotIn("247건", _source_footer({1}, evidence))


if __name__ == "__main__":
    unittest.main()
