"""A turn's executed intermediates are not conversation outputs.

Reproduces the observed refresh of an inherited population rather than the
previous projected subset. Identities, cardinality and projection vary.
"""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult, ExecutionResult, ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import SemanticProgram, RequirementNode, Operator, InputRef, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


def state(total=16, selected=7):
    entities=[f'fixture-{i}' for i in range(total)]
    ev=(Evidence('structured','synthetic','fixture','Synthetic population'),)
    full=TypedResult.success(ValueType.FACT_SET,[{'mineral':x,'value':i,'status':'success'} for i,x in enumerate(entities)],entity=tuple(entities),evidence=ev)
    subset=TypedResult.success(ValueType.FACT_SET,[{'mineral':x} for x in entities[-selected:]],entity=tuple(entities[-selected:]),evidence=ev)
    old=Turn('old','session',UserUtterance(''),semantic_program=SemanticProgram((RequirementNode('full',Operator.RETRIEVE,args={'domain':'price'}),),('full',)),result=ExecutionResult('old-pipe',ResultStatus.SUCCESS,{'full':full},()),result_id='old-result')
    inherited=live._history_node_id('history:old:full')
    new=Turn('new','session',UserUtterance(''),semantic_program=SemanticProgram((RequirementNode(inherited,Operator.ENTITY,args={'values':full.value}),RequirementNode('selected',Operator.PROJECT,inputs=(InputRef(inherited),),args={'fields':['mineral']})),('selected',)),result=ExecutionResult('new-pipe',ResultStatus.SUCCESS,{inherited:full,'selected':subset},()),result_id='new-result')
    return ConversationContext('session',(old,new)),inherited,subset


def request(ref):
    return {'result_access':'refresh','nodes':[{'node_id':'fetch','operator':'retrieve','inputs':[{'node_id':ref}],'args':{'domain':'price','metric':'price'}}],'roots':['fetch']}


def test_repair_output_contract_does_not_drop_requested_projection_fields():
    previous = {
        'nodes': [{'node_id': 'p', 'operator': 'project',
                   'inputs': [{'node_id': 'saved'}],
                   'args': {'fields': ['mineral', 'value', 'unit']}}],
        'roots': ['p'],
    }
    reduced = {
        'nodes': [{'node_id': 'p2', 'operator': 'project',
                   'inputs': [{'node_id': 'saved'}],
                   'args': {'fields': ['mineral', 'status', 'unit']}}],
        'roots': ['p2'],
    }
    assert live._root_projection_fields(previous) == {'mineral', 'value', 'unit'}
    assert live._root_projection_fields(reduced) == {'mineral', 'status', 'unit'}
    assert live._root_projection_fields(previous) - live._root_projection_fields(reduced) == {'value'}


@pytest.mark.parametrize('total,selected',[(16,7),(3,1),(31,5)])
def test_only_requested_outputs_are_exposed_not_inherited_population(total,selected):
    context,inherited,subset=state(total,selected)
    payload=live._semantic_context_payload(context)
    assert [r['step_id'] for r in payload[-1]['results']]==['selected']
    assert payload[-1]['results'][0]['entity']==list(subset.entity)
    assert inherited in context.latest.result.results  # provenance not deleted


def test_explicit_intermediate_reference_is_rejected_not_silently_retargeted():
    context,inherited,_=state()
    hidden=f'history:new:{inherited}'
    program=SemanticProgram.from_dict(live._normalize_history_aliases(request(hidden),context))
    with pytest.raises(ValueError,match='intermediate entity'):
        live._validate_live_contract(program,live.ASTProgramModel(result_access='refresh'),context)


def test_runtime_preserves_provenance_bindings_while_parser_hides_intermediate():
    context,inherited,_=state()
    factory=live.LiveOperatorFactory(message='',session_id='session',profile='public',llm=None,history=[],context=context)
    assert live._history_node_id(f'history:new:{inherited}') in factory.saved_results
    assert inherited not in str(live._semantic_context_payload(context))
    assert live._history_node_id('history:old:full') in factory.saved_results
    assert live._history_node_id('history:new:selected') in factory.saved_results
    assert live._history_node_id('result:new-result') in factory.saved_results


def test_validator_cannot_accept_pre_materialized_hidden_result():
    context,inherited,_=state()
    local=live._history_node_id(f'history:new:{inherited}')
    program=SemanticProgram((RequirementNode(local,Operator.ENTITY),RequirementNode('fetch',Operator.RETRIEVE,inputs=(InputRef(local),),args={'domain':'price'})),('fetch',))
    with pytest.raises(ValueError,match='intermediate entity'):
        live._validate_live_contract(program,live.ASTProgramModel(result_access='refresh'),context)


