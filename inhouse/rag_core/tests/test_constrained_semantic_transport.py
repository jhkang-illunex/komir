"""Wire constraints are opt-in and never replace semantic validation."""
from unittest.mock import Mock

import pytest
from pydantic import BaseModel

from inhouse.common.llm.openai_compat import OpenAICompatChat
from inhouse.common.llm_client import KomirJsonLLM


class Example(BaseModel):
    count: int


def response(status=200, content='{"count":7}'):
    result = Mock(status_code=status)
    result.json.return_value = {"choices": [{"message": {"content": content}}]}
    return result


def test_json_schema_is_forwarded_without_mutating_schema():
    client = KomirJsonLLM({"structured_output_mode": "json_schema", "retries": 1})
    client._chat._session.post = Mock(return_value=response())
    result = client.invoke(task="test", instructions="Return count", payload={},
                           output_model=Example, max_tokens=100)
    body = client._chat._session.post.call_args.kwargs["json"]
    assert body["response_format"]["json_schema"]["schema"] == Example.model_json_schema()
    assert body["response_format"]["json_schema"]["strict"] is True
    assert result.output.count == 7
    assert result.record["structured_output_mode"] == "json_schema"


@pytest.mark.parametrize("status", [400, 401, 422])
def test_schema_rejection_is_not_retried_or_downgraded(status):
    client = KomirJsonLLM({"structured_output_mode": "json_schema", "retries": 3})
    client._chat._session.post = Mock(return_value=response(status))
    with pytest.raises(RuntimeError, match="structured_output_request_rejected"):
        client.invoke(task="test", instructions="Return count", payload={},
                      output_model=Example, max_tokens=100)
    assert client._chat._session.post.call_count == 1


def test_legacy_wire_and_fallback_are_unchanged():
    client = OpenAICompatChat({"retries": 2})
    client._session.post = Mock(side_effect=[response(400), response()])
    client._complete("system", "user")
    calls = client._session.post.call_args_list
    assert calls[0].kwargs["json"]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1].kwargs["json"]


def test_constrained_output_still_requires_local_validation():
    client = KomirJsonLLM({"structured_output_mode": "json_schema", "retries": 1})
    client._chat._session.post = Mock(side_effect=[response(content='{"count":null}'), response()])
    result = client.invoke(task="test", instructions="Return count", payload={},
                           output_model=Example, max_tokens=100)
    assert result.output.count == 7
    assert len(result.record["attempts"]) == 2
    assert all(c.kwargs["json"]["response_format"]["type"] == "json_schema"
               for c in client._chat._session.post.call_args_list)


def test_schema_is_per_call_and_does_not_leak_into_another_request():
    client = OpenAICompatChat({"retries": 1})
    client._session.post = Mock(return_value=response())
    first = {"type": "object", "properties": {"count": {"type": "integer"}}}
    second = {"type": "object", "properties": {"label": {"type": "string"}}}
    client._complete("system", "user", json_schema=first)
    client._complete("system", "user", json_schema=second)
    client._complete("system", "user")
    bodies = [c.kwargs["json"] for c in client._session.post.call_args_list]
    assert bodies[0]["response_format"]["json_schema"]["schema"] == first
    assert bodies[1]["response_format"]["json_schema"]["schema"] == second
    assert bodies[2]["response_format"] == {"type": "json_object"}
