"""KOMIS 메타데이터 스냅샷 기반 필터값 검증(광종·국가·가격기준 코드 매칭).

이식 출처: komis-report-generator-main `search/metadata.py`(2026-08-11 스냅샷) —
임포트 경로만 바꿨고 로직 무수정. SNAPSHOT_PATH는 패키지 상대경로라 파일과 함께
옮긴 resources/metadata/komis-metadata.snapshot.json을 그대로 가리킨다."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .models import (
    SYMBOLIC_FILTER_VALUES,
    PageDefinition,
    PageFilter,
)

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent
    / "resources"
    / "metadata"
    / "komis-metadata.snapshot.json"
)


class MetadataSnapshotError(RuntimeError):
    """Raised when the normalized metadata snapshot cannot be loaded."""


@dataclass(frozen=True, slots=True)
class MetadataBinding:
    """Canonical and external values resolved from one metadata reference."""

    canonical_value: Any
    display_label: str
    external_value: Any
    values_ref: str
    snapshot_id: str
    status: Literal["resolved", "symbolic", "unverified"] = "resolved"
    parent_external_values: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MetadataIssue:
    """Structured metadata validation warning or blocking error."""

    code: Literal[
        "metadata_value_not_found",
        "metadata_value_ambiguous",
        "metadata_value_unverified",
        "metadata_parent_unresolved",
        "metadata_snapshot_partial",
        "metadata_period_outside_available_range",
    ]
    page_id: str
    filter_key: str
    values_ref: str
    value: Any
    message: str
    candidates: tuple[dict[str, Any], ...] = ()

    @property
    def blocking(self) -> bool:
        return self.code in {
            "metadata_value_not_found",
            "metadata_value_ambiguous",
            "metadata_period_outside_available_range",
        }

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MetadataValidation:
    """Effective filter values with metadata bindings and issues."""

    effective: dict[str, Any]
    bindings: dict[str, MetadataBinding] = field(default_factory=dict)
    issues: list[MetadataIssue] = field(default_factory=list)


class MetadataResolver(Protocol):
    """Contract for preprocessing and validating page filter metadata."""

    def preprocess_extracted(
        self,
        page: PageDefinition,
        extracted: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Canonicalize extracted filter shapes before generic validation."""

        ...

    def validate(
        self,
        page: PageDefinition,
        effective: Mapping[str, Any],
    ) -> MetadataValidation:
        """Resolve effective filter values against available metadata."""

        ...


