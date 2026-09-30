"""Deterministic Semantic IR → Pipe lowering boundary."""

from __future__ import annotations

from typing import Callable, Mapping, Protocol

from .pipe_runtime import InputBinding, Pipe, Step
from .semantic_ir import InputRef, RequirementNode, SemanticProgram


class StepFactory(Protocol):
    def build(
        self,
        node: RequirementNode,
        dependencies: tuple[str, ...],
        bindings: Mapping[str, InputBinding],
    ) -> Step: ...


class PipeLowerer:
    """Compile a validated semantic DAG without selecting tools itself."""

    def __init__(self, step_factory: StepFactory | Callable[..., Step]) -> None:
        self._step_factory = step_factory

    def lower(self, program: SemanticProgram, *, pipe_id: str) -> Pipe:
        steps: list[Step] = []
        for node in program.nodes:
            bindings: dict[str, InputBinding] = {}
            dependencies: list[str] = []
            for index, ref in enumerate(node.inputs):
                name = f"input_{index}"
                bindings[name] = InputBinding(ref.node_id, ref.selector, ref.selector_value)
                dependencies.append(ref.node_id)
            factory = getattr(self._step_factory, "build", self._step_factory)
            step = factory(
                node=node,
                dependencies=tuple(dict.fromkeys(dependencies)),
                bindings=bindings,
            )
            if step.step_id != node.node_id:
                raise ValueError(f"step factory changed semantic node id: {node.node_id} -> {step.step_id}")
            steps.append(step)
        pipe = Pipe(pipe_id, tuple(steps))
        pipe.validate()
        return pipe
