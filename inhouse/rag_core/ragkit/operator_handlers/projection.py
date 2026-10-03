"""Registered canonical projection with explicit legacy compatibility calls."""

from dataclasses import replace
import json
from typing import Any, Callable, Mapping

from ..pipe_runtime import FunctionStep, InputBinding, ResultStatus, TypedResult
from ..semantic_ir import RequirementNode, ValueType
from .projection_compatibility import document_minerals, metric_value_key, price_identity_fields


def _alias_failure(fields, aliases, resolve) -> str | None:
    if not isinstance(aliases, Mapping) or any(key not in fields or not isinstance(value, str) or not value for key, value in aliases.items()):
        return "invalid_projection_alias"
    if any(resolve([{target: None}], "unit", strict=True) is not None
           and resolve([{field: None}], "unit", strict=True) is None
           for field, target in aliases.items()):
        return "projection_reserved_unit_alias"
    if len({aliases.get(field, field) for field in fields}) != len(fields):
        return "projection_output_collision"
    return None


def _resolve_fields(source, mappings, fields, resolve):
    resolved = {}
    metadata = {}
    for field in fields:
        key = resolve(mappings, str(field), strict=True)
        key = metric_value_key(source, mappings, field, key, resolve=resolve)
        if key is None and field == "unit" and source and source.unit is not None:
            resolved[field] = None
            metadata[field] = source.unit
        elif key is None and field == "source" and source and len(source.source) == 1:
            resolved[field] = None
            metadata[field] = source.source[0]
        elif key is None and field in {"mineral", "entity"} and source and len(source.entity) == 1:
            resolved[field] = None
            metadata[field] = source.entity[0]
        elif key is None:
            return TypedResult.abstain(f"projection_field_unavailable:{field}")
        else:
            resolved[field] = key
    return resolved, metadata


def _select_rows(source, mappings, resolved, metadata, aliases, args):
    rows = [{aliases.get(field, field): metadata[field] if key is None else row.get(key)
             for field, key in resolved.items()} for row in mappings]
    if source and source.status == ResultStatus.PARTIAL:
        for projected, original in zip(rows, mappings):
            projected.update({key: original[key] for key in ("status", "reason", "output", "unit") if key in original})
    if args.get("distinct") is True:
        rows = list({json.dumps(row, sort_keys=True, ensure_ascii=False): row for row in rows}.values())
    return rows


def build_projection_step(
    *, node: RequirementNode, dependencies: tuple[str, ...],
    bindings: Mapping[str, InputBinding], resolve: Callable[..., str | None],
    entity_values: Callable[[Any], list[str]], evidence_rows: Callable[[Any], list[Any]],
    finalize: Callable[[RequirementNode, TypedResult | None, list[Any]], TypedResult],
) -> FunctionStep:
    def execute(_context, inputs: Mapping[str, TypedResult]) -> TypedResult:
        source = next(iter(inputs.values()), None)
        value = source.value if source else None
        rows = value if isinstance(value, list) else ([value] if isinstance(value, Mapping) else [])
        args = node.args
        fields = args.get("fields") or ([args["field"]] if args.get("field") else [])
        aliases = args.get("aliases") or {}
        failure = _alias_failure(fields, aliases, resolve)
        if failure:
            return TypedResult.abstain(failure)
        document = document_minerals(source, rows, fields, entity_values=entity_values, evidence_rows=evidence_rows)
        if document is not None:
            return document
        if not rows and source and isinstance(source.value, list):
            return replace(source, value=[], entity=())
        mappings = [row for row in rows if isinstance(row, Mapping)]
        if source and len({row.get("unit", source.unit) for row in mappings}) > 1:
            source = replace(source, warnings=tuple(dict.fromkeys((*source.warnings, "heterogeneous_units"))))
        if source and source.result_type == ValueType.MINERAL_SET and rows and all(isinstance(row, str) for row in rows):
            mappings = [{"mineral": row} for row in rows]
        fields = price_identity_fields(source, mappings, fields, resolve=resolve)
        resolution = _resolve_fields(source, mappings, fields, resolve)
        if isinstance(resolution, TypedResult):
            return resolution
        resolved, metadata = resolution
        if source and source.status == ResultStatus.SUCCESS and any(
            key is not None and key not in row for row in mappings for key in resolved.values()
        ):
            return TypedResult.abstain("projection_input_incomplete")
        rows = _select_rows(source, mappings, resolved, metadata, aliases, args)
        return finalize(node, source, rows)

    return FunctionStep(
        node.node_id, node.operator.value, execute,
        dependencies=dependencies, bindings=bindings,
    )
