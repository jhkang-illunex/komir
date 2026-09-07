"""페이지 정의·추천응답 pydantic 계약(43개 KOMIS 페이지 YAML의 스키마).

이식 출처: komis-report-generator-main `search/models.py`(2026-08-11 스냅샷) — 무수정.
주의: `Field(exclude_if=...)`는 pydantic 2.12+ 전용이라 rag_chat requirements.txt의
pydantic 하한을 >=2.12로 올렸다(로컬 실측 2.12.3에서 동작 확인)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared contract fields."""

    model_config = ConfigDict(extra="forbid")


SYMBOLIC_FILTER_VALUES = {"all", "latest", "site_default"}


def _normalized_filter_token(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value))
    return " ".join(normalized.strip().split()).casefold()


def _parse_declared_absolute_temporal(value: str, granularity: str) -> date:
    patterns = {
        "day": r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])",
        "month": r"\d{4}-(?:0[1-9]|1[0-2])",
        "year": r"\d{4}",
    }
    if re.fullmatch(patterns[granularity], value) is None:
        raise ValueError
    if granularity == "year":
        return date(int(value), 1, 1)
    if granularity == "month":
        return date.fromisoformat(f"{value}-01")
    return date.fromisoformat(value)


def _declared_temporal_granularities(item: PageFilter) -> set[str]:
    if item.temporal is None:
        return {"day"}
    return {item.temporal.granularity, *item.temporal.granularity_map.values()}


def _validate_declared_filter_default(item: PageFilter, value: Any) -> None:
    if value is None:
        return
    if item.type == "enum":
        if not item.options and not (
            isinstance(value, str) and value in SYMBOLIC_FILTER_VALUES
        ):
            raise ValueError("dynamic enum defaults must use a declared symbolic value")
        if item.options:
            item.canonicalize(value)
        return
    if isinstance(value, str) and value in SYMBOLIC_FILTER_VALUES:
        return
    if item.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("integer defaults must be integers")
        if item.options and value not in {option.value for option in item.options}:
            raise ValueError("integer default is not one of the filter options")
        return
    if item.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("boolean defaults must be booleans")
        return
    if item.type in {"mineral", "country", "text"}:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{item.type} defaults must be non-empty strings")
        return
    if item.type in {"date", "date_range"} and isinstance(value, dict):
        if set(value) == {"kind", "count", "unit"}:
            expected_kind = "offset" if item.type == "date" else "trailing"
            count = value.get("count")
            if value.get("kind") != expected_kind:
                raise ValueError(f"{item.type} relative defaults require kind={expected_kind}")
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 1000:
                raise ValueError("relative default count must be an integer from 0 to 1000")
            if expected_kind == "trailing" and count == 0:
                raise ValueError("trailing relative defaults require a positive count")
            if value.get("unit") not in {"day", "week", "month", "year"}:
                raise ValueError("relative default unit must be day, week, month, or year")
            return
        if (
            item.type == "date_range"
            and set(value) == {"start", "end"}
            and all(isinstance(value[key], str) and value[key].strip() for key in value)
        ):
            for granularity in _declared_temporal_granularities(item):
                try:
                    start = _parse_declared_absolute_temporal(value["start"], granularity)
                    end = _parse_declared_absolute_temporal(value["end"], granularity)
                except ValueError:
                    continue
                if start <= end:
                    return
        raise ValueError(f"invalid {item.type} default object")
    if item.type in {"date", "date_range"} and isinstance(value, str):
        for granularity in _declared_temporal_granularities(item):
            try:
                _parse_declared_absolute_temporal(value, granularity)
            except ValueError:
                continue
            return
    raise ValueError(f"invalid default for {item.type} filter")


class FilterOption(StrictModel):
    """Canonical filter value with a display label and accepted aliases."""

    value: str | int | bool
    label: str
    aliases: list[str] = Field(default_factory=list)


