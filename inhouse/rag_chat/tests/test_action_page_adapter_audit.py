# -*- coding: utf-8 -*-
"""기존 챗봇 메뉴·원자료 요구의 typed page adapter 독립 검수."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_chat.app.page_recommend.registry import load_source_registry  # noqa: E402
from rag_chat.app.page_recommend.service import PageRecommendService  # noqa: E402


class ActionPageAdapterAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = PageRecommendService(
            registry=load_source_registry(), llm=SimpleNamespace())

    def test_natural_menu_name_resolves_to_registered_page(self):
        result = self.service.recommend_action_target("광물지도", thread_id="audit-menu")
        self.assertEqual(result.response.recommendations[0].page_id, "map_mineral")
        self.assertEqual(result.response.recommendations[0].url, "/Komis/MnrlMap/MnrlMap")

    def test_natural_dataset_name_resolves_to_registered_page(self):
        result = self.service.recommend_action_target("수급동향지표", thread_id="audit-dataset")
        self.assertEqual(result.response.recommendations[0].page_id, "indicator_supply")

    def test_full_dataset_request_resolves_without_discarding_mineral(self):
        result = self.service.recommend_action_target(
            "supply_stability", thread_id="audit-full-data", mineral="NI")
        self.assertEqual(result.response.recommendations[0].page_id, "indicator_supply")
        self.assertIn("NI", result.response.answer)

    def test_menu_answer_contains_full_path_and_navigation_prompt(self):
        result = self.service.recommend_action_target("map_mineral", thread_id="audit-path")
        self.assertIn("KOMIS > 핵심광물지도 > 광물지도", result.response.answer)
        self.assertIn("바로 이동하시겠어요?", result.response.answer)


if __name__ == "__main__":
    unittest.main()
