"""Mechanical extraction of the existing FILTER execution contract."""

from dataclasses import replace
from typing import Any, Callable, Mapping

from ..pipe_runtime import FunctionStep, InputBinding, TypedResult
from ..semantic_ir import RequirementNode, ValueType


def build_filter_step(
    *,
    node: RequirementNode,
    dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding],
    resolve: Callable[..., str | None],
    numeric: Callable[[Any], float | None],
    filter_period: Callable[[list[Any], Any], list[Any]],
    resolve_country: Callable[[list[Any], str], list[Any]],
    finalize: Callable[[RequirementNode, TypedResult | None, list[Any]], TypedResult],
) -> FunctionStep:
    def execute(_context, inputs: Mapping[str, TypedResult]) -> TypedResult:
        source = next(iter(inputs.values()), None)
        value = source.value if source else None
        rows = value if isinstance(value, list) else ([value] if isinstance(value, Mapping) else [])
        args = node.args
        predicate = args.get("predicate") or {}
        if isinstance(predicate, Mapping):
            field = predicate.get("field") or args.get("field") or args.get("metric_field")
            operator = predicate.get("operator", args.get("operator", "equals"))
            expected = predicate.get("value", args.get("value"))
        else:
            # Preserve the compact predicate representation and its existing aliases.
            field = args.get("field") or args.get("metric_field")
            operator = {"increase": "greater_than", "decrease": "less_than"}.get(str(predicate), str(predicate))
            expected = args.get("value")
        if not field and args.get("metric"):
            metric_aliases = {
                "import_value_change": ("import_value_change", "import_amount_change", "change_pct"),
                "import_amount_change": ("import_amount_change", "import_value_change", "change_pct"),
                "price_change": ("price_change", "pct_change", "change_pct"),
                "price_change_rate": ("price_change_rate", "pct_change", "change_pct"),
            }
            candidates = metric_aliases.get(str(args["metric"]), (str(args["metric"]),))
            field = next((candidate for candidate in candidates if any(
                isinstance(row, Mapping) and candidate in row for row in rows
            )), None)
            field = resolve(rows, field)
        if not field:
            rows = filter_period(rows, args.get("period"))
            if args.get("metric") and rows:
                return TypedResult.empty(
                    source.result_type if source else ValueType.FACT_SET,
                    f"filter field unavailable: {args['metric']}",
                    evidence=source.evidence if source else (),
                    source=source.source if source else (),
                    provenance=source.provenance if source else (),
                    upstream_step_ids=source.upstream_step_ids if source else (),
                )
        country_matches = None
        if field == "country" and operator in {"equals", "not_equals"} and isinstance(expected, str):
            try:
                country_matches = {id(row) for row in resolve_country(rows, expected)}
            except ValueError as exc:
                return TypedResult.abstain(str(exc))

        def keep(row: Any) -> bool:
            actual = row.get(field) if isinstance(row, Mapping) else None
            if source and source.result_type == ValueType.MINERAL_SET and field in {"mineral", "entity", "광종"} and isinstance(row, str):
                actual = row
            expected_value = expected
            if country_matches is not None:
                matched = id(row) in country_matches
                return matched if operator == "equals" else not matched
            left, right = numeric(actual), numeric(expected_value)
            if left is not None and right is not None:
                actual, expected_value = left, right
            if operator == "equals":
                return actual == expected_value
            if actual is None or expected_value is None:
                return False
            if operator == "not_equals":
                return actual != expected_value
            if operator == "greater_than":
                return actual > expected_value
            if operator == "less_than":
                return actual < expected_value
            if operator == "gte":
                return actual >= expected_value
            if operator == "lte":
                return actual <= expected_value
            raise ValueError(f"unsupported filter operator: {operator}")

        if not field:
            return replace(source, value=rows) if source else TypedResult.failed("missing_input")
        rows = [row for row in rows if keep(row)]
        return finalize(node, source, rows)

    return FunctionStep(
        node.node_id, node.operator.value, execute,
        dependencies=dependencies, bindings=bindings,
    )
