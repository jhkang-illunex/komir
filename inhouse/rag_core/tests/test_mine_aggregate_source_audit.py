# -*- coding: utf-8 -*-
"""광산 OKF 실시간 집계의 원천 감사 회귀 검사."""
import unittest

from rag_core.ragkit.chatbot_graph import _source_audit_warnings
from rag_core.retrieval.evidence import Evidence


class MineAggregateSourceAuditTest(unittest.TestCase):
    @staticmethod
    def _audit(*, evidence=None, warnings=None):
        return _source_audit_warnings(
            {"mine_aggregate": object()}, {}, evidence or [], warnings or [],
        )

    def test_success_marks_okf_verified_without_other_sources(self):
        audit = self._audit(evidence=[Evidence(
            kind="aggregated", source="광산자료/동_구리", section="구리 생산량 rank", text="표",
        )])
        self.assertIn("source_audit:rdb:not_selected:0", audit)
        self.assertIn("source_audit:vector:not_selected:0", audit)
        self.assertIn("source_audit:pageindex:not_selected:0", audit)
        self.assertIn("source_audit:okf:verified:1", audit)

    def test_failure_marks_aggregate_and_okf_unavailable(self):
        audit = self._audit(warnings=["mine_aggregate_failed"])
        self.assertIn("source_audit:okf:unavailable:0", audit)

    def test_timeout_uses_the_same_failed_job_contract(self):
        # _retrieve_node는 Future timeout을 mine_aggregate_failed로 정규화한다.
        audit = self._audit(warnings=["mine_aggregate_failed"])
        self.assertIn("source_audit:okf:unavailable:0", audit)


if __name__ == "__main__":
    unittest.main()