@pytest.mark.parametrize('ref,count',[('previous',7),('history:new:selected',7),('result:new-result',7),('history:old:full',16),('result:old-result',16)])
def test_valid_output_binding_preserves_selected_population(ref,count):
    context,_,_=state()
    program=SemanticProgram.from_dict(live._normalize_history_aliases(request(ref),context))
    scope='explicit_history' if ref in {'history:old:full','result:old-result'} else 'active'
    live._validate_live_contract(program,live.ASTProgramModel(result_access='refresh',reference_scope=scope),context)
    factory=live.LiveOperatorFactory(message='',session_id='session',profile='public',llm=None,history=[],context=context)
    entity=next(n for n in program.nodes if n.operator==Operator.ENTITY)
    saved=factory._entity(entity)
    assert len(saved.entity)==count
    async def call(node,action_id,*,mineral=None,minerals=None):
        return TypedResult.success(ValueType.TIME_SERIES,[{'price':1}],entity=(mineral,),evidence=saved.evidence,unit='USD/kg')
    factory._call_action=AsyncMock(side_effect=call)
    retrieval=next(n for n in program.nodes if n.node_id=='fetch')
    result=asyncio.run(factory._retrieve(retrieval,{entity.node_id:saved}))
    assert factory._call_action.await_count==count
    assert {row['mineral'] for row in result.value}==set(saved.entity)


def test_model_wrong_intermediate_requires_repair_not_execution():
    context,inherited,_=state()
    calls=[]
    def invoke(**kwargs):
        calls.append(kwargs)
        ref=f'history:new:{inherited}' if len(calls)==1 else 'history:new:selected'
        return SimpleNamespace(output=live.ASTProgramModel.model_validate(request(ref)))
    live.clear_semantic_cache()
    asyncio.run(live._parse_ast(SimpleNamespace(invoke=invoke),'opaque',context))
    assert len(calls)==2
    assert f'history:new:{inherited}' not in calls[0]['payload']['available_input_references']
    assert calls[1]['payload']['repair']['validation_error']


def test_multiple_explicit_outputs_and_legacy_single_output_remain_available():
    context,inherited,subset=state()
    turn=context.latest
    two=replace(turn,semantic_program=SemanticProgram(turn.semantic_program.nodes,(inherited,'selected')))
    assert set(live._turn_output_results(two))=={inherited,'selected'}
    legacy=replace(turn,semantic_program=None,result=ExecutionResult('p',ResultStatus.SUCCESS,{'saved':subset},()))
    assert live._turn_output_results(legacy)=={'saved':subset}
    assert not live._turn_output_results(replace(turn,semantic_program=None))


def test_current_program_intermediates_are_unaffected():
    context,_,_=state()
    raw={'nodes':[{'node_id':'intermediate','operator':'retrieve','args':{'domain':'price','mineral':'copper'}},
                  {'node_id':'final','operator':'project','inputs':[{'node_id':'intermediate'}],'args':{'fields':['price']}}], 'roots':['final']}
    assert SemanticProgram.from_dict(live._normalize_history_aliases(raw,context)).to_dict()==SemanticProgram.from_dict(raw).to_dict()


def test_historical_declaration_does_not_publish_inherited_scratch_binding():
    context,inherited,_=state()
    program=SemanticProgram.from_dict(live._normalize_history_aliases(request(f'history:new:{inherited}'),context))
    with pytest.raises(ValueError,match='intermediate entity'):
        live._validate_live_contract(program,live.ASTProgramModel(result_access='refresh',reference_scope='explicit_history'),context)


def test_query_mode_cannot_bypass_active_scope_and_old_root_requires_explicit_intent():
    context,_,_=state()
    program=SemanticProgram.from_dict(live._normalize_history_aliases(request('history:old:full'),context))
    with pytest.raises(ValueError,match='active reference'):
        live._validate_live_contract(program,live.ASTProgramModel(result_access='query'),context)
    live._validate_live_contract(program,live.ASTProgramModel(result_access='query',reference_scope='explicit_history'),context)


@pytest.mark.parametrize('alias',['previous','result:selected'])
def test_multiroot_shorthand_never_falls_back_to_first_output(alias):
    context,inherited,_=state()
    turn=context.latest
    turn=replace(turn,semantic_program=SemanticProgram(turn.semantic_program.nodes,(inherited,'selected')))
    context=replace(context,turns=(context.turns[0],turn))
    with pytest.raises(ValueError,match='unknown'):
        SemanticProgram.from_dict(live._normalize_history_aliases(request(alias),context))
    correct=SemanticProgram.from_dict(live._normalize_history_aliases(request('history:new:selected'),context))
    factory=live.LiveOperatorFactory(message='',session_id='session',profile='public',llm=None,history=[],context=context)
    restored=factory._entity(next(n for n in correct.nodes if n.operator==Operator.ENTITY))
    assert len(restored.entity)==7
