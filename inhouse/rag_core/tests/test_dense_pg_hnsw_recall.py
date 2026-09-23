from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from rag_core.retrieval.dense_pg import dense_search_pg


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    @contextmanager
    def cursor(self):
        yield self.cursor_value

    def close(self):
        pass


def test_dense_search_uses_measured_hnsw_recall_floor():
    cursor = _Cursor()
    connection = _Connection(cursor)
    with patch("rag_core.retrieval.dense_pg.pg_connect", return_value=connection), \
            patch("rag_core.retrieval.dense_pg.get_settings", return_value=SimpleNamespace(PG_SCHEMA="test")), \
            patch("rag_core.retrieval.dense_pg.encode_query", return_value=[0.0] * 384):
        assert dense_search_pg("fixed acceptance query", k=10, _allow_fallback=False) == []

    assert cursor.calls[0] == ("SET hnsw.ef_search = %s", (200,))

