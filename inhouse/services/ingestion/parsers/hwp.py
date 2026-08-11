# -*- coding: utf-8 -*-
"""HWP → 마크다운 정규화(구조 보존: 섹션+표).

출처: komis-report-generator-main(외부 repo, 2026-08-11 확인)의
document_ingestion/parsers.py 중 HWP 관련 부분(HwpParser·extract_hwp_sections
및 하위 헬퍼)을 그대로 이식(병합계획 결정②) — pyhwp(hwp5 패키지) 기반, HWP 5.0의
XML 모델을 순회해 섹션·표 구조를 보존한다.

komir에 기존에 있던 hwp_text()(inhouse/geo/extractors.py, OLE+zlib 직접 파싱)는
평문만 반환하고 표 구조가 없어 이 파서로 대체하지 않는다 — 서로 다른 용도(geo는
GKG 이벤트용 평문 발췌, 이쪽은 RAG/Report용 구조 보존 마크다운화)라 병존.

신규 의존성: pyhwp(hwp5) — requirements.txt에 추가 필요."""
from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

from hwp5.xmlmodel import Hwp5File

from ..models import ContentUnit, ExtractedTable, TableCell
from . import ParseResult

_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_ALL_WHITESPACE_PATTERN = re.compile(r"\s+")
_BLANK_LINES_PATTERN = re.compile(r"\n{3,}")
_MIN_USABLE_SECTION_CHARS = 30


def normalize_text(value: str | None) -> str:
    """유니코드·제어문자·공백·빈줄을 정규화한다."""

    if not value:
        return ""
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    value = _CONTROL_CHARACTER_PATTERN.sub("", value)
    lines = [_INLINE_WHITESPACE_PATTERN.sub(" ", line).strip() for line in value.split("\n")]
    return _BLANK_LINES_PATTERN.sub("\n\n", "\n".join(lines)).strip()


def normalize_cell_text(value: str | None) -> str:
    """정규화된 텍스트를 표 셀 한 줄로 축약한다."""

    return _ALL_WHITESPACE_PATTERN.sub(" ", normalize_text(value)).strip()


def printable_character_count(value: str) -> int:
    """추출 텍스트 중 화면에 보이는(공백 아닌) 문자 수."""

    return sum(1 for character in value if character.isprintable() and not character.isspace())


class HwpParser:
    """pyhwp로 HWP 섹션 텍스트와 구조적 표를 추출한다."""

    name = "pyhwp"
    parser_version = version("pyhwp")
    signature = f"{name}:{parser_version}:komis-hwp-v1"

    def parse(self, path: Path) -> ParseResult:
        """HWP 파일을 파싱한다 — 원천 고유 실패는 ParseResult로 흡수한다."""

        try:
            hwp = Hwp5File(str(path))
            stream = hwp.text.xmlevents().open()
            try:
                root = ET.parse(stream).getroot()
            finally:
                stream.close()
            units = extract_hwp_sections(root)
            text = _hwp_document_text(units)
            if printable_character_count(text) == 0 and not any(unit.tables for unit in units):
                return ParseResult(status="parse_failed", error="hwp_body_text_not_detected")
            return ParseResult(status="extracted", units=units, text=text)
        except Exception as exc:  # noqa: BLE001 - 한 파일의 실패가 배치 전체를 막지 않게
            return ParseResult(status="parse_failed", error=_format_error(exc))


def extract_hwp_sections(root: ET.Element) -> list[ContentUnit]:
    """HWP XML 섹션 요소를 순서 있는 콘텐츠 유닛으로 변환한다."""

    sections = [element for element in root.iter() if _local_name(element.tag) == "SectionDef"]
    if not sections:
        raise ValueError("hwp_body_has_no_sections")

    units: list[ContentUnit] = []
    table_index = 0
    for section_number, section in enumerate(sections, start=1):
        blocks: list[str] = []
        tables: list[ExtractedTable] = []

        def append_table(
            element: ET.Element,
            section_tables: list[ExtractedTable] = tables,
        ) -> None:
            nonlocal table_index
            table_index += 1
            section_tables.append(_hwp_table(element, table_index))

        _walk_hwp_content(section, blocks, append_table)
        section_text = normalize_text("\n".join(blocks))
        char_count = printable_character_count(section_text)
        units.append(
            ContentUnit(
                sequence=section_number,
                locator_type="section",
                locator=section_number,
                text=section_text,
                char_count=char_count,
                content_status="text" if char_count >= _MIN_USABLE_SECTION_CHARS else "sparse",
                tables=tables,
                warnings=[] if char_count else ["section_body_text_not_detected"],
            )
        )
    return units


