# -*- coding: utf-8 -*-
"""P1 Q03/Q12 차트 메타데이터 회귀 테스트."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.chatbot_events import chart_spec, extract_markdown_tables, recommend_chart


def _table(text: str) -> dict:
    return extract_markdown_tables(text)[0]


class ChartMetadataRegressionTest(unittest.TestCase):
    def test_trade_share_excludes_rank_code_count_and_amount(self):
        table = _table(
            "| rank(순위) | hs_cd(HS코드) | country(국가) | total(수입금액합계(USD)) | share_pct(비중(%)) | transaction_count(거래건수) | crtr_ymd(기준일자) |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | 2603000000 | A | 800 | 80 | 4 | 20260901 |\n"
            "| 2 | 2603000000 | B | 200 | 20 | 2 | 20260901 |"
        )
        hint = recommend_chart(table)
        self.assertEqual(hint["series"], ["share_pct"])
        self.assertNotIn(hint["x"], {"rank", "hs_cd", "transaction_count", "crtr_ymd"})
        spec = chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="x")
        assert spec is not None
        self.assertEqual(spec["spec"]["y_unit"], "%")
        self.assertNotIn("rank", spec["spec"]["series"])

    def test_production_and_reserve_use_tonnes(self):
        for label in ("생산량합계(톤)", "매장량합계(톤)"):
            table = _table(
                f"| rank(순위) | country(국가) | total({label}) | share_pct(비중(%)) | record_count(레코드건수) |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| 1 | A | 800 | 80 | 4 |\n"
                "| 2 | B | 200 | 20 | 2 |"
            )
            spec = chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="x")
            assert spec is not None
            self.assertEqual(spec["spec"]["series"], ["total"])
            self.assertEqual(spec["spec"]["y_unit"], "톤")

    def test_price_comparison_uses_only_change_rate_and_dates_are_x_only(self):
        table = _table(
            "| rank(순위) | mineral(광종) | first_date(시작일) | first_price(시작가격(USD)) | last_date(종료일) | last_price(종료가격(USD)) | pct_change(변동률(%)) |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | Co | 20260902 | 100 | 20260908 | 95 | -5 |\n"
            "| 2 | Ni | 20260902 | 200 | 20260908 | 210 | 5 |"
        )
        hint = recommend_chart(table)
        self.assertEqual(hint["series"], ["pct_change"])
        self.assertNotIn("first_date", hint["series"])
        self.assertNotIn("last_date", hint["series"])
        spec = chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="x")
        assert spec is not None
        self.assertEqual(spec["spec"]["y_unit"], "%")

    def test_price_long_form_groups_each_mineral_and_preserves_basis_unit(self):
        table = _table(
            "| mineral(광종) | price_date(가격일자) | price(가격) | price_criterion(가격기준) | price_unit(가격단위) |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 코발트 | 20260901 | 100 | LME 현물 | USD/t |\n"
            "| 니켈 | 20260901 | 200 | LME 현물 | USD/t |\n"
            "| 코발트 | 20260902 | 105 | LME 현물 | USD/t |\n"
            "| 니켈 | 20260902 | 198 | LME 현물 | USD/t |"
        )
        hint = recommend_chart(table)
        self.assertEqual(hint["x"], "price_date")
        self.assertEqual(hint["group"], "mineral")
        self.assertEqual(hint["series"], ["price"])
        spec = chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="x")
        assert spec is not None
        self.assertEqual(spec["spec"]["price_criterion"], "LME 현물")
        self.assertEqual(spec["spec"]["price_unit"], "USD/t")
        self.assertEqual(spec["spec"]["y_unit"], "USD/t")

    def test_price_long_form_terra_codes_drive_unit_and_serial_is_excluded(self):
        table = _table(
            "| mineral(광종) | price_date(가격일자) | price(가격) | price_criterion_serial(가격기준순번) | price_criterion(가격기준) | price_currency_code(통화코드) | weight_unit_code(중량단위코드) |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 코발트 | 20260901 | 100 | 502 | LME 현물 | USD | KG |\n"
            "| 니켈 | 20260901 | 200 | 502 | LME 현물 | USD | KG |\n"
            "| 코발트 | 20260902 | 105 | 502 | LME 현물 | USD | KG |\n"
            "| 니켈 | 20260902 | 198 | 502 | LME 현물 | USD | KG |"
        )
        hint = recommend_chart(table)
        self.assertEqual(hint["series"], ["price"])
        spec = chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="x", unit="UNKNOWN")
        assert spec is not None
        self.assertEqual(spec["spec"]["y_unit"], "USD/kg")
        self.assertEqual(spec["spec"]["price_currency_code"], "USD")
        self.assertEqual(spec["spec"]["weight_unit_code"], "KG")

    def test_unknown_price_codes_do_not_invent_y_unit(self):
        table = _table(
            "| mineral(광종) | price_date(가격일자) | price(가격) | price_currency_code(통화코드) | weight_unit_code(중량단위코드) |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 코발트 | 20260901 | 100 | UNKNOWN | ??? |\n"
            "| 니켈 | 20260901 | 200 | UNKNOWN | ??? |"
        )
        spec = chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="x", unit="UNKNOWN")
        assert spec is not None
        self.assertIsNone(spec["spec"]["y_unit"])

    def test_month_period_uses_year_month_x_format(self):
        table = _table(
            "| month(월) | import_amount(수입금액(USD)) |\n"
            "| --- | --- |\n"
            "| 2026-01 | 100 |\n"
            "| 2026-02 | 120 |\n"
            "| 2026-03 | 115 |\n"
            "| 2026-04 | 130 |"
        )
        hint = recommend_chart(table)
        self.assertEqual(hint["x"], "month")
        self.assertEqual(hint["x_format"], "YYYY-MM")
        self.assertEqual(hint["series"], ["import_amount"])


if __name__ == "__main__":
    unittest.main()
