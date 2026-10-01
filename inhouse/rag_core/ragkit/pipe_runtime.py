"""LangGraph-backed async Pipe runtime for typed multi-hop execution."""

from __future__ import annotations

import asyncio
import inspect
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, AsyncIterator, Awaitable, Callable, Mapping, TypedDict

from langgraph.graph import END, START, StateGraph

from .semantic_ir import ValueType


class ResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    ABSTAINED = "abstained"
    DEPENDENCY_FAILED = "dependency_failed"


@dataclass(frozen=True, slots=True)
class TypedResult:
    result_type: ValueType
    value: Any = None
    status: ResultStatus = ResultStatus.SUCCESS
    entity: tuple[str, ...] = ()
    metric: str | None = None
    period: Mapping[str, Any] | None = None
    unit: str | None = None
    source: tuple[str, ...] = ()
    evidence: tuple[Any, ...] = ()
    provenance: tuple[str, ...] = ()
    confidence: float | None = None
    sufficient: bool = True
    upstream_step_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failure_reason: str | None = None

    @classmethod
    def success(cls, result_type: ValueType, value: Any, **kwargs: Any) -> "TypedResult":
        return cls(result_type=result_type, value=value, **kwargs)

    @classmethod
    def empty(cls, result_type: ValueType, reason: str, **kwargs: Any) -> "TypedResult":
        return cls(result_type=result_type, status=ResultStatus.EMPTY, sufficient=False, failure_reason=reason, **kwargs)

    @classmethod
    def failed(cls, reason: str, result_type: ValueType = ValueType.UNKNOWN, **kwargs: Any) -> "TypedResult":
        return cls(result_type=result_type, status=ResultStatus.FAILED, sufficient=False, failure_reason=reason, **kwargs)

    @classmethod
    def abstain(cls, reason: str, result_type: ValueType = ValueType.UNKNOWN, **kwargs: Any) -> "TypedResult":
        return cls(result_type=result_type, status=ResultStatus.ABSTAINED, sufficient=False, failure_reason=reason, **kwargs)


@dataclass(frozen=True, slots=True)
class InputBinding:
    source_step_id: str
    selector: str = "all"
    selector_value: str | int | None = None


@dataclass(frozen=True, slots=True)
class PipeEvent:
    event_type: str
    pipe_id: str
    step_id: str | None = None
    status: str | None = None
    result_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionContext:
    session_id: str | None = None
    turn_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    results: dict[str, TypedResult] = field(default_factory=dict)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def cancel(self) -> None:
        self.cancel_event.set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise asyncio.CancelledError


class Tracer(ABC):
    """Business-code boundary for optional Langfuse/OpenTelemetry adapters."""

    @abstractmethod
    def event(self, name: str, metadata: Mapping[str, Any]) -> None:
        raise NotImplementedError


class NoOpTracer(Tracer):
    def event(self, name: str, metadata: Mapping[str, Any]) -> None:
        return None


class Step(ABC):
    def __init__(
        self,
        step_id: str,
        operation: str,
        dependencies: tuple[str, ...] = (),
        bindings: Mapping[str, InputBinding] | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 0,
    ) -> None:
        self.step_id = step_id
        self.operation = operation
        self.dependencies = tuple(dependencies)
        self.bindings = dict(bindings or {})
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    @abstractmethod
    async def execute(self, context: ExecutionContext, inputs: Mapping[str, TypedResult]) -> TypedResult:
        raise NotImplementedError


StepHandler = Callable[[ExecutionContext, Mapping[str, TypedResult]], TypedResult | Awaitable[TypedResult]]


class FunctionStep(Step):
    def __init__(self, step_id: str, operation: str, handler: StepHandler, **kwargs: Any) -> None:
        super().__init__(step_id, operation, **kwargs)
        self._handler = handler

    async def execute(self, context: ExecutionContext, inputs: Mapping[str, TypedResult]) -> TypedResult:
        context.check_cancelled()
        result = self._handler(context, inputs)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, TypedResult):
            raise TypeError(f"step {self.step_id} returned {type(result).__name__}, expected TypedResult")
        return result


