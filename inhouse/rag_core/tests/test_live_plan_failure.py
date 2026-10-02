"""Offline chat_turn regressions: planning is not missing data or execution failure."""
import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inhouse.rag_core.ragkit import chatbot, live_multihop as live
from inhouse.rag_core.ragkit.chatbot_events import ChatEvent
from inhouse.rag_core.ragkit.history_context import InMemoryHistoryStore
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus


SECRET = "private exception detail: internal endpoint / credentials"


@pytest.fixture
def turn(monkeypatch):
    writes = []
    monkeypatch.setattr(chatbot, "get_or_create_session", lambda *a: "plan-fixture")
    monkeypatch.setattr(chatbot, "list_messages", lambda *a: [])
    monkeypatch.setattr(chatbot, "append_message", lambda *a: writes.append(a))
    monkeypatch.setattr(chatbot, "_classify_pre_gate", lambda *a: None)
    monkeypatch.setattr(chatbot, "multihop_mode", lambda: "enabled")
    monkeypatch.setattr(live, "_HISTORY", InMemoryHistoryStore())

    async def collect():
        return [event async for event in chatbot.chat_turn(
            "plan-fixture", "fixture-user", "니켈 가격을 조회해 주세요",
            router_llm=object(),
        )]

    return SimpleNamespace(collect=collect, writes=writes)


def assert_failure(events, reason):
    done = [event.data for event in events if event.type == "done"]
    assert done == [{"done": True, "abstained": True,
                     "abstain_reason": reason, "citations": []}]
    assert events[-1].type == "done"
    assert SECRET not in json.dumps([event.data for event in events], ensure_ascii=False)
    assert not any(event.type == "error" for event in events)
    return "".join(event.data["delta"] for event in events if event.type == "delta")


@pytest.mark.parametrize("error_type", [ValueError, live.LLMOutputError])
def test_real_live_parse_failure_has_distinct_safe_done(turn, monkeypatch, caplog, error_type):
    # Keep run_live_multihop real: its parser-only wrapper must classify the error.
    parser = AsyncMock(side_effect=error_type(SECRET))
    monkeypatch.setattr(live, "_parse_ast", parser)
    with caplog.at_level(logging.ERROR, logger=chatbot.__name__):
        events = asyncio.run(turn.collect())
    text = assert_failure(events, "semantic_plan_incomplete")
    assert "계획" in text and "생성하지 못했습니다" in text
    assert "데이터가 없다는 의미는 아닙니다" in text
    assert parser.await_count == 1
    assert [row[1] for row in turn.writes] == ["user"]
    records = [record for record in caplog.records if record.name == chatbot.__name__]
    assert any(record.exc_info and isinstance(record.exc_info[1], live.LivePlanError)
               and record.exc_info[1].__cause__ is not None for record in records)


def test_unclassified_parser_runtime_error_remains_execution_failure(turn, monkeypatch):
    monkeypatch.setattr(live, "_parse_ast", AsyncMock(side_effect=RuntimeError(SECRET)))
    assert_failure(asyncio.run(turn.collect()), "execution_failed")


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_history_store_failure_is_not_plan_failure(turn, monkeypatch, error_type):
    parser = AsyncMock()
    monkeypatch.setattr(live, "_parse_ast", parser)
    monkeypatch.setattr(live._HISTORY, "get_context", AsyncMock(side_effect=error_type(SECRET)))
    events = asyncio.run(turn.collect())
    assert_failure(events, "execution_failed")
    parser.assert_not_awaited()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_post_parse_execution_failure_is_not_plan_failure(turn, monkeypatch, error_type):
    monkeypatch.setattr(live, "_parse_ast", AsyncMock(return_value=object()))

    def fail_execution(*args):
        raise error_type(SECRET)

    monkeypatch.setattr(live, "_resolve_history_references", fail_execution)
    assert_failure(asyncio.run(turn.collect()), "execution_failed")


def successful_live(monkeypatch):
    run = SimpleNamespace(skipped=False, orchestration=SimpleNamespace(
        root_result=SimpleNamespace(status=ResultStatus.SUCCESS)))
    emitted = [ChatEvent(type="delta", data={"delta": "정상 결과"}),
               ChatEvent(type="done", data={"done": True, "abstained": False,
                                            "citations": [], "fixture_field": "preserved"})]
    monkeypatch.setattr(chatbot, "run_live_multihop", AsyncMock(return_value=run))
    monkeypatch.setattr(chatbot, "live_run_events", lambda result: emitted)
    return emitted


def test_normal_live_events_and_storage_unchanged(turn, monkeypatch):
    emitted = successful_live(monkeypatch)
    events = asyncio.run(turn.collect())
    assert events[-2:] == emitted
    assert [row[1] for row in turn.writes] == ["user", "assistant"]
    assert turn.writes[-1][2] == "정상 결과"


def test_assistant_store_failure_remains_execution_failed(turn, monkeypatch):
    successful_live(monkeypatch)

    def append(*args):
        if args[1] == "assistant":
            raise RuntimeError(SECRET)

    monkeypatch.setattr(chatbot, "append_message", append)
    events = asyncio.run(turn.collect())
    assert_failure(events, "execution_failed")
    assert all(event.data.get("delta") != "정상 결과" for event in events)


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_legacy_output_unchanged_after_shadow_plan_failure(turn, monkeypatch, mode):
    monkeypatch.setattr(chatbot, "multihop_mode", lambda: mode)
    parser = AsyncMock(side_effect=ValueError(SECRET))
    monkeypatch.setattr(live, "_parse_ast", parser)
    monkeypatch.setattr(chatbot, "get_settings", lambda: SimpleNamespace(DEBUG=False))
    monkeypatch.setattr(chatbot, "_is_internal_knowledge_question", lambda *a: False)
    monkeypatch.setattr(chatbot, "_resolve_abstain", lambda *a: ("source_unavailable", "legacy response"))
    retrieval_calls = []

    async def legacy(*args, **kwargs):
        retrieval_calls.append(True)
        yield "result", ([], []), {}

    monkeypatch.setattr(chatbot, "_run_with_status", legacy)
    events = asyncio.run(turn.collect())
    assert retrieval_calls == [True]
    assert parser.await_count == (1 if mode == "shadow" else 0)
    assert events[-2].data == {"delta": "legacy response"}
    assert events[-1] == chatbot._abstain_done("source_unavailable")
    assert SECRET not in json.dumps([event.data for event in events])


def test_cancellation_is_not_converted_to_any_failure_done(turn, monkeypatch):
    monkeypatch.setattr(live, "_parse_ast", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(turn.collect())
