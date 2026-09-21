# -*- coding: utf-8 -*-
"""현재 action 계약에 따른 /pubchat 라우팅과 세션 저장소 스모크.

실행: python3 inhouse/rag_chat/tests/smoke_chat_routing.py
임시 DuckDB와 결정적 ActionPlan을 사용하며 LLM·MCP는 호출하지 않는다.
페이지 추천 그래프의 상태 이월은 smoke_page_recommend.py에서 별도로 검증한다.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock

_RAG_CHAT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAG_CHAT_ROOT))
sys.path.insert(0, str(_RAG_CHAT_ROOT.parent))

_TMP_DB = Path(tempfile.mkdtemp(prefix="rag_chat_routing_")) / "chat.duckdb"
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

from app.routers import chat as chat_router  # noqa: E402
from app.streaming import sse_event  # noqa: E402
from rag_core.ragkit.action_contract import (  # noqa: E402
    ActionCall, ActionPlan, ActionSlots, IntentCall, IntentPlan, action_plan_from_intent,
)


def _events(request: chat_router.ChatRequest, profile: str = "public") -> list[dict]:
    return [json.loads(event["data"]) for event in chat_router._run_chat(request, profile)]


def _plan(action_id: str, **slots) -> ActionPlan:
    return ActionPlan(actions=[ActionCall(
        requirement_id="req_1", action_id=action_id, slots=ActionSlots(**slots),
    )])


def main() -> int:
    page_plan = _plan("menu.navigate", target_page="map_korea", mineral="리튬")
    with patch.object(chat_router, "extract_action_plan", return_value=page_plan) as planner:
        first = _events(chat_router.ChatRequest(
            user_id="smoke", message="한국 리튬 교역지도 메뉴", mode="page",
        ))
        session_id = first[0]["session_id"]
        done = first[-1]
        assert done["done"] and done["mode"] == "page", done
        assert done["status"] == "recommended", done
        assert done["recommendations"][0]["page_id"] == "map_korea", done
        assert done["recommendations"][0]["suggested_filters"]["mineral"] == "리튬", done
        assert planner.call_count == 1
        print("[OK] 검증된 menu.navigate → page 안내·광종 필터")

        second = _events(chat_router.ChatRequest(
            user_id="smoke", session_id=session_id, message="같은 메뉴 다시 알려줘", mode="auto",
        ))
        assert second[0]["session_id"] == session_id
        assert second[-1]["recommendations"][0]["page_id"] == "map_korea"
        rows = duckdb.connect(str(_TMP_DB)).execute(
            "SELECT role, citations_json FROM chat_message WHERE session_id = ? ORDER BY created_at",
            [session_id],
        ).fetchall()
        assert [row[0] for row in rows] == ["user", "assistant", "user", "assistant"], rows
        assert json.loads(rows[-1][1])["page_recommend"]["page_ids"] == ["map_korea"]
        print("[OK] 동일 사용자 세션 재사용·user/assistant 2턴 저장")

        intruder = _events(chat_router.ChatRequest(
            user_id="intruder", session_id=session_id, message="이전 대화 보여줘", mode="page",
        ))
        assert intruder == [
            {"code": "invalid_session"},
            {"done": True, "warnings": ["invalid_session"]},
        ], intruder
        assert planner.call_count == 2
        print("[OK] 다른 사용자의 session_id 재사용 차단")

        conflict = _events(chat_router.ChatRequest(
            user_id="smoke", session_id=session_id, message="교역지도 메뉴", mode="document",
        ))
        assert conflict[-1]["abstain_reason"] == "mode_action_conflict", conflict
        assert conflict[-1]["abstained"] is True
        print("[OK] 요청 mode와 검증된 action 충돌 차단")

    document_plan = _plan("document.retrieve", topic="코발트 공급망")
    received = []

    def fake_document_qa(request, session_id, profile, action_plan=None):
        received.append((request.message, session_id, profile, action_plan))
        yield sse_event({"session_id": session_id})
        yield sse_event({"done": True, "citations": [], "abstained": True}, event="done")

    with (patch.object(chat_router, "extract_action_plan", return_value=document_plan),
          patch.object(chat_router, "_run_document_qa", side_effect=fake_document_qa)):
        private = _events(chat_router.ChatRequest(
            user_id="smoke-doc", message="코발트 공급망 자료", mode="auto",
        ), profile="private")
        assert private[-1]["done"] is True, private
        assert received[0][2] == "private" and received[0][3] == document_plan, received
        assert received[0][1] == private[0]["session_id"]
        print("[OK] document.retrieve → 문서 경로·private 프로필·action 전달")

    menu_intent = IntentPlan(requirements=[IntentCall(
        requirement_id="menu_1", intent="menu", role="metadata",
        slots=ActionSlots(target_page="가격", mineral="니켈"),
    )])
    menu_plan = action_plan_from_intent(menu_intent)
    assert menu_plan.actions[0].action_id == "menu.navigate", menu_plan
    recommendation = Mock()
    recommendation.model_dump.return_value = {"page_id": "price_base_metals"}
    service = Mock()
    service.registry.resolve_action_targets.side_effect = chat_router.RegistryError("unknown target")
    service.recommend.return_value = SimpleNamespace(
        response=SimpleNamespace(answer="가격 페이지 안내", status="recommended",
                                 relation="first_turn", recommendations=[recommendation], warnings=[]),
        active_artifact=None,
    )
    with (patch.object(chat_router, "extract_action_plan", return_value=menu_plan),
          patch.object(chat_router, "get_page_recommend_service", return_value=service)):
        events = _events(chat_router.ChatRequest(
            user_id="page-navigation", message="니켈 가격 추이를 보려면 어느 페이지로 가야 돼?",
        ))
        assert events[-1]["mode"] == "page", events
        assert events[-1]["recommendations"][0]["page_id"] == "price_base_metals"
        assert service.recommend.call_count == 1
        assert service.recommend_action_target.call_count == 0
    print("[OK] role=metadata인 menu intent 보존·불명확한 대상은 페이지 추천 그래프로 전달")

    mine_plan = _plan("mine.rank", mineral="구리", country_scope="중국",
                      mine_metric="production", mine_order="level", top_n=10)
    mine_question = "구리 광산중 중국 광산 생산량 높은 순서로 10개만 표시해주세요"
    with (patch.object(chat_router, "extract_action_plan", return_value=mine_plan) as mine_planner,
          patch.object(chat_router, "_run_document_qa", side_effect=fake_document_qa)):
        ask = _events(chat_router.ChatRequest(user_id="mine", message=mine_question))
        mine_session = ask[0]["session_id"]
        assert ask[-1]["needs_clarification"] is True, ask
        assert ask[-1]["clarification"]["slot"] == "mine_country_relation"
        assert mine_planner.call_count == 1
        assert len(received) == 1, received

        chosen = _events(chat_router.ChatRequest(
            user_id="mine", session_id=mine_session, message="소재 기준으로요",
        ))
        assert chosen[-1]["done"] is True, chosen
        assert mine_planner.call_count == 1, "확인 답변에서 슬롯을 다시 추출하면 안 됨"
        resumed = received[-1]
        assert mine_question in resumed[0] and "소재지 기준" in resumed[0], resumed
        resumed_call = resumed[3].actions[0]
        assert resumed_call.slots.country_scope == "중국"
        assert resumed_call.slots.mineral == "구리"
        assert resumed_call.slots.mine_metric == "production"
        assert resumed_call.slots.top_n == 10
        print("[OK] 광산 소재·소유 확인 → 다음 턴 소재 선택 시 원래 순위 슬롯 유지")

        ask_owner = _events(chat_router.ChatRequest(user_id="mine-owner", message=mine_question))
        owner_session = ask_owner[0]["session_id"]
        owner = _events(chat_router.ChatRequest(
            user_id="mine-owner", session_id=owner_session, message="소유 기준",
        ))
        assert owner[-1]["abstain_reason"] == "source_unavailable", owner
        assert owner[-1]["failure_reason"] == "mine_ownership_unavailable", owner
        assert len(received) == 2, "소유국을 소재국 필터로 조회하면 안 됨"
        print("[OK] 소유 선택 시 소재국 순위로 오답을 만들지 않음")

    print(f"스모크 통과 (임시 DB: {_TMP_DB})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
