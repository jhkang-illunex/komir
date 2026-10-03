"""Aggregate step builder; preserves the legacy wrapper's preconditions.

The existing analytical primitive owns reduction semantics. Canonical field
resolution is injected by the composition root, not redefined by this handler.
"""

from typing import Any, Callable, Mapping

from ..analytical_aggregate import aggregate
from ..pipe_runtime import FunctionStep, InputBinding, ResultStatus, TypedResult
from ..semantic_ir import RequirementNode


def build_aggregate_step(
    *,
    node: RequirementNode,
    dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding],
    resolve: Callable[[list[Mapping[str, Any]], str | None], str | None],
) -> FunctionStep:
    def execute(_context, inputs: Mapping[str, TypedResult]) -> TypedResult:
        if any(result.status == ResultStatus.PARTIAL for result in inputs.values()):
            return TypedResult.abstain("incomplete_population")
        source = next(iter(inputs.values()), None)
        if source is None:
            return TypedResult.failed("missing_input")
        args = dict(node.args)
        # Preserve ordered first/last canonical-date binding, including the
        # fail-closed path when no unambiguous date can be resolved.
        if args.get("aggregation") in {"first", "last"} and not args.get("order_by"):
            rows = source.value if isinstance(source.value, list) else [source.value]
            if rows and all(isinstance(row, Mapping) for row in rows):
                if resolve(rows, "date") is not None:
                    args["order_by"] = "date"
        return aggregate(source, args, resolve)

    return FunctionStep(
        node.node_id, node.operator.value, execute,
        dependencies=dependencies, bindings=bindings,
    )
