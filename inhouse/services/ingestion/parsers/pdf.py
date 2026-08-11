# -*- coding: utf-8 -*-
"""PDF → 마크다운 정규화. mineral_supply_risk가 이미 pymupdf/pdfplumber를 쓰고 있음
(requirements.txt 확인됨) — 신규 의존성 추가 전 재사용 가능한지 먼저 확인할 것.

2026-08-11: 위 스켈레톤 메모대로 재사용 확인 완료 — `inhouse/geo/extractors.py`의
opendataloader-pdf → pypdf → OCR(easyocr) 3단계 폴백 체인(`extract_with_fallback`,
2026-07-07 도입, 0807 발주처자료 PDF ETL로 재검증됨)을 그대로 쓴다. 병합계획
(documents/산출물/2026-W33_0810-0816/병합계획_komis-report-generator_260811.md)
결정③: 외부 repo(komis-report-generator-main)의 PyMuPDF 단독 파서는 채택하지
않음 — komir 쪽이 이미 검증·가동 중인 파이프라인이 정본.

페이지 단위 분할·표 구조(bbox 등)는 이 체인이 보존하지 않는다(단일 텍스트 블록만
반환) — DocumentParser 계약을 맞추기 위해 문서 전체를 ContentUnit 1개로 감싼다.
페이지별 분할이 필요해지면 geo/extractors.py 자체를 바꾸지 말고(이미 검증된 코드,
CLAUDE.md §4 "최소·외과적 변경") 이 래퍼만 확장할 것."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_geo_root(start: Path) -> Path:
    """`geo/extractors.py`를 담은 디렉토리를 위로 훑어 찾는다.

    소스 트리(inhouse/services/ingestion/parsers/pdf.py, 3단 위가 inhouse/)와
    컨테이너 배포본(Containerfile이 services/ingestion→./ingestion, geo/→./geo로
    한 단씩 평평하게 COPY, 2단 위가 /app)의 상대 깊이가 다르다 — 고정 깊이 대신
    탐색으로 두 경우 다 맞춘다."""

    for candidate in (start, *start.parents):
        if (candidate / "geo" / "extractors.py").is_file():
            return candidate
    raise ImportError(f"geo/extractors.py를 {start} 상위에서 찾지 못함")


_GEO_ROOT = _find_geo_root(Path(__file__).resolve())
if str(_GEO_ROOT) not in sys.path:
    sys.path.insert(0, str(_GEO_ROOT))

from geo.extractors import extract_with_fallback, md_to_text, opendataloader_batch_convert  # noqa: E402

from ..models import ContentUnit
from . import ParseResult

_MIN_USABLE_CHARS = 30
_DEFAULT_OCR_CACHE_DIR = str(
    _GEO_ROOT / "data_lake/semi_structure/pdf_extract/_ocr_cache"
)


class PdfParser:
    """opendataloader-pdf → pypdf → OCR 폴백 체인으로 PDF를 파싱한다."""

    name = "komir-opendataloader-ocr-fallback"
    parser_version = "1"
    signature = f"{name}:{parser_version}:komis-pdf-v1"

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir or os.environ.get(
            "INGESTION_OCR_CACHE_DIR", _DEFAULT_OCR_CACHE_DIR
        )
        self._md_cache: dict[str, str] = {}

    def preload_batch(self, paths: list[str]) -> None:
        """opendataloader-pdf를 배치 1회로 호출해 markdown 결과를 내부 캐시에 채운다.

        JVM 스핀업 비용 때문에 파일 단위 호출을 피하려는 최적화(모듈 docstring
        참고) — pipeline.py가 실제 파싱이 필요한 PDF 목록을 계산해 이 메서드를
        먼저 부른다. 호출하지 않아도 parse()가 1건짜리 배치로 폴백해 정확성은
        유지된다."""

        if not paths:
            return
        batch_out = opendataloader_batch_convert(paths, out_dir=self.cache_dir + "_md")
        for p, text in batch_out.items():
            self._md_cache[p] = text or ""

    def parse(self, path: Path) -> ParseResult:
        """PDF 한 건을 파싱한다 — 원천 고유 실패는 ParseResult로 흡수한다."""

        try:
            data = path.read_bytes()
            if str(path) in self._md_cache:
                md_text = self._md_cache.pop(str(path))
            else:
                batch_out = opendataloader_batch_convert(
                    [str(path)], out_dir=self.cache_dir + "_md"
                )
                md_text = batch_out.get(str(path)) or ""
            text, method = extract_with_fallback(str(path), data, md_text, self.cache_dir)
        except Exception as exc:  # noqa: BLE001 - 한 파일의 실패가 배치 전체를 막지 않게
            return ParseResult(status="parse_failed", error=f"{type(exc).__name__}: {exc}")

        real_chars = len(md_to_text(text).strip())
        if method == "failed" or not text.strip():
            return ParseResult(status="ocr_required", warnings=["pdf_text_extraction_failed_all_methods"])

        warnings = [] if method != "partial" else ["low_text_partial_result"]
        content_status = "text" if real_chars >= _MIN_USABLE_CHARS else "sparse"
        unit = ContentUnit(
            sequence=1,
            locator_type="page",
            locator=1,
            text=text,
            char_count=real_chars,
            content_status=content_status,
            ocr_required=(method == "ocr"),
            tables=[],
            warnings=warnings,
        )
        return ParseResult(status="extracted", units=[unit], text=text, warnings=warnings + [f"extraction_method:{method}"])
