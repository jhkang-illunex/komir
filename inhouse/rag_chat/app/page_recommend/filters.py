"""필터 상속·검증·표시값 해석.

이식 출처: komis-report-generator-main `search/filters.py`(2026-08-11 스냅샷) —
임포트 경로만 패키지 상대경로로 바꿨고 로직은 무수정."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .metadata import MetadataResolver
from .models import PageDefinition, PageFilter
from .temporal import (
    TemporalGranularity,
    TemporalResolutionError,
    is_relative_temporal_intent,
    resolve_relative_temporal,
)


class FilterResolutionError(ValueError):
    """Raised when extracted filter values do not match the selected page contract."""


@dataclass(slots=True)
class ResolvedFilters:
    """Effective filters plus defaults, changes, and validation diagnostics."""

    effective: dict[str, Any] = field(default_factory=dict)
    defaulted: dict[str, Any] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    temporal_resolutions: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata_issues: list[dict[str, Any]] = field(default_factory=list)


def filter_definitions_for_prompt(page: PageDefinition) -> list[dict[str, Any]]:
    """Serialize page filters into the bounded schema shown to the LLM."""

    semantic_by_id = {item.id: item.semantic_key for item in page.filters}
    definitions = []
    for item in page.filters:
        definition: dict[str, Any] = {
            "id": item.semantic_key,
            "label": item.label,
            "type": item.type,
            "required": item.required,
        }
        if item.options:
            definition["values"] = [
                {
                    "value": option.value,
                    "label": option.label,
                    "aliases": option.aliases,
                }
                for option in item.options
            ]
        if item.values_ref:
            definition["values_ref"] = item.values_ref
        if item.depends_on:
            definition["depends_on"] = [
                semantic_by_id.get(dependency, dependency) for dependency in item.depends_on
            ]
        if item.applies_when:
            definition["applies_when"] = {
                semantic_by_id.get(parent, parent): values
                for parent, values in item.applies_when.items()
            }
        if item.temporal:
            definition["temporal"] = item.temporal.model_dump(mode="json")
        definitions.append(definition)
    return definitions


def _find_filter(page: PageDefinition, key: str) -> PageFilter | None:
    return page.filter_by_semantic_key(key) or page.filter_by_id(key)


def _temporal_granularity(
    page: PageDefinition,
    item: PageFilter,
    effective: dict[str, Any],
) -> TemporalGranularity:
    if item.temporal is None:
        return "day"
    parent_id = item.temporal.granularity_filter
    if not parent_id:
        return item.temporal.granularity
    parent = page.filter_by_id(parent_id)
    parent_key = parent.semantic_key if parent else parent_id
    parent_value = effective.get(parent_key)
    return item.temporal.granularity_map.get(str(parent_value), item.temporal.granularity)


def _parse_absolute_temporal(value: str, granularity: TemporalGranularity) -> date:
    patterns = {
        "year": r"\d{4}",
        "month": r"\d{4}-(?:0[1-9]|1[0-2])",
        "day": r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])",
    }
    if re.fullmatch(patterns[granularity], value) is None:
        raise ValueError(f"expected a {granularity}-granularity date")
    if granularity == "year":
        return date(int(value), 1, 1)
    if granularity == "month":
        return date.fromisoformat(f"{value}-01")
    return date.fromisoformat(value)


def _apply_temporal_maximum(
    item: PageFilter,
    value: Any,
    *,
    as_of: date | None,
) -> tuple[Any, dict[str, Any] | None]:
    temporal = item.temporal
    if temporal is None or temporal.max_year_offset is None:
        return value, None
    if isinstance(value, str) and value in {"all", "latest", "site_default"}:
        return value, None
    if as_of is None:
        raise FilterResolutionError(
            f"filter {item.semantic_key} requires a request date for its maximum-year policy"
        )

    maximum = as_of.year + temporal.max_year_offset
    maximum_text = f"{maximum:04d}"
    adjusted = value
    if isinstance(value, str) and re.fullmatch(r"\d{4}", value):
        if int(value) > maximum:
            adjusted = maximum_text
    elif isinstance(value, dict) and set(value) == {"start", "end"}:
        start = value["start"]
        end = value["end"]
        adjusted = {
            "start": maximum_text if int(start) > maximum else start,
            "end": maximum_text if int(end) > maximum else end,
        }

    if adjusted == value:
        return value, None
    return adjusted, {
        "code": "capped_to_previous_year",
        "requested": value,
        "applied": adjusted,
        "current_year": as_of.year,
        "maximum_year": maximum,
    }


def _normalize_value(
    page: PageDefinition,
    item: PageFilter,
    value: Any,
    *,
    effective: dict[str, Any],
    as_of: date | None,
) -> Any:
    if value is None:
        return None
    try:
        symbolic = page.canonical_symbolic_filter_value(item, value)
        if symbolic is not None:
            return symbolic[0]
        if item.type == "enum":
            return item.canonicalize(value)
        if item.type == "integer":
            if isinstance(value, bool):
                raise ValueError("expected an integer value")
            normalized_integer = int(value)
            if isinstance(value, float) and value != normalized_integer:
                raise ValueError("expected an integer value")
            normalized_value: Any = normalized_integer
        if item.type == "boolean":
            if isinstance(value, bool):
                normalized_value = value
            else:
                normalized = str(value).strip().casefold()
                if normalized in {"true", "1", "yes", "y", "예"}:
                    normalized_value = True
                elif normalized in {"false", "0", "no", "n", "아니오"}:
                    normalized_value = False
                else:
                    raise ValueError("expected a boolean value")
        elif item.type in {"mineral", "country", "text"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"expected a non-empty string for {item.type}")
            normalized_value = value.strip()
        elif item.type == "date":
            if is_relative_temporal_intent(value):
                if as_of is None:
                    raise ValueError("relative dates require a request date")
                normalized_value = resolve_relative_temporal(
                    value,
                    filter_type="date",
                    current_date=as_of,
                    granularity=_temporal_granularity(page, item, effective),
                )
            elif not isinstance(value, str) or not value.strip():
                raise ValueError("expected a non-empty string for date")
            else:
                normalized_value = value.strip()
                _parse_absolute_temporal(
                    normalized_value,
                    _temporal_granularity(page, item, effective),
                )
        elif item.type == "date_range":
            if is_relative_temporal_intent(value):
                if as_of is None:
                    raise ValueError("relative date ranges require a request date")
                normalized_value = resolve_relative_temporal(
                    value,
                    filter_type="date_range",
                    current_date=as_of,
                    granularity=_temporal_granularity(page, item, effective),
                )
            elif isinstance(value, dict) and set(value) == {"start", "end"}:
                start = value.get("start")
                end = value.get("end")
                if not all(
                    isinstance(boundary, str) and boundary.strip() for boundary in (start, end)
                ):
                    raise ValueError("date_range boundaries must be non-empty strings")
                normalized_start = start.strip()
                normalized_end = end.strip()
                granularity = _temporal_granularity(page, item, effective)
                parsed_start = _parse_absolute_temporal(normalized_start, granularity)
                parsed_end = _parse_absolute_temporal(normalized_end, granularity)
                if parsed_start > parsed_end:
                    raise ValueError("date_range start must not be after end")
                normalized_value = {"start": normalized_start, "end": normalized_end}
            else:
                raise ValueError("expected a declared symbolic value or {start, end} date range")
        elif item.type != "integer":
            normalized_value = value

        if item.options:
            allowed_values = {option.value for option in item.options}
            if normalized_value not in allowed_values:
                raise ValueError(f"unsupported value; allowed values: {sorted(allowed_values)!r}")
        return normalized_value
    except (TemporalResolutionError, TypeError, ValueError) as exc:
        raise FilterResolutionError(
            f"invalid value for filter {item.semantic_key}: {value!r}"
        ) from exc


def inherit_compatible_filters(
    source_filters: dict[str, Any], target_page: PageDefinition
) -> dict[str, Any]:
    """Retain prior filter values supported by a target page."""

    supported = {item.semantic_key for item in target_page.filters}
    return {key: value for key, value in source_filters.items() if key in supported}


def resolve_filters(
    page: PageDefinition,
    extracted: dict[str, Any],
    *,
    current: dict[str, Any] | None = None,
    current_defaulted: dict[str, Any] | None = None,
    inherited: dict[str, Any] | None = None,
    as_of: date | None = None,
    metadata_resolver: MetadataResolver | None = None,
) -> ResolvedFilters:
    """Merge, normalize, default, and validate filters for one page."""

    if metadata_resolver is not None:
        extracted = metadata_resolver.preprocess_extracted(page, extracted)
    previous = dict(current or {})
    effective: dict[str, Any] = {}
    errors: list[str] = []
    temporal_resolutions: dict[str, dict[str, Any]] = {}

    for source_name, source in (("inherited", inherited or {}), ("current", previous)):
        for key, value in source.items():
            item = _find_filter(page, key)
            if item is not None:
                try:
                    normalized = _normalize_value(
                        page, item, value, effective=effective, as_of=as_of
                    )
                    normalized, adjustment = _apply_temporal_maximum(
                        item,
                        normalized,
                        as_of=as_of,
                    )
                except FilterResolutionError as exc:
                    errors.append(str(exc))
                else:
                    effective[item.semantic_key] = normalized
                    if adjustment:
                        temporal_resolutions[item.semantic_key] = {
                            "input": value,
                            "resolved": normalized,
                            "as_of": as_of.isoformat() if as_of else None,
                            "source": source_name,
                            "adjustments": [adjustment],
                        }

    defaulted = {
        key: value
        for key, value in (current_defaulted or {}).items()
        if key in effective and effective[key] == value
    }
    explicit_keys: set[str] = set()
    known_items: list[tuple[PageFilter, Any]] = []
    for key, value in extracted.items():
        item = _find_filter(page, key)
        if item is None:
            errors.append(f"unknown filter for {page.page_id}: {key}")
            continue
        known_items.append((item, value))
    filter_order = {item.id: index for index, item in enumerate(page.filters)}
    known_items.sort(key=lambda pair: filter_order[pair[0].id])
    for item, value in known_items:
        canonical_key = item.semantic_key
        if value is None:
            explicit_keys.add(canonical_key)
            effective.pop(canonical_key, None)
            defaulted.pop(canonical_key, None)
        else:
            try:
                normalized = _normalize_value(
                    page, item, value, effective=effective, as_of=as_of
                )
                normalized, adjustment = _apply_temporal_maximum(
                    item,
                    normalized,
                    as_of=as_of,
                )
            except FilterResolutionError as exc:
                errors.append(str(exc))
            else:
                explicit_keys.add(canonical_key)
                effective[canonical_key] = normalized
                defaulted.pop(canonical_key, None)
                if is_relative_temporal_intent(value) or adjustment:
                    temporal_resolutions[canonical_key] = {
                        "input": value,
                        "resolved": normalized,
                        "as_of": as_of.isoformat() if as_of else None,
                    }
                    if adjustment:
                        temporal_resolutions[canonical_key]["adjustments"] = [adjustment]

    missing_required: list[str] = []
    semantic_by_id = {item.id: item.semantic_key for item in page.filters}
    for item in page.filters:
        key = item.semantic_key
        dependencies = [semantic_by_id.get(value, value) for value in item.depends_on]
        if any(dependency not in effective for dependency in dependencies):
            if key in explicit_keys and key in effective:
                errors.append(f"filter {key} requires parent filters: {dependencies}")
            effective.pop(key, None)
            defaulted.pop(key, None)
            continue
        applicable = all(
            effective.get(semantic_by_id.get(parent, parent)) in allowed_values
            for parent, allowed_values in item.applies_when.items()
        )
        if not applicable:
            if key in explicit_keys and key in effective:
                errors.append(f"filter {key} does not apply to the selected parent values")
            effective.pop(key, None)
            defaulted.pop(key, None)
            continue
        if key in effective:
            continue
        policy_default = page.policies.filter_defaults.get(key)
        if policy_default is not None:
            normalized = _normalize_value(
                page,
                item,
                policy_default.value,
                effective=effective,
                as_of=as_of,
            )
            normalized, adjustment = _apply_temporal_maximum(
                item,
                normalized,
                as_of=as_of,
            )
            effective[key] = normalized
            defaulted[key] = normalized
            if is_relative_temporal_intent(policy_default.value) or adjustment:
                temporal_resolutions[key] = {
                    "input": policy_default.value,
                    "resolved": normalized,
                    "as_of": as_of.isoformat() if as_of else None,
                    "source": "policy_default",
                }
                if adjustment:
                    temporal_resolutions[key]["adjustments"] = [adjustment]
        elif item.default is not None:
            normalized = _normalize_value(
                page, item, item.default, effective=effective, as_of=as_of
            )
            normalized, adjustment = _apply_temporal_maximum(
                item,
                normalized,
                as_of=as_of,
            )
            effective[key] = normalized
            defaulted[key] = normalized
            if adjustment:
                temporal_resolutions[key] = {
                    "input": item.default,
                    "resolved": normalized,
                    "as_of": as_of.isoformat() if as_of else None,
                    "source": "filter_default",
                    "adjustments": [adjustment],
                }
        elif item.required:
            missing_required.append(key)

    metadata_bindings: dict[str, dict[str, Any]] = {}
    metadata_issues: list[dict[str, Any]] = []
    if metadata_resolver is not None:
        metadata = metadata_resolver.validate(page, effective)
        effective = metadata.effective
        metadata_bindings = {
            key: binding.as_dict() for key, binding in metadata.bindings.items()
        }
        metadata_issues = [issue.as_dict() for issue in metadata.issues]
        errors.extend(issue.message for issue in metadata.issues if issue.blocking)

    missing_required = []
    for item in page.filters:
        key = item.semantic_key
        dependencies = [semantic_by_id.get(value, value) for value in item.depends_on]
        if any(dependency not in effective for dependency in dependencies):
            effective.pop(key, None)
            defaulted.pop(key, None)
            metadata_bindings.pop(key, None)
            continue
        applicable = all(
            effective.get(semantic_by_id.get(parent, parent)) in allowed_values
            for parent, allowed_values in item.applies_when.items()
        )
        if not applicable:
            effective.pop(key, None)
            defaulted.pop(key, None)
            metadata_bindings.pop(key, None)
        elif item.required and key not in effective:
            missing_required.append(key)

    for key, resolution in temporal_resolutions.items():
        applied = key in effective and effective[key] == resolution["resolved"]
        resolution["applied"] = applied
        if not applied:
            resolution["rejection_codes"] = [
                issue["code"]
                for issue in metadata_issues
                if issue["filter_key"] == key
                and issue["code"]
                in {
                    "metadata_value_not_found",
                    "metadata_value_ambiguous",
                    "metadata_period_outside_available_range",
                }
            ]

    sentinel = object()
    changed = sorted(
        key for key in explicit_keys if previous.get(key, sentinel) != effective.get(key, sentinel)
    )
    return ResolvedFilters(
        effective=effective,
        defaulted=defaulted,
        missing_required=missing_required,
        changed=changed,
        errors=errors,
        temporal_resolutions=temporal_resolutions,
        metadata_bindings=metadata_bindings,
        metadata_issues=metadata_issues,
    )


def display_filter_value(
    page: PageDefinition,
    key: str,
    value: Any,
    *,
    defaulted: bool = False,
) -> str:
    """Render a canonical filter value using page labels and policy defaults."""

    item = _find_filter(page, key)
    if item is None:
        return str(value)
    if defaulted:
        policy_default = page.policies.filter_defaults.get(item.semantic_key)
        if policy_default and policy_default.label:
            return policy_default.label
    if key and item.default == value and item.default_label:
        return item.default_label
    for option in item.options:
        if option.value == value:
            return option.label
    if item.type == "date_range" and isinstance(value, dict):
        return f"{value['start']} ~ {value['end']}"
    symbolic_labels = {
        "latest": "최신 제공 기간",
        "site_default": "사이트 기본 범위",
        "all": "전체",
    }
    return symbolic_labels.get(value, str(value)) if isinstance(value, str) else str(value)
