import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.retrieval.news import mentioned_countries, mentioned_minerals, _query_terms  # noqa: E402


class NewsMetadataTest(unittest.TestCase):
    def test_extracts_only_explicit_article_minerals_and_countries(self):
        text = "중국이 니켈·흑연 수출통제를 검토하고 호주 공급망을 언급했다."
        self.assertEqual(mentioned_minerals(text), ["니켈", "흑연"])
        self.assertEqual(mentioned_countries(text), ["중국", "호주"])

    def test_export_control_query_uses_searchable_terms(self):
        terms = _query_terms("중국 수출통제 뉴스에 나온 니켈 알려줘")
        self.assertEqual(terms, ["니켈", "수출통제"])


if __name__ == "__main__":
    unittest.main()
