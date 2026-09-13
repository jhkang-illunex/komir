# -*- coding: utf-8 -*-
"""/prichat 전용 구조화 블록(table·chart) 단위 테스트 — DB·LLM 없이
chatbot_events의 순수 함수만 검사한다(2026-09-13)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.chatbot_events import chart_spec, extract_markdown_tables, table_block  # noqa: E402

_MD = """설명 문장.
| crtr_ymd(기준일자) | 최저가 | 최고가 | mnrl_prc_crtr_sn |
| --- | --- | --- | --- |
| 20260912 | 14,300 | 14,500 | 7 |
| 20260910 | 14,390 | 14,850 | 7 |
| 20260911 | 14,200 | 14,600 | 7 |
| 20260909 | 14,672 | 14,900 | 7 |
끝."""


class PrivateBlockTest(unittest.TestCase):
    def test_table_block_types_and_markdown(self):
        table = extract_markdown_tables(_MD)[0]
        self.assertTrue(table["markdown"].startswith("| crtr_ymd"))
        block = table_block(table, block_id="t1-1", source_index=1, source_label="KOMIS · 가격")
        self.assertEqual(block["schema_version"], 1)
        self.assertEqual([c["type"] for c in block["columns_meta"]], ["date", "number", "number", "number"])
        self.assertEqual(block["columns_meta"][0]["key"], "crtr_ymd")
        self.assertEqual(block["rows_typed"][0][1], 14300.0)
        self.assertEqual(block["rows"], table["rows"])  # 구 클라이언트 호환 키 유지
        self.assertEqual(block["meta"]["source_index"], 1)

    def test_chart_spec_mirrors_png_rules(self):
        table = extract_markdown_tables(_MD)[0]
        spec = chart_spec(table, block_id="c1-1", data_ref="t1-1", source_index=1, source_label="x")
        self.assertEqual(spec["spec"]["kind"], "line")          # 4행 이상 → line
        self.assertEqual(spec["spec"]["x"], "crtr_ymd")          # 날짜열 우선
        self.assertTrue(spec["spec"]["sort_x_ascending"])
        self.assertEqual(spec["spec"]["series"], ["최저가", "최고가"])  # 고정값 열(mnrl_prc_crtr_sn) 제외
        self.assertEqual(spec["data_ref"], "t1-1")

    def test_chart_spec_none_without_numeric_series(self):
        table = extract_markdown_tables("| a | b |\n| --- | --- |\n| x | y |\n| z | w |")[0]
        self.assertIsNone(chart_spec(table, block_id="c", data_ref="t", source_index=None, source_label=None))


if __name__ == "__main__":
    unittest.main()
