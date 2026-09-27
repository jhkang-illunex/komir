# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.chatbot import _resource_rank_citation_indices


class ResourceRankCitationTest(unittest.TestCase):
    def test_combined_production_and_reserves_includes_both_sources(self):
        evidence = [
            SimpleNamespace(
                source="public.KO_RSRC_PRDCTN_QUTY",
                section="희토류 생산량 상위",
                text="| 국가 | 생산량합계(톤) |\n| --- | --- |\n| 중국 | 1 |",
            ),
            SimpleNamespace(
                source="public.KO_RSRC_BURUDG_QUTY",
                section="희토류 매장량 상위",
                text="| 국가 | 매장량합계(톤) |\n| --- | --- |\n| 중국 | 2 |",
            ),
        ]
        self.assertEqual(
            _resource_rank_citation_indices(evidence, "희토류 생산량과 매장량 상위 국가를 알려줘"),
            {1, 2},
        )

    def test_single_metric_does_not_force_unrelated_sources(self):
        evidence = [SimpleNamespace(source="public.KO_RSRC_PRDCTN_QUTY", section="", text="")]
        self.assertEqual(_resource_rank_citation_indices(evidence, "희토류 생산량 상위 국가는?"), set())


if __name__ == "__main__":
    unittest.main()
