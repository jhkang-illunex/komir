"""Semantic AST → LangGraph Pipe → validated presentation boundary."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .history_context import ConversationContext
from .lowering import PipeLowerer
from .pipe_runtime import ExecutionContext, ExecutionResult, PipeRuntime, ResultStatus, TypedResult
from .presentation import ExecutionPresentation, Renderer
from .semantic_ir import SemanticProgram, ValueType


class BrainModel(Protocol):
    async def parse(self, utterance: str, context: ConversationContext) -> SemanticProgram: ...


class GemmaBrainAdapter:
    """Adapter for a schema-constrained Gemma invocation.

    The injected callable owns the model client. This class only validates the
    returned AST, so the runtime never consumes free-form reasoning text.
    """

    def __init__(self, invoke: Callable[..., Any | Awaitable[Any]]) -> None:
        self._invoke = invoke

    async def parse(self, utterance: str, context: ConversationContext) -> SemanticProgram:
        payload = self._invoke(utterance=utterance, context=context)
        if inspect.isawaitable(payload):
            payload = await payload
        if isinstance(payload, SemanticProgram):
            payload.validate()
            return payload
        if not isinstance(payload, Mapping):
            raise TypeError("Gemma structured output must be a semantic program object")
        return SemanticProgram.from_dict(payload)


EvidenceValidator = Callable[[TypedResult], TypedResult | bool | Awaitable[TypedResult | bool]]


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    execution: ExecutionResult
    presentation: ExecutionPresentation
    root_result: TypedResult


class MultiHopOrchestrator:
    """Application-owned orchestration; physical data access stays in adapters."""

    def __init__(
        self,
        lowerer: PipeLowerer,
        runtime: PipeRuntime | None = None,
        renderer: Renderer | None = None,
    ) -> None:
        self._lowerer = lowerer
        self._runtime = runtime or PipeRuntime()
        self._renderer = renderer or Renderer()

    async def execute(
        self,
        program: SemanticProgram,
        *,
        session_id: str,
        turn_id: str,
        pipe_id: str,
        evidence_validator: EvidenceValidator,
        context_metadata: Mapping[str, Any] | None = None,
    ) -> OrchestrationResult:
        program.validate()
        pipe = self._lowerer.lower(program, pipe_id=pipe_id)
        execution = await self._runtime.execute(
            pipe,
            ExecutionContext(session_id=session_id, turn_id=turn_id, metadata=dict(context_metadata or {})),
        )
        root_values = [execution.results[root] for root in program.roots if root in execution.results]
        if len(root_values) == 1:
            root_result = root_values[0]
        elif root_values:
            successful = sum(item.status == ResultStatus.SUCCESS and item.sufficient for item in root_values)
            usable = any(item.status in {ResultStatus.SUCCESS, ResultStatus.PARTIAL} and item.sufficient for item in root_values)
            root_result = TypedResult(
                ValueType.COMPOSITE,
                {root: execution.results[root] for root in program.roots if root in execution.results},
                status=ResultStatus.SUCCESS if successful == len(program.roots) else ResultStatus.PARTIAL if usable else ResultStatus.FAILED,
                sufficient=usable,
                failure_reason=None if usable else "all_roots_failed",
                source=tuple(dict.fromkeys(source for item in root_values for source in item.source)),
                evidence=tuple(evidence for item in root_values for evidence in item.evidence),
                provenance=tuple(source for item in root_values for source in item.provenance),
                upstream_step_ids=tuple(program.roots),
            )
        else:
            root_result = TypedResult.failed("semantic program produced no root result")

        if root_result.status in {ResultStatus.SUCCESS, ResultStatus.PARTIAL}:
            validation = evidence_validator(root_result)
            if inspect.isawaitable(validation):
                validation = await validation
            if isinstance(validation, TypedResult):
                root_result = validation
            elif not validation:
                root_result = TypedResult.abstain("evidence validation failed", root_result.result_type)
        presentation = self._renderer.render(root_result)
        return OrchestrationResult(execution, presentation, root_result)