def _walk_hwp_content(
    element: ET.Element,
    blocks: list[str],
    append_table: Callable[[ET.Element], None],
) -> None:
    for child in element:
        tag = _local_name(child.tag)
        if tag == "TableControl":
            append_table(child)
        elif tag == "TableCell":
            continue
        elif tag == "Paragraph":
            _walk_hwp_paragraph(child, blocks, append_table)
        else:
            _walk_hwp_content(child, blocks, append_table)


def _walk_hwp_paragraph(
    paragraph: ET.Element,
    blocks: list[str],
    append_table: Callable[[ET.Element], None],
) -> None:
    inline_parts: list[str] = []

    def flush() -> None:
        value = normalize_text("".join(inline_parts))
        inline_parts.clear()
        if value:
            blocks.append(value)

    def visit(element: ET.Element) -> None:
        for child in element:
            tag = _local_name(child.tag)
            if tag == "Text":
                inline_parts.append(child.text or "")
            elif tag == "ControlChar":
                name = child.attrib.get("name", "")
                if name == "TAB":
                    inline_parts.append("\t")
                elif name == "LINE_BREAK":
                    inline_parts.append("\n")
            elif tag == "TableControl":
                flush()
                append_table(child)
            elif tag == "TableCell":
                continue
            elif tag == "Paragraph":
                flush()
                _walk_hwp_paragraph(child, blocks, append_table)
            else:
                visit(child)

    visit(paragraph)
    flush()


def _hwp_table(table_control: ET.Element, index: int) -> ExtractedTable:
    cells: list[TableCell] = []
    for cell_element in table_control.iter():
        if _local_name(cell_element.tag) != "TableCell":
            continue
        cell_blocks: list[str] = []
        for child in cell_element:
            if _local_name(child.tag) == "Paragraph":
                _collect_cell_paragraph(child, cell_blocks)
        cells.append(
            TableCell(
                row=_integer_attribute(cell_element, "row", 0),
                column=_integer_attribute(cell_element, "col", 0),
                text=normalize_cell_text("\n".join(cell_blocks)),
                row_span=_integer_attribute(cell_element, "rowspan", 1),
                column_span=_integer_attribute(cell_element, "colspan", 1),
            )
        )

    row_count = max((cell.row + cell.row_span for cell in cells), default=0)
    column_count = max((cell.column + cell.column_span for cell in cells), default=0)
    rows = [["" for _ in range(column_count)] for _ in range(row_count)]
    for cell in cells:
        if cell.row < row_count and cell.column < column_count:
            rows[cell.row][cell.column] = cell.text
    return ExtractedTable(
        index=index,
        rows=rows,
        cells=cells,
        text=_table_text(rows),
        row_count=row_count,
        column_count=column_count,
        strategy="hwp_xml",
        quality="structural",
    )


def _collect_cell_paragraph(paragraph: ET.Element, blocks: list[str]) -> None:
    parts: list[str] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            tag = _local_name(child.tag)
            if tag == "Text":
                parts.append(child.text or "")
            elif tag == "ControlChar":
                if child.attrib.get("name") == "TAB":
                    parts.append("\t")
                elif child.attrib.get("name") == "LINE_BREAK":
                    parts.append("\n")
            elif tag not in {"TableControl", "TableCell", "Paragraph"}:
                visit(child)

    visit(paragraph)
    value = normalize_text("".join(parts))
    if value:
        blocks.append(value)


def _table_text(rows: list[list[str]]) -> str:
    lines = ["\t".join(row).rstrip() for row in rows]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _hwp_document_text(units: list[ContentUnit]) -> str:
    parts: list[str] = []
    for unit in units:
        if unit.text:
            parts.append(unit.text)
        parts.extend(table.text for table in unit.tables if table.text)
    return normalize_text("\n\n".join(parts))


def _integer_attribute(element: ET.Element, name: str, default: int) -> int:
    try:
        return int(element.attrib.get(name, default))
    except (TypeError, ValueError):
        return default


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _format_error(exc: Exception) -> str:
    message = normalize_cell_text(str(exc))
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
