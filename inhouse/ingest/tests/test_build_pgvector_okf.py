# -*- coding: utf-8 -*-
"""OKF → pgvector 날짜 전달의 단위 검사(DB 쓰기 없음)."""
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest.vectorize.build_pgvector_okf import (  # noqa: E402
    build,
    _load_okf_record,
    _pub_date,
    _validated_document_date,
)


class OkfDocumentDateTest(unittest.TestCase):
    def test_valid_frontmatter_date_reaches_doc_record_and_pg_date(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ocr.md"
            path.write_text(
                "---\n"
                "doc_id: doc_51886c72704a2c9017503e3c\n"
                "document_date: '2006-11-27'\n"
                "resource: documents/조달청보고서/11.27.pdf\n"
                "source_group: 조달청보고서\n"
                "fmt: pdf\n"
                "---\n\n# 11.27\n본문\n",
                encoding="utf-8",
            )
            record = _load_okf_record(path)

        self.assertEqual(record.doc_date, "2006-11-27")
        self.assertEqual(_pub_date(record.doc_date).isoformat(), "2006-11-27")

    def test_invalid_or_missing_frontmatter_date_does_not_create_date(self):
        for value in (None, "", "2026-02-30", "2026-2-3", "USGS_2026"):
            self.assertEqual(_validated_document_date(value), "")
        self.assertIsNone(_pub_date(""))

    def test_pre_2000_iso_date_keeps_its_century(self):
        self.assertEqual(_validated_document_date("1999-12-31"), "1999-12-31")
        self.assertEqual(_pub_date("1999-12-31").isoformat(), "1999-12-31")

    def test_build_passes_frontmatter_date_to_sql_row_without_db_write(self):
        """이 assertion은 rows의 pub_date를 None으로 되돌리면 실패한다."""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            okf = root / "test" / "ocr.md"
            okf.parent.mkdir()
            okf.write_text(
                "---\n"
                "doc_id: doc_51886c72704a2c9017503e3c\n"
                "document_date: '2006-11-27'\n"
                "resource: documents/조달청보고서/11.27.pdf\n"
                "source_group: test\n"
                "fmt: pdf\n"
                "---\n\n# 11.27\n본문이 충분히 길어 청크가 생성됩니다.\n",
                encoding="utf-8",
            )
            cur = MagicMock()
            cur.rowcount = 0
            cur.fetchone.return_value = (1,)
            con = MagicMock()
            con.cursor.return_value.__enter__.return_value = cur
            captured: list[tuple] = []

            def capture_execute_values(_cur, _sql, rows, **_kwargs):
                captured.extend(rows)

            with patch("ingest.vectorize.build_pgvector_okf.OKF_DOCUMENTS_ROOT", root), \
                    patch("ingest.vectorize.build_pgvector_okf.get_settings", return_value=SimpleNamespace(PG_SCHEMA="test_schema")), \
                    patch("ingest.vectorize.build_pgvector_okf.encode_passages", return_value=[[0.0] * 384]), \
                    patch("ingest.vectorize.build_pgvector_okf.pg_connect", return_value=con), \
                    patch("psycopg2.extras.execute_values", side_effect=capture_execute_values), \
                    patch("ingest.vectorize.build_pgvector_okf.ingest_status.pg_connect_safe", return_value=None), \
                    patch("ingest.vectorize.build_pgvector_okf.ingest_status.upsert_source_file"), \
                    patch("ingest.vectorize.build_pgvector_okf.ingest_status.bulk_file_stage_status"), \
                    patch("ingest.vectorize.build_pgvector_okf.ingest_status.commit_close_safe"):
                self.assertEqual(build(("test",)), 1)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][4], date(2006, 11, 27))


if __name__ == "__main__":
    unittest.main()
