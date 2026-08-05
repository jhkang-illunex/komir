# -*- coding: utf-8 -*-
"""인용 강제 + 검증게이트 기반 답변 생성 (가이드 §4).
효과 우선순위 1위 원칙 그대로 구현: "모델이 절대 틀리지 않게" 대신
"증명 가능한 것만 말하고 나머지는 기권" — 생성 → 문장별 인용 파싱 →
검증 실패 인용 제거 → 유효 인용이 하나도 안 남으면 답변 전체 기권.
LLM 클라이언트는 geo/llm/openai_compat.py 재사용(공용 provider 추상화 재발명 금지)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

from geo.llm.openai_compat import OpenAICompatChat

from .build_index import DB_PATH
from .retrieve import RetrievedChunk, hybrid_search

ABSTAIN_TEXT = "제공된 문서에서 근거를 찾지 못했습니다."

SYSTEM_PROMPT = (
    "당신은 '핵심광물 수급위기 진단·수요예측' 프로젝트의 내부 문서 기반 Q&A 어시스턴트입니다.\n"
    "반드시 지킬 규칙:\n"
    "1. 오직 [근거] 섹션의 발췌문에만 근거해 답하세요. 외부지식·추정·일반상식 사용 금지.\n"
    "2. 모든 문장 끝에 그 문장의 근거가 된 발췌 번호를 [n] 형식으로 표기하세요"
    "(예: ...2,772건 제거되었다. [2]). 여러 근거를 종합했다면 [2][4]처럼 복수 표기.\n"
    "3. 발췌문에 없는 숫자·이름·날짜·결론을 지어내지 마세요.\n"
    f"4. 질문에 답할 근거가 발췌문에 전혀 없으면 다른 말 없이 정확히 이렇게만 답하세요: \"{ABSTAIN_TEXT}\"\n"
    "5. 인용 번호가 없는 문장은 존재해서는 안 됩니다."
)

CITE_RE = re.compile(r"\[(\d+)\]")


@dataclass
class Answer:
    question: str
    text: str
    abstained: bool
    chunks: list[RetrievedChunk] = field(default_factory=list)
    bogus_citations: list[int] = field(default_factory=list)
    raw_text: str = ""


def _cfg_from_env() -> dict:
    load_dotenv()
    return {
        "provider": os.environ.get("LLM_PROVIDER", "openai_compat"),
        "base_url": os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"),
        "model": os.environ.get("LLM_MODEL", "qwen2.5:32b"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", 0)),
        "json_mode": False,  # 인용 포함 자유서술 답변 — JSON 강제 안 함
    }


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    lines = [f"[질문]\n{question}\n", "[근거]"]
    for i, c in enumerate(chunks, 1):
        lines.append(f"[{i}] (출처: {c.source_path} · {c.section_heading})\n{c.text}\n")
    return "\n".join(lines)


CLAUSE_RE = re.compile(r"(.+?)((?:\[\d+\]\s*)+)", re.S)


def _strip_uncited_sentences(text: str, n_chunks: int) -> tuple[str, list[int]]:
    """인용 태그([n]) 등장 지점을 절 경계로 삼아, 인용이 없거나 존재하지 않는
    근거번호를 인용한 절을 제거. 한국어 종결어미(다/요/음 등)는 문장 중간에도
    흔히 등장해 구두점 기반 문장분리가 깨지기 쉬우므로, 모델이 반드시 붙이도록
    강제한 [n] 태그 자체를 분리 기준으로 쓴다(더 견고함).
    (guide §4-2: 실제 청크와 매칭되지 않는 '날조 인용'은 사용자 도달 전 제거)"""
    valid = set(range(1, n_chunks + 1))
    bogus: list[int] = []
    kept = []
    for m in CLAUSE_RE.finditer(text):
        clause_text = m.group(1).strip()
        cites = [int(n) for n in CITE_RE.findall(m.group(2))]
        bad = [n for n in cites if n not in valid]
        if bad:
            bogus.extend(bad)
            continue
        if clause_text:
            kept.append(f"{clause_text} " + " ".join(f"[{n}]" for n in cites))
    return " ".join(kept).strip(), bogus


def answer(question: str, k: int = 6, db_path: str = DB_PATH, chat: OpenAICompatChat | None = None) -> Answer:
    chunks = hybrid_search(question, k=k, db_path=db_path)
    if not chunks:
        return Answer(question=question, text=ABSTAIN_TEXT, abstained=True)

    chat = chat or OpenAICompatChat(_cfg_from_env())
    user = build_user_prompt(question, chunks)
    result = chat.complete(SYSTEM_PROMPT, user, max_tokens=800)
    raw = result.text.strip()

    if raw == ABSTAIN_TEXT or not raw:
        return Answer(question=question, text=ABSTAIN_TEXT, abstained=True, chunks=chunks, raw_text=raw)

    cleaned, bogus = _strip_uncited_sentences(raw, len(chunks))
    if not cleaned.strip():
        return Answer(question=question, text=ABSTAIN_TEXT, abstained=True, chunks=chunks,
                       bogus_citations=bogus, raw_text=raw)
    return Answer(question=question, text=cleaned, abstained=False, chunks=chunks,
                  bogus_citations=bogus, raw_text=raw)


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "진단모델 AUC는 얼마인가?"
    a = answer(q)
    print("Q:", a.question)
    print("A:", a.text)
    print("기권:", a.abstained, "/ 날조인용:", a.bogus_citations)
    for i, c in enumerate(a.chunks, 1):
        print(f"  [{i}] {c.source_path} :: {c.section_heading}")