class TemporalFilterSpec(StrictModel):
    """Granularity and bounded-overflow policy for a temporal filter."""

    granularity: Literal["day", "month", "year"]
    granularity_filter: str | None = None
    granularity_map: dict[str, Literal["day", "month", "year"]] = Field(
        default_factory=dict
    )
    max_year_offset: int | None = Field(
        default=None,
        ge=-100,
        le=100,
        exclude_if=lambda value: value is None,
    )
    overflow_policy: Literal["reject", "clamp_and_disclose"] = Field(
        default="reject",
        exclude_if=lambda value: value == "reject",
    )

    @model_validator(mode="after")
    def validate_dynamic_granularity(self) -> TemporalFilterSpec:
        if bool(self.granularity_filter) != bool(self.granularity_map):
            raise ValueError("granularity_filter and granularity_map must be configured together")
        has_maximum = self.max_year_offset is not None
        should_clamp = self.overflow_policy == "clamp_and_disclose"
        if has_maximum != should_clamp:
            raise ValueError(
                "max_year_offset and overflow_policy=clamp_and_disclose must be configured together"
            )
        granularities = {self.granularity, *self.granularity_map.values()}
        if has_maximum and granularities != {"year"}:
            raise ValueError("max_year_offset is only valid for year-granularity filters")
        return self


class PageFilter(StrictModel):
    """Validated filter contract exposed by a registered page."""

    id: str
    semantic_key: str
    label: str
    type: Literal[
        "enum",
        "mineral",
        "country",
        "date",
        "date_range",
        "text",
        "integer",
        "boolean",
    ]
    required: bool = False
    default: Any | None = None
    default_label: str | None = None
    options: list[FilterOption] = Field(default_factory=list)
    values_ref: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    applies_when: dict[str, list[str | int | bool]] = Field(default_factory=dict)
    temporal: TemporalFilterSpec | None = None

    @model_validator(mode="after")
    def validate_enum_options(self) -> PageFilter:
        if self.type == "enum" and not self.options and not self.values_ref:
            raise ValueError("enum filters require options or values_ref")
        if self.temporal is not None and self.type not in {"date", "date_range"}:
            raise ValueError("temporal metadata is only valid for date filters")
        if self.default is not None:
            try:
                _validate_declared_filter_default(self, self.default)
            except ValueError as exc:
                raise ValueError(f"invalid filter default for {self.id}: {exc}") from exc
        return self

    def canonicalize(self, value: Any) -> Any:
        if value is None or self.type != "enum":
            return value
        if not isinstance(value, (str, int, bool)):
            raise ValueError("enum values must be a string, integer, or boolean")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("enum values must not be empty")
        if not self.options and self.values_ref:
            return value
        normalized = str(value).strip().casefold()
        for option in self.options:
            candidates = [str(option.value), option.label, *option.aliases]
            if normalized in {candidate.strip().casefold() for candidate in candidates}:
                return option.value
        allowed = ", ".join(str(option.value) for option in self.options)
        raise ValueError(f"unsupported value for {self.id}; allowed values: {allowed}")


class Navigation(StrictModel):
    """HTTP navigation target and fixed parameters for a page."""

    method: Literal["GET", "POST"]
    target: str
    params: dict[str, str] = Field(default_factory=dict)


class ScreenControl(StrictModel):
    """Observed screen widget that supplies one or more semantic filters."""

    id: str
    label: str
    description: str
    widget: Literal["radio", "select", "text_search"]
    role: Literal["direct", "shortcut", "lookup"]
    native_name: str | None = None
    target_filters: list[str] = Field(min_length=1)
    transform: Literal[
        "identity",
        "relative_date_range",
        "lookup_selection",
        "split_mineral_variant",
    ] = "identity"
    options: list[FilterOption] = Field(default_factory=list)
    values_ref: str | None = None
    observed_default: Any | None = None


class PageScreen(StrictModel):
    """Observed controls and inference policy for a page screen."""

    infer_unlisted_query_filters: bool = True
    controls: list[ScreenControl] = Field(default_factory=list)


