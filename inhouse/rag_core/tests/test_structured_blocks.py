# -*- coding: utf-8 -*-
"""사용자용 정형 근거 표현과 원천 감사 데이터의 경계 회귀."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.retrieval.evidence import from_komis_raw


class StructuredBlockPresentationTest(unittest.TestCase):
    def test_raw_price_serial_is_not_in_prompt_table_but_raw_dataset_is_unchanged(self):
        rows = [
            {"mnrl_prc_crtr_sn": 502, "crtr_ymd": "20260902", "cmerc_prc": 15100},
            {"mnrl_prc_crtr_sn": 502, "crtr_ymd": "20260901", "cmerc_prc": 15000},
        ]
        dataset = SimpleNamespace(
            source_table="KO_MNRL_PRC",
            columns=["mnrl_prc_crtr_sn", "crtr_ymd", "cmerc_prc"],
            column_labels={"mnrl_prc_crtr_sn": "가격기준일련번호"},
            rows=rows,
            row_count=2,
            metadata={"period_range_complete": True},
            unit="USD/t",
        )

        evidence = from_komis_raw("price_base_metals", [dataset])[0]

        self.assertNotIn("mnrl_prc_crtr_sn", evidence.text)
        self.assertIn("cmerc_prc", evidence.text)
        self.assertEqual(dataset.columns[0], "mnrl_prc_crtr_sn")
        self.assertEqual(dataset.row_count, 2)

    def test_display_period_keeps_range_and_partial_status_without_count(self):
        complete = SimpleNamespace(
            source_table="KO_MNRL_PRC", columns=["crtr_ymd", "cmerc_prc"],
            column_labels={}, rows=[
                {"crtr_ymd": "20260902", "cmerc_prc": 15100},
                {"crtr_ymd": "20260901", "cmerc_prc": 15000},
            ], row_count=2, metadata={"period_range_complete": True}, unit="USD/t",
        )
        partial = SimpleNamespace(
            source_table="KO_MNRL_PRC", columns=["crtr_ymd", "cmerc_prc"],
            column_labels={}, rows=[
                {"crtr_ymd": "20260902", "cmerc_prc": 15100},
                {"crtr_ymd": "20260901", "cmerc_prc": 15000},
            ], row_count=2, metadata={"period_range_complete": False}, unit="USD/t",
        )

        complete_period = from_komis_raw("price_base_metals", [complete])[0].as_of
        partial_period = from_komis_raw("price_base_metals", [partial])[0].as_of

        self.assertEqual(complete_period, "2026-09-01~2026-09-02, 지정 기간 내 관측 2건 전체")
        self.assertEqual(partial_period, "2026-09-01~2026-09-02, 최신순 2건만, 최신 일부 관측치 제공됨(요청한 전체 기간이 아닐 수 있음)")


if __name__ == "__main__":
    unittest.main()
