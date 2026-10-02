from types import SimpleNamespace
import pytest
from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult, ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import RequirementNode, Operator, ValueType


def execute(op, args, rows):
    factory = LiveOperatorFactory(message="", session_id="qa500", profile="public", llm=None, history=[])
    return factory._derive(RequirementNode("op", op, args=args), {
        "source": TypedResult.success(ValueType.FACT_SET, rows, unit="t")})


def test_grouped_mean_counts_valid_rows_and_preserves_zero():
    result = execute(Operator.AGGREGATE, {"field": "value", "aggregation": "mean", "group_by": ["month"],
        "include_count": True, "null_policy": "skip"}, [
        {"month": "01", "value": 0}, {"month": "01", "value": 10},
        {"month": "01", "value": None}, {"month": "02", "value": 20}])
    assert result.value == [{"month": "01", "value": 5, "observation_count": 2},
                            {"month": "02", "value": 20, "observation_count": 1}]


@pytest.mark.parametrize("operator", [Operator.ARG_MAX, Operator.ARG_MIN])
def test_explicit_extremum_ties_are_not_silently_dropped(operator):
    result = execute(operator, {"field": "value", "ties": "all"}, [
        {"date": "a", "value": 10}, {"date": "b", "value": 10}, {"date": "c", "value": None}])
    assert [row["date"] for row in result.value] == ["a", "b"]


def test_calendar_year_not_limited_by_month_count():
    from inhouse.rag_core.ragkit.semantic_v2 import TimeRange
    assert TimeRange(kind="calendar_year", value=2025).to_period().calendar_year == 2025
    with pytest.raises(ValueError):
        TimeRange(kind="trailing_months", value=2025)


def test_v2_aggregate_and_calculation_are_executable_nodes_not_retrieve_labels():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements
    plan = SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'r','metric':'import_value','dimension':'country',
         'aggregation':'sum','operation':'share','entity':{'value':'니켈'}}]})
    program = logical_program_from_requirements(plan)
    assert [n.op.value for n in program.nodes] == ['Retrieve','Aggregate','Calculate']
    assert program.nodes[1].arguments['group_by'] == ['country']
    assert program.nodes[2].arguments['calculation'] == 'share'


def test_redundant_measure_annotation_never_generates_fake_calculation():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2,logical_program_from_requirements
    plan=SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'r','metric':'price','operation':'high_price',
         'selection':{'mode':'argmax','field':'high_price','ties':'all'}}]})
    program=logical_program_from_requirements(plan)
    assert [n.op.value for n in program.nodes]==['Retrieve','Select']
    assert program.nodes[-1].arguments['field']=='high_price'
    assert program.nodes[-1].arguments['ties']=='all'


def test_v2_trade_comparison_does_not_become_price_action():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements, LegacyActionLowerer
    plan = SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'a','metric':'import_value','entity':{'value':'니켈'}},
        {'requirement_id':'b','metric':'import_value','entity':{'value':'구리'}}],
        'relationships':[{'kind':'compare','inputs':['a','b'],'fields':['value']}]})
    calls = LegacyActionLowerer().lower(logical_program_from_requirements(plan))
    assert [c.action_id for c in calls] == ['trade.monthly','trade.monthly']
    assert all(c.slots.metric=='import_amount' for c in calls)


def test_v2_static_retrieval_satisfies_existing_required_action_slots():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements, LegacyActionLowerer
    from inhouse.rag_core.ragkit.action_contract import REQUIRED
    for metric in ('import_value','production','reserves'):
        plan=SemanticRequirementPlanV2.model_validate({'requirements':[
            {'requirement_id':'r','metric':metric,'entity':{'value':'니켈'}}]})
        calls=LegacyActionLowerer().lower(logical_program_from_requirements(plan))
        for call in calls:
            assert all(getattr(call.slots,f) is not None for f in REQUIRED[call.action_id]),call


def test_share_and_hhi_do_not_use_top_n_denominator():
    rows = [{'country':'A','value':1},{'country':'B','value':1},{'country':'C','value':2}]
    share = execute(Operator.CALCULATE, {'calculation':'share','field':'value'}, rows)
    hhi = execute(Operator.CALCULATE, {'calculation':'hhi','field':'value'}, rows)
    assert [r['value'] for r in share.value] == [25,25,50]
    assert hhi.value == [{'value':3750}]
    assert share.unit == '%'
    for invalid in (None,-1,float('nan'),True):
        bad = execute(Operator.CALCULATE, {'calculation':'share','field':'value'}, [{'value':invalid}])
        assert bad.status == ResultStatus.ABSTAINED


