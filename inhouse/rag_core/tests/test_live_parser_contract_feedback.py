import asyncio
from types import SimpleNamespace

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult, ExecutionResult, ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import SemanticProgram, RequirementNode, Operator, ValueType, InputRef
from inhouse.rag_core.retrieval.evidence import Evidence


def test_schema_declares_live_dependency_arity():
    schema = live.ASTNodeModel.model_json_schema()
    rules = schema.get("allOf", [])
    aggregate = next(rule for rule in rules if "aggregate" in rule["if"]["properties"]["operator"]["enum"])
    assert aggregate["then"]["properties"]["inputs"]["minItems"] == 1
    assert "inputs" in aggregate["then"]["required"]


def test_foreach_field_contract_is_runtime_envelope_not_document_or_flat_metric():
    nodes=(RequirementNode("d",Operator.RETRIEVE_DOCUMENT,args={"topic":"fixture"}),
           RequirementNode("f",Operator.FOR_EACH,inputs=(InputRef("d"),),args={"domain":"price","metric":"price"}))
    for fields in (["mineral","value","status","unit"], ["mineral","price"], ["title"]):
        def make():
            return SemanticProgram(nodes+(RequirementNode("p",Operator.PROJECT,inputs=(InputRef("f"),),args={"fields":fields}),),("p",))
        if fields[1:]==["value","status","unit"]:
            make().validate()
        else:
            with pytest.raises(ValueError,match="not produced"):
                make()


def test_repair_receives_structured_failed_plan_and_field_contracts():
    live.clear_semantic_cache()
    bad = {"nodes": [{"node_id": "a", "operator": "aggregate", "args": {"aggregation": "sum", "field": "production_volume"}}], "roots": ["a"]}
    good = {"nodes": [{"node_id": "r", "operator": "retrieve", "args": {"metric": "production_volume", "mineral": "copper"}},
                      {"node_id": "a", "operator": "aggregate", "inputs": [{"node_id": "r"}], "args": {"aggregation": "sum", "field": "production_volume"}}], "roots": ["a"]}
    calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output=live.ASTProgramModel.model_validate(bad if len(calls)==1 else good))
    result = asyncio.run(live._parse_ast(SimpleNamespace(invoke=invoke), "opaque test utterance", ConversationContext("fixture")))
    assert len(result.nodes) == 2
    repair = calls[1]["payload"]["repair"]
    assert repair["previous_program"]["nodes"][0]["node_id"] == "a"
    assert "upstream" in repair["validation_error"]
    assert "date" in calls[0]["payload"]["metric_fields"]["price"]
    assert "period" not in calls[0]["payload"]["metric_fields"]["price"]
    assert "previous_node_contracts" not in calls[1]["instructions"]


def test_invalid_plans_never_execute_or_enter_cache():
    live.clear_semantic_cache()
    calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output=live.ASTProgramModel.model_validate({"nodes": [{"node_id": "a", "operator": "aggregate", "args": {"aggregation": "sum", "field": "price"}}], "roots": ["a"]}))
    with pytest.raises(ValueError, match="upstream"):
        asyncio.run(live._parse_ast(SimpleNamespace(invoke=invoke), "opaque", ConversationContext("fixture")))
    assert len(calls) == 3
    assert not live._AST_CACHE


def test_missing_resource_entity_is_repaired_before_data_execution():
    live.clear_semantic_cache()
    calls=[]
    def invoke(**kwargs):
        calls.append(kwargs)
        args={"domain":"production","metric":"production_volume"}
        if len(calls)>1:args['mineral']='copper'
        return SimpleNamespace(output=live.ASTProgramModel.model_validate({'nodes':[{'node_id':'r','operator':'retrieve','args':args}],'roots':['r']}))
    result=asyncio.run(live._parse_ast(SimpleNamespace(invoke=invoke),'opaque',ConversationContext('fixture')))
    assert len(calls)==2 and result.nodes[0].args['mineral']=='copper'
    assert 'mineral binding' in calls[1]['payload']['repair']['validation_error']


