import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.retrieval.mineral_info import fetch_mineral_info_evidence  # noqa: E402


class MineralInfoResourceTest(unittest.TestCase):
    def test_manganese_and_tungsten_have_verified_structured_records(self):
        for mineral, symbol, atomic_number, use_fragment in (
            ("망간", "Mn", "25", "강철"),
            ("텅스텐", "W", "74", "텅스텐 카바이드"),
        ):
            evidence, warnings = fetch_mineral_info_evidence(mineral)
            self.assertFalse(warnings)
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].source, "Royal Society of Chemistry")
            self.assertIn(f"| {mineral} | element_symbol | {symbol} |", evidence[0].text)
            self.assertIn(f"| {mineral} | atomic_number | {atomic_number} |", evidence[0].text)
            self.assertIn(use_fragment, evidence[0].text)


if __name__ == "__main__":
    unittest.main()
