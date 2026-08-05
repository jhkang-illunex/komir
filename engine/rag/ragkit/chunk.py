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

HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
MAX_CHARS = 1400       # 이 이상이면 문단 경계에서 추가 분할(임베딩 모델 컨텍스트·검색 정밀도 고려)
MIN_CHARS = 40          # 이보다 짧은 헤딩-only 청크는 다음 청크에 병합
WINDOW = 1000
OVERLAP = 200


@dataclass
class ChunkRecord:
    chunk_id: str
    doc_id: str
    chunk_order: int
    section_heading: str
    text: str


def _split_long(text: str, heading: str) -> list[str]:
    """MAX_CHARS 초과 섹션을 문단(빈 줄) 경계에서 나눔."""
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
        if len(seg) <= MAX_CHARS:
            final.append(seg)
        else:
            for i in range(0, len(seg), WINDOW - OVERLAP):
                final.append(seg[i:i + WINDOW])
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
        for piece in _split_long(body, heading):
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
