# -*- coding: utf-8 -*-
"""`ingest/pageindex/build_pageindex_trees.py` 전처리 함수 단위 테스트 —
파일 I/O·LLM 없이 순수 문자열 함수만 검사한다.

    cd inhouse && python -m unittest ingest.tests.test_build_pageindex_trees
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest.pageindex.build_pageindex_trees import (  # noqa: E402
    demote_numeric_only_headings,
    fix_blank_heading_titles,
)


class DemoteNumericOnlyHeadingsTest(unittest.TestCase):
    def test_demotes_currency_percent_unit_only_heading(self):
        # 2026-09-17 실측(BHP Escondida 연차보고서) — mine_aggregate.py 값
        # 흔들림의 근본 원인이었던 실제 헤딩 문자열.
        text = "### Escondida\n\n### 1,305 kt 16% US$1.19/lb 18% US$8.6 bn 49%\n\nFY24 1,125 kt\n"
        out = demote_numeric_only_headings(text)
        lines = out.splitlines()
        self.assertEqual(lines[0], "### Escondida")  # 진짜 제목은 그대로
        self.assertEqual(lines[2], "1,305 kt 16% US$1.19/lb 18% US$8.6 bn 49%")  # 헤딩 마커만 제거

    def test_demotes_short_currency_headings(self):
        for heading in ("### US$9.0 bn 14%", "### US$10.4 bn", "### US$9.8 bn 6%"):
            with self.subTest(heading=heading):
                out = demote_numeric_only_headings(heading + "\n")
                self.assertFalse(out.lstrip().startswith("#"), out)

    def test_keeps_real_titles_untouched(self):
        for heading in (
            "### Escondida",
            "### Financial results Payments to governments",
            "###### Copper Production (in kt)",
            "### Safety Operational excellence Improvement in key metrics Record copper and iron ore production",
        ):
            with self.subTest(heading=heading):
                out = demote_numeric_only_headings(heading + "\n")
                self.assertEqual(out, heading + "\n")

    def test_preserves_line_count(self):
        # body_line_offset/line_num이 깨지면 안 되므로 줄 수가 절대 안 바뀐다.
        text = "# Title\n\n### 1,305 kt 16%\n\nbody text\n"
        out = demote_numeric_only_headings(text)
        self.assertEqual(len(out.splitlines()), len(text.splitlines()))

    def test_composes_with_fix_blank_heading_titles(self):
        # build_tree_for_okf()가 두 전처리를 순서대로 거는 것과 같은 순서.
        text = "###   \n\n### 1,305 kt 16%\nEscondida detail\n"
        out = demote_numeric_only_headings(fix_blank_heading_titles(text))
        self.assertEqual(len(out.splitlines()), len(text.splitlines()))
        self.assertFalse(out.splitlines()[2].startswith("#"))


if __name__ == "__main__":
    unittest.main()
