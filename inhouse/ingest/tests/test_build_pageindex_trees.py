# -*- coding: utf-8 -*-
"""`ingest/pageindex/build_pageindex_trees.py` 전처리 함수 단위 테스트 —
파일 I/O·LLM 없이 순수 문자열 함수만 검사한다.

    cd inhouse && python -m unittest ingest.tests.test_build_pageindex_trees
"""
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest.pageindex.build_pageindex_trees import (  # noqa: E402
    demote_numeric_only_headings,
    fix_blank_heading_titles,
    restore_document_title_heading,
    build_all,
    main,
    okf_body_sha256,
    tree_is_fresh_for_okf,
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

    def test_restores_only_document_title_when_demoted_title_was_sole_heading(self):
        text = "# 11.27\n\nOCR 본문\n"
        demoted = demote_numeric_only_headings(text)
        restored = restore_document_title_heading(demoted, "11.27")
        self.assertEqual(restored, text)
        self.assertEqual(len(restored.splitlines()), len(text.splitlines()))
        self.assertEqual(
            restore_document_title_heading("1,305 kt\n본문\n", "Escondida"),
            "1,305 kt\n본문\n",
        )


class PageIndexFreshnessTest(unittest.TestCase):
    def test_metadata_only_change_keeps_tree_fresh(self):
        """메타 동기화는 재요약 없이 가능하고, 트리 입력 본문은 그대로다."""

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            okf = root / "report.md"
            tree = root / "report.tree.json"
            okf.write_text("---\ntitle: 최초 제목\n---\n\n# 본문\n원문\n", encoding="utf-8")
            tree.write_text(
                json.dumps({"okf_body_sha256": okf_body_sha256(okf), "structure": []}),
                encoding="utf-8",
            )
            self.assertTrue(tree_is_fresh_for_okf(tree, okf))

            okf.write_text("---\ntitle: 변경 제목\n---\n\n# 본문\n원문\n", encoding="utf-8")
            self.assertTrue(tree_is_fresh_for_okf(tree, okf))

    def test_changed_okf_body_and_legacy_tree_are_stale(self):
        """OCR 재처리 본문 변경과 checksum 없는 구형 트리 모두 재생성 대상이다."""

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            okf = root / "report.md"
            tree = root / "report.tree.json"
            okf.write_text("---\ntitle: 보고서\n---\n\n# 본문\nOCR 전 텍스트\n", encoding="utf-8")
            tree.write_text(
                json.dumps({"okf_body_sha256": okf_body_sha256(okf), "structure": []}),
                encoding="utf-8",
            )
            self.assertTrue(tree_is_fresh_for_okf(tree, okf))

            okf.write_text("---\ntitle: 보고서\n---\n\n# 본문\nOCR 후 텍스트\n", encoding="utf-8")
            self.assertFalse(tree_is_fresh_for_okf(tree, okf))

            tree.write_text("{}", encoding="utf-8")
            self.assertFalse(tree_is_fresh_for_okf(tree, okf))

            tree.write_text("[]", encoding="utf-8")
            self.assertFalse(tree_is_fresh_for_okf(tree, okf))

            tree.write_text(json.dumps({"okf_body_sha256": okf_body_sha256(okf)}), encoding="utf-8")
            self.assertFalse(tree_is_fresh_for_okf(tree, okf))

    def test_regular_batch_syncs_metadata_for_fresh_tree(self):
        """정기 체인도 본문이 같은 트리의 새 검색 메타를 반영한다."""

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            okf_root, trees_root = root / "okf", root / "trees"
            okf = okf_root / "report.md"
            tree_path = trees_root / "report.tree.json"
            okf_root.mkdir()
            trees_root.mkdir()
            okf.write_text("---\ntitle: 변경 제목\nminerals: [LI]\n---\n\n# 본문\n같은 원문\n", encoding="utf-8")
            tree_path.write_text(json.dumps({
                "title": "이전 제목", "okf_body_sha256": okf_body_sha256(okf), "structure": [],
            }), encoding="utf-8")

            with patch("ingest.pageindex.build_pageindex_trees.ingest_status.pg_connect_safe", return_value=None), \
                    patch("ingest.pageindex.build_pageindex_trees.ingest_status.commit_close_safe"):
                summary = build_all(okf_root=okf_root, trees_root=trees_root, with_summary=False)

            self.assertEqual(summary["target_count"], 0)
            self.assertEqual(summary["metadata_synced"], 1)
            tree = json.loads(tree_path.read_text(encoding="utf-8"))
            self.assertEqual(tree["title"], "변경 제목")
            self.assertEqual(tree["minerals"], ["LI"])

    def test_build_all_rebuilds_changed_body_but_skips_fresh_tree(self):
        """실제 배치 선택도 checksum을 사용해 stale 트리를 다시 대상으로 넣는다."""

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            okf_root, trees_root = root / "okf", root / "trees"
            okf = okf_root / "report.md"
            tree_path = trees_root / "report.tree.json"
            okf_root.mkdir()
            trees_root.mkdir()
            okf.write_text("---\ndoc_id: doc_test\n---\n\n# 본문\nOCR 전\n", encoding="utf-8")
            tree_path.write_text(
                json.dumps({"okf_body_sha256": okf_body_sha256(okf), "structure": []}),
                encoding="utf-8",
            )

            with patch("ingest.pageindex.build_pageindex_trees.ingest_status.pg_connect_safe", return_value=None), \
                    patch("ingest.pageindex.build_pageindex_trees.ingest_status.commit_close_safe"):
                fresh = build_all(okf_root=okf_root, trees_root=trees_root, with_summary=False)
            self.assertEqual(fresh["target_count"], 0)
            self.assertEqual(fresh["fresh_skipped"], 1)

            okf.write_text("---\ndoc_id: doc_test\n---\n\n# 본문\nOCR 후\n", encoding="utf-8")
            generated = {"doc_id": "doc_test", "structure": [{"nodes": []}]}
            with patch("ingest.pageindex.build_pageindex_trees.ingest_status.pg_connect_safe", return_value=None), \
                    patch("ingest.pageindex.build_pageindex_trees.ingest_status.commit_close_safe"), \
                    patch("ingest.pageindex.build_pageindex_trees.ingest_status.upsert_file_stage_status"), \
                    patch("ingest.pageindex.build_pageindex_trees.build_tree_for_okf", return_value=generated) as build:
                stale = build_all(okf_root=okf_root, trees_root=trees_root, with_summary=False)
            self.assertEqual(build.call_count, 1)
            self.assertEqual(stale["stale_candidates"], 1)
            self.assertEqual(stale["done"], 1)

    def test_main_raises_nonzero_when_document_build_failed(self):
        """문서별 실패가 PageIndex와 상위 체인 모두에 실패로 전달된다."""

        metrics: dict = {}
        exits: list[int] = []

        @contextmanager
        def fake_pipeline_run(*_args, **_kwargs):
            try:
                yield SimpleNamespace(metrics=metrics)
            except SystemExit as exc:
                exits.append(exc.code)
                raise

        summary = {"failed": 1, "done": 0}
        with patch("ingest.pageindex.build_pageindex_trees.ingest_status.pipeline_run", fake_pipeline_run), \
                patch("ingest.pageindex.build_pageindex_trees.build_all", return_value=summary), \
                patch("ingest.pageindex.build_pageindex_trees.configure_logging"):
            with self.assertRaises(SystemExit) as raised:
                main([])

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(exits, [1])
        self.assertEqual(metrics, summary)

    def test_sync_metadata_uses_cli_roots(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            okf_root, trees_root = root / "custom-okf", root / "custom-trees"
            with patch("ingest.pageindex.build_pageindex_trees.sync_tree_metadata", return_value=2) as sync:
                self.assertEqual(
                    main(["--sync-metadata", "--okf-root", str(okf_root), "--trees-root", str(trees_root)]),
                    0,
                )
            sync.assert_called_once_with(okf_root=okf_root.resolve(), trees_root=trees_root.resolve())


if __name__ == "__main__":
    unittest.main()
