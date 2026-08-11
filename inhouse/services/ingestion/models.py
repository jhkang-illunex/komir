# -*- coding: utf-8 -*-
"""문서 추출 산출물의 검증된 레코드·매니페스트 스키마.

출처: komis-report-generator-main(외부 repo, git 없는 스냅샷, 2026-08-11 확인)의
document_ingestion/models.py를 거의 그대로 이식(pydantic 계약이라 komir 쪽 판단이
개입할 여지가 적어 원본 그대로가 최선). 2026-08-11 병합계획(문서_산출물/
2026-W33_0810-0816/병합계획_komis-report-generator_260811.md) 결정②(코드 이식)에
따른 작업.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

ExtractionStatus = Literal["extracted", "ocr_required", "parse_failed"]
ManifestAction = Literal["processed", "unchanged", "duplicate"]


class StrictModel(BaseModel):
    """undeclared 필드를 거부하는 base model."""

    model_config = ConfigDict(extra="forbid")


class TableCell(StrictModel):
    """표 셀 하나의 정규화된 텍스트·스팬 좌표."""

    row: int = Field(ge=0)
    column: int = Field(ge=0)
    text: str
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)


class ExtractedTable(StrictModel):
    """문서 콘텐츠 유닛에서 추출된 정규화 표."""

    index: int = Field(ge=1)
    rows: list[list[str]]
    cells: list[TableCell]
    text: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    bbox: tuple[float, float, float, float] | None = None
    strategy: str
    quality: Literal["candidate", "structural"]
    warnings: list[str] = Field(default_factory=list)


class ContentUnit(StrictModel):
    """문서에서 추출된 순서 있는 페이지/섹션 콘텐츠."""

    sequence: int = Field(ge=1)
    locator_type: Literal["page", "section"]
    locator: int = Field(ge=1)
    text: str
    char_count: int = Field(ge=0)
    content_status: Literal["text", "sparse", "empty"]
    ocr_required: bool = False
    tables: list[ExtractedTable] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentRecord(StrictModel):
    """승인된 원천 문서 1건의 완전한 정규화 표현.

    extension은 현재 구현된 파서(pdf/hwp)로 제한 — docx/doc/xlsx/xls/csv 파서
    구현 시 이 Literal도 함께 확장할 것(parsers/__init__.py의 DEFAULT_PARSERS와
    동기화 필요).
    """

    schema_version: Literal[1] = SCHEMA_VERSION
    document_id: str
    content_sha256: str
    title: str
    source_group: str
    source_relative_path: str
    extension: Literal[".pdf", ".hwp"]
    file_size: int = Field(ge=0)
    source_type: Literal["komis"] = "komis"
    provider: str = "한국광해광업공단"
    access_level: Literal["public"] = "public"
    policy_status: Literal["approved"] = "approved"
    allow_index: Literal[True] = True
    parser_name: str
    parser_version: str
    parser_signature: str
    status: ExtractionStatus
    unit_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    text: str
    units: list[ContentUnit] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class ManifestEntry(StrictModel):
    """원천 파일 1건의 처리 결과와 산출물 참조."""

    source_relative_path: str
    content_sha256: str
    document_id: str
    status: ExtractionStatus
    action: ManifestAction
    parser_signature: str
    document_output: str | None = None
    text_output: str | None = None
    duplicate_of: str | None = None
    error: str | None = None


class ExtractionManifest(StrictModel):
    """배치 단위 문서 추출 결과 인벤토리."""

    schema_version: Literal[1] = SCHEMA_VERSION
    generated_at: str
    data_root: str
    source_groups: list[str]
    supported_extensions: list[str]
    source_file_count: int = Field(ge=0)
    unique_document_count: int = Field(ge=0)
    action_counts: dict[str, int]
    status_counts: dict[str, int]
    entries: list[ManifestEntry]