def test_null_excluded_sum_cannot_become_complete_share_denominator():
    rows=[{'country':'A','value':100},{'country':'A','value':None},{'country':'B','value':100}]
    result=execute(Operator.AGGREGATE,{'aggregation':'sum','field':'value','group_by':['country'],'null_policy':'skip'},rows)
    assert result.status==ResultStatus.PARTIAL
    assert result.warnings==('aggregate_nulls_excluded:1',)
    factory=LiveOperatorFactory(message='',session_id='qa500',profile='public',llm=None,history=[])
    for calculation in ('share','hhi'):
        shares=factory._derive(RequirementNode('share',Operator.CALCULATE,args={'field':'value','calculation':calculation}),{'source':result})
        assert shares.status==ResultStatus.ABSTAINED
        assert shares.failure_reason=='incomplete_population'
    stale=execute(Operator.AGGREGATE,{'aggregation':'sum','field':'value'},[
        {'value':1,'status':'SUCCESS'},{'value':999,'status':'EXECUTION_FAILED'}])
    assert stale.failure_reason=='incomplete_population'


def test_count_non_numeric_dimension_values():
    result=execute(Operator.AGGREGATE,{'aggregation':'count','field':'mineral','group_by':['mineral']},[
        {'mineral':'니켈'},{'mineral':'니켈'},{'mineral':'리튬'}])
    # An explicit alias is required when the count field is also a group key.
    assert result.failure_reason=='aggregate_output_collision'
    result=execute(Operator.AGGREGATE,{'aggregation':'count','field':'mineral','group_by':['mineral'],'output_field':'count'},[
        {'mineral':'니켈'},{'mineral':'니켈'},{'mineral':'리튬'}])
    assert result.value==[{'mineral':'니켈','count':2},{'mineral':'리튬','count':1}]
    assert result.unit is None


def test_date_sort_is_not_a_numeric_noop():
    result=execute(Operator.SORT,{'field':'date','order':'desc'},[
        {'date':'2025-01-01'},{'date':'2025-12-01'},{'date':None}])
    assert [r['date'] for r in result.value] == ['2025-12-01','2025-01-01',None]


def test_date_extrema_select_actual_first_and_latest_dates():
    rows=[{'date':'2025-12-01','value':1},{'date':'2025-01-01','value':20},{'date':None,'value':999}]
    maximum=execute(Operator.ARG_MAX,{'field':'date'},rows)
    minimum=execute(Operator.ARG_MIN,{'field':'date'},rows)
    assert maximum.value==[rows[0]]
    assert minimum.value==[rows[1]]


def test_project_explicit_alias_preserves_join_namespaces_without_collisions():
    result=execute(Operator.PROJECT,{'fields':['left.month','left.value'],'aliases':{'left.month':'month','left.value':'value'}},[
        {'left.month':'01','left.value':10,'right.value':5}])
    assert result.value==[{'month':'01','value':10}]
    bad=execute(Operator.PROJECT,{'fields':['left.value','right.value'],'aliases':{'left.value':'value','right.value':'value'}},[
        {'left.value':10,'right.value':5}])
    assert bad.failure_reason=='projection_output_collision'


def test_topk_keeps_document_type_for_mineral_projection():
    factory=LiveOperatorFactory(message='',session_id='qa500',profile='public',llm=None,history=[])
    source=TypedResult.success(ValueType.DOCUMENT_EVIDENCE,[{'mineral_list':['니켈','리튬']}])
    selected=factory._derive(RequirementNode('top',Operator.TOP_K,args={'k':1}),{'source':source})
    assert selected.result_type==ValueType.DOCUMENT_EVIDENCE
    projected=factory._derive(RequirementNode('list',Operator.PROJECT,args={'fields':['mineral_list']}),{'source':selected})
    assert projected.value==['니켈','리튬']