@dataclass(frozen=True, slots=True)
class Pipe:
    pipe_id: str
    steps: tuple[Step, ...]

    def validate(self) -> None:
        step_ids = {step.step_id for step in self.steps}
        if len(step_ids) != len(self.steps):
            raise ValueError("duplicate pipe step_id")
        by_id = {step.step_id: step for step in self.steps}
        for step in self.steps:
            deps = set(step.dependencies) | {b.source_step_id for b in step.bindings.values()}
            missing = deps - step_ids
            if missing:
                raise ValueError(f"step {step.step_id} has unknown dependencies: {sorted(missing)}")

        state: dict[str, int] = {}

        def visit(step_id: str) -> None:
            marker = state.get(step_id, 0)
            if marker == 1:
                raise ValueError(f"cycle in pipe at: {step_id}")
            if marker == 2:
                return
            state[step_id] = 1
            step = by_id[step_id]
            for dep in set(step.dependencies) | {b.source_step_id for b in step.bindings.values()}:
                visit(dep)
            state[step_id] = 2

        for step in self.steps:
            visit(step.step_id)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    pipe_id: str
    status: ResultStatus
    results: Mapping[str, TypedResult]
    events: tuple[PipeEvent, ...]
    failure_reason: str | None = None


def _merge_results(left: dict[str, TypedResult] | None, right: dict[str, TypedResult] | None) -> dict[str, TypedResult]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def _append_events(left: list[PipeEvent] | None, right: list[PipeEvent] | None) -> list[PipeEvent]:
    return [*(left or []), *(right or [])]


class GraphState(TypedDict, total=False):
    context: ExecutionContext
    results: Annotated[dict[str, TypedResult], _merge_results]
    events: Annotated[list[PipeEvent], _append_events]


def _field_key(value: Mapping[str, Any], requested: str) -> str | None:
    if requested in value:
        return requested
    aliases = {
        "mineral": {"mineral", "광종", "광물", "원소", "entity"},
        "entity": {"mineral", "광종", "광물", "원소", "entity"},
        "country": {"country", "국가", "국가명", "수입국", "상대국"},
        "share_percentage": {"share_percentage", "비중", "점유율", "수입비중", "수입 비중"},
        "import_amount": {"import_amount", "수입액", "수입금액", "금액"},
        "import_value": {"import_value", "수입액", "수입금액", "금액"},
        "period": {"period", "기간", "대상기간", "기준기간", "기준연도"},
        "unit": {"unit", "단위"},
    }
    requested_names = aliases.get(requested.casefold(), {requested})
    for key in value:
        if key in requested_names:
            return key
    normalized = re.sub(r"[^a-z0-9가-힣]+", "", requested.casefold())
    for key in value:
        key_normalized = re.sub(r"[^a-z0-9가-힣]+", "", str(key).casefold())
        if key_normalized.startswith(normalized) or normalized in key_normalized:
            return str(key)
    return None


def _select(result: TypedResult, selector: str, selector_value: str | int | None) -> TypedResult:
    if selector == "all":
        return result
    if selector == "index":
        if not isinstance(selector_value, int) or not isinstance(result.value, (list, tuple)):
            raise TypeError("index binding requires an integer and a sequence result")
        try:
            value = result.value[selector_value]
        except IndexError as exc:
            raise ValueError(f"result index out of range: {selector_value}") from exc
        return TypedResult(result_type=result.result_type, value=value, status=result.status, entity=result.entity, metric=result.metric, period=result.period, unit=result.unit, source=result.source, evidence=result.evidence, provenance=result.provenance, confidence=result.confidence, sufficient=result.sufficient, upstream_step_ids=result.upstream_step_ids, warnings=result.warnings, failure_reason=result.failure_reason)
    if selector == "field":
        if not isinstance(selector_value, str):
            raise TypeError("field binding requires a field name")
        if isinstance(result.value, Mapping):
            key = _field_key(result.value, selector_value)
            if key is None:
                raise ValueError(f"result field not found: {selector_value}")
            value = result.value[key]
        elif isinstance(result.value, (list, tuple)):
            rows = [row for row in result.value if isinstance(row, Mapping)]
            keys = [_field_key(row, selector_value) for row in rows]
            if not rows or any(key is None for key in keys):
                raise ValueError(f"result field not found in sequence: {selector_value}")
            value = [row[key] for row, key in zip(rows, keys) if key is not None]
        else:
            raise TypeError("field binding requires a mapping or sequence of mappings")
        return TypedResult(
            result_type=result.result_type, value=value, status=result.status,
            entity=result.entity, metric=result.metric, period=result.period,
            unit=result.unit, source=result.source, evidence=result.evidence,
            provenance=result.provenance, confidence=result.confidence,
            sufficient=result.sufficient, upstream_step_ids=result.upstream_step_ids,
            warnings=result.warnings, failure_reason=result.failure_reason,
        )
    if selector == "predicate":
        raise ValueError("predicate bindings must be lowered to deterministic code")
    raise ValueError(f"unsupported input selector: {selector}")


