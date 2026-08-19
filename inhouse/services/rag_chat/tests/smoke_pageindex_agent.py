# -*- coding: utf-8 -*-
"""`shared.retrieval.pageindex_agent` 루프 메커니즘 스모크 테스트 —
`python3 services/rag_chat/tests/smoke_pageindex_agent.py`.

`chatbot_graph.py`가 route.pageindex_mode=="agentic"일 때 부르는
`pageindex_agent.agentic_lookup()`의 ReAct 루프(step LLM 1회 -> 결정적 도구
실행 -> scratchpad 되먹임, 최대 MAX_AGENT_STEPS회)가 계약대로 도는지만 본다 —
LLM은 전부 ScriptedJsonLLM(smoke_page_recommend.py 이식) 더블이고,
`commodity_world_table`은 실제 USGS 원문을 안 읽도록 모의로 갈아끼운다(원문
파싱 정확도 자체는 `pageindex_agent_data_probe.py`가 실데이터로 별도 검증).
"""
from __future__ import annotations

import sys
from pathlib import Path

_RAG_CHAT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAG_CHAT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_INHOUSE_ROOT = _RAG_CHAT_ROOT.parents[1]
sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

from smoke_page_recommend import ScriptedJsonLLM  # noqa: E402

from shared.retrieval import pageindex_agent  # noqa: E402
from shared.llm_client import LLMError, LLMOutputError  # noqa: E402


def _fake_blocks(commodity: str, *, max_editions: int = 3) -> list[dict]:
    if commodity == "NICKEL":
        return [
            {"doc": "USGS_2026", "text": "World Mine Production: Indonesia 2,200 ...", "density": 5},
            {"doc": "USGS_2025", "text": "World Mine Production: Indonesia 1,800 ...", "density": 5},
        ]
    if commodity == "TIN":
        return [{"doc": "USGS_2026", "text": "World Mine Production: Indonesia 60 ...", "density": 4}]
    return []  # COBALT 등 "못 찾음" 경로 테스트용


def main() -> int:
    # 1) open_commodity 성공 -> evidence 축적, checked 경고 남음
    pageindex_agent.commodity_world_table = _fake_blocks  # type: ignore[assignment]
    llm = ScriptedJsonLLM({
        "pageindex_agent_step": [
            {"action": "open_commodity", "commodity": "NICKEL"},
            {"action": "finish"},
        ],
    })
    ev, warn = pageindex_agent.agentic_lookup("니켈 세계 생산 1위는?", llm=llm)
    assert len(ev) == 2, ev
    assert all(e.kind == "pageindex" for e in ev), ev
    assert "NICKEL" in ev[0].section, ev[0]
    assert "pageindex_agent_checked:NICKEL" in warn, warn
    print(f"[OK] open_commodity 성공: evidence {len(ev)}건, warnings={warn}")

    # 2) 못 찾음 -> evidence 0건이어도 다음 스텝은 계속 진행, no_evidence 경고
    llm2 = ScriptedJsonLLM({
        "pageindex_agent_step": [
            {"action": "open_commodity", "commodity": "COBALT"},
            {"action": "finish"},
        ],
    })
    ev2, warn2 = pageindex_agent.agentic_lookup("코발트 1위는?", llm=llm2)
    assert ev2 == [], ev2
    assert "pageindex_agent_no_evidence" in warn2, warn2
    assert "pageindex_agent_checked:COBALT" in warn2, warn2
    print(f"[OK] 미발견 경로: evidence 0건, warnings={warn2}")

    # 3) 스텝 예산 소진 — finish 없이 서로 다른 광종을 계속 열면 max_steps에서 멈춘다
    llm3 = ScriptedJsonLLM({
        "pageindex_agent_step": [
            {"action": "open_commodity", "commodity": "NICKEL"},
            {"action": "open_commodity", "commodity": "TIN"},
            {"action": "list_commodities"},
            {"action": "open_commodity", "commodity": "COBALT"},
            {"action": "open_commodity", "commodity": "COPPER"},
            {"action": "open_commodity", "commodity": "ZINC"},  # max_steps=5라 여기까진 안 감
        ],
    })
    ev3, warn3 = pageindex_agent.agentic_lookup("여러 나라 순위 비교", llm=llm3, max_steps=5)
    assert len(llm3.calls) == 5, llm3.calls
    checked_warning = next(w for w in warn3 if w.startswith("pageindex_agent_checked:"))
    assert checked_warning.count(",") == 3, checked_warning  # NICKEL,TIN,COBALT,COPPER = 4개
    print(f"[OK] 스텝 예산(5) 소진: LLM 호출 {len(llm3.calls)}회, {checked_warning}")

    # 4) 반복 가드 — 같은 (action, commodity)를 또 고르면 즉시 종료
    llm4 = ScriptedJsonLLM({
        "pageindex_agent_step": [
            {"action": "open_commodity", "commodity": "NICKEL"},
            {"action": "open_commodity", "commodity": "NICKEL"},  # 반복 -> 여기서 중단
            {"action": "finish"},  # 소비되지 않아야 함
        ],
    })
    ev4, warn4 = pageindex_agent.agentic_lookup("니켈 반복 요청", llm=llm4)
    assert len(llm4.calls) == 2, llm4.calls
    assert "pageindex_agent_repeat_guard" in warn4, warn4
    print(f"[OK] 반복 가드: LLM 호출 {len(llm4.calls)}회(3번째 미소비), warnings={warn4}")

    # 5) LLM 장애 — 그 시점까지 모은 근거만 부분 반환(부분 열화)
    class DyingLLM:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, *, task, instructions, payload, output_model, max_tokens):
            self.calls += 1
            if self.calls == 1:
                return ScriptedJsonLLM({
                    "pageindex_agent_step": [{"action": "open_commodity", "commodity": "NICKEL"}],
                }).invoke(task=task, instructions=instructions, payload=payload,
                          output_model=output_model, max_tokens=max_tokens)
            raise LLMOutputError("boom")

    ev5, warn5 = pageindex_agent.agentic_lookup("니켈 그리고 장애", llm=DyingLLM())
    assert len(ev5) == 2, ev5  # 1스텝에서 이미 모은 NICKEL 2건은 살아남음
    assert any(w.startswith("pageindex_agent_llm_error:") for w in warn5), warn5
    print(f"[OK] LLM 장애 시 부분 열화: evidence {len(ev5)}건, warnings={warn5}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
