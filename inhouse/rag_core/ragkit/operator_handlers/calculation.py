"""Route existing CALCULATE families without unifying their contracts."""

from typing import Any, Callable, Mapping

from ..analytical_mapping_change import calculate_mapping_change
from ..analytical_series import CALCULATIONS, calculate_series
from ..analytical_share import calculate_ratio, calculate_ratio_between, calculate_share
from ..pipe_runtime import FunctionStep, InputBinding, ResultStatus, TypedResult
from ..semantic_ir import RequirementNode


def build_calculation_step(
    *,
    node: RequirementNode,
    dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding],
    resolve: Callable[..., str | None],
    numeric: Callable[[Any], float | None],
    finalize: Callable[[RequirementNode, TypedResult | None, list[Any]], TypedResult],
) -> FunctionStep:
    def execute(_context, inputs: Mapping[str, TypedResult]) -> TypedResult:
        args = node.args
        # Preserve input insertion order and binary-ratio failure precedence.
        if str(args.get("calculation", "")).casefold() == "ratio" and len(inputs) == 2:
            left, right = inputs.values()
            return calculate_ratio_between(left, right, args, resolve)
        if any(result.status == ResultStatus.PARTIAL for result in inputs.values()):
            return TypedResult.abstain("incomplete_population")
        source = next(iter(inputs.values()), None)
        value = source.value if source else None
        calculation = args.get("calculation")
        if calculation in CALCULATIONS:
            return calculate_series(source, args, resolve)
        normalized_calculation = str(calculation).lower()
        if normalized_calculation in {"share", "hhi", "division", "percentage", "percent"}:
            # These legacy aliases mean population share, not row-wise ratio.
            share_args = dict(args)
            share_args["calculation"] = "hhi" if normalized_calculation == "hhi" else "share"
            return calculate_share(source, share_args, resolve)
        if normalized_calculation == "ratio":
            return calculate_ratio(source, args, resolve)
        if calculation in {"change_pct", "percent_change"} and isinstance(value, Mapping):
            return calculate_mapping_change(
                value, numeric, lambda rows: finalize(node, source, rows),
            )
        return TypedResult.abstain("unsupported_calculation_contract")

    return FunctionStep(
        node.node_id, node.operator.value, execute,
        dependencies=dependencies, bindings=bindings,
    )
