# -*- coding: utf-8 -*-
"""페이지추천 이식본 스모크 테스트 — `python3 services/rag_chat/tests/smoke_page_recommend.py`.

pytest를 쓰지 않는다: 이 저장소에 아직 테스트 러너가 없고(2026-08-11 기준 komir 전체에
test_*.py 0건, pytest 미설치), 이식이 깨지지 않았는지 확인하는 게 목적이라 표준 라이브러리만으로
돌아가는 실행 스크립트로 뒀다.

LLM 서버(vLLM)는 이 환경에서 접속 불가(`host.docker.internal:52302`는 컨테이너 전용 호스트명)
이므로 실제 호출은 하지 않는다 — 외부 repo 테스트가 쓰던 결정론적 더블 ScriptedJsonLLM
(원본 `search/llm.py`, 프로덕션 코드가 아니라 테스트 더블이라 여기로만 이식)을 끼워 그래프
배선·상태이월·필터해석까지 검증한다. DB(MSR_DB)도 건드리지 않는다 — service.py가 세션
저장소를 모르게 설계했기 때문(routers/chat.py가 session_store로 처리)."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_RAG_CHAT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAG_CHAT_ROOT))

from app.page_recommend.filters import display_filter_value, resolve_filters  # noqa: E402
from app.page_recommend.metadata import SnapshotMetadataResolver  # noqa: E402
from app.page_recommend.registry import load_source_registry  # noqa: E402
from app.page_recommend.renderer import build_recommendation, page_url  # noqa: E402
from app.page_recommend.service import PageRecommendService  # noqa: E402
from app.page_recommend.temporal import (  # noqa: E402
    build_request_context,
    resolve_relative_temporal,
)
from shared.llm_client import LLMInvocation, LLMOutputError  # noqa: E402


class ScriptedJsonLLM:
    """KomirJsonLLM 자리에 끼우는 결정론적 더블(원본 search/llm.py에서 이식)."""

    def __init__(self, responses: Mapping[str, Iterable[Mapping[str, Any]]]) -> None:
        self._responses: dict[str, deque] = defaultdict(deque)
        for task, task_responses in responses.items():
            self._responses[task].extend(dict(item) for item in task_responses)
        self.calls: list[dict[str, Any]] = []

    def invoke(self, *, task, instructions, payload, output_model, max_tokens):
        self.calls.append({"task": task, "payload": dict(payload)})
        if not self._responses[task]:
            raise AssertionError(f"no scripted response remaining for task {task}")
        raw = self._responses[task].popleft()
        validated = output_model.model_validate(raw)
        return LLMInvocation(
            output=validated,
            record={
                "task": task,
                "input": dict(payload),
                "output_schema": output_model.__name__,
                "attempts": [{"attempt": 1, "raw_content": json.dumps(raw, ensure_ascii=False)}],
                "outcome": "success",
            },
        )


def _fixed_clock():
    return datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc)


def _service(llm, registry, resolver) -> PageRecommendService:
    return PageRecommendService(
        registry=registry,
        llm=llm,
        metadata_resolver=resolver,
        clock=_fixed_clock,
        timezone_name="Asia/Seoul",
    )


def main() -> int:
    checks: list[str] = []

    # 1) 레지스트리 — YAML 직접 로드(생성 JSON 미이식)로 43개 페이지가 다 검증되는지
    started = time.perf_counter()
    registry = load_source_registry()
    load_seconds = time.perf_counter() - started
    assert len(registry.pages) == 43, len(registry.pages)
    assert registry.get("map_korea").identity.name
    checks.append(f"registry: {len(registry.pages)}개 페이지, 로드 {load_seconds:.2f}s")

    # 2) 메타데이터 스냅샷(패키지 상대경로)
    resolver = SnapshotMetadataResolver.from_path()
    checks.append(f"metadata snapshot: snapshot_id={resolver.snapshot_id}")

    # 3) 순수함수 — 상대기간 해석/필터 해석/렌더링(LLM·DB 불필요)
    trailing = resolve_relative_temporal(
        {"kind": "trailing", "count": 5, "unit": "year"},
        filter_type="date_range",
        current_date=date(2026, 8, 11),
        granularity="year",
    )
    assert trailing == {"start": "2021", "end": "2026"}, trailing
    context = build_request_context(_fixed_clock(), "Asia/Seoul")
    assert context["current_date"] == "2026-08-11", context
    checks.append(f"temporal: 최근5년→{trailing}, request_context={context['current_datetime']}")

    page = registry.get("price_base_metals")
    resolved = resolve_filters(
        page,
        {"mineral": "구리"},
        as_of=date(2026, 8, 11),
        metadata_resolver=resolver,
    )
    assert resolved.effective.get("mineral"), resolved
    item = build_recommendation(
        page,
        effective_filters=resolved.effective,
        defaulted_filters=resolved.defaulted,
    )
    assert item.url.startswith("https://www.komis.or.kr"), item.url
    checks.append(
        f"filters: price_base_metals '구리' → effective={resolved.effective} "
        f"defaulted={sorted(resolved.defaulted)} url={page_url(page)}"
    )
    assert display_filter_value(page, "mineral", resolved.effective["mineral"])

    # 4) 그래프 배선 — 1턴(추천)
    llm = ScriptedJsonLLM(
        {
            "candidate_discovery": [{"candidate_page_ids": ["map_korea"]}],
            "filter_extraction": [{"filter_values": {"mineral": "리튬", "measure": "amount"}}],
        }
    )
    service = _service(llm, registry, resolver)
    first = service.recommend("한국의 리튬 수입 거래금액을 국가별로 어디서 봐?", thread_id="t1")
    assert first.response.status == "recommended", first.response.status
    assert first.response.relation == "first_turn"
    assert first.response.recommendations[0].page_id == "map_korea"
    checks.append(
        f"graph 1턴: status={first.response.status} page={first.response.recommendations[0].page_id} "
        f"filters={first.response.recommendations[0].suggested_filters}"
    )

    # 5) 상태이월(체크포인터 대체) — 2턴 same_task에서 이전 필터가 유지되는지
    llm2 = ScriptedJsonLLM(
        {
            "relation": [{"relation": "same_task"}],
            "filter_extraction": [{"filter_values": {"measure": "weight"}}],
        }
    )
    service2 = _service(llm2, registry, resolver)
    second = service2.recommend(
        "달러 말고 톤 단위로 보고 싶어",
        thread_id="t1",
        message_history=first.message_history,
        active_artifact=first.active_artifact,
    )
    filters = second.response.recommendations[0].suggested_filters
    assert second.response.relation == "same_task", second.response.relation
    assert filters.get("mineral") == "리튬", filters
    assert filters.get("measure") == "weight", filters
    assert [call["task"] for call in llm2.calls] == ["relation", "filter_extraction"]
    checks.append(f"graph 2턴(same_task, 상태이월): filters={filters}")

    # 6) 후보 2개 → ambiguous
    llm3 = ScriptedJsonLLM(
        {
            "candidate_discovery": [{"candidate_page_ids": ["map_korea", "map_global"]}],
            "page_selection": [{"page_id": None}],
        }
    )
    ambiguous = _service(llm3, registry, resolver).recommend(
        "리튬 거래량을 국가별로 보고 싶어", thread_id="t2"
    )
    assert ambiguous.response.status == "ambiguous", ambiguous.response.status
    assert {item.page_id for item in ambiguous.response.recommendations} == {
        "map_korea",
        "map_global",
    }
    checks.append(
        "graph ambiguous: "
        f"{[item.page_id for item in ambiguous.response.recommendations]} "
        f"artifact={sorted(ambiguous.active_artifact or {})}"
    )

    # 7) LLM 출력오류(LLMOutputError)는 흡수되고 경고로 남는지 — 전송오류 분기를 뺀 뒤에도
    #    원본과 같은 열화(degrade) 동작이 유지되는지 확인
    class BrokenRelationLLM(ScriptedJsonLLM):
        def invoke(self, **kwargs):
            if kwargs["task"] == "relation":
                raise LLMOutputError("invalid relation", record={"outcome": "invalid_output"})
            return super().invoke(**kwargs)

    llm4 = BrokenRelationLLM(
        {
            "candidate_discovery": [{"candidate_page_ids": ["map_korea"]}],
            "filter_extraction": [{"filter_values": {"mineral": "리튬"}}],
        }
    )
    degraded = _service(llm4, registry, resolver).recommend(
        "그거 말고 다른 건?",
        thread_id="t1",
        message_history=first.message_history,
        active_artifact=first.active_artifact,
    )
    assert "relation_invalid_output" in degraded.response.warnings, degraded.response.warnings
    checks.append(f"graph LLM출력오류 흡수: warnings={degraded.response.warnings}")

    for line in checks:
        print(f"[OK] {line}")
    print("\n=== 1턴 응답 본문 ===")
    print(first.response.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
