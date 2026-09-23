# -*- coding: utf-8 -*-
"""OKF 검색 메타데이터의 OCR 회귀 검사."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest.okf.build_okf_documents import extract_document_metadata  # noqa: E402


class MineralAliasWhitespaceTest(unittest.TestCase):
    def test_hwp_ocr_spaced_nickel_is_detected(self):
        metadata = extract_document_metadata(
            title="LME Seminar 품목별 동향",
            resource="documents/조달청보고서/sample.hwp",
            body="니 켈 가격 추가 하락 전망",
        )
        self.assertEqual(metadata["minerals"], ["니켈"])

    def test_only_registered_alias_internal_whitespace_is_normalized(self):
        metadata = extract_document_metadata(
            title="일반 문장",
            resource="sample.txt",
            body="수 요와 공 급을 검토하고 전기 동향을 기록한다.",
        )
        self.assertEqual(metadata["minerals"], [])

    def test_spaced_alias_does_not_match_inside_normal_korean_words(self):
        metadata = extract_document_metadata(
            title="일반 문장",
            resource="sample.txt",
            body="아니 켈리에게 문의하고 누구 리더에게 연락했다.",
        )
        self.assertEqual(metadata["minerals"], [])

    def test_spaced_alias_keeps_postposition_use(self):
        metadata = extract_document_metadata(
            title="광물 문장",
            resource="sample.txt",
            body="니 켈의 가격과 구리가 변동했다.",
        )
        self.assertEqual(metadata["minerals"], ["구리", "니켈"])

    def test_contiguous_alias_keeps_existing_compound_and_price_matching(self):
        metadata = extract_document_metadata(
            title="황산니켈과 탄산리튬",
            resource="sample.txt",
            body="니켈가격과 구리수요를 검토한다.",
        )
        self.assertEqual(metadata["minerals"], ["구리", "니켈", "리튬"])

    def test_english_alias_does_not_accept_internal_whitespace(self):
        metadata = extract_document_metadata(
            title="nick el price",
            resource="sample.txt",
            body="nick el is not a normalized English alias",
        )
        self.assertEqual(metadata["minerals"], [])


class DocumentDateValidationTest(unittest.TestCase):
    def test_invalid_full_date_is_not_written_to_metadata(self):
        metadata = extract_document_metadata(
            title="2026-99-99 report",
            resource="sample.txt",
            body="본문",
        )
        self.assertIsNone(metadata["document_date"])

    def test_invalid_yymmdd_fallback_is_not_written_to_metadata(self):
        metadata = extract_document_metadata(
            title="report",
            resource="sample.txt",
            body="본문",
            doc_date="261399",
        )
        self.assertIsNone(metadata["document_date"])

    def test_invalid_title_candidate_does_not_hide_later_valid_resource_date(self):
        metadata = extract_document_metadata(
            title="2026-99-99 report",
            resource="sample_2026-09-23.txt",
            body="본문",
        )
        self.assertEqual(metadata["document_date"], "2026-09-23")

    def test_title_date_precedes_historical_body_date(self):
        metadata = extract_document_metadata(
            title="보고서 2026-09-23",
            resource="sample.txt",
            body="2019년 1월 2일 광산 생산을 시작했다.",
        )
        self.assertEqual(metadata["document_date"], "2026-09-23")

    def test_title_date_precedes_resource_date(self):
        metadata = extract_document_metadata(
            title="발행일 2026-09-23",
            resource="documents/archive_2020년1월1일/report.pdf",
            body="본문",
        )
        self.assertEqual(metadata["document_date"], "2026-09-23")

    def test_generic_historical_body_date_is_not_document_date(self):
        metadata = extract_document_metadata(
            title="보고서",
            resource="sample.txt",
            body="2019년 1월 2일 광산 생산을 시작했다.",
        )
        self.assertIsNone(metadata["document_date"])

    def test_labeled_body_publication_date_is_document_date(self):
        metadata = extract_document_metadata(
            title="보고서",
            resource="sample.txt",
            body="발행일: 2026-09-23\n2019년 1월 2일 광산 생산을 시작했다.",
        )
        self.assertEqual(metadata["document_date"], "2026-09-23")

    def test_labeled_english_publication_date_is_document_date(self):
        metadata = extract_document_metadata(
            title="report",
            resource="sample.txt",
            body="Published: 2026-09-23\nThe mine began production in 2019.",
        )
        self.assertEqual(metadata["document_date"], "2026-09-23")

    def test_jodalcheong_ocr_header_date_is_preserved(self):
        metadata = extract_document_metadata(
            title="11.27",
            resource="documents/조달청보고서/11.27.pdf",
            body="# 11.27\nGlobal Commodities Weekly\n2006.11.27\n조달청\n본문",
        )
        self.assertEqual(metadata["document_date"], "2006-11-27")


if __name__ == "__main__":
    unittest.main()
