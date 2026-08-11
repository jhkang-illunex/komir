"""페이지 추천 대화를 진행하는 LangGraph 상태그래프.

이식 출처: komis-report-generator-main `search/graph.py`(2026-08-11 스냅샷).
노드·엣지·라우팅 로직은 원본 그대로이고, komir 이식에서 바꾼 것은 두 가지뿐이다.

1. LLM 클라이언트: 원본의 `JsonLLM` Protocol(=httpx 기반 OpenAICompatibleJsonLLM)
   자리에 `services/shared/llm_client.KomirJsonLLM`을 그대로 끼웠다(같은 invoke
   시그니처). 프로젝트에 LLM 클라이언트를 2벌 두지 않기 위함.
2. 전송오류 분기 제거: 원본은 `except LLMTransportError: raise`로 전송실패를
   먼저 재던지고 그 아래 `except LLMError`에서 출력오류만 흡수했다. komir의
   OpenAICompatChat은 전송실패 시 `requests.RequestException`/`RuntimeError`를
   던지는데 이들은 LLMError 계열이 아니라 어차피 그대로 전파된다 — 즉
   `except LLMError`만 남겨도 동작이 동일하다(중복 분기라서 뺀 것이지, 전송오류를
   흡수하도록 바꾼 게 아님. 나중에 "빠졌네" 하고 되돌리지 말 것).

체크포인터(대화상태 저장)는 이 파일이 아니라 service.py 주석 참고 — komir는
SQLite 체크포인터를 쓰지 않는다."""

from __future__ import annotations

from datetime import date
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from .filters import (
    FilterResolutionError,
    filter_definitions_for_prompt,
    inherit_compatible_filters,
    resolve_filters,
)
from shared.llm_client import KomirJsonLLM, LLMError
from .metadata import MetadataResolver
from .models import (
    CandidateDiscovery,
    FilterExtraction,
    PageSelection,
    RelationDecision,
    SearchResponse,
)
from .prompts import (
    CANDIDATE_DISCOVERY_PROMPT,
    FILTER_EXTRACTION_PROMPT,
    PAGE_SELECTION_PROMPT,
    RELATION_PROMPT,
)
from .registry import ServiceRegistry
from .renderer import (
    build_recommendation,
    render_ambiguous,
    render_not_found,
    render_relation_ambiguous,
    render_selected,
)


class SearchState(TypedDict, total=False):
    """Checkpointed state exchanged between search workflow nodes."""

    current_question: str
    request_context: dict[str, str]
    message_history: list[dict[str, str]]
    execution_history: list[dict[str, Any]]
    active_artifact: dict[str, Any] | None
    relation: str
    inherited_filters: dict[str, Any]
    excluded_page_ids: list[str]
    candidate_page_ids: list[str]
    selected_page_id: str | None
    ambiguous_page_ids: list[str]
    extracted_filters: dict[str, Any]
    effective_filters: dict[str, Any]
    defaulted_filters: dict[str, Any]
    missing_required_filters: list[str]
    changed_filter_ids: list[str]
    answer: str
    response: dict[str, Any]
    turn_trace: list[dict[str, Any]]
    warnings: list[str]
    temporal_resolutions: dict[str, dict[str, Any]]
    metadata_bindings: dict[str, dict[str, Any]]
    metadata_issues: list[dict[str, Any]]


def _trace(state: SearchState, node: str, **data: Any) -> list[dict[str, Any]]:
    return [*state.get("turn_trace", []), {"node": node, **data}]


