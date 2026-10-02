"""Failed parsing remains inspectable, without promoting a rejected plan."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inhouse.common.llm.openai_compat import OpenAICompatChat
from inhouse.common.llm_client import KomirJsonLLM, LLMOutputError
from inhouse.rag_core.ragkit.semantic_v2 import parse_v2_shadow


def client(responses):
    llm = KomirJsonLLM({"retries": 1})
    llm._chat.complete = Mock(side_effect=responses)
    return llm


def completion(text, reason="stop"):
    return SimpleNamespace(text=text, finish_reason=reason, model="test-model",
                           usage={"completion_tokens": 9})


@pytest.mark.parametrize("raw,reason,kind", [
    ('{"requirements":', "length", "OUTPUT_TRUNCATED"),
    ('{"requirements":', "stop", "JSON_PARSE_ERROR"),
    ('{"requirements":[{"requirement_id":"x","metric":"not_a_metric"}]}', "stop", "SCHEMA_VALIDATION_ERROR"),
])
def test_terminal_output_error_keeps_all_raw_attempts(raw, reason, kind):
    llm = client([completion(raw, reason), completion(raw, reason)])
    trace = parse_v2_shadow("opaque input", llm)
    assert trace.failure_class == "PARSER_MISSING_OUTPUT"
    assert trace.logical_program is None and trace.lowering == []
    assert len(trace.attempts) == 1
    attempts = trace.attempts[0]["model_attempts"]
    assert len(attempts) == 2
    for attempt in attempts:
        assert attempt["raw_content"] == raw
        assert attempt["error_kind"] == kind
        assert attempt["finish_reason"] == reason
        assert attempt["model"] == "test-model"
        assert attempt["usage"]["completion_tokens"] == 9
    if kind == "SCHEMA_VALIDATION_ERROR":
        assert attempts[0]["parsed_json"]["requirements"][0]["metric"] == "not_a_metric"


def test_failed_second_semantic_attempt_does_not_erase_first():
    invalid_contract = '{"requirements":[{"requirement_id":"r","metric":"price"}]}'
    llm = client([completion(invalid_contract), completion('{'), completion('{')])
    trace = parse_v2_shadow("opaque input", llm)
    assert [a["attempt"] for a in trace.attempts] == [1, 2]
    assert trace.attempts[0]["contract_errors"]
    assert trace.attempts[1]["model_attempts"][1]["raw_content"] == '{'
    assert trace.logical_program is None and not trace.lowering


def test_trace_allowlist_and_request_isolation():
    record = {"headers": {"Authorization": "SECRET"}, "attempts": [
        {"attempt": 1, "raw_content": '{', "headers": "SECRET", "error_kind": "JSON_PARSE_ERROR"}]}
    llm = SimpleNamespace(invoke=Mock(side_effect=LLMOutputError("invalid", record=record)))
    trace = parse_v2_shadow("first", llm)
    assert trace.attempts
    record["attempts"][0]["raw_content"] = "changed"
    assert trace.attempts[0]["model_attempts"][0]["raw_content"] == '{'
    assert "SECRET" not in trace.model_dump_json()
    second = parse_v2_shadow("second", SimpleNamespace(invoke=Mock(side_effect=RuntimeError("unavailable"))))
    assert second.attempts == []


def test_adapter_preserves_actual_finish_reason():
    chat = OpenAICompatChat({"model": "requested-model", "retries": 1})
    response = Mock(status_code=200)
    response.json.return_value = {"model": "served-model", "choices": [
        {"message": {"content": '{'}, "finish_reason": "length"}], "usage": {"completion_tokens": 5}}
    chat._session.post = Mock(return_value=response)
    result = chat._complete("system", "user")
    assert result.finish_reason == "length"
    assert result.model == "served-model"


@pytest.mark.parametrize("attempts", [None, "invalid", {"raw_content":"not-an-attempt-list"}])
def test_malformed_diagnostic_record_does_not_escape_shadow(attempts):
    llm = SimpleNamespace(invoke=Mock(side_effect=LLMOutputError("invalid", record={"attempts":attempts})))
    trace = parse_v2_shadow("opaque", llm)
    assert trace.failure_class == "PARSER_MISSING_OUTPUT"
    assert trace.attempts[0]["model_attempts"] == []
