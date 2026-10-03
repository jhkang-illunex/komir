"""Registered JOIN/COMPARE delegation; relation semantics stay in relational_ops."""

from typing import Callable, Mapping

from ..pipe_runtime import FunctionStep, InputBinding
from ..relational_ops import execute_relation
from ..semantic_ir import RequirementNode


def build_relation_step(
    *,
    node: RequirementNode,
    dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding],
    resolve: Callable[..., str | None],
) -> FunctionStep:
    return FunctionStep(
        node.node_id, node.operator.value,
        lambda _context, inputs: execute_relation(node, inputs, resolve),
        dependencies=dependencies, bindings=bindings,
    )
