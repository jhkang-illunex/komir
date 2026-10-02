from __future__ import annotations

from types import SimpleNamespace

from rag_chat.app.query_gate import (
    GateDependency,
    QueryGateDecision,
    classify_query_gate,
    navigation_fast_path_applicable,
)


class FakeLLM:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        value = kwargs["output_model"].model_validate(self.output)
        return SimpleNamespace(output=value)


def test_gate_only_returns_route_and_dependency_without_ast_fields():
    llm = FakeLLM({
        "route": "NAVIGATION",
        "dependency": {"required": False, "type": "none"},
        "confidence": 0.97,
        "target_page": "price_minor_metals",
    })
    decision = classify_query_gate("리튬 가격 화면 어디야?", llm=llm)

    assert decision.route == "NAVIGATION"
    assert decision.dependency == GateDependency(required=False, type="none")
    assert not hasattr(decision, "action_id")
    assert navigation_fast_path_applicable(decision)
    assert llm.calls[0]["task"] == "query_gate"


def test_dependent_navigation_is_not_fast_path():
    decision = QueryGateDecision(
        route="NAVIGATION",
        dependency=GateDependency(required=True, type="previous_result"),
        confidence=0.9,
    )
    assert not navigation_fast_path_applicable(decision)


def test_gate_fail_closed_to_complex():
    class BrokenLLM:
        def invoke(self, **kwargs):
            raise RuntimeError("endpoint unavailable")

    decision = classify_query_gate("니켈 수입 상위 5개국", llm=BrokenLLM())
    assert decision.route == "COMPLEX"
    assert not navigation_fast_path_applicable(decision)