def test_filtered_mineral_set_does_not_restore_stale_entity_binding():
    factory=LiveOperatorFactory(message='',session_id='qa500',profile='public',llm=None,history=[])
    source=TypedResult.success(ValueType.MINERAL_SET,['니켈','리튬'],entity=('니켈','리튬'))
    result=factory._derive(RequirementNode('filter',Operator.FILTER,args={
        'predicate':{'field':'mineral','operator':'not_equals','value':'니켈'}}),{'source':source})
    assert result.value==['리튬'] and result.entity==('리튬',)
    empty=factory._derive(RequirementNode('filter2',Operator.FILTER,args={
        'predicate':{'field':'mineral','operator':'equals','value':'없는 광종'}}),{'source':result})
    assert empty.value==[] and empty.entity==()


def test_lowering_preserves_reserve_metric_and_as_of():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements, LegacyActionLowerer
    plan=SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'r','metric':'reserves','entity':{'value':'구리'},'time_range':{'kind':'latest','end':'2025-03-31'}}]})
    call=LegacyActionLowerer().lower(logical_program_from_requirements(plan))[0]
    assert call.slots.metric=='reserves'
    assert call.slots.period.end=='2025-03-31'


def test_explicit_iso_date_bounds_normalize_without_raw_query_parsing():
    from inhouse.rag_core.ragkit.semantic_v2 import TimeRange
    for kind in ('period','month','monthly','specific_period','specific_month','quarter','custom'):
        period=TimeRange(kind=kind,start='2025-01-01',end='2025-03-31').to_period()
        assert (period.start,period.end)==('2025-01-01','2025-03-31')
    with pytest.raises(ValueError):
        TimeRange(kind='quarter',value=2).to_period()


def test_document_requirement_never_turns_into_usage_lookup():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements, LegacyActionLowerer
    plan=SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'r','metric':'document_evidence','entity':{'value':'니켈'},
         'document_requirement':{'topic':'희소금속 월간동향'}}]})
    call=LegacyActionLowerer().lower(logical_program_from_requirements(plan))[0]
    assert call.slots.topic=='희소금속 월간동향'


def test_lowering_revalidates_model_copy_slots():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements, LegacyActionLowerer
    plan=SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'r','metric':'indicator','indicator':'observation_count'}]})
    with pytest.raises(ValueError):
        LegacyActionLowerer().lower(logical_program_from_requirements(plan))


def test_scalar_broadcast_requires_explicit_direction_and_typed_scalar():
    from inhouse.rag_core.retrieval.evidence import Evidence
    factory=LiveOperatorFactory(message='',session_id='qa500',profile='public',llm=None,history=[])
    evidence=(Evidence('structured','synthetic','test','fixture'),)
    data=TypedResult.success(ValueType.FACT_SET,[{'month':'01','value':10},{'month':'02','value':20}],unit='t',evidence=evidence)
    mean=TypedResult.success(ValueType.SCALAR_METRIC,[{'value':15}],unit='t',evidence=evidence)
    args={'field':'value','operation':'difference'}
    refused=factory._derive(RequirementNode('compare',Operator.COMPARE,args=args),{'data':data,'mean':mean})
    assert refused.failure_reason=='comparison_alignment_required'
    accepted=factory._derive(RequirementNode('compare',Operator.COMPARE,args={**args,'broadcast':'right'}),{'data':data,'mean':mean})
    assert [r['difference'] for r in accepted.value]==[-5,5]
    assert [r['left.month'] for r in accepted.value]==['01','02']
    assert accepted.unit=='t' and accepted.evidence==evidence+evidence
    refused=factory._derive(RequirementNode('compare',Operator.COMPARE,args={**args,'broadcast':'left'}),{'data':data,'mean':mean})
    assert refused.failure_reason=='broadcast_requires_typed_scalar'


