"""Action별 조회 결과와 기존 (evidence, warnings) 계약의 공통 표현."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .action_contract import ActionPlan, ActionSlots
from rag_core.retrieval.evidence import Evidence


ActionStatus = Literal[
    "success", "no_data", "source_unavailable", "validation_failed", "blocked", "failed",
]


@dataclass
class ActionResult:
    requirement_id: str
    action_id: str
    slots: ActionSlots
    status: ActionStatus
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failure_reason: str | None = None


@dataclass
class RetrievalResult:
    action_plan: ActionPlan | None
    action_results: list[ActionResult] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def legacy_pair(self) -> tuple[list[Evidence], list[str]]:
        """기존 retrieve_evidence() 호출자에게 반환하던 정확한 2개 값을 만든다."""
        return self.evidence, self.warnings
