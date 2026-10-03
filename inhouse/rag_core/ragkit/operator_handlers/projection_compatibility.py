"""Frozen projection compatibility, not new capability/output guarantees.

These legacy domain adaptations remain explicit debt. Do not widen aliases,
infer units, or replace their ordering with a different catalog convention.
"""

from dataclasses import replace
from typing import Mapping

from ..pipe_runtime import TypedResult
from ..semantic_capabilities import capability_identity_fields
from ..semantic_ir import ValueType


def document_minerals(source, rows, fields, *, entity_values, evidence_rows):
    """Preserve the existing document-to-set early result and empty failure."""
    if source and source.result_type == ValueType.DOCUMENT_EVIDENCE and fields in (["minerals"], ["mineral_list"]):
        entities = entity_values(rows) or entity_values(evidence_rows(list(source.evidence)))
        if not entities:
            return TypedResult.empty(ValueType.MINERAL_SET, "document_mineral_list_unavailable")
        return replace(source, result_type=ValueType.MINERAL_SET, value=entities, entity=tuple(entities))
    return None


def price_identity_fields(source, mappings, fields, *, resolve):
    """Keep literal-key compatibility before the registry-owned identity pass."""
    if source and source.metric == "price" and not any(
        isinstance(row, Mapping) and "price_measure" in row for row in mappings
    ):
        # Optional legacy REPRESENTATIVE/EXPLICIT identity, before annotated lookup.
        fields = [field for field in fields if field not in {
            "price_measure", "price_measure_label", "price_criterion",
            "price_criterion_serial",
        }]
    if any(
        isinstance(row, Mapping) and "price_measure" in row for row in mappings
    ):
        fields = list(fields)
        identity_fields = {
            "price_measure", "price_measure_label", "price_criterion",
            "price_criterion_serial",
        }
        fields = [
            field for field in fields
            if field not in identity_fields
            or resolve(mappings, field, strict=True) is not None
        ]
        # This legacy order differs from the catalog tuple; preserve both passes.
        for identity_field in (
            "price_measure", "price_measure_label", "price_criterion",
            "price_criterion_serial",
        ):
            if identity_field not in fields and resolve(
                mappings, identity_field, strict=True
            ) is not None:
                fields.append(identity_field)
    if source and source.metric == "price":
        price_identity_fields = {
            "price_measure", "price_measure_label", "price_criterion",
            "price_criterion_serial",
        }
        fields = [
            field for field in fields
            if field not in price_identity_fields
            or resolve(mappings, field, strict=True) is not None
        ]
        for identity_field in capability_identity_fields("price", "price"):
            if identity_field not in fields and resolve(
                mappings, identity_field, strict=True
            ) is not None:
                fields.append(identity_field)
    return fields


def metric_value_key(source, mappings, field, key, *, resolve):
    """Legacy typed metric fallback, never an arbitrary numeric field choice."""
    if key is None and field == "inventory" and source and source.metric == "inventory":
        key = (resolve(mappings, "재고량", strict=True)
               or resolve(mappings, "value", strict=True))
    if key is None and field == "value" and source:
        metric_value_fields = {
            "price": "price",
            "inventory": "재고량",
            "indicator": "value",
            "production": "production",
            "reserves": "reserves",
        }
        value_field = metric_value_fields.get(source.metric)
        if value_field:
            key = resolve(mappings, value_field, strict=True)
            if key is None and source.metric == "inventory":
                key = resolve(mappings, "inventory", strict=True)
    return key
