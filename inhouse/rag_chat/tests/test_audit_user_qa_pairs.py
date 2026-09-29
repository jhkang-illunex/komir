import unittest
from unittest.mock import patch

from audit_user_qa_pairs import classify, debug_enabled, debug_notes


class AuditUserQaPairsTest(unittest.TestCase):
    def test_gm08_does_not_pass_when_only_production_action_succeeds(self):
        events = [{"delta": "광물정보 : 주요 용도 : 제공된 문서에서 근거를 찾지 못했습니다.\n광물지도 : 생산 상위국 SU"}]
        terminal = {"done": True, "citations": [{"action_id": "resource.rank"}]}
        status, notes = classify(events, terminal, ("용도", "생산"), "GM08")
        self.assertEqual(status, "PARTIAL")
        self.assertTrue(any("광물정보" in note for note in notes))
        self.assertTrue(any("생산국 코드 미정규화" in note for note in notes))

    def test_gm08_passes_only_when_both_actions_and_answer_parts_exist(self):
        events = [{"delta": "광물정보 : 주요 용도 : 절삭 공구\n광물지도 : 생산 상위국 중국(78.82%)"}]
        terminal = {"done": True, "citations": [
            {"action_id": "document.retrieve"}, {"action_id": "resource.rank"},
        ]}
        status, notes = classify(events, terminal, ("용도", "생산"), "GM08")
        self.assertEqual(status, "PASS")
        self.assertEqual(notes, [])

    def test_debug_notes_only_reports_failed_actions_and_selected_warnings(self):
        notes = debug_notes([{
            "enabled": True,
            "action_results": [
                {"requirement_id": "price", "action_id": "price.series", "status": "success"},
                {"requirement_id": "forecast", "action_id": "forecast.price", "status": "source_unavailable",
                 "failure_reason": "source_unavailable"},
            ],
            "warnings": ["aggregate_incomplete:komis_price_time_aggregate", "source_audit:rdb:queried:1"],
        }])
        self.assertIn("DEBUG 처리 실패: forecast/forecast.price (source_unavailable)", notes)
        self.assertIn("DEBUG 경고: aggregate_incomplete:komis_price_time_aggregate", notes)
        self.assertEqual(len(notes), 2)

    def test_debug_enabled_uses_environment_override(self):
        with patch.dict("os.environ", {"DEBUG": "false"}, clear=False):
            self.assertFalse(debug_enabled())
        with patch.dict("os.environ", {"DEBUG": "True"}, clear=False):
            self.assertTrue(debug_enabled())

    def test_semantic_marker_aliases_do_not_create_false_partial(self):
        events = [{"delta": "최근 월간동향의 제목은 전략광종 인사이트 2026년 6월호입니다."}]
        terminal = {"done": True, "citations": [{"action_id": "document.retrieve"}]}
        status, notes = classify(events, terminal, ("최신", "제목"), "DOC02")
        self.assertEqual(status, "PASS")
        self.assertEqual(notes, [])

        events = [{"delta": "수입금액 비중 상위 광종과 가격 상승 광종을 확인했습니다."}]
        terminal = {"done": True, "citations": [{"action_id": "trade.price_cross_rank"}]}
        status, notes = classify(events, terminal, ("점유율", "가격"), "MP02")
        self.assertEqual(status, "PASS")
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
