"""Live-contract regressions, independent of question wording and mineral identity."""
from inhouse.rag_core.tests.registered_step_helpers import execute_registered
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


def factory():
    return live.LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])


def context(result):
    return ConversationContext("fixture", (Turn("prior", "fixture", UserUtterance("old"),
        semantic_program=SemanticProgram((RequirementNode("root", Operator.ENTITY),), ("root",)),
        result=ExecutionResult("pipe", result.status, {"root": result}, ())),))


@pytest.mark.parametrize("field", ["mineral", "entity"])
def test_projection_resolves_entity_dimension_without_new_retrieval(field):
    source = TypedResult.success(ValueType.TIME_SERIES, [{"date": "2024-01-01", "price": 10}], entity=("A",))
    result = execute_registered(factory(), RequirementNode("project", Operator.PROJECT, args={"fields": [field]}), {"in": source})
    assert result.status == ResultStatus.SUCCESS
    assert result.value == [{field: "A"}]


def test_entity_alias_uses_filtered_row_not_all_snapshot_entities():
    source = TypedResult(ValueType.COMPOSITE, [{"mineral": "B", "status": "success"}],
                         status=ResultStatus.PARTIAL, entity=("A", "B", "C"))
    result = execute_registered(factory(), RequirementNode("project", Operator.PROJECT, args={"fields": ["entity"]}), {"in": source})
    # Partial snapshots retain row status for later success projections.
    assert result.value == [{"entity": "B", "status": "success"}]
    assert result.entity == ("B",)
    assert result.status == ResultStatus.PARTIAL
    assert result.result_type == ValueType.FACT_SET
    assert not live._result_events(result)[-1].data["abstained"]


def test_ambiguous_entity_metadata_is_not_broadcast_to_rows():
    source = TypedResult.success(ValueType.FACT_SET, [{"price": 10}], entity=("A", "B"))
    result = execute_registered(factory(), RequirementNode("p", Operator.PROJECT, args={"fields": ["entity"]}), {"in": source})
    assert result.status == ResultStatus.ABSTAINED


def test_history_prompt_exposes_fields_not_values():
    source = TypedResult.success(ValueType.COMPOSITE, [{"mineral": "A", "output": "latest_value", "status": "success", "value": 987654321}])
    result = live._semantic_context_payload(context(source))[0]["results"][0]
    assert set(result["fields"]) >= {"mineral", "output", "status"}
    assert result["reference"] == "history:prior:root"
    assert "987654321" not in str(result)


@pytest.mark.parametrize("args", [{"calculation": "sum", "field": "price"}, {"aggregation": "sum", "field": "price"}])
def test_live_aggregate_requires_upstream_before_execution(args):
    model = live.ASTProgramModel.model_validate({"nodes": [{"node_id": "sum", "operator": "aggregate", "args": args}], "roots": ["sum"]})
    program = SemanticProgram.from_dict(model.model_dump())
    with pytest.raises(ValueError, match="upstream"):
        live._validate_live_contract(program, model)


def test_reference_contract_rejects_requery_but_refresh_allows_it():
    program = SemanticProgram((RequirementNode("r", Operator.RETRIEVE, args={"metric": "price"}),), ("r",))
    with pytest.raises(ValueError, match="reference.*retriev"):
        live._validate_live_contract(program, live.ASTProgramModel(result_access="reference"))
    # Refresh allows retrieval, but does not authorize an unbound new query.
    with pytest.raises(ValueError, match="refresh.*authorized"):
        live._validate_live_contract(program, live.ASTProgramModel(result_access="refresh"))


def test_reference_requires_authorized_binding_on_every_root():
    declaration = live.ASTProgramModel(result_access="reference")
    fabricated = SemanticProgram((RequirementNode("ctx_fabricated", Operator.ENTITY),), ("ctx_fabricated",))
    with pytest.raises(ValueError, match="authorized"):
        live._validate_live_contract(fabricated, declaration, ConversationContext("empty"))
    ctx = context(TypedResult.success(ValueType.MINERAL_SET, ["A"], entity=("A",), evidence=(Evidence("structured", "fixture", "fixture", "A"),)))
    saved = live._history_node_id("history:prior:root")
    unrelated = SemanticProgram((RequirementNode(saved, Operator.ENTITY), RequirementNode("invented", Operator.ENTITY)), ("invented",))
    with pytest.raises(ValueError, match="authorized"):
        live._validate_live_contract(unrelated, declaration, ctx)
    valid = SemanticProgram((RequirementNode(saved, Operator.ENTITY),), (saved,))
    live._validate_live_contract(valid, declaration, ctx)
    hijack = SemanticProgram((RequirementNode("static", Operator.ENTITY, args={"values": ["invented"]}),
        RequirementNode(saved, Operator.PROJECT, inputs=(InputRef("static"),), args={"fields": ["mineral"]})), (saved,))
    with pytest.raises(ValueError, match="authorized"):
        live._validate_live_contract(hijack, declaration, ctx)