def test_refresh_must_use_real_saved_binding_not_literal_identifier():
    source=TypedResult.success(ValueType.MINERAL_SET, ["A"], entity=("A",), evidence=(Evidence("structured","fixture","fixture","A"),))
    previous=Turn("past","fixture",UserUtterance(""),semantic_program=SemanticProgram((RequirementNode("root",Operator.ENTITY),),("root",)),result=ExecutionResult("p",ResultStatus.SUCCESS,{"root":source},()))
    context=ConversationContext("fixture",(previous,))
    external="history:past:root"
    bad=SemanticProgram((RequirementNode("r",Operator.RETRIEVE,args={"mineral":external,"metric":"price"}),),("r",))
    declaration=live.ASTProgramModel(result_access="refresh")
    with pytest.raises(ValueError,match="authorized"):
        live._validate_live_contract(bad,declaration,context)
    local=live._history_node_id(external)
    valid=SemanticProgram((RequirementNode(local,Operator.ENTITY),RequirementNode("r",Operator.RETRIEVE,inputs=(InputRef(local),),args={"metric":"price"})),("r",))
    live._validate_live_contract(valid,declaration,context)
    stale=SemanticProgram(valid.nodes,(local,))
    with pytest.raises(ValueError,match="refresh root"):
        live._validate_live_contract(stale,declaration,context)
    extra=SemanticProgram(valid.nodes+(RequirementNode("unbound",Operator.RETRIEVE,args={"metric":"price","mineral":"B"}),),valid.roots)
    with pytest.raises(ValueError,match="refresh retrieval"):
        live._validate_live_contract(extra,declaration,context)


def test_repeated_history_materialization_has_bounded_local_ids():
    identifier="root"
    for turn in range(20):
        external=f"history:turn-{turn}:{identifier}"
        live.ASTInputModel(node_id=external)
        identifier=live._history_node_id(external)
        assert len(identifier)<=80
    assert live._history_node_id("history:turn:price-CU") != live._history_node_id("history:turn:price_CU")
    old="history:turn:ctx_"+"old-reference".encode().hex()*20
    live.ASTInputModel(node_id=old)
    assert len(live._history_node_id(old))<=80


def test_parser_advertises_exact_history_namespace_and_rejects_invented_result():
    live.clear_semantic_cache()
    source=TypedResult.success(ValueType.MINERAL_SET, ["A"], entity=("A",), evidence=(Evidence("structured","fixture","fixture","A"),))
    previous=Turn("past","fixture",UserUtterance(""),semantic_program=SemanticProgram((RequirementNode("root",Operator.ENTITY),),("root",)),result=ExecutionResult("p",ResultStatus.SUCCESS,{"root":source},()))
    context=ConversationContext("fixture",(previous,))
    calls=[]
    def invoke(**kwargs):
        calls.append(kwargs)
        ref="history:past:root"
        return SimpleNamespace(output=live.ASTProgramModel.model_validate({"result_access":"refresh","nodes":[{"node_id":"r","operator":"retrieve","inputs":[{"node_id":ref}],"args":{"domain":"price","metric":"price"}}],"roots":["r"]}))
    result=asyncio.run(live._parse_ast(SimpleNamespace(invoke=invoke),"opaque refresh",context))
    assert len(calls)==1
    assert calls[0]["payload"]["available_input_references"]==["history:past:root"]
    assert result.roots==("r",)


@pytest.mark.parametrize("reason", ["resource_population_unresolved_category", "price_criterion_selection_required:TEST:1=A;2=B", "price_criterion_mapping_missing:TEST"])
def test_adapter_failure_reason_survives_typed_bridge(reason):
    action=live.ActionCall(requirement_id="test",action_id="price.series",slots=live.ActionSlots(mineral="니켈"))
    result=SimpleNamespace(evidence=[],action_results=[SimpleNamespace(evidence=[],status="validation_failed",failure_reason=reason,warnings=[reason])])
    typed=live._typed_from_retrieval(result,action,input_entities=[])
    assert typed.failure_reason==reason.split(":",1)[0]
    assert typed.warnings==(reason,)
    assert not typed.sufficient


