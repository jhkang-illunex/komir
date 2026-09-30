"""Adapter contracts for reusing existing Action/Tool/Data access code."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Mapping

from .pipe_runtime import ExecutionContext, FunctionStep, InputBinding, Step, TypedResult
from .semantic_ir import RequirementNode


LegacyExecutor = Callable[[Any, ExecutionContext, Mapping[str, TypedResult]], Any | Awaitable[Any]]
LegacyResultAdapter = Callable[[Any, Any], TypedResult]


class LegacyActionStep(Step):
    """Run an existing ActionCall/tool executor without changing its interface."""

    def __init__(
        self,
        step_id: str,
        operation: str,
        action_call: Any,
        executor: LegacyExecutor,
        result_adapter: LegacyResultAdapter,
        **kwargs: Any,
    ) -> None:
        super().__init__(step_id, operation, **kwargs)
        self.action_call = action_call
        self._executor = executor
        self._result_adapter = result_adapter

    async def execute(self, context: ExecutionContext, inputs: Mapping[str, TypedResult]) -> TypedResult:
        raw = self._executor(self.action_call, context, inputs)
        if inspect.isawaitable(raw):
            raw = await raw
        result = self._result_adapter(raw, self.action_call)
        if not isinstance(result, TypedResult):
            raise TypeError("legacy result adapter must return TypedResult")
        return result


class LegacyOperatorFactory:
    """Small factory hook for lowering only; physical action selection stays outside."""

    def __init__(self, builders: Mapping[str, Callable[..., Step]]) -> None:
        self._builders = dict(builders)

    def build(
        self,
        node: RequirementNode,
        dependencies: tuple[str, ...],
        bindings: Mapping[str, InputBinding],
    ) -> Step:
        try:
            builder = self._builders[node.operator.value]
        except KeyError as exc:
            raise ValueError(f"no physical adapter for semantic operator: {node.operator.value}") from exc
        return builder(node=node, dependencies=dependencies, bindings=bindings)