class SearchWorkflow:
    """Compile and execute the conversational page-selection state graph."""

    def __init__(
        self,
        registry: ServiceRegistry,
        llm: KomirJsonLLM,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        metadata_resolver: MetadataResolver | None = None,
    ) -> None:
        self.registry = registry
        self.llm = llm
        self.metadata_resolver = metadata_resolver
        self.graph = self._build().compile(checkpointer=checkpointer, name="komis-page-search")

    @staticmethod
    def _error_record(error: LLMError) -> list[dict[str, Any]]:
        return [error.record] if error.record is not None else []

    @staticmethod
    def _append_warning_notice(answer: str, warnings: list[str]) -> str:
        notices = []
        if "candidate_discovery_lexical_fallback" in warnings:
            notices.append("후보 탐색 결과를 읽지 못해 키워드 기반 후보를 사용했습니다.")
        if "candidate_discovery_invalid_page_ids" in warnings:
            notices.append("후보 결과에 알 수 없는 페이지가 있어 해당 항목을 제외했습니다.")
        if "page_selection_invalid_output" in warnings:
            notices.append("페이지를 하나로 확정하지 못해 관련 후보를 함께 안내했습니다.")
        if "filter_extraction_invalid_output" in warnings:
            notices.append("질문의 필터를 읽지 못해 페이지 기본값만 적용했습니다.")
        if "relation_invalid_output" in warnings:
            notices.append("이전 검색과의 관계를 확정하지 못해 기존 검색 상태를 유지했습니다.")
        if "some_filter_values_were_ignored" in warnings:
            notices.append("지원되지 않거나 해석할 수 없는 일부 필터값은 적용하지 않았습니다.")
        if "some_filter_values_were_unverified" in warnings:
            notices.append(
                "일부 동적 필터값은 현재 메타데이터 스냅샷으로 완전히 검증할 수 없습니다."
            )
        if "requested_period_outside_available_range" in warnings:
            notices.append(
                "요청 기간이 페이지의 확인된 제공 범위를 벗어나 기간 조건은 적용하지 않았습니다."
            )
        if notices:
            return f"{answer}\n주의: {' '.join(notices)}"
        return answer

    @staticmethod
    def _append_temporal_adjustment_notice(
        answer: str,
        temporal_resolutions: dict[str, dict[str, Any]],
    ) -> str:
        notices: list[str] = []
        for resolution in temporal_resolutions.values():
            for adjustment in resolution.get("adjustments", []):
                if adjustment.get("code") != "capped_to_previous_year":
                    continue
                requested = adjustment.get("requested")
                requested_end = requested.get("end") if isinstance(requested, dict) else requested
                maximum_year = adjustment["maximum_year"]
                notice = (
                    f"연 단위 자료는 현재연도 값이 아직 확정되지 않은 것으로 보아, "
                    f"요청한 상한 {requested_end}년을 현재연도-1인 {maximum_year}년으로 "
                    "조정했습니다."
                )
                if notice not in notices:
                    notices.append(notice)
        if notices:
            return f"{answer}\n적용 조정: {' '.join(notices)}"
        return answer

    def _build(self) -> StateGraph[SearchState]:
        """Register workflow nodes, routes, and terminal edges."""

        builder = StateGraph(SearchState)
        builder.add_node("start_turn", self._start_turn)
        builder.add_node("classify_relation", self._classify_relation)
        builder.add_node("discover_candidates", self._discover_candidates)
        builder.add_node("select_candidate", self._select_candidate)
        builder.add_node("extract_filters", self._extract_filters)
        builder.add_node("finalize_selected", self._finalize_selected)
        builder.add_node("finalize_ambiguous", self._finalize_ambiguous)
        builder.add_node("finalize_not_found", self._finalize_not_found)

        builder.add_edge(START, "start_turn")
        builder.add_conditional_edges(
            "start_turn",
            self._route_after_start,
            {"relation": "classify_relation", "discovery": "discover_candidates"},
        )
        builder.add_conditional_edges(
            "classify_relation",
            self._route_after_relation,
            {
                "same_task": "extract_filters",
                "pending_selection": "select_candidate",
                "discovery": "discover_candidates",
                "ambiguous": "finalize_ambiguous",
            },
        )
        builder.add_conditional_edges(
            "discover_candidates",
            self._route_after_discovery,
            {
                "selected": "extract_filters",
                "selection": "select_candidate",
                "not_found": "finalize_not_found",
            },
        )
        builder.add_conditional_edges(
            "select_candidate",
            self._route_after_selection,
            {"selected": "extract_filters", "ambiguous": "finalize_ambiguous"},
        )
        builder.add_edge("extract_filters", "finalize_selected")
        builder.add_edge("finalize_selected", END)
        builder.add_edge("finalize_ambiguous", END)
        builder.add_edge("finalize_not_found", END)
        return builder

    def _start_turn(self, state: SearchState) -> SearchState:
        """Validate request context and initialize turn-local state."""

        question = state.get("current_question", "").strip()
        if not question:
            raise ValueError("current_question must not be empty")
        request_context = state.get("request_context") or {}
        if not request_context.get("current_date") or not request_context.get("timezone"):
            raise ValueError("request_context must include current_date and timezone")
        active = state.get("active_artifact")
        relation = "pending" if active else "first_turn"
        return {
            "current_question": question,
            "relation": relation,
            "inherited_filters": {},
            "excluded_page_ids": [],
            "candidate_page_ids": [],
            "selected_page_id": None,
            "ambiguous_page_ids": [],
            "extracted_filters": {},
            "effective_filters": {},
            "defaulted_filters": {},
            "missing_required_filters": [],
            "changed_filter_ids": [],
            "answer": "",
            "response": {},
            "warnings": [],
            "temporal_resolutions": {},
            "metadata_bindings": {},
            "metadata_issues": [],
            "turn_trace": [{"node": "start_turn", "has_active_artifact": bool(active)}],
        }

    @staticmethod
    def _route_after_start(state: SearchState) -> str:
        return "relation" if state.get("active_artifact") else "discovery"

    def _classify_relation(self, state: SearchState) -> SearchState:
        """Ask the LLM how the question relates to persisted conversation state."""

        active = state.get("active_artifact") or {}
        page_id = active.get("selected_page_id")
        pending_page_ids = active.get("pending_candidate_page_ids", [])
        if not page_id and not pending_page_ids:
            return {"relation": "new_task", "active_artifact": None}
        history = state.get("message_history", [])
        if page_id:
            page = self.registry.get(page_id)
            active_context = {
                "selected_page_id": page.page_id,
                "name": page.identity.name,
                "summary": page.routing.summary,
                "effective_filters": active.get("effective_filters", {}),
            }
        else:
            active_context = {
                "original_question": active.get("original_question", ""),
                "pending_candidates": self.registry.selection_context(pending_page_ids),
            }
        payload = {
            "request_context": state["request_context"],
            "current_question": state["current_question"],
            "previous_turn": {
                "question": history[-2]["content"] if len(history) >= 2 else "",
                "answer": history[-1]["content"] if history else "",
            },
            "active_page": active_context,
        }
        try:
            invocation = self.llm.invoke(
                task="relation",
                instructions=RELATION_PROMPT,
                payload=payload,
                output_model=RelationDecision,
                max_tokens=32,
            )
            relation = invocation.output.relation
            llm_calls = [invocation.record]
            error = None
        except LLMError as exc:
            relation = "ambiguous"
            llm_calls = self._error_record(exc)
            error = type(exc).__name__

        warnings = list(state.get("warnings", []))
        if error:
            warnings.append("relation_invalid_output")

        update: SearchState = {
            "relation": relation,
            "warnings": warnings,
            "turn_trace": _trace(
                state,
                "classify_relation",
                relation=relation,
                error=error,
                llm_calls=llm_calls,
            ),
        }
        if relation == "same_task":
            if page_id:
                update["selected_page_id"] = page_id
            else:
                update["candidate_page_ids"] = list(pending_page_ids)
                update["inherited_filters"] = dict(active.get("inherited_filters", {}))
        elif relation == "related_new_page":
            active_filters = dict(active.get("effective_filters", {}))
            defaulted_keys = set(active.get("defaulted_filters", {}))
            update["inherited_filters"] = {
                key: value for key, value in active_filters.items() if key not in defaulted_keys
            }
            update["excluded_page_ids"] = [page_id] if page_id else []
        elif relation == "new_task":
            update["inherited_filters"] = {}
            update["excluded_page_ids"] = []
            update["active_artifact"] = None
        elif relation == "ambiguous":
            update["ambiguous_page_ids"] = [page_id] if page_id else list(pending_page_ids)
        return update

    @staticmethod
    def _route_after_relation(state: SearchState) -> str:
        relation = state.get("relation")
        if relation == "same_task":
            return "same_task" if state.get("selected_page_id") else "pending_selection"
        if relation == "ambiguous":
            return "ambiguous"
        return "discovery"

    def _discover_candidates(self, state: SearchState) -> SearchState:
        """Ask the LLM for candidate pages with a lexical fallback."""

        excluded = set(state.get("excluded_page_ids", []))
        payload = {
            "request_context": state["request_context"],
            "question": state["current_question"],
            "context": {
                "prior_page_id": (
                    (state.get("active_artifact") or {}).get("selected_page_id")
                    if state.get("relation") == "related_new_page"
                    else None
                ),
                "inherited_entities": state.get("inherited_filters", {}),
                "excluded_page_ids": sorted(excluded),
            },
            "page_index": self.registry.routing_index(),
        }
        try:
            invocation = self.llm.invoke(
                task="candidate_discovery",
                instructions=CANDIDATE_DISCOVERY_PROMPT,
                payload=payload,
                output_model=CandidateDiscovery,
                max_tokens=64,
            )
            requested = invocation.output.candidate_page_ids
            llm_calls = [invocation.record]
            error = None
        except LLMError as exc:
            requested = self.registry.lexical_candidates(state["current_question"])
            llm_calls = self._error_record(exc)
            error = type(exc).__name__

        warnings = list(state.get("warnings", []))
        if error:
            warnings.append("candidate_discovery_lexical_fallback")

        candidates = []
        invalid_requested: list[str] = []
        for page_id in requested:
            try:
                canonical = self.registry.get(page_id).page_id
            except Exception:
                invalid_requested.append(page_id)
                continue
            if canonical in excluded:
                invalid_requested.append(page_id)
            elif canonical not in candidates:
                candidates.append(canonical)
            if len(candidates) == 3:
                break
        if invalid_requested:
            warnings.append("candidate_discovery_invalid_page_ids")
        if requested and not candidates and error is None:
            candidates = [
                page_id
                for page_id in self.registry.lexical_candidates(state["current_question"])
                if page_id not in excluded
            ]
            warnings.append("candidate_discovery_lexical_fallback")
        selected = candidates[0] if len(candidates) == 1 else None
        return {
            "candidate_page_ids": candidates,
            "selected_page_id": selected,
            "warnings": warnings,
            "turn_trace": _trace(
                state,
                "discover_candidates",
                candidate_page_ids=candidates,
                error=error,
                llm_calls=llm_calls,
            ),
        }

    @staticmethod
    def _route_after_discovery(state: SearchState) -> str:
        count = len(state.get("candidate_page_ids", []))
        if count == 0:
            return "not_found"
        if count == 1:
            return "selected"
        return "selection"

    def _select_candidate(self, state: SearchState) -> SearchState:
        """Ask the LLM to choose only among discovered page candidates."""

        candidates = state.get("candidate_page_ids", [])
        payload = {
            "request_context": state["request_context"],
            "question": state["current_question"],
            "context": {
                "inherited_entities": state.get("inherited_filters", {}),
                "original_question": (state.get("active_artifact") or {}).get("original_question"),
            },
            "candidates": self.registry.selection_context(candidates),
        }
        try:
            invocation = self.llm.invoke(
                task="page_selection",
                instructions=PAGE_SELECTION_PROMPT,
                payload=payload,
                output_model=PageSelection,
                max_tokens=32,
            )
            requested_page_id = invocation.output.page_id
            selected = requested_page_id if requested_page_id in candidates else None
            llm_calls = [invocation.record]
            error = (
                "page_id_outside_candidates"
                if requested_page_id is not None and selected is None
                else None
            )
        except LLMError as exc:
            selected = None
            llm_calls = self._error_record(exc)
            error = type(exc).__name__
        warnings = list(state.get("warnings", []))
        if error:
            warnings.append("page_selection_invalid_output")
        ambiguous = [] if selected else candidates
        return {
            "selected_page_id": selected,
            "ambiguous_page_ids": ambiguous,
            "warnings": warnings,
            "turn_trace": _trace(
                state,
                "select_candidate",
                selected_page_id=selected,
                error=error,
                llm_calls=llm_calls,
            ),
        }

    @staticmethod
    def _route_after_selection(state: SearchState) -> str:
        return "selected" if state.get("selected_page_id") else "ambiguous"

    def _extract_filters(self, state: SearchState) -> SearchState:
        """Extract, inherit, resolve, and validate filters for the selected page."""

        page = self.registry.get(state["selected_page_id"] or "")
        active = state.get("active_artifact") or {}
        pending_original_question = active.get("original_question")
        same_task = state.get("relation") == "same_task" and bool(active.get("selected_page_id"))
        current = dict(active.get("effective_filters", {})) if same_task else {}
        current_defaulted = dict(active.get("defaulted_filters", {})) if same_task else {}
        inherited_source = (
            active.get("inherited_filters", {})
            if pending_original_question
            else state.get("inherited_filters", {})
        )
        inherited = (
            inherit_compatible_filters(inherited_source, page)
            if state.get("relation") == "related_new_page" or pending_original_question
            else {}
        )
        payload = {
            "request_context": state["request_context"],
            "mode": "patch" if same_task else "initial",
            "question": (
                f"원래 질문: {pending_original_question}\n추가 선택: {state['current_question']}"
                if pending_original_question
                else state["current_question"]
            ),
            "page_id": page.page_id,
            "current_filters": current,
            "inherited_filters": inherited,
            "filter_definitions": filter_definitions_for_prompt(page),
        }
        try:
            if page.filters:
                invocation = self.llm.invoke(
                    task="filter_extraction",
                    instructions=FILTER_EXTRACTION_PROMPT,
                    payload=payload,
                    output_model=FilterExtraction,
                    max_tokens=192,
                )
                extracted = invocation.output.filter_values
                llm_calls = [invocation.record]
            else:
                extracted = {}
                llm_calls = []
            extraction_error = None
        except LLMError as exc:
            extracted = {}
            llm_calls = self._error_record(exc)
            extraction_error = type(exc).__name__

        try:
            resolved = resolve_filters(
                page,
                extracted,
                current=current,
                current_defaulted=current_defaulted,
                inherited=inherited,
                as_of=date.fromisoformat(state["request_context"]["current_date"]),
                metadata_resolver=self.metadata_resolver,
            )
            validation_errors = resolved.errors
        except FilterResolutionError as exc:
            resolved = resolve_filters(
                page,
                {},
                current=current,
                current_defaulted=current_defaulted,
                inherited=inherited,
                as_of=date.fromisoformat(state["request_context"]["current_date"]),
                metadata_resolver=self.metadata_resolver,
            )
            validation_errors = [str(exc)]

        warnings = list(state.get("warnings", []))
        if extraction_error:
            warnings.append("filter_extraction_invalid_output")
        if validation_errors:
            warnings.append("some_filter_values_were_ignored")
        metadata_issue_codes = {issue["code"] for issue in resolved.metadata_issues}
        if metadata_issue_codes & {
            "metadata_value_unverified",
            "metadata_parent_unresolved",
            "metadata_snapshot_partial",
        }:
            warnings.append("some_filter_values_were_unverified")
        if "metadata_period_outside_available_range" in metadata_issue_codes:
            warnings.append("requested_period_outside_available_range")
        if any(
            adjustment.get("code") == "capped_to_previous_year"
            for resolution in resolved.temporal_resolutions.values()
            for adjustment in resolution.get("adjustments", [])
        ):
            warnings.append("temporal_period_capped_to_previous_year")

        return {
            "extracted_filters": extracted,
            "effective_filters": resolved.effective,
            "defaulted_filters": resolved.defaulted,
            "missing_required_filters": resolved.missing_required,
            "changed_filter_ids": resolved.changed,
            "temporal_resolutions": resolved.temporal_resolutions,
            "metadata_bindings": resolved.metadata_bindings,
            "metadata_issues": resolved.metadata_issues,
            "warnings": warnings,
            "turn_trace": _trace(
                state,
                "extract_filters",
                extracted_filters=extracted,
                extraction_error=extraction_error,
                validation_errors=validation_errors,
                temporal_resolutions=resolved.temporal_resolutions,
                metadata_bindings=resolved.metadata_bindings,
                metadata_issues=resolved.metadata_issues,
                llm_calls=llm_calls,
            ),
        }

    def _finalize_selected(self, state: SearchState) -> SearchState:
        """Render and persist a selected-page recommendation."""

        page = self.registry.get(state["selected_page_id"] or "")
        item = build_recommendation(
            page,
            effective_filters=state.get("effective_filters"),
            defaulted_filters=state.get("defaulted_filters"),
            missing_required_filters=state.get("missing_required_filters"),
        )
        status = "needs_filter" if item.missing_required_filters else "recommended"
        answer = self._append_temporal_adjustment_notice(
            render_selected(item),
            state.get("temporal_resolutions", {}),
        )
        answer = self._append_warning_notice(answer, state.get("warnings", []))
        return self._finalize(
            state,
            status=status,
            answer=answer,
            recommendations=[item.model_dump(mode="json")],
            active_artifact={
                "selected_page_id": page.page_id,
                "effective_filters": state.get("effective_filters", {}),
                "defaulted_filters": state.get("defaulted_filters", {}),
                "temporal_resolutions": state.get("temporal_resolutions", {}),
                "metadata_bindings": state.get("metadata_bindings", {}),
                "metadata_issues": state.get("metadata_issues", []),
                "tool": {
                    "name": page.tool.planned_name,
                    "arguments": None,
                    "result_ref": None,
                },
            },
        )

    def _finalize_ambiguous(self, state: SearchState) -> SearchState:
        """Render and persist unresolved candidate or relation choices."""

        page_ids = state.get("ambiguous_page_ids", [])
        relation_ambiguous = state.get("relation") == "ambiguous" and len(page_ids) == 1
        active = state.get("active_artifact") or {}
        if relation_ambiguous:
            items = [
                build_recommendation(
                    self.registry.get(page_ids[0]),
                    effective_filters=active.get("effective_filters"),
                    defaulted_filters=active.get("defaulted_filters"),
                )
            ]
        else:
            items = [build_recommendation(self.registry.get(page_id)) for page_id in page_ids]
        answer = (
            render_relation_ambiguous(items[0]) if relation_ambiguous else render_ambiguous(items)
        )
        answer = self._append_warning_notice(answer, state.get("warnings", []))
        if relation_ambiguous:
            active_artifact = state.get("active_artifact")
        else:
            previous_active = state.get("active_artifact") or {}
            active_artifact = {
                "pending_candidate_page_ids": page_ids,
                "original_question": previous_active.get(
                    "original_question", state["current_question"]
                ),
                "inherited_filters": state.get(
                    "inherited_filters", previous_active.get("inherited_filters", {})
                )
                or previous_active.get("inherited_filters", {}),
            }
        return self._finalize(
            state,
            status="ambiguous",
            answer=answer,
            recommendations=[item.model_dump(mode="json") for item in items],
            active_artifact=active_artifact,
        )

    def _finalize_not_found(self, state: SearchState) -> SearchState:
        """Render and persist a no-match response."""

        return self._finalize(
            state,
            status="not_found",
            answer=self._append_warning_notice(render_not_found(), state.get("warnings", [])),
            recommendations=[],
            active_artifact=None,
        )

    def _finalize(
        self,
        state: SearchState,
        *,
        status: str,
        answer: str,
        recommendations: list[dict[str, Any]],
        active_artifact: dict[str, Any] | None,
    ) -> SearchState:
        """Append response and execution records to checkpointed state."""

        relation = state.get("relation", "first_turn")
        if relation == "pending":
            relation = "first_turn"
        response_without_thread = {
            "status": status,
            "relation": relation,
            "answer": answer,
            "recommendations": recommendations,
            "warnings": state.get("warnings", []),
        }
        messages = [
            *state.get("message_history", []),
            {"role": "user", "content": state["current_question"]},
            {"role": "assistant", "content": answer},
        ]
        execution = [
            *state.get("execution_history", []),
            {
                "question": state["current_question"],
                "request_context": state["request_context"],
                "relation": relation,
                "trace": state.get("turn_trace", []),
                "response": response_without_thread,
            },
        ]
        return {
            "answer": answer,
            "response": response_without_thread,
            "message_history": messages,
            "execution_history": execution,
            "active_artifact": active_artifact,
            "turn_trace": [],
        }


def validate_response(thread_id: str, state: SearchState) -> SearchResponse:
    """Validate final graph state as the public response contract."""

    return SearchResponse.model_validate({"thread_id": thread_id, **state["response"]})
