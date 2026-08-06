# -*- coding: utf-8 -*-
"""날짜 미상 문서의 발행일 추정 — classify.date_of()(파일명)가 실패했을 때의 후속 폴백 체인.
실측(2026-07-07, §9): 조달청 887건 중 189건이 파일명만으론 날짜를 못 읽었는데, 그중 대다수가
PDF 메타데이터(/CreationDate)로 해결됨(245건 중 242건, 2016+만 61건 실질 대상).
우선순위: ①classify.date_of(파일명) ②PDF 메타데이터 ③본문 날짜패턴 ④발행처 기본값(정적 스냅샷)."""
import re
from . import classify

_META_DATE = re.compile(r"D:(\d{4})(\d{2})(\d{2})")
_CONTENT_DATE = re.compile(r"(20\d{2})[.\-/년]\s?(0?[1-9]|1[0-2])[.\-/월]\s?(0?[1-9]|[12]\d|3[01])")

# 필명·본문 어디에도 신뢰 가능한 날짜가 없는 정적 스냅샷 자료 — sources.yaml의 근거와 동일
# (EU_SCRREEN: "EU 정책보고서 스냅샷(2020)").
SOURCE_DEFAULT = {
    "EU_SCRREEN": "2020-01-01",
}


def _from_pdf_metadata(path: str) -> str | None:
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        md = r.metadata or {}
        raw = md.get("/CreationDate") or md.get("/ModDate")
        if not raw:
            return None
        m = _META_DATE.search(str(raw))
        if not m:
            return None
        return classify._valid(*m.groups())
    except Exception:
        return None


def _from_ole_metadata(path: str) -> str | None:
    """hwp/xls(구형 OLE 복합문서) — 실측(2026-07-08): xls는 create_time이 종종 채워져 있으나
    hwp는 필드 자체가 비어있는 경우가 많음(None이면 자연히 다음 폴백으로 넘어감)."""
    try:
        import olefile
        ole = olefile.OleFileIO(path)
        meta = ole.get_metadata()
        ole.close()
        dt = meta.create_time or meta.last_saved_time
        if not dt:
            return None
        return classify._valid(dt.year, dt.month, dt.day)
    except Exception:
        return None


def _from_xlsx_metadata(path: str) -> str | None:
    """xlsx(OOXML) — docProps/core.xml의 created/modified 속성."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True)
        p = wb.properties
        dt = p.created or p.modified
        if not dt:
            return None
        return classify._valid(dt.year, dt.month, dt.day)
    except Exception:
        return None


def _from_metadata(path: str) -> str | None:
    low = path.lower()
    if low.endswith(".pdf"):
        return _from_pdf_metadata(path)
    if low.endswith((".hwp", ".xls")):
        return _from_ole_metadata(path)
    if low.endswith(".xlsx"):
        return _from_xlsx_metadata(path)
    return None


def _from_content(text: str) -> str | None:
    if not text:
        return None
    for m in _CONTENT_DATE.finditer(text[:3000]):
        v = classify._valid(m.group(1), m.group(2), m.group(3))
        if v:
            return v
    return None


def resolve_date(path: str, name: str, text: str, source: str) -> tuple:
    """반환 (pub_date: str|None, method: str) — method는 감사/성공률 리포트용."""
    d = classify.date_of(name)
    if d:
        return d, "filename"
    d = _from_metadata(path)
    if d:
        return d, "file_metadata"
    d = _from_content(text)
    if d:
        return d, "content"
    d = SOURCE_DEFAULT.get(source)
    if d:
        return d, "source_default"
    return None, "unresolved"