@pytest.mark.parametrize("all_failed", [False, True])
def test_composite_sse_preserves_failed_items_and_reasons(all_failed):
    rows = [{"mineral": "B", "metric": "price", "output": "latest_value", "status": "empty", "reason": "advisor_rejected", "value": []},
            {"mineral": "C", "metric": "price", "output": "latest_value", "status": "failed", "reason": "execution_failed", "value": None}]
    if not all_failed:
        rows.insert(0, {"mineral": "A", "metric": "price", "output": "latest_value", "status": "success", "value": [{"price": 10}]})
    source = TypedResult(ValueType.COMPOSITE, rows, status=ResultStatus.FAILED if all_failed else ResultStatus.PARTIAL,
                         sufficient=not all_failed, failure_reason="all_items_failed" if all_failed else None)
    events = live._result_events(source)
    tables = [e.data for e in events if e.type == "table"]
    assert "advisor_rejected" in str(tables) and "execution_failed" in str(tables)
    assert "B" in str(tables) and "C" in str(tables)
    assert len([e for e in events if e.type == "done"]) == 1
    assert events[-1].data["abstained"] is all_failed


def test_production_column_alias_preserves_units_and_aggregate_value():
    source = TypedResult.success(ValueType.FACT_SET, [{"국가": "A", "생산량(톤)": "7"}, {"국가": "B", "생산량(톤)": "11"}], unit="톤")
    out = execute_registered(factory(), RequirementNode("s", Operator.AGGREGATE,
        args={"aggregation": "sum", "field": "production_volume"}), {"in": source})
    assert out.value == [{"생산량(톤)": 18}]
    assert out.unit == "톤"


@pytest.mark.parametrize("metric", ["production", "reserves"])
def test_logical_resource_collection_is_unbounded_but_explicit_ranking_is_not(metric):
    node = RequirementNode("r", Operator.RETRIEVE, args={"metric": metric, "mineral": "구리"})
    assert live._action_slots(node).resource_population == "all"
    limited = RequirementNode("r", Operator.RETRIEVE, args={**node.args, "top_n": 5})
    slots = live._action_slots(limited)
    assert slots.top_n == 5 and slots.resource_population is None


def test_resource_domain_never_silently_replaces_metric():
    with pytest.raises(ValueError, match="conflict"):
        live._action_slots(RequirementNode("r", Operator.RETRIEVE, args={"domain": "production", "metric": "reserves"}))
    with pytest.raises(ValueError, match="metric_required"):
        live._action_slots(RequirementNode("r", Operator.RETRIEVE, args={"domain": "resource"}))
    with pytest.raises(ValueError, match="resource_country_filter_required"):
        live._action_slots(RequirementNode("r", Operator.RETRIEVE, args={"metric": "production", "reporter_country": "CL"}))
    assert live._action_slots(RequirementNode("r", Operator.RETRIEVE, args={"metric": "production", "resource_country": "CL"})).resource_country == "CL"


def test_multisource_project_rejected_in_live_instead_of_dropping_inputs():
    model = live.ASTProgramModel(nodes=[live.ASTNodeModel(node_id="p", operator="project",
        inputs=[live.ASTInputModel(node_id="a"), live.ASTInputModel(node_id="b")], args={"fields": ["value"]})])
    with pytest.raises(ValueError, match="exactly one"):
        live._validate_live_contract(None, model)


def test_projection_distinct_does_not_duplicate_timeseries_entity():
    source = TypedResult.success(ValueType.TIME_SERIES, [{"price": 10}, {"price": 11}], entity=("A",))
    out = execute_registered(factory(), RequirementNode("p", Operator.PROJECT,
        args={"fields": ["mineral"], "distinct": True}), {"in": source})
    assert out.value == [{"mineral": "A"}]


def test_saved_mineral_set_projection_compiles_and_preserves_identity():
    source = TypedResult.success(ValueType.MINERAL_SET, ["A", "B"], entity=("A", "B"))
    payload = {"nodes": [{"node_id": "p", "operator": "project", "inputs": [{"node_id": "history:prior:root"}],
                           "args": {"fields": ["mineral"]}}], "roots": ["p"]}
    program = SemanticProgram.from_dict(live._normalize_history_aliases(payload, context(source)))
    result = execute_registered(factory(), program.nodes[-1], {"saved": source})
    assert result.value == [{"mineral": "A"}, {"mineral": "B"}]


@pytest.mark.parametrize("name", ["칠레", "Chile", "CL"])
def test_country_filter_uses_source_owned_names_without_role_replacement(name):
    source = TypedResult.success(ValueType.FACT_SET, [{"country": "칠레", "country_code": "CL", "country_name_en": "Chile", "value": 7},
                                                    {"country": "다른국가", "country_code": "ZZ", "value": 11}])
    result = execute_registered(factory(), RequirementNode("f", Operator.FILTER,
        args={"predicate": {"field": "country", "operator": "equals", "value": name}}), {"in": source})
    assert len(result.value) == 1 and result.value[0]["country_code"] == "CL"
