from datetime import date
import unittest

from rag_core.retrieval.monthly_trend import (
    _MonthlyDocument,
    _MINERAL_NOT_MENTIONED_WARNING,
    _period_bounds_for_topic,
    _publication_month,
    _select_document,
    _source_groups_for_topic,
)


def _doc(doc_id: str, source: str, month: date) -> _MonthlyDocument:
    return _MonthlyDocument(doc_id, source, doc_id, f"income_data/{doc_id}.pdf", month)


class MonthlyTrendTest(unittest.TestCase):
    def test_mineral_not_mentioned_warning_is_a_stable_contract_marker(self):
        self.assertEqual(_MINERAL_NOT_MENTIONED_WARNING + "니켈",
                         "monthly_trend_mineral_not_mentioned:니켈")

    def test_monthly_trend_label_does_not_make_copper_a_requested_mineral(self):
        from rag_core.retrieval.monthly_trend import _mentioned_minerals
        self.assertEqual(_mentioned_minerals("2026년 5월 희소금속 월간동향에서 니켈 관련 내용"), ("니켈",))
    def test_publication_month_uses_filename_when_db_date_is_missing(self):
        self.assertEqual(
            _publication_month(None, "income_data/희소금속 월간동향/2025-05_희소금속.pdf", ""), date(2025, 5, 1),
        )

    def test_topic_source_group_does_not_mix_rare_and_strategic_monthly_documents(self):
        self.assertEqual(_source_groups_for_topic("최근 희소금속 월간동향 보고서 제목 알려줘"), ("희소금속 월간동향",))
        self.assertEqual(_source_groups_for_topic("이번 달 전략광종 월간동향 요약해줘"), ("전략광종 월간동향",))

    def test_recent_without_explicit_count_selects_latest_available_month(self):
        docs = [_doc("rare-2024-12", "희소금속 월간동향", date(2024, 12, 1)), _doc("rare-2025-05", "희소금속 월간동향", date(2025, 5, 1))]
        selected = _select_document(docs, "최근 희소금속 월간동향 보고서 제목 알려줘")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.doc_id, "rare-2025-05")

    def test_explicit_current_month_does_not_substitute_an_old_monthly_report(self):
        docs = [_doc("rare-2025-05", "희소금속 월간동향", date(2025, 5, 1))]
        self.assertIsNone(_select_document(docs, "이번 달 희소금속 월간동향", today=date(2026, 9, 28)))

    def test_explicit_recent_period_is_preserved(self):
        self.assertEqual(
            _period_bounds_for_topic("최근 3개월 월간동향에서 리튬 관련 내용 찾아줘", today=date(2026, 9, 28)),
            (date(2026, 7, 1), date(2026, 9, 28)),
        )

    def test_explicit_year_month_is_a_single_month_period(self):
        self.assertEqual(
            _period_bounds_for_topic("2026년 5월 희소금속 월간동향 요약해줘"),
            (date(2026, 5, 1), date(2026, 5, 31)),
        )
