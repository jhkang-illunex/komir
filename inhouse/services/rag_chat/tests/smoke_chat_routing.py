# -*- coding: utf-8 -*-
"""/chat 두 경로 배선 스모크 테스트 — `python3 services/rag_chat/tests/smoke_chat_routing.py`.

검증 대상은 routers/chat.py의 분기·세션 연동이다.
- 임시 DuckDB(MSR_DB 환경변수로 주입, chat_session/chat_message만 생성)를 쓴다 —
  운영 DB(data_lake/db/minerals.duckdb)에 테스트 행을 남기지 않기 위함.
- LLM은 전부 더블: 의도분류는 지정한 경로를 반환하는 가짜, 페이지추천 그래프는
  smoke_page_recommend.py의 ScriptedJsonLLM.
- 문서 Q&A 경로는 검색 계층(rag/index) 미구축 상태를 그대로 태워 기권 응답으로
  끝나는지만 본다(그 경로 자체는 이번 변경 대상이 아님 — 회귀 확인용)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_RAG_CHAT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAG_CHAT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

_TMP_DB = Path(tempfile.mkdtemp(prefix="rag_chat_smoke_")) / "chat.duckdb"
os.environ["MSR_DB"] = str(_TMP_DB)

import duckdb  # noqa: E402

duckdb.connect(str(_TMP_DB)).execute(
    """
    CREATE TABLE chat_session (
      session_id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(80), title VARCHAR(200),
      created_at TIMESTAMP, updated_at TIMESTAMP);
    CREATE TABLE chat_message (
      message_id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36), role VARCHAR(16),
      content TEXT, citations_json VARCHAR(4000), created_at TIMESTAMP);
    """
)

from smoke_page_recommend import ScriptedJsonLLM, _fixed_clock  # noqa: E402

from app.page_recommend import service as page_service  # noqa: E402
from app.page_recommend.metadata import SnapshotMetadataResolver  # noqa: E402
from app.page_recommend.registry import load_source_registry  # noqa: E402
from app.routers import chat as chat_router  # noqa: E402


def _events(generator) -> list[dict]:
    return [json.loads(event["data"]) for event in generator]


def _install_scripted_service(responses: dict) -> ScriptedJsonLLM:
    llm = ScriptedJsonLLM(responses)
    page_service._service = page_service.PageRecommendService(
        registry=_REGISTRY,
        llm=llm,
        metadata_resolver=_RESOLVER,
        clock=_fixed_clock,
        timezone_name="Asia/Seoul",
    )
    return llm


_REGISTRY = load_source_registry()
_RESOLVER = SnapshotMetadataResolver.from_path()


def main() -> int:
    # 1) mode="page" — 명시적 라우팅(의도분류 LLM 호출 없음)
    _install_scripted_service(
        {
            "candidate_discovery": [{"candidate_page_ids": ["map_korea"]}],
            "filter_extraction": [{"filter_values": {"mineral": "리튬"}}],
        }
    )
    request = chat_router.ChatRequest(
        user_id="smoke", message="한국 리튬 수입 현황은 어디서 봐?", mode="page"
    )
    events = _events(chat_router._run_chat(request, "public"))
    session_id = events[0]["session_id"]
    done = events[-1]
    assert done["done"] and done["mode"] == "page", done
    assert done["status"] == "recommended", done["status"]
    assert done["recommendations"][0]["page_id"] == "map_korea"
    print(f"[OK] mode=page 1턴: session={session_id[:8]} status={done['status']} "
          f"page={done['recommendations'][0]['page_id']} 이벤트 {len(events)}건")

    # 2) 같은 세션 2턴 — DB에 저장된 상태로 same_task 이월이 되는지(체크포인터 대체 경로)
    llm2 = _install_scripted_service(
        {
            "relation": [{"relation": "same_task"}],
            "filter_extraction": [{"filter_values": {"measure": "weight"}}],
        }
    )
    followup = chat_router.ChatRequest(
        user_id="smoke", session_id=session_id, message="톤 단위로 보고 싶어", mode="page"
    )
    events2 = _events(chat_router._run_chat(followup, "public"))
    done2 = events2[-1]
    filters = done2["recommendations"][0]["suggested_filters"]
    assert done2["relation"] == "same_task", done2["relation"]
    assert filters.get("mineral") == "리튬", filters
    assert filters.get("measure") == "weight", filters
    relation_payload = next(call for call in llm2.calls if call["task"] == "relation")["payload"]
    # 히스토리를 이번 질문 저장 "전"에 읽는지 확인 — 저장 후에 읽으면 previous_turn.question이
    # 이번 질문으로 오염된다.
    assert relation_payload["previous_turn"]["question"] == "한국 리튬 수입 현황은 어디서 봐?"
    print(f"[OK] mode=page 2턴(DB 왕복 상태이월): relation={done2['relation']} filters={filters}")
    print(f"     previous_turn.question={relation_payload['previous_turn']['question']!r}")

    # 3) 저장된 행 확인 — 중복저장 없이 user/assistant 4행, 상태 JSON 파싱 가능
    rows = duckdb.connect(str(_TMP_DB)).execute(
        "SELECT role, content, citations_json FROM chat_message ORDER BY created_at"
    ).fetchall()
    assert [row[0] for row in rows] == ["user", "assistant", "user", "assistant"], rows
    state = json.loads(rows[-1][2])["page_recommend"]
    assert state["active_artifact"]["selected_page_id"] == "map_korea", state
    print(f"[OK] chat_message {len(rows)}행(중복저장 없음), "
          f"citations_json {len(rows[-1][2])}자, artifact 키={sorted(state['active_artifact'])}")

    # 3-b) ambiguous → 후속 선택. same_task와 저장되는 상태 키가 다른 경로다
    #      (pending_candidate_page_ids·original_question·inherited_filters) — 여기서
    #      original_question이 DB를 왕복해 살아남아야 2턴 필터추출이 "원래 질문 + 추가
    #      선택" 합성 질문으로 돈다. 트리밍(_persistable_artifact)이 잘못되면 조용히
    #      새 검색으로 열화되므로 별도로 확인한다.
    _install_scripted_service(
        {
            "candidate_discovery": [{"candidate_page_ids": ["map_korea", "map_global"]}],
            "page_selection": [{"page_id": None}],
        }
    )
    amb_events = _events(
        chat_router._run_chat(
            chat_router.ChatRequest(
                user_id="smoke2", message="리튬 거래량을 국가별로 보고 싶어", mode="page"
            ),
            "public",
        )
    )
    amb_session = amb_events[0]["session_id"]
    assert amb_events[-1]["status"] == "ambiguous", amb_events[-1]

    llm_pick = _install_scripted_service(
        {
            "relation": [{"relation": "same_task"}],
            "page_selection": [{"page_id": "map_global"}],
            "filter_extraction": [{"filter_values": {"mineral": "리튬"}}],
        }
    )
    pick_events = _events(
        chat_router._run_chat(
            chat_router.ChatRequest(
                user_id="smoke2",
                session_id=amb_session,
                message="세계 수급지도로 볼게",
                mode="page",
            ),
            "public",
        )
    )
    pick_done = pick_events[-1]
    assert pick_done["status"] == "recommended", pick_done
    assert pick_done["recommendations"][0]["page_id"] == "map_global", pick_done
    extraction_question = next(
        call for call in llm_pick.calls if call["task"] == "filter_extraction"
    )["payload"]["question"]
    assert extraction_question.startswith("원래 질문: 리튬 거래량"), extraction_question
    print(f"[OK] mode=page ambiguous→후속선택(DB 왕복): {pick_done['status']} "
          f"page={pick_done['recommendations'][0]['page_id']}")
    print(f"     합성 질문={extraction_question!r}")

    # 4) mode="auto" — 의도분류 더블이 page를 고르면 페이지추천으로 간다
    class FakeIntentLLM:
        def __init__(self, route: str) -> None:
            self.route = route
            self.calls = 0

        def invoke(self, *, task, instructions, payload, output_model, max_tokens):
            self.calls += 1
            from shared.llm_client import LLMInvocation

            return LLMInvocation(
                output=output_model.model_validate({"route": self.route}), record={"task": task}
            )

    from app import intent  # noqa: PLC0415

    fake = FakeIntentLLM("page")
    original_classify = chat_router.classify_intent
    chat_router.classify_intent = lambda message: intent.classify_intent(message, llm=fake)
    try:
        _install_scripted_service(
            {
                "relation": [{"relation": "new_task"}],
                "candidate_discovery": [{"candidate_page_ids": ["price_base_metals"]}],
                "filter_extraction": [{"filter_values": {"mineral": "구리"}}],
            }
        )
        auto_request = chat_router.ChatRequest(
            user_id="smoke", session_id=session_id, message="구리 가격 화면 알려줘"
        )
        events3 = _events(chat_router._run_chat(auto_request, "public"))
        done3 = events3[-1]
        assert fake.calls == 1, fake.calls
        assert done3["recommendations"][0]["page_id"] == "price_base_metals", done3
        print(f"[OK] mode=auto → 의도분류 1회 호출 → page 경로: "
              f"{done3['recommendations'][0]['page_id']}")

        # 5) 의도분류가 document면 문서 Q&A 경로(검색 미구축 → 기권)
        fake_doc = FakeIntentLLM("document")
        chat_router.classify_intent = lambda message: intent.classify_intent(message, llm=fake_doc)
        doc_request = chat_router.ChatRequest(
            user_id="smoke", message="코발트 공급위기 원인이 뭐야?"
        )
        events4 = _events(chat_router._run_chat(doc_request, "public"))
        assert events4[-1]["done"] is True, events4[-1]
        print(f"[OK] mode=auto → document 경로: 마지막 이벤트 keys={sorted(events4[-1])} "
              f"(검색계층 미구축이라 기권 응답)")
    finally:
        chat_router.classify_intent = original_classify

    print(f"\n임시 DB: {_TMP_DB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
