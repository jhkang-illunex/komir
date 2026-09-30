"""Live integration adapter for the LangGraph multi-hop vertical slice.

The adapter owns only semantic parsing, physical ActionCall projection and
canonical-result-to-SSE conversion. PostgreSQL, PageIndex, OKF and existing
retrieval functions remain the source of data and evidence.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import os
import re
from dataclasses import replace
from uuid import uuid4
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from ._shared_root import ensure_shared_on_path

ensure_shared_on_path(Path(__file__).resolve())

from common.llm_client import KomirJsonLLM

from .action_contract import ActionCall, ActionPlan, ActionSlots, MINERAL_ALIASES, Period
from .chatbot_events import ChatEvent, chart_spec, extract_markdown_tables, table_block
from .chatbot_graph import retrieve_evidence
from .history_context import ConversationContext, InMemoryHistoryStore, Turn, UserUtterance
from .legacy_bridge import LegacyOperatorFactory
from .lowering import PipeLowerer
from .multihop_orchestrator import MultiHopOrchestrator
from .pipe_runtime import ExecutionContext, ExecutionResult, FunctionStep, ResultStatus, TypedResult
from .semantic_ir import Operator, SemanticProgram, ValueType

_logger = logging.getLogger(__name__)


def multihop_mode() -> str:
    value = os.getenv("MULTIHOP_ORCHESTRATOR_MODE", "off").strip().casefold()
    return value if value in {"off", "shadow", "enabled"} else "off"


class ASTInputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=80)
    selector: str = "all"
    selector_value: str | int | None = None


class ASTNodeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str = Field(min_length=1, max_length=80)
    operator: str
    inputs: list[ASTInputModel] = []
    args: dict[str, Any] = {}
    expected_type: str = "unknown"
    constraints: dict[str, Any] = {}
    evidence_required: bool = True


class ASTProgramModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[ASTNodeModel] = Field(min_length=1)
    roots: list[str] = Field(min_length=1)


AST_PROMPT = """자연어 BI 질문을 물리 Action 이름 없이 Typed Semantic AST JSON으로 변환한다.
JSON 외 설명은 출력하지 않는다. 각 node는 하나의 primitive만 표현하며, 문자열로
중간 결과를 전달하지 않는다.

허용 operator: entity, retrieve, retrieve_document, filter, project, sort, rank,
top_k, aggregate, compare, arg_max, arg_min, join, calculate, resolve_reference,
validate_evidence.

필수 원칙:
- 이전 결과를 가리키는 '그중', '그 광물', '세 번째'는 inputs의 node_id와
  selector(index/field/all)로 표현한다.
- 현재 질문의 node가 참조하는 모든 node_id는 같은 JSON의 nodes에 실제로 존재해야 한다.
  존재하지 않는 `mineral_data`, `previous`, `all` 같은 임의 node는 만들지 않는다.
- selector=index일 때 selector_value는 0부터 시작하는 정수이고, field일 때는
  실제 upstream 행의 필드명이다. selector=all이면 selector_value를 생략한다.
- 이전 turn 결과를 참조해야 하면 semantic_history에 표시된 정확한
  `history:<turn_id>:<step_id>` node_id를 사용한다.
- 가격 상승 광물 순위는 rank 또는 sort → top_k로 표현한다.
- top_k 결과를 다시 조회할 때 downstream retrieve node의 input으로 연결한다.
- 독립적인 국가비중·생산량 조회는 각각 node로 만들고 dependency가 없으면 병렬 가능하게 한다.
- 질문에 없는 광물·기간·단위·수치를 추정하지 않는다.
- source, metric, period, unit 조건을 args에 보존한다.
- operator args에는 domain, metric, flow, scope, mineral, minerals, period,
  top_n, order, field, predicate, topic, calculation을 사용할 수 있다.
- unsupported data는 AST에 억지로 만들지 말고 validate_evidence 단계에서 기권할 수 있게 한다.

