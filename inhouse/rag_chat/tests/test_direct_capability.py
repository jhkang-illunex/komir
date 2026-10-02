from __future__ import annotations

from rag_core.ragkit.action_contract import ActionCall, ActionPlan, ActionSlots, Period
from rag_core.ragkit.direct_capability import validate_direct_capability


def _call(action_id: str, mineral: str, *, period: Period | None = None, depends_on=None):
    return ActionCall(
        requirement_id=f"r-{mineral}",
        action_id=action_id,
        slots=ActionSlots(mineral=mineral, period=period),
        depends_on=depends_on or [],
    )


def test_single_complete_capability_is_direct():
    decision = validate_direct_capability(ActionPlan(actions=[_call("price.series", "니켈")]))
    assert decision.mode == "direct"
    assert decision.capability == "price.series"
    assert decision.map_count == 0


def test_independent_same_capability_is_direct_map():
    plan = ActionPlan(actions=[_call("price.series", "니켈"), _call("price.series", "구리")])
    decision = validate_direct_capability(plan)
    assert decision.mode == "map"
    assert decision.map_count == 2


def test_dependency_escalates_to_ast():
    plan = ActionPlan(actions=[_call("price.series", "니켈", depends_on=["previous"])])
    decision = validate_direct_capability(plan)
    assert decision.mode == "ast"
    assert decision.reason == "DEPENDENCY_REQUIRED"


def test_mixed_capabilities_escalate_to_ast():
    plan = ActionPlan(actions=[
        _call("price.series", "니켈"),
        _call("inventory.latest", "니켈"),
    ])
    decision = validate_direct_capability(plan)
    assert decision.mode == "ast"
    assert decision.reason == "COMPOSITION_REQUIRED"


def test_period_is_part_of_map_contract():
    plan = ActionPlan(actions=[
        _call("price.series", "니켈", period=Period(kind="latest")),
        _call("price.series", "구리", period=Period(kind="trailing_months", trailing_months=3)),
    ])
    decision = validate_direct_capability(plan)
    assert decision.mode == "ast"
    assert decision.reason == "CONTRACT_MISMATCH"


def test_partial_legacy_plan_escalates_when_typed_branch_is_missing():
    plan = ActionPlan(actions=[
        _call("price.series", "구리"),
        _call("price.series", "니켈"),
    ])
    plan._semantic_requirements = [
        {"domain": "price", "metric": "price_series", "mineral": "구리"},
        {"domain": "price", "metric": "price_series", "mineral": "니켈"},
        {"domain": "forecast", "metric": "price_forecast", "mineral": "구리"},
    ]
    plan._semantic_resolution_error = "SemanticResolutionError: requested_output_not_produced:price_forecast"
    decision = validate_direct_capability(plan)
    assert decision.mode == "ast"
    assert decision.reason == "BRANCH_COVERAGE_REQUIRED"
