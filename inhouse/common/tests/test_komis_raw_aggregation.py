# -*- coding: utf-8 -*-
"""P1 결정적 RDB 집계의 반환값과 SQL 범위 회귀 테스트."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.komis_raw import KomisRawDataRepository  # noqa: E402


class MonthlyTradeAggregationTest(unittest.TestCase):
    def test_monthly_trade_uses_actual_months_and_keeps_amount_weight_separate(self):
        responses = [
            pd.DataFrame([
                ("202601", 100, 20, 2),
                ("202603", 300, 30, 1),
            ], columns=["month", "import_amount", "import_weight", "transaction_count"]),
            pd.DataFrame([("20260101", "20260331", 400, 50, 3, "정광")], columns=["available_start", "available_end", "period_total_amount", "period_total_weight", "period_transaction_count", "item_names"]),
        ]
        queries: list[str] = []

        def read(query: str):
            queries.append(query)
            return responses.pop(0)

        with patch("common.komis_raw.read_sql_pg", side_effect=read):
            data = KomisRawDataRepository().fetch_monthly_trade_summary(
                hs_codes=["2603000000"], start_period="202601", end_period="202612",
            )

        self.assertEqual([row["month"] for row in data.rows], ["2026-01", "2026-03"])
        self.assertEqual(data.rows[0]["import_amount"], 100)
        self.assertEqual(data.rows[0]["import_weight"], 20)
        self.assertEqual(data.metadata["available_end"], "2026-03-31")
        self.assertEqual(data.metadata["period_total_amount"], 400)
        self.assertEqual(data.metadata["period_total_weight"], 50)
        self.assertIn("LEFT(CRTR_YMD, 6)", queries[0])
        self.assertIn("SUM(INCM_AMT)", queries[0])
        self.assertIn("SUM(INCM_WEIG)", queries[0])

    def test_explicit_hs_never_expands_to_a_mineral_hs_population(self):
        responses = [
            pd.DataFrame([], columns=["month", "import_amount", "import_weight", "transaction_count"]),
            pd.DataFrame([(None, None, None, None, None, None)], columns=["available_start", "available_end", "period_total_amount", "period_total_weight", "period_transaction_count", "item_names"]),
        ]
        queries: list[str] = []
        with patch("common.komis_raw.read_sql_pg", side_effect=lambda query: (queries.append(query), responses.pop(0))[1]):
            data = KomisRawDataRepository().fetch_explicit_hs_import_summary(
                hs_code="2603000000", start_period=None, end_period=None,
            )
        self.assertEqual(data.metadata["scope"], "explicit_hs_only")
        self.assertEqual(data.metadata["hs_code"], "2603000000")
        self.assertIn("HS_CD IN ('2603000000')", queries[0])
        self.assertNotIn("ai_hs_mnrl_map", queries[0])


class PriceComparisonAggregationTest(unittest.TestCase):
    def test_price_dummy_status_uses_selected_criterion_not_mineral_master(self):
        captured: list[str] = []
        dummy_rows = pd.DataFrame([(900002,)], columns=["serial"])
        with patch("common.komis_raw.read_sql_pg", side_effect=lambda query: (captured.append(query), dummy_rows)[1]):
            status = KomisRawDataRepository().price_criteria_have_dummy_rows([502, 900002])

        self.assertEqual(status, {502: False, 900002: True})
        self.assertIn("tbl_nm = 'ko_mnrl_prc'", captured[0])
        self.assertIn("SPLIT_PART(nat_key, '|', 1)", captured[0])
        self.assertNotIn("ko_data_src_cd", captured[0])

    def test_price_criterion_metadata_keeps_raw_unit_codes(self):
        metadata = pd.DataFrame([("LME CASH", "PR001", "WT002")],
                                columns=["prc_crtr", "prc_unit_cd", "weig_unit_cd"])
        with patch("common.komis_raw.read_sql_pg", return_value=metadata):
            result = KomisRawDataRepository().resolve_price_criterion_metadata(502)

        self.assertEqual(result, ("LME CASH", "PR001", "WT002"))

    def test_price_comparison_uses_common_available_window_and_signed_change(self):
        criteria = pd.DataFrame([
            ("니켈", 502, "LME CASH", "PR001", "WT002", "20260101", "20261231"),
            ("동", 709, "LME CASH", "PR001", "WT002", "20260201", "20261130"),
        ], columns=["mineral", "serial", "prc_crtr", "prc_unit_cd", "weig_unit_cd", "available_start", "available_end"])
        series = pd.DataFrame([
            ("니켈", "20260201", 100, 502, "LME CASH", "PR001", "WT002"),
            ("니켈", "20261130", 80, 502, "LME CASH", "PR001", "WT002"),
            ("동", "20260201", 50, 709, "LME CASH", "PR001", "WT002"),
            ("동", "20261130", 75, 709, "LME CASH", "PR001", "WT002"),
        ], columns=["mineral", "price_date", "price", "price_criterion_serial", "price_criterion", "price_currency_code", "weight_unit_code"])
        queries: list[str] = []
        with patch("common.komis_raw.read_sql_pg", side_effect=lambda query: (queries.append(query), criteria if len(queries) == 1 else series)[1]):
            data = KomisRawDataRepository().fetch_price_comparison(
                mineral_names=["니켈", "구리"], start_period="2026", end_period="2026",
            )

        self.assertEqual(data.metadata["common_available_start"], "2026-02-01")
        self.assertEqual(data.metadata["common_available_end"], "2026-11-30")
        self.assertEqual(data.metadata["common_actual_start"], "2026-02-01")
        self.assertEqual(data.metadata["common_actual_end"], "2026-11-30")
        comparison = {row["mineral"]: row for row in data.metadata["comparison"]}
        self.assertEqual(comparison["구리"]["pct_change"], 50.0)
        self.assertEqual(comparison["니켈"]["pct_change"], -20.0)
        self.assertTrue(all(row["price_date"] in {"2026-02-01", "2026-11-30"} for row in data.rows))
        self.assertIn("p.crtr_ymd >= '20260201'", queries[1])
        self.assertIn("p.crtr_ymd <= '20261130'", queries[1])
        self.assertIn("KO_MNRL_PRC_CRTR", queries[0])
        self.assertIn("'동'", queries[0])
        self.assertEqual(data.metadata["missing_minerals"], [])


if __name__ == "__main__":
    unittest.main()
