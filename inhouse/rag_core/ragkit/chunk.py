# -*- coding: utf-8 -*-
"""문서를 마크다운 헤딩 기준으로 청킹. 헤딩이 없으면 고정폭+오버랩 폴백.
헤딩 경계로 자르는 이유(가이드 §1): "긴 문서인데 검색이 엉뚱한 섹션에 착지"하는
탐색(navigation) 실패를 애초에 줄이기 위함 — 이 코퍼스는 실제로 저자가 ##/### 로
구획을 나눠 써서 별도 목차 추출(PageIndex) 없이도 그 구조를 그대로 재사용 가능.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .ingest import DocRecord

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")  # opendataloader-pdf 산출 md는 6단계까지 씀
MAX_CHARS = 1400       # 이 이상이면 문단 경계에서 추가 분할(임베딩 모델 컨텍스트·검색 정밀도 고려)
MIN_CHARS = 40          # 이보다 짧은 헤딩-only 청크는 다음 청크에 병합
WINDOW = 1000
OVERLAP = 200
PROSE_WINDOW = 800      # 긴 산문은 문장 경계를 지키며 이 크기까지 인접 문장을 병합
FACT_SENTENCE_MAX = 80  # 짧은 수치 사실 문장은 이웃 주제에 묻히지 않게 독립 보존
SEMANTIC_DOCUMENT_MIN_CHARS = 100_000  # 대용량 보고서만 세밀 청킹해 소형 문서 회귀 방지


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_order: int
    section_heading: str
    text: str


def _pack_units(units: list[str], *, limit: int) -> list[str]:
    """자연 경계 단위를 ``limit`` 안에서 순서대로 묶는다."""

    packed: list[str] = []
    current = ""
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        if current and len(current) + len(unit) + 1 > limit:
            packed.append(current)
            current = unit
        else:
            current = f"{current} {unit}" if current else unit
    if current:
        packed.append(current)
    return packed


def _fixed_windows(text: str) -> list[str]:
    return [text[i:i + WINDOW] for i in range(0, len(text), WINDOW - OVERLAP)]


def _split_oversized_paragraph(text: str) -> list[str]:
    """표는 행을 보존하고, 긴 영어 산문은 문장 경계에서 나눈다."""

    stripped_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if stripped_lines and all(line.startswith("|") for line in stripped_lines):
        # 표의 셀 관계는 행을 자르면 손실된다. 기존 고정폭보다 행 경계를 우선한다.
        table_units = [part for line in stripped_lines for part in (
            [line] if len(line) <= WINDOW else _fixed_windows(line)
        )]
        return _pack_units(table_units, limit=WINDOW)

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    if len(sentences) > 1:
        pieces: list[str] = []
        pending: list[str] = []

        def flush_pending() -> None:
            if pending:
                pieces.extend(_pack_units(pending, limit=PROSE_WINDOW))
                pending.clear()

        for sentence in sentences:
            numeric_values = re.findall(r"(?<![A-Za-z])\d[\d,.]*", sentence)
            if len(sentence) <= FACT_SENTENCE_MAX and len(numeric_values) >= 2:
                flush_pending()
                pieces.append(sentence.strip())
            else:
                pending.append(sentence)
        flush_pending()

        final: list[str] = []
        for packed in pieces:
            if len(packed) <= WINDOW:
                final.append(packed)
            else:
                final.extend(
                    packed[i:i + WINDOW]
                    for i in range(0, len(packed), WINDOW - OVERLAP)
                )
        return final

    return _fixed_windows(text)


def _split_long(text: str, heading: str, *, semantic_prose: bool = False) -> list[str]:
    """MAX_CHARS 초과 섹션을 문단(빈 줄) 경계에서 나눔."""
    # OCR HWP는 광종별 표 행이 줄바꿈으로만 구분되는 경우가 있다. 여러 광종 행을
    # 한 청크에 섞지 않고 각 행의 광종-전망 관계를 보존한다.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1 and any("▪" in line for line in lines) and not any(
        line.startswith("|") for line in lines
    ):
        return lines
    if len(text) <= MAX_CHARS:
        return [text]
    paras = re.split(r"\n{2,}", text)
    out, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > MAX_CHARS:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    # 문단 자체가 MAX_CHARS를 넘는 경우(긴 표 등) 고정폭으로 추가 분할
    final = []
    for seg in out:
        # 전체 섹션이 길면 그 안의 1,400자 미만 영어 문단도 여러 주제를 담을 수
        # 있다. 문장 경계가 실제로 있을 때는 짧은 의미단위로 나눈다.
        if semantic_prose and len(seg) > PROSE_WINDOW and len(
            re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", seg)
        ) > 1:
            final.extend(_split_oversized_paragraph(seg))
        elif len(seg) <= MAX_CHARS:
            final.append(seg)
        else:
            final.extend(_fixed_windows(seg))
    # 원본의 "---" 구분선처럼 문단 경계에 홀로 남는 자투리(<MIN_CHARS)는 인접 조각에 흡수
    # (섹션 끝 "---"가 blank-line으로 분리돼 독립 문단이 되는 경우가 실제로 발생함)
    merged = []
    for seg in final:
        if merged and len(seg) < MIN_CHARS:
            merged[-1] = f"{merged[-1]}\n\n{seg}"
        elif merged and len(merged[-1]) < MIN_CHARS:
            merged[-1] = f"{merged[-1]}\n\n{seg}"
        else:
            merged.append(seg)
    return merged


def chunk_document(doc: DocRecord) -> list[ChunkRecord]:
    lines = doc.raw_text.splitlines()
    sections: list[tuple[str, list[str]]] = []  # (heading, body_lines)
    cur_heading = doc.title
    cur_body: list[str] = []
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            if cur_body:
                sections.append((cur_heading, cur_body))
            cur_heading = m.group(2).strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_body:
        sections.append((cur_heading, cur_body))

    if not sections:
        # 헤딩이 전혀 없는 원문(드묾) → 고정폭 폴백
        text = doc.raw_text
        chunks = []
        for i in range(0, len(text), WINDOW - OVERLAP):
            seg = text[i:i + WINDOW].strip()
            if len(seg) >= MIN_CHARS:
                chunks.append((doc.title, seg))
        sections = chunks if chunks else [(doc.title, text)]
    else:
        # 너무 짧은 섹션은 다음 섹션과 합쳐 헤딩만 있고 내용 없는 청크를 방지
        merged: list[tuple[str, str]] = []
        pending_heading = None
        pending_text = ""
        for heading, body_lines in sections:
            body = "\n".join(body_lines).strip()
            if pending_text and len(pending_text) < MIN_CHARS:
                body = f"{pending_text}\n\n{body}".strip()
                heading = f"{pending_heading} / {heading}"
            if len(body) < MIN_CHARS:
                pending_heading, pending_text = heading, body
                continue
            merged.append((heading, body))
            pending_heading, pending_text = None, ""
        if pending_text:
            if merged:
                h, t = merged[-1]
                merged[-1] = (h, f"{t}\n\n{pending_text}")
            else:
                merged.append((pending_heading, pending_text))
        sections = merged

    records: list[ChunkRecord] = []
    order = 0
    for heading, body in sections:
        for piece in _split_long(
            body,
            heading,
            semantic_prose=len(doc.raw_text) >= SEMANTIC_DOCUMENT_MIN_CHARS,
        ):
            piece = piece.strip()
            if not piece:
                continue
            cid = hashlib.md5(f"{doc.doc_id}:{order}".encode("utf-8")).hexdigest()[:16]
            records.append(ChunkRecord(
                chunk_id=cid,
                doc_id=doc.doc_id,
                chunk_order=order,
                section_heading=heading,
                text=piece,
            ))
            order += 1
    return records


if __name__ == "__main__":
    from .ingest import load_documents

    docs = load_documents()
    total = 0
    lens = []
    for d in docs:
        cs = chunk_document(d)
        total += len(cs)
        lens.extend(len(c.text) for c in cs)
    print(f"문서 {len(docs)}건 -> 청크 {total}개")
    print(f"청크 길이: 평균 {sum(lens)/len(lens):.0f}자, 최대 {max(lens)}자, 최소 {min(lens)}자")