class PageIdentity(StrictModel):
    """Human identity, navigation, and access traits of a page."""

    section: str
    name: str
    page_kind: Literal["board", "data", "info", "external", "account"]
    navigation: Navigation
    login_required: bool
    external: bool


class PageDistinction(StrictModel):
    """Reason a similar page should be distinguished during routing."""

    page_id: str
    reason: str


class PageRouting(StrictModel):
    """Examples and decision guidance used to route questions to a page."""

    summary: str
    use_when: list[str]
    do_not_use_when: list[str]
    distinguish_from: list[PageDistinction] = Field(default_factory=list)
    example_queries: list[str]
    keywords: list[str] = Field(default_factory=list)


class MachineDataField(StrictModel):
    """Canonical field metadata for a future DB/data-tool result."""

    id: str
    label: str
    role: Literal["dimension", "measure", "status", "metadata"]
    data_type: Literal["string", "integer", "number", "boolean", "date", "datetime"]
    unit: str | None = None
    unit_ref: str | None = None
    grain: str | None = None
    nullable: bool = True
    missing_semantics: Literal["null_is_missing", "empty_is_missing", "zero_is_value"] = (
        "null_is_missing"
    )
    source_field: str | None = None
    panel_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unit_source(self) -> MachineDataField:
        if self.unit and self.unit_ref:
            raise ValueError("machine fields must use either unit or unit_ref, not both")
        return self


