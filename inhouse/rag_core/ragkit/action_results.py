"""Action별 조회 결과와 기존 (evidence, warnings) 계약의 공통 표현."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from .action_contract import ActionPlan, ActionSlots
from rag_core.retrieval.evidence import Evidence


ActionStatus = Literal[
    "success", "no_data", "source_unavailable", "validation_failed", "blocked", "failed",
]

ItemStatus = Literal[
    "success", "NEEDS_SELECTION", "DATA_UNAVAILABLE", "EXECUTION_FAILED",
    "DEPENDENCY_FAILED",
]


@dataclass
class ItemResult:
    """독립 ForEach/병렬 조회 한 항목의 결과 계약.

    ``key``는 (광종 ID, 지표)처럼 호출 범위를 식별하며, 실패 항목도
    value/evidence를 버리지 않고 같은 composite 결과에 남긴다.
    """

    key: tuple[str, str]
    value: Any = None
    status: ItemStatus = "success"
    reason: str | None = None
    evidence: list[Evidence] = field(default_factory=list)

    def snapshot(self, *, turn_id: str, result_id: str) -> dict[str, object]:
        return {
            "turn_id": turn_id, "result_id": result_id,
            "mineral_id": self.key[0], "output_id": self.key[1],
            "status": self.status, "value": self.value,
            "reason": self.reason, "evidence": list(self.evidence),
        }


def classify_item(*, key: tuple[str, str] = ("", ""), value: Any = None, evidence: list[Evidence] | None = None,
                  failure_reason: str | None = None,
                  dependency_failed: bool = False) -> ItemResult:
    """공통 실패 taxonomy를 적용한다. 호출부는 질문 의미를 재해석하지 않는다."""
    if dependency_failed:
        status: ItemStatus = "DEPENDENCY_FAILED"
    elif failure_reason in {"ambiguous", "needs_selection", "advisor_rejected"}:
        status = "NEEDS_SELECTION"
    elif failure_reason in {"no_data", "source_unavailable", "data_unavailable"}:
        status = "DATA_UNAVAILABLE"
    elif failure_reason:
        status = "EXECUTION_FAILED"
    else:
        status = "success"
    return ItemResult(key, value=value, status=status, reason=failure_reason,
                      evidence=list(evidence or []))


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
    item_results: dict[tuple[str, str], ItemResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 기존 ActionResult 목록을 항목 결과로도 노출한다. 새 실행기를
        # 만들지 않고, 현재 병렬 Action 결과를 광종×지표 키로 보존한다.
        if self.item_results:
            return
        for action in self.action_results:
            mineral = getattr(action.slots, "mineral", None) or action.requirement_id
            if action.status == "success":
                status: ItemStatus = "success"
            elif action.status == "validation_failed" or action.failure_reason in {"ambiguous", "advisor_rejected"}:
                status = "NEEDS_SELECTION"
            elif action.status in {"no_data", "source_unavailable"}:
                status = "DATA_UNAVAILABLE"
            elif action.status == "blocked" or action.failure_reason == "dependency_failed":
                status = "DEPENDENCY_FAILED"
            else:
                status = "EXECUTION_FAILED"
            self.item_results[(str(mineral), action.action_id)] = ItemResult(
                key=(str(mineral), action.action_id),
                value=action.evidence if action.status == "success" else None,
                status=status, reason=action.failure_reason,
                evidence=list(action.evidence),
            )

    @property
    def outcome(self) -> str:
        """항목 단위 결과를 전체 성공으로 오인하지 않도록 요약한다."""
        if not self.item_results:
            return "SUCCESS" if self.evidence else "DATA_UNAVAILABLE"
        statuses = {item.status for item in self.item_results.values()}
        if statuses == {"success"}:
            return "SUCCESS"
        if "success" in statuses:
            return "PARTIAL"
        return "FAILED"

    def snapshots(self, *, turn_id: str, result_id: str) -> tuple[dict[str, object], ...]:
        return tuple(item.snapshot(turn_id=turn_id, result_id=result_id)
                     for item in self.item_results.values())

    def legacy_pair(self) -> tuple[list[Evidence], list[str]]:
        """기존 retrieve_evidence() 호출자에게 반환하던 정확한 2개 값을 만든다."""
        return self.evidence, self.warnings