def test_adapter_exception_details_do_not_cross_public_boundary():
    call=live.ActionCall(requirement_id="r",action_id="price.series",slots=live.ActionSlots(mineral="니켈"))
    raw=SimpleNamespace(evidence=[],action_results=[SimpleNamespace(evidence=[],status="failed",failure_reason="exception: private connection detail",warnings=[])])
    typed=live._typed_from_retrieval(raw,call,input_entities=[])
    assert typed.failure_reason=="retrieval unavailable: failed"
    assert "private connection detail" not in str(live._result_events(typed))


@pytest.mark.parametrize("action_id,metric,field",[("price.series",None,"price"),("resource.rank","production","production_volume"),("resource.rank","reserves","reserves_volume")])
def test_declared_scalar_value_is_materialized_from_typed_metric(monkeypatch,action_id,metric,field):
    monkeypatch.setattr(live,"_rows",lambda evidence:[{field:12,"year":2024}])
    action=live.ActionCall(requirement_id="r",action_id=action_id,slots=live.ActionSlots(mineral="구리",metric=metric))
    result=SimpleNamespace(evidence=[Evidence("structured","fixture","fixture","A")],action_results=[])
    typed=live._typed_from_retrieval(result,action,input_entities=[])
    assert typed.value[0]['value']==12
    assert typed.metric==("price" if action_id=="price.series" else metric)


def test_typed_boundary_adds_canonical_country_and_metric_fields(monkeypatch):
    monkeypatch.setattr(live, "_rows", lambda evidence: [{
        "국가명": "칠레", "ntn_eng_cd": "CL", "총계": 12,
        "crtr_yr": 2024, "mass_unit_cd": "WT002",
    }])
    action = live.ActionCall(requirement_id="r", action_id="resource.rank",
                             slots=live.ActionSlots(mineral="구리", metric="production"))
    result = SimpleNamespace(evidence=[Evidence("structured", "fixture", "fixture", "A")], action_results=[])
    typed = live._typed_from_retrieval(result, action, input_entities=[])
    row = typed.value[0]
    assert row["country"] == "칠레"
    assert row["country_code"] == "CL"
    assert row["production_volume"] == 12
    assert row["value"] == 12
    assert row["year"] == 2024


def test_typed_boundary_normalizes_inventory_observation_fields(monkeypatch):
    monkeypatch.setattr(live, "_rows", lambda evidence: [{
        "광종": "니켈", "obs_date": "2026-10-01", "invt": 42,
        "weight_unit_code": "WT002",
    }])
    action = live.ActionCall(requirement_id="r", action_id="inventory.latest",
                             slots=live.ActionSlots(mineral="니켈"))
    result = SimpleNamespace(evidence=[Evidence("structured", "fixture", "fixture", "A")], action_results=[])
    typed = live._typed_from_retrieval(result, action, input_entities=[])
    row = typed.value[0]
    assert typed.result_type == live.ValueType.FACT_SET
    assert row["mineral"] == "니켈"
    assert row["date"] == "2026-10-01"
    assert row["inventory"] == 42
    assert row["value"] == 42


@pytest.mark.parametrize("code,expected",[("WT001","USD/kg"),("WT006","USD/lb"),("WT007","USD/톤"),("WT008",None)])
def test_text_and_typed_result_share_verified_unit_registry(code,expected):
    from inhouse.rag_core.ragkit.renderers.price import price_display_unit
    raw=f"통화코드=PR001; 중량단위코드={code}"
    assert price_display_unit(raw)==live._typed_unit(raw)==expected