class MachineDataContract(StrictModel):
    """Optional contract populated only after a data source has been verified."""

    status: Literal["draft", "verified"]
    fields: list[MachineDataField] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_verified_contract(self) -> MachineDataContract:
        if self.status == "verified" and not self.fields:
            raise ValueError("verified machine data contracts require at least one field")
        field_ids = [item.id for item in self.fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("machine data field IDs must be unique within a page")
        return self


class PageOutputs(StrictModel):
    """Human-facing outputs and optional verified machine data contract."""

    # These are human-facing descriptions, not DB columns or Tool result field names.
    available_data_labels: list[str] = Field(min_length=1)
    machine_contract: MachineDataContract | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class PresentationPanel(StrictModel):
    """Human-readable description of one visible page panel."""

    type: str
    label: str
    description: str


class MachineAxisBinding(StrictModel):
    """Canonical field and unit binding for a presentation axis."""

    id: str
    field: str | None = None
    granularity: Literal["day", "week", "month", "quarter", "year"] | None = None
    unit: str | None = None
    unit_ref: str | None = None

    @model_validator(mode="after")
    def validate_unit_source(self) -> MachineAxisBinding:
        if self.unit and self.unit_ref:
            raise ValueError("machine axes must use either unit or unit_ref, not both")
        return self


class MachineSeriesBinding(StrictModel):
    """Canonical data-series binding for a machine presentation panel."""

    field: str
    label: str
    mark: str
    axis: str | None = None
    semantic_role: str
    stacked: bool = False
    line_style: str | None = None


class MachineMapBinding(StrictModel):
    """Location and magnitude fields required to render a map."""

    origin_field: str | None = None
    destination_field: str | None = None
    area_field: str | None = None
    magnitude_field: str
    direction: Literal["origin_to_destination", "destination_to_origin", "none"]

    @model_validator(mode="after")
    def validate_location_fields(self) -> MachineMapBinding:
        if self.direction == "none" and self.area_field is None:
            raise ValueError("non-directional maps require an area_field")
        if self.direction != "none" and (
            self.origin_field is None or self.destination_field is None
        ):
            raise ValueError("directional maps require origin_field and destination_field")
        return self


class MachinePresentationPanel(StrictModel):
    """Machine-readable fields and axes for one presentation panel."""

    id: str
    title: str
    visual_type: str
    x_axis: MachineAxisBinding | None = None
    y_axes: list[MachineAxisBinding] = Field(default_factory=list)
    series: list[MachineSeriesBinding] = Field(default_factory=list)
    map_binding: MachineMapBinding | None = None
    human_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_axis_references(self) -> MachinePresentationPanel:
        if self.x_axis is not None and self.x_axis.field is None:
            raise ValueError("machine presentation x axes require a field")
        axis_ids = [axis.id for axis in self.y_axes]
        if self.x_axis is not None:
            axis_ids.append(self.x_axis.id)
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("machine presentation axis IDs must be unique within a panel")
        y_axis_ids = {axis.id for axis in self.y_axes}
        unknown_axes = {
            series.axis
            for series in self.series
            if series.axis is not None and series.axis not in y_axis_ids
        }
        if unknown_axes:
            raise ValueError(
                f"machine presentation series reference unknown axes: {sorted(unknown_axes)}"
            )
        if len(self.y_axes) > 1 and any(series.axis is None for series in self.series):
            raise ValueError("series in multi-axis panels must identify their y axis")
        return self


class MachinePresentationTemplate(StrictModel):
    """Static bindings; availability status is supplied by each runtime Tool result."""

    status: Literal["draft", "verified"]
    panels: list[MachinePresentationPanel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_panel_ids(self) -> MachinePresentationTemplate:
        if self.status == "verified" and not self.panels:
            raise ValueError("verified machine presentation templates require at least one panel")
        panel_ids = [item.id for item in self.panels]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("machine presentation panel IDs must be unique within a page")
        if self.status == "verified":
            empty_panels = [
                item.id
                for item in self.panels
                if not (item.x_axis or item.y_axes or item.series or item.map_binding)
            ]
            if empty_panels:
                raise ValueError(
                    f"verified machine presentation panels require data bindings: {empty_panels}"
                )
        return self


class PagePresentation(StrictModel):
    """Human presentation summary plus optional machine template."""

    summary: str
    panels: list[PresentationPanel] = Field(default_factory=list)
    machine_template: MachinePresentationTemplate | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class PolicyDefault(StrictModel):
    """Page-policy default value and optional user-facing label."""

    value: Any
    label: str | None = None


class PagePolicies(StrictModel):
    """Recommendation, mutation, caveat, and default policies for a page."""

    recommendation_only: bool = True
    mutation: Literal["read_only", "account_change"] = "read_only"
    caveats: list[str] = Field(default_factory=list)
    filter_defaults: dict[str, PolicyDefault] = Field(
        default_factory=dict,
        exclude_if=lambda value: not value,
    )


class ToolPlan(StrictModel):
    """Whether a future executable tool is planned for a page."""

    status: Literal["planned", "none"]
    planned_name: str | None = None

    @model_validator(mode="after")
    def validate_planned_name(self) -> ToolPlan:
        if self.status == "planned" and not self.planned_name:
            raise ValueError("planned tools require planned_name")
        return self


class PageProvenance(StrictModel):
    """Observation time and sources supporting a page definition."""

    observed_at: str
    sources: list[str]


class PageDefinition(StrictModel):
    """Complete validated registry contract for one KOMIS page."""

    schema_version: Literal[1]
    page_id: str
    aliases: list[str] = Field(default_factory=list)
    identity: PageIdentity
    screen: PageScreen | None = Field(default=None, exclude_if=lambda value: value is None)
    routing: PageRouting
    filters: list[PageFilter] = Field(default_factory=list)
    outputs: PageOutputs
    presentation: PagePresentation
    policies: PagePolicies
    tool: ToolPlan
    provenance: PageProvenance

    @field_validator("page_id")
    @classmethod
    def validate_page_id(cls, value: str) -> str:
        if not value or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value
        ):
            raise ValueError("page_id must use lowercase ASCII letters, digits, and underscores")
        return value

    @model_validator(mode="after")
    def validate_unique_filter_ids(self) -> PageDefinition:
        filter_ids = [item.id for item in self.filters]
        if len(filter_ids) != len(set(filter_ids)):
            raise ValueError("filter IDs must be unique within a page")
        semantic_keys = [item.semantic_key for item in self.filters]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("filter semantic keys must be unique within a page")
        known_ids = set(filter_ids)
        known_semantic_keys = set(semantic_keys)
        for item in self.filters:
            temporal_parent = (
                {item.temporal.granularity_filter}
                if item.temporal and item.temporal.granularity_filter
                else set()
            )
            missing = (
                set(item.depends_on) | set(item.applies_when) | temporal_parent
            ) - known_ids
            if missing:
                raise ValueError(
                    f"filter {item.id} references unknown parent filters: {sorted(missing)}"
                )
            empty_conditions = [key for key, values in item.applies_when.items() if not values]
            if empty_conditions:
                raise ValueError(
                    f"filter {item.id} has empty applicability values: {empty_conditions}"
                )
        unknown_policy_defaults = set(self.policies.filter_defaults) - known_semantic_keys
        if unknown_policy_defaults:
            raise ValueError(
                f"policy defaults reference unknown filters: {sorted(unknown_policy_defaults)}"
            )
        for semantic_key, policy_default in self.policies.filter_defaults.items():
            item = self.filter_by_semantic_key(semantic_key)
            if item is None:
                continue
            try:
                _validate_declared_filter_default(item, policy_default.value)
            except ValueError as exc:
                raise ValueError(
                    f"invalid policy default for {semantic_key}: {exc}"
                ) from exc
        if self.screen:
            control_ids = [control.id for control in self.screen.controls]
            if len(control_ids) != len(set(control_ids)):
                raise ValueError("screen control IDs must be unique within a page")
            for control in self.screen.controls:
                unknown_targets = set(control.target_filters) - known_semantic_keys
                if unknown_targets:
                    raise ValueError(
                        f"screen control {control.id} targets unknown filters: "
                        f"{sorted(unknown_targets)}"
                    )
        self._validate_machine_contract_references()
        return self

    def _validate_machine_contract_references(self) -> None:
        data_contract = self.outputs.machine_contract
        presentation_template = self.presentation.machine_template
        if presentation_template is None:
            if data_contract is not None and any(item.panel_ids for item in data_contract.fields):
                raise ValueError("machine data fields with panel_ids require a machine template")
            return
        if presentation_template.panels and data_contract is None:
            raise ValueError("machine presentation panels require a machine data contract")
        if (
            presentation_template.status == "verified"
            and data_contract is not None
            and data_contract.status != "verified"
        ):
            raise ValueError("verified machine templates require a verified data contract")

        field_ids = {item.id for item in data_contract.fields} if data_contract else set()
        panel_ids = {item.id for item in presentation_template.panels}
        if data_contract:
            unknown_panels = {
                panel_id
                for item in data_contract.fields
                for panel_id in item.panel_ids
                if panel_id not in panel_ids
            }
            if unknown_panels:
                raise ValueError(
                    f"machine data fields reference unknown panels: {sorted(unknown_panels)}"
                )

        for panel in presentation_template.panels:
            referenced_fields = {
                *(series.field for series in panel.series),
                *(axis.field for axis in panel.y_axes if axis.field is not None),
            }
            if panel.x_axis and panel.x_axis.field:
                referenced_fields.add(panel.x_axis.field)
            if panel.map_binding:
                referenced_fields.update(
                    field
                    for field in (
                        panel.map_binding.origin_field,
                        panel.map_binding.destination_field,
                        panel.map_binding.area_field,
                        panel.map_binding.magnitude_field,
                    )
                    if field is not None
                )
            unknown_fields = referenced_fields - field_ids
            if unknown_fields:
                raise ValueError(
                    f"machine presentation panel {panel.id} references unknown fields: "
                    f"{sorted(unknown_fields)}"
                )

    def filter_by_id(self, filter_id: str) -> PageFilter | None:
        return next((item for item in self.filters if item.id == filter_id), None)

    def filter_by_semantic_key(self, semantic_key: str) -> PageFilter | None:
        return next((item for item in self.filters if item.semantic_key == semantic_key), None)

    def canonical_symbolic_filter_value(
        self,
        item: PageFilter,
        value: Any,
    ) -> tuple[str, str] | None:
        """Resolve only symbolic values explicitly declared for this page filter."""

        if not isinstance(value, str):
            return None
        candidates: list[tuple[str, str, list[str]]] = []

        def add(candidate: Any, label: str | None, aliases: list[str] | None = None) -> None:
            if isinstance(candidate, str) and candidate in SYMBOLIC_FILTER_VALUES:
                candidates.append((candidate, label or candidate, aliases or []))

        add(item.default, item.default_label)
        policy_default = self.policies.filter_defaults.get(item.semantic_key)
        if policy_default is not None:
            add(policy_default.value, policy_default.label)
        for option in item.options:
            add(option.value, option.label, option.aliases)
        if self.screen:
            for control in self.screen.controls:
                if item.semantic_key not in control.target_filters:
                    continue
                for option in control.options:
                    add(option.value, option.label, option.aliases)

        needle = _normalized_filter_token(value)
        for canonical, label, aliases in candidates:
            tokens = [canonical, label, *aliases]
            if needle in {_normalized_filter_token(token) for token in tokens}:
                return canonical, label
        return None

    def routing_index_entry(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "section": self.identity.section,
            "name": self.identity.name,
            "summary": self.routing.summary,
            "use_when": self.routing.use_when,
            "do_not_use_when": self.routing.do_not_use_when,
            "distinguish_from": [
                item.model_dump(mode="json") for item in self.routing.distinguish_from
            ],
            "example_queries": self.routing.example_queries,
            "filter_ids": [item.semantic_key for item in self.filters],
            "keywords": self.routing.keywords,
        }


RelationType = Literal["same_task", "related_new_page", "new_task", "ambiguous"]


class RelationDecision(StrictModel):
    """LLM decision relating the current question to prior context."""

    relation: RelationType


class CandidateDiscovery(StrictModel):
    """Bounded set of page IDs discovered for a question."""

    candidate_page_ids: list[str] = Field(max_length=3)

    @field_validator("candidate_page_ids")
    @classmethod
    def validate_unique_candidates(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("candidate_page_ids must not contain duplicates")
        return value


class PageSelection(StrictModel):
    """Selected canonical page ID, or ``None`` when no page is chosen."""

    page_id: str | None


class FilterExtraction(StrictModel):
    """Semantic filter values extracted from a user question."""

    filter_values: dict[str, Any] = Field(default_factory=dict)


class FilterDisplay(StrictModel):
    """Canonical and user-facing forms of one effective filter."""

    key: str
    label: str
    value: Any
    display_value: str
    defaulted: bool


class RecommendationItem(StrictModel):
    """Display-ready page recommendation with filters and caveats."""

    page_id: str
    page_name: str
    section: str
    url: str
    navigation_method: Literal["GET", "POST"]
    navigation_params: dict[str, str] = Field(default_factory=dict)
    reason: str
    suggested_filters: dict[str, Any] = Field(default_factory=dict)
    defaulted_filters: dict[str, Any] = Field(default_factory=dict)
    filter_display: list[FilterDisplay] = Field(default_factory=list)
    missing_required_filters: list[str] = Field(default_factory=list)
    missing_required_filter_labels: list[str] = Field(default_factory=list)
    available_data: list[str] = Field(default_factory=list)
    presentation_summary: str
    presentation: list[PresentationPanel] = Field(default_factory=list)
    screen_guidance: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    login_required: bool
    external: bool
    mutation: Literal["read_only", "account_change"]


class DataBlock(StrictModel):
    """Structured table data returned with the final chatbot answer."""

    type: Literal["table"] = "table"
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]


class EvidenceReference(StrictModel):
    """User-visible provenance without internal file or storage references."""

    source_type: Literal["komis", "komis_linked_external", "external"]
    provider: str
    title: str
    edition: str | None = None
    as_of: str | None = None
    document_locator: str | None = None
    url: HttpUrl | None = None


class SearchResponse(StrictModel):
    """Final conversational recommendation response returned by the service."""

    thread_id: str
    status: Literal["recommended", "ambiguous", "not_found", "needs_filter"]
    relation: RelationType | Literal["first_turn"]
    answer: str
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_blocks: list[DataBlock] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
