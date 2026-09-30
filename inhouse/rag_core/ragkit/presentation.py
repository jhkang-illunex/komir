"""Canonical presentation results, separate from the existing SSE wire format."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .pipe_runtime import ResultStatus, TypedResult


@dataclass(frozen=True, slots=True)
class TextResult:
    text: str


@dataclass(frozen=True, slots=True)
class TableResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    units: Mapping[str, str] = field(default_factory=dict)
    evidence: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class ChartResult:
    chart_type: str
    series: tuple[Mapping[str, Any], ...]
    categories: tuple[Any, ...] = ()
    unit: str | None = None
    evidence: tuple[Any, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionPresentation:
    status: ResultStatus
    typed_result: TypedResult
    text: TextResult | None = None
    table: TableResult | None = None
    chart: ChartResult | None = None
    warnings: tuple[str, ...] = ()
    abstain_reason: str | None = None
    template_name: str | None = None


class Renderer:
    """Deterministic boundary; protocol adapters remain outside this contract."""

    def render(self, result: TypedResult, *, template_name: str | None = None) -> ExecutionPresentation:
        if result.status == ResultStatus.ABSTAINED:
            return ExecutionPresentation(result.status, result, abstain_reason=result.failure_reason, template_name=template_name)
        return ExecutionPresentation(result.status, result, template_name=template_name)