def test_explicit_inputref_slot_roles_do_not_substitute_reporter_and_partner():
    import asyncio
    from inhouse.rag_core.ragkit.semantic_ir import InputRef
    class Capture(LiveOperatorFactory):
        async def _call_action(self,node,action_id,**kwargs):
            from inhouse.rag_core.ragkit.live_multihop import _action_slots
            return TypedResult.success(ValueType.FACT_SET,_action_slots(node,**kwargs).model_dump())
    async def run():
        factory=Capture(message='',session_id='qa500',profile='public',llm=None,history=[])
        node=RequirementNode('read',Operator.RETRIEVE,(InputRef('prior','field','partner_country'),),args={
            'domain':'trade','metric':'import_value','mineral':'니켈','reporter_country':'KR'})
        source=TypedResult.success(ValueType.FACT_SET,['CL'])
        result=await factory._retrieve(node,{'input_0':source})
        assert result.value['reporter_country']=='KR'
        assert result.value['partner_country']=='CL'
        assert result.value['mineral']=='니켈'
        unrelated=await factory._retrieve(node,{'input_0':TypedResult.success(ValueType.FACT_SET,['CL'],entity=('구리',))})
        assert unrelated.value['mineral']=='니켈'
        ambiguous=await factory._retrieve(node,{'input_0':TypedResult.success(ValueType.FACT_SET,['CL','CN'])})
        assert ambiguous.failure_reason=='ambiguous_or_missing_slot_binding'
    asyncio.run(run())


def test_history_reference_ids_are_lossless_and_do_not_alias_steps():
    from inhouse.rag_core.ragkit.live_multihop import _history_node_id, _normalize_history_aliases
    from inhouse.rag_core.ragkit.history_context import ConversationContext, Turn, UserUtterance
    from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult
    from inhouse.rag_core.ragkit.semantic_ir import SemanticProgram
    a=TypedResult.success(ValueType.SCALAR_METRIC,[{'value':10}])
    b=TypedResult.success(ValueType.SCALAR_METRIC,[{'value':20}])
    turn=Turn('t','s',UserUtterance(''),result=ExecutionResult('p',ResultStatus.SUCCESS,{'price-CU':a,'price_CU':b},()))
    context=ConversationContext('s',(turn,))
    payload={'nodes':[{'node_id':'a','operator':'project','inputs':[{'node_id':'history:t:price-CU'}],'args':{'fields':['value']}},
                      {'node_id':'b','operator':'project','inputs':[{'node_id':'history:t:price_CU'}],'args':{'fields':['value']}}],
             'roots':['a','b']}
    normalized=_normalize_history_aliases(payload,context)
    program=SemanticProgram.from_dict(normalized)
    factory=LiveOperatorFactory(message='',session_id='s',profile='public',llm=None,history=[],context=context)
    ids=[_history_node_id('history:t:'+key) for key in ('price-CU','price_CU')]
    assert ids[0]!=ids[1]
    assert [factory._entity(next(n for n in program.nodes if n.node_id==key)).value for key in ids]==[a.value,b.value]


def test_single_requested_output_fields_become_final_project_not_retrieve_annotation():
    from inhouse.rag_core.ragkit.semantic_v2 import SemanticRequirementPlanV2, logical_program_from_requirements
    plan=SemanticRequirementPlanV2.model_validate({'requirements':[
        {'requirement_id':'r','metric':'price','entity':{'value':'구리'},
         'selection':{'mode':'argmax','field':'high_price','ties':'all'}}],
        'requested_outputs':[{'name':'peak','fields':['date','high_price']}]})
    program=logical_program_from_requirements(plan)
    assert [n.op.value for n in program.nodes]==['Retrieve','Select','Project']
    assert program.roots==[program.nodes[-1].node_id]
    assert program.nodes[-1].arguments=={'fields':['date','high_price']}
    assert program.nodes[-1].inputs[0].node_id==program.nodes[-2].node_id
    # An explicitly different source is not silently replaced by the root.
    plan.requested_outputs[0].source_node='unknown'
    with pytest.raises(ValueError, match='requested_output_source_unknown'):
        logical_program_from_requirements(plan)


def test_project_missing_column_is_not_successful_null_but_real_null_is_preserved():
    missing=execute(Operator.PROJECT,{'fields':['value','country_count']},[{'value':10}])
    assert missing.status==ResultStatus.ABSTAINED
    assert missing.failure_reason=='projection_field_unavailable:country_count'
    actual_null=execute(Operator.PROJECT,{'fields':['value','unit']},[{'value':None}])
    assert actual_null.value==[{'value':None,'unit':'t'}]
    incomplete=execute(Operator.PROJECT,{'fields':['value']},[{'value':10},{'country':'A'}])
    assert incomplete.failure_reason=='projection_input_incomplete'
    empty=execute(Operator.PROJECT,{'fields':['value']},[])
    assert empty.status==ResultStatus.SUCCESS and empty.value==[]