class PipeRuntime:
    """Lower a Pipe to a LangGraph StateGraph and execute it asynchronously."""

    def __init__(self, tracer: Tracer | None = None) -> None:
        self._tracer = tracer or NoOpTracer()

    def _compile(self, pipe: Pipe):
        pipe.validate()
        builder = StateGraph(GraphState)
        # Semantic IDs are opaque references. LangGraph's reserved characters
        # and sentinels must not restrict them or alter persisted result keys.
        graph_ids = {step.step_id: f"step_{index}" for index, step in enumerate(pipe.steps)}

        for step in pipe.steps:
            async def run_node(state: GraphState, current_step: Step = step) -> dict[str, Any]:
                context = state["context"]
                context.check_cancelled()
                results = state.get("results", {})
                input_ids = set(current_step.dependencies) | {b.source_step_id for b in current_step.bindings.values()}
                failed = [results[item] for item in input_ids if results[item].status in {ResultStatus.FAILED, ResultStatus.ABSTAINED, ResultStatus.DEPENDENCY_FAILED}]
                if failed:
                    result = TypedResult(result_type=ValueType.UNKNOWN, status=ResultStatus.DEPENDENCY_FAILED,
                                         sufficient=False,
                                         failure_reason=f"upstream step failed: {', '.join(sorted(input_ids))}",
                                         upstream_step_ids=tuple(sorted(input_ids)))
                    return {"results": {current_step.step_id: result}, "events": [PipeEvent("step_skipped", pipe.pipe_id, current_step.step_id, result.status.value)]}
                try:
                    self._tracer.event("step_started", {"pipe_id": pipe.pipe_id, "step_id": current_step.step_id, "operation": current_step.operation})
                    started_event = PipeEvent("step_started", pipe.pipe_id, current_step.step_id, "running", metadata={"operation": current_step.operation})
                    last_error: Exception | None = None
                    for attempt in range(current_step.max_retries + 1):
                        try:
                            if current_step.bindings:
                                inputs = {name: _select(results[b.source_step_id], b.selector, b.selector_value) for name, b in current_step.bindings.items()}
                            else:
                                inputs = {item: results[item] for item in current_step.dependencies}
                            context.check_cancelled()
                            call = current_step.execute(context, inputs)
                            result = await call if current_step.timeout_seconds is None else await asyncio.wait_for(call, current_step.timeout_seconds)
                            if not isinstance(result, TypedResult):
                                raise TypeError(f"step {current_step.step_id} returned non-TypedResult")
                            if input_ids and not result.upstream_step_ids:
                                result = TypedResult(result_type=result.result_type, value=result.value, status=result.status, entity=result.entity, metric=result.metric, period=result.period, unit=result.unit, source=result.source, evidence=result.evidence, provenance=result.provenance, confidence=result.confidence, sufficient=result.sufficient, upstream_step_ids=tuple(sorted(input_ids)), warnings=result.warnings, failure_reason=result.failure_reason)
                            event_type = "step_completed" if result.status in {ResultStatus.SUCCESS, ResultStatus.PARTIAL, ResultStatus.EMPTY} else "step_failed"
                            self._tracer.event(event_type, {"pipe_id": pipe.pipe_id, "step_id": current_step.step_id, "status": result.status.value, "attempt": attempt + 1})
                            return {"results": {current_step.step_id: result}, "events": [started_event, PipeEvent(event_type, pipe.pipe_id, current_step.step_id, result.status.value, result.result_type.value, {"attempt": attempt + 1})]}
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            last_error = exc
                    result = TypedResult.failed(f"step execution failed: {last_error}")
                    self._tracer.event("step_failed", {"pipe_id": pipe.pipe_id, "step_id": current_step.step_id, "error": str(last_error)})
                    return {"results": {current_step.step_id: result}, "events": [started_event, PipeEvent("step_failed", pipe.pipe_id, current_step.step_id, result.status.value, metadata={"error": str(last_error)})]}
                except asyncio.CancelledError:
                    raise

            builder.add_node(graph_ids[step.step_id], run_node)

        downstream: set[str] = set()
        for step in pipe.steps:
            dependencies = set(step.dependencies) | {b.source_step_id for b in step.bindings.values()}
            downstream.update(dependencies)
            if not dependencies:
                builder.add_edge(START, graph_ids[step.step_id])
            else:
                # A multi-input step is a barrier: LangGraph must wait for
                # every upstream result before evaluating its bindings. A
                # separate edge per dependency would permit any one branch
                # to trigger the downstream node prematurely.
                builder.add_edge([graph_ids[dep] for dep in sorted(dependencies)], graph_ids[step.step_id])
        for step in pipe.steps:
            if step.step_id not in downstream:
                builder.add_edge(graph_ids[step.step_id], END)
        return builder.compile(name=f"pipe:{pipe.pipe_id}")

    async def execute_stream(self, pipe: Pipe, context: ExecutionContext | None = None) -> AsyncIterator[PipeEvent]:
        context = context or ExecutionContext()
        self._tracer.event("pipe_started", {"pipe_id": pipe.pipe_id})
        yield PipeEvent("pipe_started", pipe.pipe_id)
        if not pipe.steps:
            yield PipeEvent("pipe_completed", pipe.pipe_id, status=ResultStatus.SUCCESS.value)
            return
        graph = self._compile(pipe)
        initial: GraphState = {"context": context, "results": dict(context.results), "events": []}
        try:
            async for update in graph.astream(initial, stream_mode="updates"):
                for node_update in update.values():
                    if not isinstance(node_update, Mapping):
                        continue
                    for step_id, result in node_update.get("results", {}).items():
                        context.results[step_id] = result
                    for event in node_update.get("events", []):
                        yield event
            status = ResultStatus.SUCCESS
            if any(result.status == ResultStatus.ABSTAINED for result in context.results.values()):
                status = ResultStatus.ABSTAINED
            elif any(result.status == ResultStatus.FAILED for result in context.results.values()):
                status = ResultStatus.FAILED
            elif any(result.status == ResultStatus.DEPENDENCY_FAILED for result in context.results.values()):
                status = ResultStatus.DEPENDENCY_FAILED
            yield PipeEvent("pipe_completed", pipe.pipe_id, status=status.value)
        except asyncio.CancelledError:
            context.cancel()
            yield PipeEvent("pipe_cancelled", pipe.pipe_id, status="cancelled")
            raise

    async def execute(self, pipe: Pipe, context: ExecutionContext | None = None) -> ExecutionResult:
        context = context or ExecutionContext()
        events: list[PipeEvent] = []
        try:
            async for event in self.execute_stream(pipe, context):
                events.append(event)
        except asyncio.CancelledError:
            return ExecutionResult(pipe.pipe_id, ResultStatus.ABSTAINED, dict(context.results), tuple(events), "cancelled")
        status = ResultStatus.SUCCESS
        if any(result.status == ResultStatus.ABSTAINED for result in context.results.values()):
            status = ResultStatus.ABSTAINED
        elif any(result.status == ResultStatus.FAILED for result in context.results.values()):
            status = ResultStatus.FAILED
        return ExecutionResult(pipe.pipe_id, status, dict(context.results), tuple(events))
