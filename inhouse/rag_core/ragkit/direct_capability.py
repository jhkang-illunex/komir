"""Deterministic boundary between a complete capability and AAST.

This module does not parse natural language and does not execute a second data
path.  It validates an already typed legacy ActionPlan, then lets the normal
retrieval/action executor handle the call.  A failed validation is an explicit
escalation reason, never a runtime fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .action_contract import ActionPlan, PlanAssessment, validate_action_plan


# Only capabilities whose repeated calls are independent are eligible for the
# limited Map path.  The action catalog and required-slot definitions remain in
# action_contract.py; this is only the execution-boundary metadata.
DIRECT_MAP_ACTIONS = frozenset({"price.series", "trade.country_rank"})


DirectMode = Literal["direct", "map", "ast"]


@dataclass(frozen=True)
class DirectCapabilityDecision:
    mode: DirectMode
    capability: str | None
    map_count: int = 0
    reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.mode in {"direct", "map"}


def _slot_fingerprint(call) -> dict:
    """Return call arguments excluding the entity that Map is allowed to vary."""

    slots = call.slots.model_dump(mode="json", exclude_none=False)
    slots.pop("mineral", None)
    slots.pop("minerals", None)
    return slots


def validate_direct_capability(
    plan: ActionPlan | None,
    assessment: PlanAssessment | None = None,
) -> DirectCapabilityDecision:
    """Validate a complete, dependency-free capability call.

    This intentionally accepts only an already typed ActionPlan.  It does not
    inspect the raw query, infer missing slots, resolve history, or repair a
    plan.  The caller can therefore safely send every non-valid outcome to the
    existing AAST path.
    """

    if not isinstance(plan, ActionPlan) or not plan.actions:
        return DirectCapabilityDecision("ast", None, reason="NOT_APPLICABLE")
    if any(call.depends_on or call.input_bindings for call in plan.actions):
        return DirectCapabilityDecision("ast", None, reason="DEPENDENCY_REQUIRED")
    # A legacy ActionPlan can look atomic even when the typed semantic parser
    # found more than one requested capability.  Do not execute a partial
    # direct plan: preserve branch coverage by escalating to the existing
    # AAST path.  This consumes only the already attached typed snapshot and
    # never reparses the user query.
    semantic_error = getattr(plan, "_semantic_resolution_error", None) or ""
    planned = [call.action_id for call in plan.actions]
    # A failed semantic output contract must not be hidden by a surviving
    # legacy map.  This is intentionally keyed to the typed parser's
    # requested-output diagnostic, not to a query, mineral, or QA identifier.
    # Other semantic fallback snapshots may still be correctly served by a
    # complete legacy composite action and must not be escalated wholesale.
    if "requested_output_not_produced:price_forecast" in semantic_error and "forecast.price" not in planned:
        return DirectCapabilityDecision("ast", None, reason="BRANCH_COVERAGE_REQUIRED")
    if len(plan.actions) > 1 and len({call.action_id for call in plan.actions}) > 1:
        return DirectCapabilityDecision("ast", None, reason="COMPOSITION_REQUIRED")
    assessment = assessment or validate_action_plan(plan)
    if not assessment.approved:
        reason = assessment.failure_reason or "CONTRACT_MISMATCH"
        if any(call.depends_on or call.input_bindings for call in plan.actions):
            reason = "DEPENDENCY_REQUIRED"
        return DirectCapabilityDecision("ast", None, reason=reason)
    if any(call.action_id == "off_topic" for call in plan.actions):
        return DirectCapabilityDecision("ast", None, reason="UNSUPPORTED")

    action_ids = {call.action_id for call in plan.actions}
    if len(plan.actions) == 1:
        return DirectCapabilityDecision("direct", plan.actions[0].action_id)
    if len(action_ids) != 1:
        return DirectCapabilityDecision("ast", None, reason="COMPOSITION_REQUIRED")
    action_id = next(iter(action_ids))
    if action_id not in DIRECT_MAP_ACTIONS:
        return DirectCapabilityDecision("ast", None, reason="COMPOSITION_REQUIRED")

    fingerprints = {_slot_fingerprint(call).__repr__() for call in plan.actions}
    if len(fingerprints) != 1:
        return DirectCapabilityDecision("ast", None, reason="CONTRACT_MISMATCH")
    minerals = [call.slots.mineral for call in plan.actions]
    if any(not isinstance(mineral, str) or not mineral.strip() for mineral in minerals):
        return DirectCapabilityDecision("ast", None, reason="CONTRACT_MISMATCH")
    if len(set(minerals)) != len(minerals):
        return DirectCapabilityDecision("ast", None, reason="CONTRACT_MISMATCH")
    return DirectCapabilityDecision("map", action_id, map_count=len(plan.actions))


__all__ = ["DIRECT_MAP_ACTIONS", "DirectCapabilityDecision", "validate_direct_capability"]
