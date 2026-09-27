import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.action_contract import ActionCall, ActionSlots, Period  # noqa: E402
from rag_core.retrieval.cross_rank import fetch_cross_rank_evidence  # noqa: E402


class _Repo:
    def fetch_country_import_mineral_shares(self, **kwargs):
        return SimpleNamespace(rows=[{"mineral_code": "MNRL1", "mineral": "리튬", "data_source": "KOMIS_SAMPLE", "country": "중국", "share_pct": 60.0, "first_date": "20260101", "last_date": "20261231"}])

    def fetch_top_producer_mineral_shares(self, **kwargs):
        return SimpleNamespace(rows=[{"mineral_code": "MNRL1", "mineral": "리튬", "data_source": "KOMIS_SAMPLE", "country": "호주", "share_pct": 60.0, "year": 2025}])

    def fetch_price_comparison(self, **kwargs):
        return SimpleNamespace(metadata={"comparison": [{"mineral": "리튬", "start_date": "20260101", "end_date": "20261231", "pct_change": 12.5, "price_criterion": "LME Cash", "price_currency_code": "USD", "weight_unit_code": "TON"}]})

    def resolve_price_criterion_serials(self, mineral):
        return [1]

    def price_criteria_have_dummy_rows(self, serials):
        return {1: False}


class CrossRankTest(unittest.TestCase):
    def test_import_country_share_and_price(self):
        call = ActionCall(requirement_id="x", action_id="trade.price_cross_rank",
                          slots=ActionSlots(partner_country="중국", metric="import_amount",
                                            period=Period(kind="calendar_year", calendar_year=2026)))
        evidence, warnings = fetch_cross_rank_evidence(call, today=__import__("datetime").date(2026, 12, 31), repo=_Repo())
        self.assertFalse(warnings)
        self.assertIn("share_pct", evidence[0].text)
        self.assertIn("12.5", evidence[0].text)

    def test_producer_share_excludes_total_row_by_contract(self):
        call = ActionCall(requirement_id="x", action_id="resource.price_cross_rank",
                          slots=ActionSlots(metric="production", reference_year=2025))
        evidence, warnings = fetch_cross_rank_evidence(call, repo=_Repo())
        self.assertFalse(warnings)
        self.assertIn("호주", evidence[0].text)


if __name__ == "__main__":
    unittest.main()
