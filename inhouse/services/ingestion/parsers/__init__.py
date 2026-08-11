# -*- coding: utf-8 -*-
"""포맷별 파서 — 전부 텍스트+표를 마크다운으로 정규화해 rag/ragkit/chunk.py(헤딩 기반
청킹)에 그대로 태운다(청킹 로직 재구현 금지, docs/CONTAINER_ARCHITECTURE.md §5).
RAG·Report 양쪽이 공유하는 공통 모듈.

DocumentParser 계약(name/parser_version/signature/parse())과 ParseResult는
komis-report-generator-main(외부 repo, 2026-08-11 확인)의 document_ingestion/
parsers.py에서 이식(병합계획 결정②). pdf.py는 원본의 PyMuPDF 단독 구현 대신
komir 자체 opendataloader-pdf+OCR폴백 체인을 쓴다(병합계획 결정③ — komir 쪽이
이미 검증·가동 중인 파이프라인을 정본으로 유지).

docx/doc/xlsx/xls/csv는 외부 repo에도 구현이 없어 이번 이식 범위 밖 — 여전히
스켈레톤(raise NotImplementedError)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..models import ContentUnit, ExtractionStatus


@dataclass(slots=True)
class ParseResult:
    """단일 원천 문서에 대한 정규화된 파서 결과."""

    status: ExtractionStatus
    units: list[ContentUnit] = field(default_factory=list)
    text: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


class DocumentParser(Protocol):
    """지원 문서 파서가 구현해야 하는 계약."""

    name: str
    parser_version: str
    signature: str

    def parse(self, path: Path) -> ParseResult:
        """문서를 읽어 정규화한다 — 원천 고유 실패를 상위로 전파하지 않는다."""
        ...


def _default_parsers() -> dict[str, DocumentParser]:
    from .hwp import HwpParser
    from .pdf import PdfParser

    return {".pdf": PdfParser(), ".hwp": HwpParser()}


DEFAULT_PARSERS: dict[str, DocumentParser] = _default_parsers()
