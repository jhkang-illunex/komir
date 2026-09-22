# -*- coding: utf-8 -*-
"""이미지 참조만 남긴 PDF Markdown이 OCR 경로로 가는지 검사한다."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest.parsers.pdf import PdfParser  # noqa: E402


class PdfParserImageOcrTest(unittest.TestCase):
    def test_image_dominant_markdown_forces_cached_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "scan.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            markdown = "\n".join(f"![image {index}](page-{index}.png)" for index in range(4))
            with patch.object(PdfParser, "_raw_markdown", return_value=markdown), \
                 patch("ingest.parsers.pdf.opendataloader_batch_convert"), \
                 patch("ingest.parsers.pdf.cached_ocr_pdf_text", return_value="리튬 수급과 배터리 설치량") as ocr:
                result = PdfParser(cache_dir=directory).parse(pdf)
            ocr.assert_called_once()
            self.assertEqual(result.status, "extracted")
            self.assertTrue(result.units[0].ocr_required)
            self.assertIn("extraction_method:ocr", result.warnings)

    def test_text_markdown_keeps_existing_extraction_path(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "text.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            markdown = "# 리튬 시장\n\n" + ("리튬 수요와 공급 동향을 분석합니다. " * 30)
            with patch.object(PdfParser, "_raw_markdown", return_value=markdown), \
                 patch("ingest.parsers.pdf.opendataloader_batch_convert"), \
                 patch("ingest.parsers.pdf.cached_ocr_pdf_text") as ocr:
                result = PdfParser(cache_dir=directory).parse(pdf)
            ocr.assert_not_called()
            self.assertEqual(result.status, "extracted")
            self.assertFalse(result.units[0].ocr_required)

    def test_image_references_that_dominate_markdown_force_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "image-heavy.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            images = "\n".join(f"![](<{index * 'x'}.png>)" for index in range(1, 20))
            markdown = images + "\n" + ("짧은 본문 " * 100)
            with patch.object(PdfParser, "_raw_markdown", return_value=markdown), \
                 patch("ingest.parsers.pdf.opendataloader_batch_convert"), \
                 patch("ingest.parsers.pdf.cached_ocr_pdf_text", return_value="OCR 본문") as ocr:
                result = PdfParser(cache_dir=directory).parse(pdf)
            ocr.assert_called_once()
            self.assertTrue(result.units[0].ocr_required)


if __name__ == "__main__":
    unittest.main()