def _normalized(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    return " ".join(normalized.strip().split()).casefold()


def _candidate_payload(option: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "value": option.get("value"),
        "label": option.get("label"),
        "external_value": option.get("external_value"),
    }


class SnapshotMetadataResolver:
    """Resolve filters against a normalized, provenance-bearing snapshot."""

    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        if snapshot.get("schema_version") != 1:
            raise MetadataSnapshotError("unsupported metadata snapshot schema_version")
        refs = snapshot.get("refs")
        if not isinstance(refs, dict) or snapshot.get("ref_count") != len(refs):
            raise MetadataSnapshotError("metadata snapshot ref_count does not match refs")
        observed_at = snapshot.get("observed_at")
        source_hash = snapshot.get("source_sha256")
        if not observed_at or not source_hash:
            raise MetadataSnapshotError("metadata snapshot provenance is missing")
        self._refs: dict[str, Any] = dict(refs)
        self.snapshot_id = f"{observed_at}:{str(source_hash)[:12]}"

    @classmethod
    def from_path(cls, path: Path = SNAPSHOT_PATH) -> SnapshotMetadataResolver:
        """Read and validate a metadata snapshot from disk."""

        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MetadataSnapshotError(f"cannot load metadata snapshot {path}: {exc}") from exc
        return cls(snapshot)

    def preprocess_extracted(
        self,
        page: PageDefinition,
        extracted: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Split known composite mineral-map values into canonical filters."""

        result = dict(extracted)
        if page.page_id != "map_mineral" or "mineral" not in result:
            return result
        ref = self._refs.get("metadata.maps.mineral_map_minerals", {})
        raw = result["mineral"]
        if not isinstance(raw, str):
            return result
        matches = []
        for variant in ref.get("variants", []):
            tokens = [variant.get("input_value"), variant.get("label"), *variant.get("aliases", [])]
            if _normalized(raw) in {_normalized(token) for token in tokens if token is not None}:
                matches.append(variant)
        if len(matches) == 1:
            variant = matches[0]
            result["mineral"] = variant["mineral"]
            result.setdefault("mineral_subtype", variant["subtype"])
        return result

    def validate(
        self,
        page: PageDefinition,
        effective: Mapping[str, Any],
    ) -> MetadataValidation:
        """Resolve each referenced page filter and collect validation issues."""

        validated = dict(effective)
        bindings: dict[str, MetadataBinding] = {}
        issues: list[MetadataIssue] = []
        for item in page.filters:
            key = item.semantic_key
            if not item.values_ref or key not in validated:
                continue
            value = validated[key]
            symbolic = page.canonical_symbolic_filter_value(item, value)
            if symbolic is not None:
                canonical_value, display_label = symbolic
                validated[key] = canonical_value
                bindings[key] = MetadataBinding(
                    canonical_value=canonical_value,
                    display_label=display_label,
                    external_value=None,
                    values_ref=item.values_ref,
                    snapshot_id=self.snapshot_id,
                    status="symbolic",
                )
                continue
            ref = self._refs.get(item.values_ref)
            if ref is None or ref.get("coverage") == "absent":
                fallback = self._country_fallback(item, value)
                if fallback is not None:
                    validated[key] = fallback.canonical_value
                    bindings[key] = fallback
                issues.append(
                    self._issue(
                        "metadata_value_unverified",
                        page,
                        item,
                        value,
                        (ref or {}).get("note", "metadata snapshot에 해당 참조가 없다."),
                    )
                )
                continue

            kind = ref.get("kind")
            if kind == "independent":
                resolution = self._resolve_independent(page, item, value, ref)
            elif kind in {"year_range", "year_and_latest_month"}:
                resolution = self._resolve_partial_period(page, item, value, ref)
            elif kind == "map_dependency":
                resolution = self._resolve_map_dependency(
                    page, item, value, ref, validated, bindings
                )
            elif kind == "price_criteria":
                resolution = self._resolve_price_criterion(
                    page, item, value, ref, validated, bindings
                )
            elif kind == "price_specifications":
                resolution = self._resolve_price_specification(
                    page, item, value, validated, bindings
                )
            else:
                resolution = MetadataValidation(
                    effective={key: value},
                    issues=[
                        self._issue(
                            "metadata_value_unverified",
                            page,
                            item,
                            value,
                            f"지원하지 않는 metadata snapshot kind: {kind}",
                        )
                    ],
                )
            if key in resolution.effective:
                validated[key] = resolution.effective[key]
            else:
                validated.pop(key, None)
            bindings.update(resolution.bindings)
            issues.extend(resolution.issues)
        return MetadataValidation(effective=validated, bindings=bindings, issues=issues)

    def _resolve_independent(
        self,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        ref: Mapping[str, Any],
    ) -> MetadataValidation:
        if item.type == "date_range" and isinstance(value, dict):
            options = ref.get("options", [])
            start = self._match(value.get("start"), options)
            end = self._match(value.get("end"), options)
            if len(start) == len(end) == 1:
                canonical = {"start": start[0]["value"], "end": end[0]["value"]}
                binding = self._binding(
                    item,
                    canonical,
                    f"{start[0]['label']} ~ {end[0]['label']}",
                    {
                        "start": start[0]["external_value"],
                        "end": end[0]["external_value"],
                    },
                )
                return MetadataValidation(
                    effective={item.semantic_key: canonical},
                    bindings={item.semantic_key: binding},
                )
            available = sorted(
                ref.get("options", []),
                key=lambda option: str(option.get("value")),
            )
            if available:
                first = available[0]
                last = available[-1]
                return MetadataValidation(
                    effective={},
                    issues=[
                        self._issue(
                            "metadata_period_outside_available_range",
                            page,
                            item,
                            value,
                            "요청 기간이 snapshot의 제공 범위를 벗어났다. "
                            f"확인된 범위: {first['value']} ~ {last['value']}.",
                            candidates=(
                                _candidate_payload(first),
                                _candidate_payload(last),
                            ),
                        )
                    ],
                )
            return self._unmatched(page, item, value, [*start, *end])
        matches = self._match(value, ref.get("options", []))
        if len(matches) != 1:
            return self._unmatched(page, item, value, matches)
        option = matches[0]
        binding = self._binding(
            item,
            option["value"],
            option["label"],
            option["external_value"],
        )
        return MetadataValidation(
            effective={item.semantic_key: option["value"]},
            bindings={item.semantic_key: binding},
        )

    def _resolve_partial_period(
        self,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        ref: Mapping[str, Any],
    ) -> MetadataValidation:
        known_years = {
            str(option["value"])
            for option in ref.get("options", [])
            if option.get("value") is not None
        }
        if not known_years:
            known_years = {
                str(row.get("crtrYr"))
                for row in ref.get("rows", [])
                if row.get("crtrYr")
            }
        values = list(value.values()) if isinstance(value, dict) else [value]
        valid_shape = all(
            isinstance(candidate, str)
            and re.fullmatch(r"\d{4}(?:-(?:0[1-9]|1[0-2]))?", candidate)
            for candidate in values
        )
        years_known = valid_shape and all(str(candidate)[:4] in known_years for candidate in values)
        status = "metadata_snapshot_partial" if years_known else "metadata_value_unverified"
        message = ref.get("note") or "부분 snapshot으로만 검증했다."
        return MetadataValidation(
            effective={item.semantic_key: value},
            bindings={
                item.semantic_key: MetadataBinding(
                    canonical_value=value,
                    display_label=str(value),
                    external_value=value if years_known else None,
                    values_ref=item.values_ref or "",
                    snapshot_id=self.snapshot_id,
                    status="unverified",
                )
            },
            issues=[self._issue(status, page, item, value, message)],
        )

    def _resolve_map_dependency(
        self,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        ref: Mapping[str, Any],
        effective: Mapping[str, Any],
        bindings: Mapping[str, MetadataBinding],
    ) -> MetadataValidation:
        mineral_binding = bindings.get("mineral")
        mineral_code = mineral_binding.external_value if mineral_binding else None
        flow = effective.get("material_flow")
        context_key = f"{mineral_code}|{flow}" if mineral_code and flow else None
        options = ref.get("contexts", {}).get(context_key) if context_key else None
        if options is None:
            return MetadataValidation(
                effective={item.semantic_key: value},
                issues=[
                    self._issue(
                        "metadata_value_unverified",
                        page,
                        item,
                        value,
                        ref.get("note") or "이 상위 필터 조합은 snapshot에 없다.",
                    )
                ],
            )
        matches = self._match(value, options)
        if len(matches) != 1:
            return self._unmatched(page, item, value, matches)
        option = matches[0]
        binding = self._binding(
            item,
            option["value"],
            option["label"],
            option["external_value"],
            parent_external_values={"mineral": mineral_code, "material_flow": flow},
        )
        return MetadataValidation(
            effective={item.semantic_key: option["value"]},
            bindings={item.semantic_key: binding},
            issues=[
                self._issue(
                    "metadata_snapshot_partial",
                    page,
                    item,
                    value,
                    ref.get("note") or "부분 snapshot에서 확인했다.",
                )
            ],
        )

    def _resolve_price_criterion(
        self,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        ref: Mapping[str, Any],
        effective: Mapping[str, Any],
        bindings: Mapping[str, MetadataBinding],
    ) -> MetadataValidation:
        mineral_key = (
            "compare_mineral" if item.semantic_key.startswith("compare_") else "mineral"
        )
        mineral = bindings.get(mineral_key)
        mineral_code = mineral.external_value if mineral else None
        rows = (
            ref.get("pages", {})
            .get(page.page_id, {})
            .get("by_mineral", {})
            .get(str(mineral_code), [])
        )
        candidates = [
            row
            for row in rows
            if _normalized(value)
            in {_normalized(row["criterion"]), _normalized(row["external_value"])}
        ]
        specification_key = (
            "compare_specification"
            if item.semantic_key.startswith("compare_")
            else "specification"
        )
        specification = effective.get(specification_key)
        if specification and specification not in SYMBOLIC_FILTER_VALUES:
            narrowed = [
                row
                for row in candidates
                if row.get("specification") is not None
                and _normalized(row["specification"]) == _normalized(specification)
            ]
            if narrowed:
                candidates = narrowed
        if len(candidates) != 1:
            return self._unmatched(page, item, value, candidates)
        row = candidates[0]
        binding = self._binding(
            item,
            row["criterion"],
            row["criterion"],
            row["external_value"],
            parent_external_values={"mineral": mineral_code},
        )
        return MetadataValidation(
            effective={item.semantic_key: row["criterion"]},
            bindings={item.semantic_key: binding},
        )

    def _resolve_price_specification(
        self,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        effective: Mapping[str, Any],
        bindings: Mapping[str, MetadataBinding],
    ) -> MetadataValidation:
        criterion_key = (
            "compare_price_criterion"
            if item.semantic_key.startswith("compare_")
            else "price_criterion"
        )
        criterion = bindings.get(criterion_key)
        if criterion is None:
            return MetadataValidation(
                effective={item.semantic_key: value},
                issues=[
                    self._issue(
                        "metadata_parent_unresolved",
                        page,
                        item,
                        value,
                        "가격기준이 확정되지 않아 규격을 검증하지 못했다.",
                    )
                ],
            )
        criterion_ref = self._refs["metadata.prices.price_criteria"]
        rows = (
            criterion_ref.get("pages", {})
            .get(page.page_id, {})
            .get("by_mineral", {})
            .get(str(criterion.parent_external_values.get("mineral")), [])
        )
        matches = [
            row
            for row in rows
            if row["external_value"] == criterion.external_value
            and row.get("specification") is not None
            and _normalized(row["specification"]) == _normalized(value)
        ]
        if len(matches) != 1:
            return self._unmatched(page, item, value, matches)
        row = matches[0]
        binding = self._binding(
            item,
            row["specification"],
            row["specification"],
            row["external_value"],
            parent_external_values={"price_criterion": criterion.external_value},
        )
        return MetadataValidation(
            effective={item.semantic_key: row["specification"]},
            bindings={item.semantic_key: binding},
        )

    def _country_fallback(self, item: PageFilter, value: Any) -> MetadataBinding | None:
        if item.values_ref != "metadata.maps.mineral_map_countries":
            return None
        ref = self._refs["metadata.information.all_countries"]
        matches = self._match(value, ref.get("options", []))
        if len(matches) != 1:
            return None
        option = matches[0]
        return MetadataBinding(
            canonical_value=option["value"],
            display_label=option["label"],
            external_value=option["external_value"],
            values_ref=item.values_ref,
            snapshot_id=self.snapshot_id,
            status="unverified",
        )

    @staticmethod
    def _match(value: Any, options: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        needle = _normalized(value)
        matches = []
        seen: set[tuple[str, str]] = set()
        for option in options:
            tokens = [
                option.get("value"),
                option.get("label"),
                option.get("external_value"),
                *option.get("aliases", []),
            ]
            if needle not in {_normalized(token) for token in tokens if token is not None}:
                continue
            identity = (str(option.get("external_value")), str(option.get("value")))
            if identity not in seen:
                seen.add(identity)
                matches.append(option)
        return matches

    def _binding(
        self,
        item: PageFilter,
        canonical_value: Any,
        display_label: str,
        external_value: Any,
        *,
        parent_external_values: dict[str, Any] | None = None,
    ) -> MetadataBinding:
        return MetadataBinding(
            canonical_value=canonical_value,
            display_label=display_label,
            external_value=external_value,
            values_ref=item.values_ref or "",
            snapshot_id=self.snapshot_id,
            parent_external_values=parent_external_values or {},
        )

    def _unmatched(
        self,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        candidates: list[Mapping[str, Any]],
    ) -> MetadataValidation:
        code = "metadata_value_ambiguous" if len(candidates) > 1 else "metadata_value_not_found"
        message = (
            "여러 메타데이터 값이 일치해 하나로 확정할 수 없다."
            if len(candidates) > 1
            else "페이지의 지원 메타데이터에서 값을 찾지 못했다."
        )
        return MetadataValidation(
            effective={},
            issues=[
                self._issue(
                    code,
                    page,
                    item,
                    value,
                    message,
                    candidates=tuple(_candidate_payload(candidate) for candidate in candidates),
                )
            ],
        )

    @staticmethod
    def _issue(
        code: str,
        page: PageDefinition,
        item: PageFilter,
        value: Any,
        message: str,
        *,
        candidates: tuple[dict[str, Any], ...] = (),
    ) -> MetadataIssue:
        return MetadataIssue(
            code=code,  # type: ignore[arg-type]
            page_id=page.page_id,
            filter_key=item.semantic_key,
            values_ref=item.values_ref or "",
            value=value,
            message=message,
            candidates=candidates,
        )