예: 가격 상승률 상위 3개 중 수입액이 가장 큰 광물
rank(price_change) → top_k(3) → retrieve(import_value, input=top_k) → arg_max(import_value)
"""


_HISTORY = InMemoryHistoryStore()


def _semantic_context_payload(context: ConversationContext) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for turn in context.turns[-8:]:
        result = turn.result
        roots: list[dict[str, Any]] = []
        if result:
            for step_id, typed in result.results.items():
                roots.append({
                    "step_id": step_id,
                    "result_type": typed.result_type.value,
                    "status": typed.status.value,
                    "entity": list(typed.entity),
                    "metric": typed.metric,
                    "period": typed.period,
                    "unit": typed.unit,
                    "source": list(typed.source),
                    "provenance": list(typed.provenance),
                })
        payload.append({"turn_id": turn.turn_id, "utterance": turn.utterance.text, "results": roots})
    return payload


async def _parse_ast(llm: KomirJsonLLM, message: str, context: ConversationContext) -> SemanticProgram:
    invocation = await asyncio.to_thread(
        llm.invoke,
        task="semantic_ast",
        instructions=AST_PROMPT,
        payload={"question": message, "semantic_history": _semantic_context_payload(context)},
        output_model=ASTProgramModel,
        max_tokens=1400,
    )
    payload = invocation.output.model_dump(mode="json")
    return SemanticProgram.from_dict(_normalize_history_aliases(payload, context))


def _latest_history_binding(context: ConversationContext) -> tuple[str, TypedResult] | None:
    latest = context.latest
    if latest is None or latest.result is None:
        return None
    step_id = next(
        (step_id for step_id in (latest.semantic_program.roots if latest.semantic_program else ()) if step_id in latest.result.results),
        next(reversed(latest.result.results), None),
    )
    if step_id is None:
        return None
    return f"history:{latest.turn_id}:{step_id}", latest.result.results[step_id]


def _normalize_history_aliases(payload: Mapping[str, Any], context: ConversationContext) -> dict[str, Any]:
    """Repair model-local reference aliases before strict SemanticProgram validation."""
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    nodes = list(normalized.get("nodes", []))
    local_ids = {str(node.get("node_id")) for node in nodes}
    binding = _latest_history_binding(context)
    if binding is None:
        return normalized
    canonical_ref, typed = binding
    synthetic_id = "ctx_" + re.sub(r"[^A-Za-z0-9_]+", "_", canonical_ref).strip("_")
    aliases = {"previous", "previous_turn", "latest", "latest_result", "history:0:0", "history:latest"}
    aliases.update({canonical_ref})

    def is_alias(value: Any) -> bool:
        text = str(value)
        return text in aliases or text.startswith("history:") and text != canonical_ref

    # A model may emit the alias as a pseudo-node and even point that node to
    # itself. Materialize it as a typed entity binding before graph validation.
    rewritten_nodes: list[dict[str, Any]] = []
    alias_node_ids = {node_id for node_id in local_ids if is_alias(node_id)}
    for raw in nodes:
        node = dict(raw)
        node_id = str(node.get("node_id"))
        if node_id in alias_node_ids:
            node = {
                "node_id": synthetic_id,
                "operator": Operator.ENTITY.value,
                "inputs": [],
                "args": {"values": typed.value, "entity": list(typed.entity)},
                "expected_type": typed.result_type.value,
                "constraints": {},
                "evidence_required": False,
            }
        rewritten_nodes.append(node)

    local_ids = {str(node.get("node_id")) for node in rewritten_nodes}
    for node in rewritten_nodes:
        inputs = []
        for raw_ref in node.get("inputs", []) or []:
            ref = dict(raw_ref)
            ref_id = str(ref.get("node_id"))
            if is_alias(ref_id) or ref_id == node.get("node_id"):
                ref["node_id"] = synthetic_id
            inputs.append(ref)
        node["inputs"] = inputs
    if any(ref.get("node_id") == synthetic_id for node in rewritten_nodes for ref in node.get("inputs", [])) and synthetic_id not in local_ids:
        rewritten_nodes.insert(0, {
            "node_id": synthetic_id,
            "operator": Operator.ENTITY.value,
            "inputs": [],
            "args": {"values": typed.value, "entity": list(typed.entity)},
            "expected_type": typed.result_type.value,
            "constraints": {},
            "evidence_required": False,
        })
    normalized["nodes"] = rewritten_nodes
    normalized["roots"] = [synthetic_id if is_alias(root) else root for root in normalized.get("roots", [])]
    return normalized


def _resolve_history_references(program: SemanticProgram, context: ConversationContext) -> SemanticProgram:
    """Materialize deterministic previous-turn bindings as typed entity nodes."""
    history_results: dict[str, TypedResult] = {}
    for turn in context.turns:
        if not turn.result:
            continue
        for step_id, result in turn.result.results.items():
            history_results[f"history:{turn.turn_id}:{step_id}"] = result
    if not history_results:
        return program

    nodes = {node.node_id: node for node in program.nodes}
    additions: list[Any] = []
    replacements: dict[str, str] = {}
    for node in program.nodes:
        for ref in node.inputs:
            if ref.node_id in nodes or ref.node_id in replacements:
                continue
            result = history_results.get(ref.node_id)
            if result is None:
                raise ValueError(f"unresolved semantic history reference: {ref.node_id}")
            synthetic = "ctx_" + re.sub(r"[^A-Za-z0-9_]+", "_", ref.node_id).strip("_")
            if synthetic not in nodes:
                additions.append(RequirementNode(
                    node_id=synthetic,
                    operator=Operator.ENTITY,
                    args={"values": result.value, "entity": list(result.entity)},
                    expected_type=result.result_type,
                    evidence_required=False,
                ))
                nodes[synthetic] = additions[-1]
            replacements[ref.node_id] = synthetic

    resolved_nodes = []
    for node in (*additions, *program.nodes):
        resolved_nodes.append(replace(node, inputs=tuple(
            replace(ref, node_id=replacements.get(ref.node_id, ref.node_id)) for ref in node.inputs
        )))
    return SemanticProgram(tuple(resolved_nodes), program.roots)


def _period(value: Any) -> Period | None:
    if value is None:
        return None
    if isinstance(value, Period):
        return value
    if isinstance(value, Mapping):
        return Period.model_validate(dict(value))
    return None


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _rows(evidence: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in evidence:
        for table in extract_markdown_tables(getattr(item, "text", "")):
            for row in table["rows"]:
                rows.append(dict(zip(table["columns"], row)))
    return rows


def _entity_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        value = [value]
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, Mapping):
                for key, candidate in item.items():
                    if any(token in str(key).casefold() for token in ("광종", "광물", "mineral", "원소")):
                        if candidate and str(candidate) not in values:
                            values.append(str(candidate))
                        break
    return values


def _row_date(row: Mapping[str, Any]) -> date | None:
    for key, value in row.items():
        key_text = str(key).casefold()
        if not any(token in key_text for token in ("date", "ymd", "일자", "기준일", "시점")):
            continue
        raw = str(value).strip()
        try:
            return date.fromisoformat(raw[:10]) if "-" in raw else date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
        except (ValueError, IndexError):
            continue
    return None


def _subtract_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _filter_period(rows: list[Any], period: Any) -> list[Any]:
    if not isinstance(period, Mapping):
        return rows
    dates = [item_date for item in rows if isinstance(item, Mapping) and (item_date := _row_date(item)) is not None]
    if not dates:
        return rows
    latest = max(dates)
    if period.get("trailing_months"):
        cutoff = _subtract_months(latest, int(period["trailing_months"]))
        return [row for row in rows if not isinstance(row, Mapping) or (_row_date(row) is not None and _row_date(row) >= cutoff)]
    start = period.get("start")
    end = period.get("end")
    try:
        start_date = date.fromisoformat(str(start)[:10]) if start else None
        end_date = date.fromisoformat(str(end)[:10]) if end else None
    except ValueError:
        return rows
    return [
        row for row in rows
        if not isinstance(row, Mapping) or (_row_date(row) is not None and (start_date is None or _row_date(row) >= start_date) and (end_date is None or _row_date(row) <= end_date))
    ]


def _typed_from_retrieval(result: Any, action: ActionCall, *, input_entities: list[str]) -> TypedResult:
    action_result = next(iter(getattr(result, "action_results", []) or []), None)
    evidence = tuple(getattr(result, "evidence", []) or [])
    if action_result is not None:
        evidence = tuple(action_result.evidence or evidence)
    rows = _rows(list(evidence))
    action_id = action.action_id
    result_type = {
        "price.volatility_rank": ValueType.MINERAL_RANKING,
        "trade.country_rank": ValueType.COUNTRY_SHARE,
        "trade.monthly": ValueType.TRADE_SERIES,
        "price.series": ValueType.TIME_SERIES,
        "document.retrieve": ValueType.DOCUMENT_EVIDENCE,
        "document.lookup": ValueType.DOCUMENT_EVIDENCE,
        "resource.rank": ValueType.FACT_SET,
    }.get(action_id, ValueType.FACT_SET)
    status = getattr(action_result, "status", "success") if action_result else ("success" if evidence else "no_data")
    if status != "success" or not evidence:
        return TypedResult.empty(result_type, f"retrieval unavailable: {status}", evidence=evidence)
    entities = list(input_entities)
    if not entities:
        entities = _entity_values(rows)
    if action.slots.mineral and action.slots.mineral not in entities:
        entities.append(action.slots.mineral)
    if action.slots.minerals:
        entities.extend(item for item in action.slots.minerals if item not in entities)
    sources = tuple(dict.fromkeys(str(getattr(item, "source", "")) for item in evidence if getattr(item, "source", None)))
    provenance = tuple(dict.fromkeys(
        f"{action.requirement_id}:{getattr(item, 'source_id', None) or getattr(item, 'source', 'unknown')}"
        for item in evidence
    ))
    return TypedResult.success(
        result_type,
        rows or list(evidence),
        entity=tuple(entities),
        metric=action.slots.metric or action.slots.trade_metric,
        period=action.slots.period.model_dump(mode="json") if action.slots.period else None,
        unit=next((getattr(item, "unit", None) for item in evidence if getattr(item, "unit", None)), None),
        source=sources,
        evidence=evidence,
        provenance=provenance,
    )


def _action_id(node: Any) -> str:
    args = node.args
    if node.operator == Operator.RETRIEVE_DOCUMENT.value:
        return "document.retrieve"
    domain = str(args.get("domain", "")).casefold()
    metric = str(args.get("metric", "")).casefold()
    price_metrics = {"rank", "price_change", "price_change_rate", "price_growth_rate", "change", "volatility"}
    trade_series_metrics = {"import_value", "import_amount", "import_weight", "export_value", "export_amount", "export_weight", "trade_series"}
    trade_rank_metrics = {"import_share", "country_share", "country_rank"}
    if metric in price_metrics or (node.operator == Operator.RANK.value and domain == "price"):
        return "price.volatility_rank"
    if domain == "price":
        return "price.series"
    if metric in trade_series_metrics:
        return "trade.monthly"
    if metric in trade_rank_metrics or domain == "trade":
        return "trade.country_rank"
    if domain == "resource" or metric in {"production", "reserves", "production_change"}:
        return "resource.rank"
    if domain == "inventory":
        return "inventory.latest"
    return "document.retrieve"


def _action_slots(node: Any, mineral: str | None = None, minerals: list[str] | None = None) -> ActionSlots:
    args = node.args
    metric = args.get("metric")
    domain = str(args.get("domain", "")).casefold()
    def canonical_mineral(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return MINERAL_ALIASES.get(text.casefold(), text)

    resolved_mineral = canonical_mineral(mineral or args.get("mineral"))
    resolved_minerals = [canonical_mineral(item) for item in (minerals or args.get("minerals") or [])]
    resolved_minerals = [item for item in resolved_minerals if item]
    if metric in {"import_value", "import_share", "country_share", "country_rank"} or domain == "trade":
        metric = metric if metric in {"import_amount", "import_weight", "export_amount", "export_weight"} else "import_amount"
    if domain == "resource" and metric not in {"production", "reserves"}:
        metric = "production"
    if domain == "price" or metric in {"price", "price_change", "price_change_rate", "price_growth_rate", "change", "volatility", "rank"}:
        metric = None
    scope = args.get("scope") or args.get("trade_scope")
    if scope in {"KR", "korea", "국내", "한국"}:
        scope = "korea"
    if scope in {"WORLD", "GLOBAL", "global", "세계"}:
        scope = "global"
    return ActionSlots(
        mineral=resolved_mineral,
        minerals=resolved_minerals or None,
        metric=metric,
        flow=args.get("flow"),
        trade_scope=scope,
        period=_period(args.get("period")),
        top_n=args.get("top_n") or args.get("limit"),
        topic=args.get("topic") or args.get("question"),
        requested_outputs={"text", "table", "chart"},
    )


class LiveOperatorFactory:
    def __init__(self, *, message: str, session_id: str, profile: str, llm: KomirJsonLLM, history: list[dict[str, str]]):
        self.message = message
        self.session_id = session_id
        self.profile = profile
        self.llm = llm
        self.history = history

    def build(self, *, node: Any, dependencies: tuple[str, ...], bindings: Mapping[str, Any]):
        if node.operator == Operator.ENTITY.value:
            return FunctionStep(node.node_id, node.operator.value, lambda _c, _i: self._entity(node), dependencies=dependencies, bindings=bindings)
        if node.operator in {Operator.TOP_K.value, Operator.FILTER.value, Operator.SORT.value, Operator.RANK.value, Operator.ARG_MAX.value, Operator.ARG_MIN.value, Operator.PROJECT.value, Operator.CALCULATE.value, Operator.AGGREGATE.value, Operator.COMPARE.value, Operator.JOIN.value} and (dependencies or node.operator != Operator.RANK.value):
            return FunctionStep(node.node_id, node.operator.value, lambda _c, inputs: self._derive(node, inputs), dependencies=dependencies, bindings=bindings)
        if node.operator == Operator.VALIDATE_EVIDENCE.value:
            return FunctionStep(node.node_id, node.operator.value, lambda _c, inputs: self._validate(inputs), dependencies=dependencies, bindings=bindings)
        return FunctionStep(node.node_id, node.operator.value, lambda _c, inputs: self._retrieve(node, inputs), dependencies=dependencies, bindings=bindings)

    @staticmethod
    def _entity(node: Any) -> TypedResult:
        values = node.args.get("values") or node.args.get("minerals") or node.args.get("mineral") or []
        if isinstance(values, str):
            values = [values]
        return TypedResult.success(ValueType.MINERAL_SET, list(values), entity=tuple(str(item) for item in values))

    @staticmethod
    def _input_value(inputs: Mapping[str, TypedResult]) -> Any:
        return next(iter(inputs.values())).value if inputs else None

    def _derive(self, node: Any, inputs: Mapping[str, TypedResult]) -> TypedResult:
        source = next(iter(inputs.values()), None)
        value = source.value if source else None
        rows = value if isinstance(value, list) else ([value] if isinstance(value, Mapping) else [])
        args = node.args
        if node.operator == Operator.TOP_K.value:
            rows = rows[: int(args.get("k") or args.get("top_n") or 5)]
        elif node.operator in {Operator.SORT.value, Operator.RANK.value}:
            field = args.get("field") or args.get("metric_field")
            if field is None and rows and isinstance(rows[0], Mapping):
                field = next((key for key, item in rows[0].items() if _numeric(item) is not None), None)
            reverse = str(args.get("order", "desc")).casefold() in {"desc", "decreasing", "decrease"}
            rows = sorted(rows, key=lambda row: _numeric(row.get(field)) if isinstance(row, Mapping) and field else float("-inf"), reverse=reverse)
        elif node.operator == Operator.FILTER.value:
            predicate = args.get("predicate") or {}
            field, operator, expected = predicate.get("field"), predicate.get("operator", "equals"), predicate.get("value")
            if not field:
                rows = _filter_period(rows, args.get("period"))
                field = None
            def keep(row: Any) -> bool:
                actual = row.get(field) if isinstance(row, Mapping) else None
                expected_value = expected
                left, right = _numeric(actual), _numeric(expected_value)
                if left is not None and right is not None:
                    actual, expected_value = left, right
                return {"equals": actual == expected_value, "greater_than": actual > expected_value, "less_than": actual < expected_value, "gte": actual >= expected_value, "lte": actual <= expected_value}.get(operator, False)
            if not field:
                return TypedResult.success(ValueType.FACT_SET, rows, entity=tuple(_entity_values(rows)), evidence=source.evidence if source else (), source=source.source if source else (), provenance=source.provenance if source else (), sufficient=source.sufficient if source else False, upstream_step_ids=source.upstream_step_ids if source else ())
            rows = [row for row in rows if keep(row)]
        elif node.operator in {Operator.ARG_MAX.value, Operator.ARG_MIN.value}:
            field = args.get("field") or args.get("metric_field")
            if rows and field:
                rows = [max(rows, key=lambda row: _numeric(row.get(field)) or float("-inf")) if node.operator == Operator.ARG_MAX.value else min(rows, key=lambda row: _numeric(row.get(field)) or float("inf"))]
        elif node.operator == Operator.PROJECT.value:
            fields = args.get("fields") or []
            rows = [{field: row.get(field) for field in fields} for row in rows if isinstance(row, Mapping)]
        elif node.operator == Operator.COMPARE.value or node.operator == Operator.JOIN.value:
            rows = [item.value for item in inputs.values()]
        elif node.operator == Operator.CALCULATE.value:
            calculation = args.get("calculation")
            if calculation in {"change_pct", "percent_change"} and isinstance(value, Mapping):
                start, end = _numeric(value.get("start")), _numeric(value.get("end"))
                if start is not None and start != 0 and end is not None:
                    rows = [{**value, "change_pct": (end - start) / abs(start) * 100}]
        entities = _entity_values(rows) or (list(source.entity) if source else [])
        result_type = ValueType.MINERAL_SET if node.operator == Operator.TOP_K.value else (source.result_type if source else ValueType.FACT_SET)
        return TypedResult.success(result_type, rows, entity=tuple(entities), evidence=source.evidence if source else (), source=source.source if source else (), provenance=source.provenance if source else (), sufficient=source.sufficient if source else False, upstream_step_ids=source.upstream_step_ids if source else ())

    def _validate(self, inputs: Mapping[str, TypedResult]) -> TypedResult:
        source = next(iter(inputs.values()), None)
        if source is None or not source.evidence or not source.sufficient:
            return TypedResult.abstain("evidence validation failed")
        return source

    async def _retrieve(self, node: Any, inputs: Mapping[str, TypedResult]) -> TypedResult:
        input_entities = []
        for item in inputs.values():
            input_entities.extend(entity for entity in (list(item.entity) or _entity_values(item.value)) if entity not in input_entities)
        action_id = _action_id(node)
        minerals = input_entities or list(node.args.get("minerals") or [])
        if not minerals and node.args.get("mineral"):
            minerals = [str(node.args["mineral"])]
        if action_id in {"trade.country_rank", "trade.monthly", "resource.rank"} and len(minerals) > 1:
            results = await asyncio.gather(*(self._call_action(node, action_id, mineral=minerals[0] if action_id == "trade.monthly" else mineral) for mineral in minerals))
            merged = TypedResult.empty(ValueType.FACT_SET, "no data")
            merged_rows: list[dict[str, Any]] = []
            evidences: list[Any] = []
            sources: list[str] = []
            provenance: list[str] = []
            for item in results:
                if item.status == ResultStatus.SUCCESS:
                    if isinstance(item.value, list):
                        merged_rows.extend(item.value)
                    evidences.extend(item.evidence)
                    sources.extend(item.source)
                    provenance.extend(item.provenance)
            if evidences:
                merged = TypedResult.success(ValueType.FACT_SET, merged_rows, entity=tuple(dict.fromkeys(minerals)), evidence=tuple(evidences), source=tuple(dict.fromkeys(sources)), provenance=tuple(dict.fromkeys(provenance)))
            return merged
        return await self._call_action(node, action_id, mineral=minerals[0] if minerals else None, minerals=minerals or None)

    async def _call_action(self, node: Any, action_id: str, *, mineral: str | None = None, minerals: list[str] | None = None) -> TypedResult:
        slots = _action_slots(node, mineral=mineral, minerals=minerals)
        if action_id == "price.volatility_rank":
            slots = slots.model_copy(update={"minerals": minerals or slots.minerals, "top_n": slots.top_n or 5})
        if action_id == "document.retrieve" and not slots.topic:
            slots = slots.model_copy(update={"topic": self.message})
        call = ActionCall(requirement_id=node.node_id, action_id=action_id, slots=slots, requested_outputs={"text", "table", "chart"})
        plan = ActionPlan(actions=[call])
        result = await asyncio.to_thread(
            retrieve_evidence,
            self.message,
            session_id=self.session_id,
            history=self.history,
            llm=self.llm,
            profile=self.profile,
            action_plan=plan,
            include_action_results=True,
        )
        return _typed_from_retrieval(result, call, input_entities=[mineral] if mineral else [])


@dataclass(frozen=True)
class LiveRun:
    program: SemanticProgram
    orchestration: Any
    skipped: bool = False
    session_id: str | None = None
    turn_id: str | None = None


async def run_live_multihop(
    *,
    message: str,
    session_id: str,
    profile: str,
    llm: KomirJsonLLM,
    history: list[dict[str, str]],
    legacy_action_ids: list[str] | None = None,
) -> LiveRun:
    context = await _HISTORY.get_context(session_id)
    program = await _parse_ast(llm, message, context)
    program = _resolve_history_references(program, context)
    turn_id = f"turn-{uuid4().hex[:12]}"
    has_dependency = any(node.inputs for node in program.nodes) or len(program.nodes) > 1
    if not has_dependency:
        await _HISTORY.append_turn(Turn(
            turn_id=turn_id,
            session_id=session_id,
            utterance=UserUtterance(message),
            semantic_program=program,
        ))
        return LiveRun(program, None, skipped=True, session_id=session_id, turn_id=turn_id)
    factory = LiveOperatorFactory(message=message, session_id=session_id, profile=profile, llm=llm, history=history)
    lowerer = PipeLowerer(LegacyOperatorFactory({node.operator.value: factory.build for node in program.nodes}))
    pipe_id = f"pipe-{uuid4().hex[:12]}"
    orchestration = await MultiHopOrchestrator(lowerer).execute(
        program,
        session_id=session_id,
        turn_id=turn_id,
        pipe_id=pipe_id,
        evidence_validator=lambda typed: bool(typed.evidence) and typed.sufficient,
        context_metadata={"legacy_action_ids": legacy_action_ids or []},
    )
    await _HISTORY.append_turn(Turn(
        turn_id=turn_id,
        session_id=session_id,
        utterance=UserUtterance(message),
        semantic_program=program,
        pipe_id=pipe_id,
        result=orchestration.execution,
        bindings=orchestration.execution.results,
        evidence=tuple(orchestration.root_result.evidence),
    ))
    _logger.info(
        "multihop_shadow_compare session=%s legacy_actions=%s ast=%s pipe=%s status=%s root_type=%s root_failure=%s steps=%s",
        session_id,
        legacy_action_ids or [],
        json.dumps(program.to_dict(), ensure_ascii=False, separators=(",", ":")),
        orchestration.execution.pipe_id,
        orchestration.root_result.status.value,
        orchestration.root_result.result_type.value,
        orchestration.root_result.failure_reason,
        json.dumps({key: {"status": value.status.value, "failure": value.failure_reason} for key, value in orchestration.execution.results.items()}, ensure_ascii=False, separators=(",", ":")),
    )
    return LiveRun(program, orchestration, session_id=session_id, turn_id=turn_id)


async def record_legacy_comparison(run: LiveRun, retrieval_result: Any | None) -> None:
    """Log a same-turn semantic comparison without changing legacy output."""
    if retrieval_result is None:
        return
    legacy_results = list(getattr(retrieval_result, "action_results", []) or [])
    legacy_evidence = list(getattr(retrieval_result, "evidence", []) or [])
    if run.skipped and run.session_id and run.turn_id and legacy_results:
        typed_results: dict[str, TypedResult] = {}
        for action_result in legacy_results:
            action_plan = getattr(retrieval_result, "action_plan", None)
            action = next((item for item in getattr(action_plan, "actions", []) if item.requirement_id == action_result.requirement_id), None)
            if action is None:
                continue
            single = type(retrieval_result)(
                action_plan=action_plan,
                action_results=[action_result],
                evidence=list(action_result.evidence),
                warnings=list(getattr(retrieval_result, "warnings", []) or []),
            )
            typed_results[action_result.requirement_id] = _typed_from_retrieval(single, action, input_entities=[])
        if typed_results:
            status = ResultStatus.SUCCESS if any(item.status == ResultStatus.SUCCESS for item in typed_results.values()) else ResultStatus.EMPTY
            result = ExecutionResult(
                pipe_id=f"legacy-{run.turn_id}",
                status=status,
                results=typed_results,
                events=(),
                failure_reason=None if status == ResultStatus.SUCCESS else "legacy result unavailable",
            )
            await _HISTORY.save_result(run.session_id, run.turn_id, result)
    if run.skipped or run.orchestration is None:
        return
    _logger.info(
        "multihop_shadow_result_compare pipe=%s new_status=%s new_evidence=%d legacy_actions=%s legacy_evidence=%d",
        run.orchestration.execution.pipe_id,
        run.orchestration.root_result.status.value,
        len(run.orchestration.root_result.evidence),
        [getattr(item, "action_id", None) for item in legacy_results],
        len(legacy_evidence),
    )


def live_run_events(run: LiveRun) -> list[ChatEvent]:
    """Encode validated canonical results using the existing ChatEvent contract."""
    if run.orchestration is None:
        return []
    result = run.orchestration.root_result
    if result.status in {ResultStatus.ABSTAINED, ResultStatus.EMPTY, ResultStatus.FAILED}:
        return [
            ChatEvent("delta", {"delta": result.failure_reason or "확인 가능한 근거가 없어 답변할 수 없습니다."}),
            ChatEvent("done", {"done": True, "abstained": True, "abstain_reason": result.failure_reason or "source_unavailable", "citations": []}),
        ]
    events = [ChatEvent("delta", {"delta": "요청하신 조건을 기존 데이터 원천에서 단계적으로 확인했습니다."})]
    if isinstance(result.value, list) and result.value and all(isinstance(row, Mapping) for row in result.value):
        columns = list(dict.fromkeys(key for row in result.value for key in row.keys()))
        table = {
            "columns": columns,
            "rows": [[str(row.get(column, "")) for column in columns] for row in result.value],
            "markdown": "",
        }
        table["markdown"] = "\n".join([
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
            *["| " + " | ".join(row) + " |" for row in table["rows"]],
        ])
        events.append(ChatEvent("table", table_block(table, block_id="multihop-table", source_index=1, source_label=(result.source[0] if result.source else None), unit=result.unit)))
        chart = chart_spec(table, block_id="multihop-chart", data_ref="multihop-table", source_index=1, source_label=(result.source[0] if result.source else None), unit=result.unit)
        if chart:
            events.append(ChatEvent("chart", chart))
    citations = [{"index": index, "source": source} for index, source in enumerate(result.source, 1)]
    events.append(ChatEvent("done", {"done": True, "abstained": False, "citations": citations, "bogus_citations": []}))
    return events
