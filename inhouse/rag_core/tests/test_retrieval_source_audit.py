# -*- coding: utf-8 -*-
"""RDB·Vector·PageIndex·OKF 조회 상태가 근거 검증 결과에 남는지 검사한다."""
import unittest

from rag_core.ragkit.chatbot import _retrieval_source_status
from rag_core.ragkit.chatbot_graph import _source_audit_warnings
from rag_core.retrieval.evidence import Evidence


class RetrievalSourceAuditTest(unittest.TestCase):
    def test_pageindex_text_marks_okf_verified(self):
        evidence = [Evidence(kind="dense", source="a", section="", text="x"),
                    Evidence(kind="pageindex", source="b", section="", text="원문")]
        warnings = _source_audit_warnings({"dense": object(), "pageindex": object()}, {}, evidence, [])
        self.assertEqual(_retrieval_source_status(warnings), [
            {"source": "rdb", "status": "not_selected", "evidence_count": 0},
            {"source": "vector", "status": "queried", "evidence_count": 1},
            {"source": "pageindex", "status": "queried", "evidence_count": 1},
            {"source": "okf", "status": "verified", "evidence_count": 1},
        ])

    def test_unselected_sources_are_explicit(self):
        warnings = _source_audit_warnings({}, {}, [], [])
        self.assertEqual(len(warnings), 4)
        self.assertIn("source_audit:vector:not_selected:0", warnings)


if __name__ == "__main__":
    unittest.main()
