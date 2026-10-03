"""Mechanical extraction of SORT, upstream RANK and TOP_K execution."""

from typing import Any, Awaitable, Callable, Mapping

from ..pipe_runtime import FunctionStep, InputBinding, ResultStatus, TypedResult
from ..semantic_ir import Operator, RequirementNode


def build_ordering_step(
    *,
    node: RequirementNode,
    dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding],
    resolve: Callable[..., str | None],
    numeric: Callable[[Any], float | None],
    finalize: Callable[[RequirementNode, TypedResult | None, list[Any]], TypedResult],
    retrieve: Callable[[RequirementNode, Mapping[str, TypedResult]], Awaitable[TypedResult]],
) -> FunctionStep:
    # Legacy routing depends on lowered dependencies, not args or runtime rows.
    # A source rank still executes the existing capability retrieval unchanged.
    if node.operator == Operator.RANK.value and not dependencies:
        return FunctionStep(
            node.node_id, node.operator.value, lambda _c, inputs: retrieve(node, inputs),
            dependencies=dependencies, bindings=bindings,
        )

    def execute(_context, inputs: Mapping[str, TypedResult]) -> TypedResult:
        if any(result.status == ResultStatus.PARTIAL for result in inputs.values()) and node.operator in {
            Operator.RANK, Operator.TOP_K,
        }:
            return TypedResult.abstain("incomplete_population")
        source = next(iter(inputs.values()), None)
        value = source.value if source else None
        rows = value if isinstance(value, list) else ([value] if isinstance(value, Mapping) else [])
        args = node.args
        if node.operator == Operator.TOP_K.value:
            rows = rows[: int(args.get("k") or args.get("top_n") or 5)]
        else:
            field = args.get("field") or args.get("metric_field")
            if field is None and rows and isinstance(rows[0], Mapping):
                field = next((key for key, item in rows[0].items() if numeric(item) is not None), None)
            field = resolve(rows, field) or field
            reverse = str(args.get("order", "desc")).casefold() in {"desc", "decreasing", "decrease"}
            tie_breaker = args.get("tie_breaker")
            if tie_breaker:
                tie_field = resolve(rows, tie_breaker, strict=True)
                if not tie_field or any(not isinstance(row, Mapping) or row.get(tie_field) is None for row in rows):
                    return TypedResult.abstain("sort_tie_field_unavailable")
                rows = sorted(rows, key=lambda row: str(row[tie_field]))
            valid = [row for row in rows if isinstance(row, Mapping) and field and row.get(field) is not None]
            missing = [row for row in rows if row not in valid]
            if valid and all(numeric(row[field]) is not None for row in valid):
                rows = sorted(valid, key=lambda row: numeric(row[field]), reverse=reverse) + missing
            elif all(isinstance(row[field], str) for row in valid):
                # Preserve lexical ordering for ISO dates and identifiers.
                rows = sorted(valid, key=lambda row: row[field], reverse=reverse) + missing
            else:
                return TypedResult.abstain("incompatible_sort_values")
        return finalize(node, source, rows)

    return FunctionStep(
        node.node_id, node.operator.value, execute,
        dependencies=dependencies, bindings=bindings,
    )
