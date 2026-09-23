"""Astra 독립 부정 입력/SQL 전달 mutation. 공유 DB에는 접속하지 않는다."""
from pathlib import Path
import inspect
import json
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "inhouse"))
from ingest.okf.build_okf_documents import extract_document_metadata as meta
from ingest.vectorize import build_pgvector_okf as vectorizer
from ingest.tests import test_build_pgvector_okf as tests

cases = [
    ("ordinary words", dict(title="", resource="", body="아니 켈리에게 문의했다. 누구 리더에게 연락했다."), "minerals", []),
    ("spaced minerals", dict(title="", resource="", body="니 켈의 가격과 구 리 공급"), "minerals", ["구리", "니켈"]),
    ("compounds", dict(title="", resource="", body="황산니켈 탄산리튬 구리가격"), "minerals", ["구리", "니켈", "리튬"]),
    ("title first", dict(title="보고서 2026-09-23", resource="archive_2020년1월1일.pdf", body="2019년 1월 2일 광산 생산을 시작했다."), "document_date", "2026-09-23"),
    ("event only", dict(title="보고서", resource="documents/조달청보고서/sample.pdf", body="2019년 1월 2일 광산 생산을 시작했다."), "document_date", None),
    ("publication label", dict(title="보고서", resource="report.pdf", body="발행일 2026-09-23"), "document_date", "2026-09-23"),
    ("invalid date", dict(title="보고서 2026-13-99", resource="report.pdf", body=""), "document_date", None),
]
for label, kwargs, key, expected in cases:
    actual = meta(**kwargs)[key]
    assert actual == expected, (label, actual, expected)
    print(label, json.dumps(actual, ensure_ascii=False))
assert vectorizer._pub_date(vectorizer._validated_document_date("1999-12-31")).isoformat() == "1999-12-31"
print("pre-2000 century preserved")

test_name = "test_build_passes_frontmatter_date_to_sql_row_without_db_write"
control = unittest.TestResult()
tests.OkfDocumentDateTest(test_name).run(control)
assert control.wasSuccessful(), (control.failures, control.errors)

source = inspect.getsource(vectorizer.build)
assert "_pub_date(d.doc_date)" in source
namespace = {}
exec(source.replace("_pub_date(d.doc_date)", "None"), vectorizer.__dict__, namespace)
with patch.object(tests, "build", namespace["build"]):
    mutated = unittest.TestResult()
    tests.OkfDocumentDateTest(test_name).run(mutated)
assert len(mutated.failures) == 1 and not mutated.errors, (mutated.failures, mutated.errors)
assert "None != datetime.date(2006, 11, 27)" in mutated.failures[0][1]
print("SQL pub_date=None mutation rejected by value assertion")
