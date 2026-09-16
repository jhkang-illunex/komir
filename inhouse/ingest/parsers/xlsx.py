# -*- coding: utf-8 -*-
"""XLSX → 마크다운 표 정규화(openpyxl, 2026-09-16 구현).

계기: `nas_document/학습데이터/`(광종별 광산 생산·매장량 자료, 사용자 지시 2026-09-16)에
xlsx 18건 — Kazatomprom 우라늄 광산 정리자료(광산명·위도·경도·지분)와 광산별 생산량
산출 워크북 — 이 섞여 있어 PDF/HWP만 받던 `ingest.pipeline`이 이 파일들을 건너뛰었다.

규칙
- 시트마다 `## <시트명>` 헤딩 + 마크다운 표 1개. 헤딩 기반 청킹(rag_core/ragkit/chunk.py)과
  PageIndex 트리가 그대로 먹는다.
- 완전히 빈 행·열은 버린다(재무제표 워크북은 좌상단 여백이 크다). 셀 값은 문자열화하되
  숫자는 불필요한 `.0`을 떼고, 파이프(`|`)·개행은 표를 깨지 않게 치환한다.
- 상한: 시트 30개, 시트당 행 500·열 40 — 그 이상은 경고를 남기고 자른다(연간보고서 재무제표
  워크북은 수백 행이지만 광산 자료로서 의미 있는 부분은 앞쪽이다).
- 수식은 `data_only=True`로 캐시된 계산값을 읽는다(엑셀이 마지막에 저장한 값). 캐시가 없는
  수식 셀은 빈 값이 된다.
- 표 구조(ExtractedTable)는 채우지 않고 본문 마크다운으로만 낸다 — pdf 파서와 같은 수준의
  계약(ContentUnit 1개=시트 1개, tables=[]).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from ..models import ContentUnit
from . import ParseResult

MAX_SHEETS = 30
MAX_ROWS = 500
MAX_COLS = 40
_MIN_USABLE_CHARS = 30


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-") else "0"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()[:10]
    return str(v).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def sheet_to_markdown(rows: list[list[str]]) -> str:
    """빈 행·열을 걷어낸 문자열 격자 → 마크다운 표(첫 행을 헤더로)."""
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [j for j in range(width) if any(r[j] for r in rows)]
    rows = [[r[j] for j in keep] for r in rows]
    if not rows or not rows[0]:
        return ""
    header = [c or f"col{j + 1}" for j, c in enumerate(rows[0])]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


class XlsxParser:
    name = "komir-openpyxl-sheets"
    parser_version = "1"
    signature = f"{name}:{parser_version}"

    def parse(self, path: Path) -> ParseResult:
        try:
            import openpyxl

            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 — 한 파일 실패가 배치를 막지 않게
            return ParseResult(status="parse_failed", error=f"{type(exc).__name__}: {exc}")
        warnings: list[str] = []
        units: list[ContentUnit] = []
        parts: list[str] = []
        try:
            sheets = wb.worksheets
            if len(sheets) > MAX_SHEETS:
                warnings.append(f"sheets_truncated:{len(sheets)}>{MAX_SHEETS}")
            for idx, ws in enumerate(sheets[:MAX_SHEETS], start=1):
                grid: list[list[str]] = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= MAX_ROWS:
                        warnings.append(f"rows_truncated:{ws.title}")
                        break
                    if len(row) > MAX_COLS and any(row[MAX_COLS:]):
                        warnings.append(f"cols_truncated:{ws.title}")
                    grid.append([_cell(v) for v in row[:MAX_COLS]])
                table = sheet_to_markdown(grid)
                if not table:
                    continue
                text = f"## {ws.title}\n\n{table}"
                chars = len(table)
                units.append(ContentUnit(
                    sequence=idx, locator_type="section", locator=idx, text=text, char_count=chars,
                    content_status="text" if chars >= _MIN_USABLE_CHARS else "sparse",
                    tables=[], warnings=[],
                ))
                parts.append(text)
        finally:
            wb.close()
        text = "\n\n".join(parts)
        if not text.strip():
            return ParseResult(status="parse_failed", warnings=warnings, error="empty_workbook")
        return ParseResult(status="extracted", units=units, text=text, warnings=warnings + ["extraction_method:openpyxl"])
