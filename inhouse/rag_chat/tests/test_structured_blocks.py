# -*- coding: utf-8 -*-
"""구조화 블록(table·chart, public/private 공통)과 SSE 취소선 필터 단위 테스트 —
DB·LLM 없이 순수 함수만 검사한다(2026-09-13 private 전용 → 2026-09-16 공통)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.streaming import StrikethroughFilter, strip_strikethrough  # noqa: E402
from rag_core.ragkit.chatbot_events import (  # noqa: E402
    chart_spec, extract_markdown_tables, recommend_chart, table_block,
)

_PRICE_MD = """설명 문장.
| mnrl_prc_crtr_sn(광물가격기준순번) | crtr_ymd(기준일자) | lowst_prc(최저가격) | hghst_prc(최고가격) | uplmt(상한) |
| --- | --- | --- | --- | --- |
| 502.0 | 20260908 | 16410.62 | 17080.44 | None |
| 502.0 | 20260907 | None | 16733.26 | None |
| 502.0 | 20260904 | 16110.08 | 16767.64 | None |
| 502.0 | 20260903 | 16004.4 | 16657.64 | None |
끝."""

_RESERVE_MD = """| mnrknd_unq_cd(광종고유코드) | crtr_yr(기준년도) | ntn_eng_cd(국가코드 영문) | burudg_quty(매장량) | burudg_quty_ton([샘플확장] 매장량(톤환산)) |
| --- | --- | --- | --- | --- |
| MNRL1001 | 2026 | US | 19000.0 | 19000.0 |
| MNRL1001 | 2026 | ID | 38000.0 | 38000.0 |
| MNRL1001 | 2026 | CN | 275500.0 | 275500.0 |"""

_RESERVE_2Y_MD = """| crtr_yr(기준년도) | ntn_eng_cd(국가코드 영문) | burudg_quty(매장량) |
| --- | --- | --- |
| 2026 | US | 19000.0 |
| 2026 | CN | 275500.0 |
| 2025 | US | 18000.0 |
| 2025 | CN | 267235.0 |"""


class StructuredBlockTest(unittest.TestCase):
    def test_table_block_types_nulls_and_hint(self):
        table = extract_markdown_tables(_PRICE_MD)[0]
        self.assertTrue(table["markdown"].startswith("| mnrl_prc_crtr_sn"))
        block = table_block(table, block_id="t1-1", source_index=1, source_label="KOMIS · 가격")
        self.assertEqual(block["schema_version"], 1)
        # 내부 가격기준 순번은 표시에서 제거한다. "None" 셀이 있어도
        # 숫자열은 number, 전부 None인 열은 string으로 유지한다.
        self.assertEqual(
            [c["type"] for c in block["columns_meta"]],
            ["date", "number", "number", "string"],
        )
        self.assertEqual(block["columns_meta"][1]["display"], "최저가격")
        self.assertEqual(block["rows_typed"][0][1], 16410.62)
        self.assertIsNone(block["rows_typed"][1][1])
        self.assertEqual(block["rows"], [row[1:] for row in table["rows"]])
        self.assertEqual(block["chart_hint"]["recommended"], "line")
        self.assertNotIn("row_count", block["meta"])

    def test_time_series_line_spec(self):
        table = extract_markdown_tables(_PRICE_MD)[0]
        spec = chart_spec(table, block_id="c1-1", data_ref="t1-1", source_index=1, source_label="x")
        s = spec["spec"]
        self.assertEqual(s["kind"], "line")                  # 시점 4개 이상
        self.assertEqual((s["x"], s["x_type"], s["x_format"]), ("crtr_ymd", "date", "YYYYMMDD"))
        self.assertTrue(s["sort_x_ascending"])
        self.assertEqual(s["series"], ["lowst_prc", "hghst_prc"])  # 고정 식별자·전부 None 열 제외
        self.assertIsNone(s["group"])
        self.assertEqual(s["title"], "최저가격 · 최고가격")
        self.assertEqual(spec["data_ref"], "t1-1")

    def test_single_year_snapshot_bar_with_pie_alternative(self):
        table = extract_markdown_tables(_RESERVE_MD)[0]
        hint = recommend_chart(table)
        self.assertEqual(hint["recommended"], "bar")
        self.assertEqual(hint["alternatives"], ["pie"])      # 단일 계열·양수·범주 3개
        self.assertEqual((hint["x"], hint["x_type"]), ("ntn_eng_cd", "category"))
        self.assertEqual(hint["series"], ["burudg_quty"])    # 톤환산 중복 열은 계열에서 제외
        self.assertFalse(hint["sort_x_ascending"])

    def test_year_by_country_grouped(self):
        hint = recommend_chart(extract_markdown_tables(_RESERVE_2Y_MD)[0])
        self.assertEqual(hint["recommended"], "bar")         # 시점 2개 → bar
        self.assertEqual((hint["x"], hint["group"]), ("crtr_yr", "ntn_eng_cd"))
        self.assertEqual(hint["x_format"], "YYYY")

    def test_no_chart_without_numeric_series(self):
        table = extract_markdown_tables("| a | b |\n| --- | --- |\n| x | y |\n| z | w |")[0]
        self.assertIsNone(chart_spec(table, block_id="c", data_ref="t", source_index=None, source_label=None))
        self.assertIsNone(recommend_chart(table)["recommended"])


class StrikethroughFilterTest(unittest.TestCase):
    def test_footer_tildes_escaped(self):
        # 2026-09-16 실측(/prichat 코발트 광물종합지표 12개월): 출처 푸터의 기간
        # 표기 두 개 사이가 GFM 렌더러에서 취소선으로 그려졌다.
        footer = ("[1] KO_MNRL_SNTHS_INDX (기준시점 2026-08-11~2026-09-05)\n"
                  "[2] Argus Metal_비철금속_2023~2026_일일 (2023-09-21~2024-12).pdf")
        out = strip_strikethrough(footer)
        self.assertNotIn("~2026-09-05", out.replace("\\~", ""))  # 원문은 보존되고
        self.assertEqual(out.count("\\~"), 3)                      # 물결표는 전부 이스케이프
        self.assertEqual(out.replace("\\~", "~"), footer)

    def test_strike_spans_dropped_across_chunks(self):
        f = StrikethroughFilter()
        out = "".join(f.feed(c) for c in ["가격 ~", "~14,300~", "~ 14,500 ", "<de", "l>지움</del> 끝"])
        out += f.flush()
        self.assertEqual(out, "가격  14,500  끝")

    def test_unclosed_marker_becomes_literal_at_newline_and_flush(self):
        f = StrikethroughFilter()
        out = f.feed("열린 ~~ 마커\n다음줄 ~끝") + f.flush()
        self.assertEqual(out, "열린 \\~\\~ 마커\n다음줄 \\~끝")


if __name__ == "__main__":
    unittest.main()
