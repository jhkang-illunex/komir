from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ingest.vectorize.build_pgvector_okf import build


def test_targeted_reindex_adds_context_but_preserves_stored_text(tmp_path):
    doc_id = "51886c72704a2c90"
    okf = tmp_path / "test" / "ocr.md"
    okf.parent.mkdir()
    okf.write_text(
        "---\n"
        f"doc_id: doc_{doc_id}17503e3c\n"
        "resource: documents/sample.hwp\n"
        "source_group: test\n"
        "title: LME Seminar 품목별 전망\n"
        "fmt: hwp\n"
        "---\n\n"
        "# 니켈 전망\n"
        "니 켈 ▪ 추가 하락 전망과 가격 추가 하락 가능성\n",
        encoding="utf-8",
    )
    cur = MagicMock()
    cur.rowcount = 1
    cur.fetchone.return_value = (1,)
    con = MagicMock()
    con.cursor.return_value.__enter__.return_value = cur
    embedded: list[str] = []
    inserted: list[tuple] = []

    def encode(texts):
        embedded.extend(texts)
        return [[0.0] * 384 for _ in texts]

    def capture_rows(_cur, _sql, rows, **_kwargs):
        inserted.extend(rows)

    with patch("ingest.vectorize.build_pgvector_okf.OKF_DOCUMENTS_ROOT", tmp_path), \
            patch("ingest.vectorize.build_pgvector_okf.get_settings", return_value=SimpleNamespace(PG_SCHEMA="test_schema")), \
            patch("ingest.vectorize.build_pgvector_okf.encode_passages", side_effect=encode), \
            patch("ingest.vectorize.build_pgvector_okf.pg_connect", return_value=con), \
            patch("psycopg2.extras.execute_values", side_effect=capture_rows), \
            patch("ingest.vectorize.build_pgvector_okf.ingest_status.pg_connect_safe", return_value=None), \
            patch("ingest.vectorize.build_pgvector_okf.ingest_status.upsert_source_file"), \
            patch("ingest.vectorize.build_pgvector_okf.ingest_status.bulk_file_stage_status"), \
            patch("ingest.vectorize.build_pgvector_okf.ingest_status.commit_close_safe"):
        assert build(("test",), doc_ids=(f"doc_{doc_id}17503e3c",)) == 1

    assert embedded == [
        "LME Seminar 품목별 전망\n니켈 전망\n니켈 ▪ 추가 하락 전망과 가격 추가 하락 가능성"
    ]
    assert inserted[0][6] == "니 켈 ▪ 추가 하락 전망과 가격 추가 하락 가능성"
    delete_sql, delete_params = cur.execute.call_args_list[0].args
    assert "doc_id = ANY" in delete_sql
    assert delete_params == (["test"], [doc_id])


def test_targeted_reindex_fails_before_db_when_doc_is_missing(tmp_path):
    with patch("ingest.vectorize.build_pgvector_okf.OKF_DOCUMENTS_ROOT", tmp_path), \
            patch("ingest.vectorize.build_pgvector_okf.get_settings", return_value=SimpleNamespace(PG_SCHEMA="test_schema")), \
            patch("ingest.vectorize.build_pgvector_okf.pg_connect") as connect:
        try:
            build(("test",), doc_ids=("doc_deadbeefdeadbeef",))
        except ValueError as exc:
            assert "deadbeefdeadbeef" in str(exc)
        else:
            raise AssertionError("missing doc_id must fail")
    connect.assert_not_called()

