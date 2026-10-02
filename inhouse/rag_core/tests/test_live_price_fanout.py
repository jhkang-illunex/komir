import asyncio
from unittest.mock import AsyncMock

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.semantic_ir import RequirementNode, Operator, ValueType
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult, ResultStatus
from inhouse.rag_core.retrieval.evidence import Evidence


def run(failure=False):
    factory=live.LiveOperatorFactory(message="",session_id="fixture",profile="public",llm=None,history=[])
    async def action(node,action_id,*,mineral=None,minerals=None):
        assert minerals==[mineral]
        assert node.args['output']=='latest_value'
        if failure and mineral=='B':return TypedResult.empty(ValueType.TIME_SERIES,'price_criterion_selection_required')
        return TypedResult.success(ValueType.TIME_SERIES,[{'date':'2024-01-01','price':10 if mineral=='A' else 20}],entity=(mineral,),unit='USD/kg' if mineral=='A' else 'USD/톤',evidence=(Evidence('structured','fixture','fixture',mineral),))
    factory._call_action=AsyncMock(side_effect=action)
    node=RequirementNode('retrieve',Operator.RETRIEVE,args={'domain':'price','metric':'price'})
    source=TypedResult.success(ValueType.MINERAL_SET,['A','B'],entity=('A','B'))
    result=asyncio.run(factory._retrieve(node,{'saved':source}))
    return factory,result


def test_multi_price_retrieval_materializes_each_entity_and_unit():
    factory,result=run()
    assert factory._call_action.await_count==2
    assert result.status==ResultStatus.SUCCESS
    assert [(r['mineral'],r['price'],r['unit']) for r in result.value]==[('A',10,'USD/kg'),('B',20,'USD/톤')]
    projected=factory._derive(RequirementNode('project',Operator.PROJECT,args={'fields':['mineral','price','value','date','unit']}),{'source':result})
    assert projected.status==ResultStatus.SUCCESS and len(projected.value)==2
    assert [row['value'] for row in projected.value]==[10,20]
    events=live._result_events(projected)
    assert any(event.type=='table' for event in events)
    assert not any(event.type=='chart' for event in events)
    aggregate=factory._derive(RequirementNode('sum',Operator.AGGREGATE,args={'aggregation':'sum','field':'price'}),{'source':result})
    assert aggregate.failure_reason=='unit_mismatch'


def test_failed_price_entity_is_not_erased_by_projection():
    factory,result=run(True)
    assert result.status==ResultStatus.PARTIAL
    projected=factory._derive(RequirementNode('project',Operator.PROJECT,args={'fields':['mineral','price','date','unit']}),{'source':result})
    assert projected.status==ResultStatus.PARTIAL
    failed=next(r for r in projected.value if r['mineral']=='B')
    assert failed['status']=='empty' and failed['reason']=='price_criterion_selection_required'
    successful=factory._derive(RequirementNode('f',Operator.FILTER,args={'field':'status','operator':'equals','value':'success'}),{'source':projected})
    assert [row['mineral'] for row in successful.value]==['A']
    compact=factory._derive(RequirementNode('p',Operator.PROJECT,args={'fields':['mineral','price']}),{'source':result})
    assert next(row for row in compact.value if row['mineral']=='A')['unit']=='USD/kg'
    with_status=factory._derive(RequirementNode('project',Operator.PROJECT,args={'fields':['mineral','price','status']}),{'source':result})
    events=live._result_events(with_status)
    assert '1개 처리 완료' in str(events)


def test_refresh_preserves_per_output_metadata_for_downstream_projection():
    from inhouse.rag_core.ragkit.semantic_ir import SemanticProgram, InputRef
    factory,result=run(True)
    fields=['mineral','price','status','reason','output','unit']
    SemanticProgram((RequirementNode('r',Operator.RETRIEVE,args={'metric':'price'}),
                     RequirementNode('p',Operator.PROJECT,inputs=(InputRef('r'),),args={'fields':fields})),('p',))
    projected=factory._derive(RequirementNode('p',Operator.PROJECT,args={'fields':fields}),{'r':result})
    assert projected.status==ResultStatus.PARTIAL
    success,failed=projected.value
    assert success['status']=='success' and success['reason'] is None
    assert failed['status']=='empty' and failed['reason']=='price_criterion_selection_required'
    assert success['output']==failed['output']=='latest_value'
    assert failed['price'] is None


def test_projection_cannot_hide_mixed_units_from_aggregate():
    factory,result=run()
    for args in ({'fields':['mineral','price']}, {'fields':['mineral','price','unit'],'aliases':{'unit':'단위'}}):
        projected=factory._derive(RequirementNode('p',Operator.PROJECT,args=args),{'source':result})
        total=factory._derive(RequirementNode('a',Operator.AGGREGATE,args={'aggregation':'sum','field':'price'}),{'source':projected})
        assert total.failure_reason=='unit_mismatch'
        assert not any(e.type=='chart' for e in live._result_events(projected))
    retained=factory._derive(RequirementNode('p',Operator.PROJECT,args={'fields':['mineral','price','unit']}),{'source':result})
    filtered=factory._derive(RequirementNode('f',Operator.FILTER,args={'field':'mineral','operator':'equals','value':'A'}),{'source':retained})
    total=factory._derive(RequirementNode('a',Operator.AGGREGATE,args={'aggregation':'sum','field':'price'}),{'source':filtered})
    assert total.status==ResultStatus.SUCCESS
    assert total.unit=='USD/kg'
    fabricated=factory._derive(RequirementNode('p',Operator.PROJECT,args={'fields':['mineral','price','date'],'aliases':{'date':'unit'}}),{'source':result})
    assert fabricated.failure_reason=='projection_reserved_unit_alias'
    indirect=factory._derive(RequirementNode('p',Operator.PROJECT,args={'fields':['mineral','price','date'],'aliases':{'date':'단위'}}),{'source':result})
    assert indirect.failure_reason=='projection_reserved_unit_alias'
    for reserved in ('unit(label)', '단위(label)'):
        first=factory._derive(RequirementNode('p',Operator.PROJECT,args={'fields':['mineral','price','date'],'aliases':{'date':reserved}}),{'source':result})
        assert first.failure_reason=='projection_reserved_unit_alias'
