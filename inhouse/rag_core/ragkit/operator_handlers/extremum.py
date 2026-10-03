"""Mechanical extraction of legacy ARG_MAX/ARG_MIN row selection."""

from datetime import date
from typing import Any, Callable, Mapping

from ..pipe_runtime import FunctionStep, InputBinding, ResultStatus, TypedResult
from ..semantic_ir import Operator, RequirementNode, ValueType


def build_extremum_step(
    *,
    node: RequirementNode,
    dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding],
    resolve: Callable[[list[Any], str | None], str | None],
    numeric: Callable[[Any], float | None],
    finalize: Callable[[RequirementNode, TypedResult | None, list[Any]], TypedResult],
) -> FunctionStep:
    def execute(_context, inputs: Mapping[str, TypedResult]) -> TypedResult:
        if any(result.status == ResultStatus.PARTIAL for result in inputs.values()):
            return TypedResult.abstain("incomplete_population")
        source = next(iter(inputs.values()), None)
        value = source.value if source else None
        rows = value if isinstance(value, list) else ([value] if isinstance(value, Mapping) else [])
        args = node.args
        field = args.get("field") or args.get("metric_field")
        field = resolve(rows, field) or field
        if rows and field:
            candidates = [row for row in rows if isinstance(row, Mapping) and row.get(field) is not None]
            key = lambda row: numeric(row[field])
            if candidates and any(key(row) is None for row in candidates):
                try:
                    for row in candidates:
                        date.fromisoformat(row[field])
                    key = lambda row: date.fromisoformat(row[field])
                except (ValueError, TypeError):
                    return TypedResult.abstain("incompatible_extremum_values")
            if not candidates:
                return TypedResult.empty(
                    source.result_type if source else ValueType.FACT_SET,
                    f"arg field unavailable: {field}",
                    evidence=source.evidence if source else (),
                    source=source.source if source else (),
                    provenance=source.provenance if source else (),
                    upstream_step_ids=source.upstream_step_ids if source else (),
                )
            select = max if node.operator == Operator.ARG_MAX.value else min
            extremum = select(key(row) for row in candidates)
            tied = [row for row in candidates if key(row) == extremum]
            policy = args.get("ties", "first")
            if policy not in {"all", "first", "error"}:
                return TypedResult.abstain("unsupported_tie_policy")
            if policy == "error" and len(tied) > 1:
                return TypedResult.abstain("ambiguous_extremum_tie")
            rows = tied if policy == "all" else tied[:1]
        return finalize(node, source, rows)

    return FunctionStep(
        node.node_id, node.operator.value, execute,
        dependencies=dependencies, bindings=bindings,
    )
