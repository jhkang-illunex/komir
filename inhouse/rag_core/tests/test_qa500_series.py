"""Direct helper contracts and test-only gold plans; no production I/O."""
import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from inhouse.rag_core.ragkit.analytical_series import CALCULATIONS, calculate_series
from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory, _resolve_row_field
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode
from inhouse.rag_core.tests.qa500_series_backend import (
    CASES, SUPPORTED, CONTRACT_GAPS, execute, fixture, gold, typed_source,
)


def resolve(rows, field):
    return _resolve_row_field(rows, field, strict=True)


def source(values=(100, 120, 90), **metadata):
    rows = [{'date': f'2025-{i+1:02}-01', 'value': value, 'unit':'USD/t'} for i, value in enumerate(values)]
    return replace(typed_source(rows), **metadata)


def calculate(src=None, operation='endpoint_change', **args):
    return calculate_series(src if src is not None else source(),
        {'calculation':operation, 'field':'value', 'time_field':'date', **args}, resolve)


def assert_rows(actual, expected):
    def stable(rows):
        return sorted(rows, key=lambda row: repr(sorted(row.items())))
    assert len(actual) == len(expected)
    for got, want in zip(stable(actual), stable(expected)):
        assert got.keys() == want.keys()
        for key, value in want.items():
            if isinstance(value, (int, float)):
                assert got[key] == pytest.approx(value, rel=1e-9, abs=1e-8), (key, got, want)
            else:
                assert got[key] == value


def test_endpoint_order_bounds_metadata_and_no_mutation():
    src = source()
    src = replace(src, value=list(reversed(src.value)), entity=('example',), warnings=('synthetic',),
                  period={'start':'2025-01-01','end':'2025-03-31'}, upstream_step_ids=('input',))
    before = deepcopy(src)
    result = calculate(src, start='2025-02-01', end='2025-03-31', endpoint_policy='inside')
    assert result.status == ResultStatus.SUCCESS
    assert result.value == [{'value':-25, 'start_date':'2025-02-01','end_date':'2025-03-01',
                             'start_value':120, 'end_value':90, 'source_unit':'USD/t','observation_count':2}]
    for field in ('source','evidence','provenance','entity','period','warnings','upstream_step_ids'):
        assert getattr(result, field) == getattr(src, field)
    assert result.unit == '%'
    assert src == before


@pytest.mark.parametrize('operation,extra,expected', [
    ('base100',{},[100,120,90]),
    ('periodic_return',{'frequency':'observation'},[20,-25]),
    ('periodic_return',{'frequency':'month'},[20,-25]),
])
def test_series_arithmetic(operation, extra, expected):
    result = calculate(operation=operation, **extra)
    assert result.status == ResultStatus.SUCCESS
    assert [r['value'] for r in result.value] == expected
    assert result.unit == ('index' if operation == 'base100' else '%')


def test_population_division_alias_returns_share_percentage():
    from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
    from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode
    source_result = source((100, 50))
    source_result = replace(source_result, value=[{"country": "A", "value": 100}, {"country": "B", "value": 50}],
                            metric="reserves")
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    result = factory._derive(RequirementNode("share", Operator.CALCULATE,
                                             args={"calculation": "division", "field": "value", "group_by": []}),
                             {"source": source_result})
    assert result.status.value == "success"
    assert result.unit == "%"
    assert [row["value"] for row in result.value] == pytest.approx([100 * 100 / 150, 50 * 100 / 150])
    assert all('unit' not in r for r in result.value)  # No stale USD/t on normalized values.


@pytest.mark.parametrize('operation,extra', [('endpoint_change',{}),('base100',{}),
    ('periodic_return',{'frequency':'observation'})])
def test_zero_base_is_not_null_or_infinity(operation, extra):
    assert calculate(source((0,10)), operation, **extra).failure_reason == 'zero_denominator'
    result = calculate(source((10,0)), operation, **extra)
    assert result.status == ResultStatus.SUCCESS
    assert result.value[-1]['value'] == (0 if operation == 'base100' else -100)


@pytest.mark.parametrize('bad', [True, False, float('nan'), float('inf'), 'oops', [], {}])
def test_reject_invalid_numbers(bad):
    assert calculate(source((100,bad))).status == ResultStatus.ABSTAINED


@pytest.mark.parametrize('metadata,reason', [
    ({'status':ResultStatus.PARTIAL},'incomplete_population'),
    ({'status':ResultStatus.EMPTY},'incomplete_population'),
    ({'status':ResultStatus.ABSTAINED},'incomplete_population'),
    ({'sufficient':False},'evidence_insufficient'),
    ({'evidence':()},'evidence_insufficient'),
    ({'warnings':('incomplete_population',)},'incomplete_population'),
    ({'warnings':('rows_truncated',)},'incomplete_population'),
])
def test_incomplete_source_never_promoted(metadata, reason):
    src = source(**metadata)
    result = calculate(src)
    assert result.failure_reason == reason
    assert result.value is None and not result.sufficient
    assert result.evidence == src.evidence


@pytest.mark.parametrize('args,reason', [
    ({'group_by':{}},'invalid_group_by'),
    ({'group_by':['value','value']},'invalid_group_by'),
    ({'group_by':['missing']},'group_field_unavailable'),
    ({'group_by':['date']},'series_output_collision'),
    ({'output_field':'start_date'},'series_output_collision'),
    ({'time_field':'absent'},'series_fields_required'),
    ({'null_policy':'fill_zero'},'invalid_null_policy'),
    ({'start':'2025-01-01','end':'2025-03-31'},'endpoint_policy_required'),
    ({'endpoint_policy':'nearest'},'unsupported_endpoint_policy'),
    ({'operation':'periodic_return'},'return_frequency_required'),
    ({'operation':'daily_volatility'},'unsupported_calculation_contract'),
])
def test_explicit_contract_rejections(args, reason):
    assert calculate(**args).failure_reason == reason


def test_dates_duplicates_gaps_and_row_status():
    src = source()
    for bad in ('2025-02-30','2025-2-01',None,20250101):
        rows = deepcopy(src.value)
        rows[0]['date'] = bad
        assert calculate(replace(src,value=rows)).failure_reason == 'invalid_series_date'
    for change, reason in [({'date':'2025-01-01'},'duplicate_series_date'),
                           ({'unit':'EUR/t'},'unit_mismatch'),
                           ({'unit':None},'unit_unavailable'),
                           ({'status':'FAILED'},'incomplete_population')]:
        rows = deepcopy(src.value)
        rows[1].update(change)
        assert calculate(replace(src,value=rows)).failure_reason == reason
    gap = replace(src,value=[src.value[0],src.value[2]])
    assert calculate(gap,'periodic_return',frequency='month').failure_reason == 'nonconsecutive_months'
    assert calculate(gap,'periodic_return',frequency='observation').value[0]['value'] == -10


def test_nulls_are_never_implicitly_skipped():
    src = source((100,None,50))
    assert calculate(src).failure_reason == 'series_input_incomplete'
    result = calculate(src,'periodic_return',frequency='observation',null_policy='skip')
    assert result.value == [{'date':'2025-03-01','start_date':'2025-01-01','value':-50}]
    assert 'null_observations_skipped' in result.warnings
    assert calculate(src,'periodic_return',frequency='month',null_policy='skip').status == ResultStatus.ABSTAINED


def test_groups_allow_different_units_but_not_mixed_units_within_series():
    rows = [{**r,'mineral':'A'} for r in source().value]
    rows += [{**r,'mineral':'B','unit':'EUR/kg'} for r in source((20,40,60)).value]
    src = typed_source(rows)
    result = calculate(src,'base100',group_by=['mineral'])
    assert result.status == ResultStatus.SUCCESS
    assert [r['value'] for r in result.value] == [100,120,90,100,200,300]
    assert result.unit == 'index'
    assert calculate(src).status == ResultStatus.ABSTAINED
    for invalid in (None, True, [], float('nan')):
        changed = deepcopy(rows)
        changed[0]['mineral'] = invalid
        assert calculate(typed_source(changed),group_by=['mineral']).failure_reason == 'invalid_group_key'


def test_group_keys_remain_type_distinct():
    rows = [{**r,'key':key} for key in (1,'1') for r in source().value]
    result = calculate(typed_source(rows),group_by='key')
    assert [r['key'] for r in result.value] == [1,'1']


def test_base100_first_valid_date_is_kept_per_group():
    rows = [{**r,'series':'A'} for r in source((100,120,90)).value]
    rows += [{**r,'series':'B'} for r in source((None,40,60)).value]
    result = calculate(typed_source(rows),'base100',group_by='series',null_policy='skip')
    assert result.status == ResultStatus.SUCCESS
    a = [r for r in result.value if r['series'] == 'A']
    b = [r for r in result.value if r['series'] == 'B']
    assert {r['base_date'] for r in a} == {'2025-01-01'}
    assert {r['base_date'] for r in b} == {'2025-02-01'}
    assert [r['value'] for r in b] == [100,150]


def test_first_threshold_hit_and_no_match():
    result = calculate(source((100,40,20)), 'threshold_first', threshold_ratio=.5, comparison='le')
    assert result.value[0]['date'] == '2025-02-01'
    assert result.value[0]['value'] == 40
    assert result.value[0]['matched'] is True
    no_match = calculate(operation='threshold_first',threshold_ratio=.5,comparison='le')
    assert no_match.status == ResultStatus.SUCCESS
    assert no_match.value[0]['matched'] is False and no_match.value[0]['date'] is None


def test_correlation_counts_unmatched_and_rejects_constant():
    rows = [
        {'date':'2025-01-01','value':1,'other':3,'unit':'t','other_unit':'USD/t'},
        {'date':'2025-01-02','value':2,'other':6,'unit':'t','other_unit':'USD/t'},
        {'date':'2025-01-03','value':4,'other':None,'unit':'t','other_unit':None},
        {'date':'2025-01-04','value':None,'other':9,'unit':None,'other_unit':'USD/t'},
    ]
    args = dict(other_field='other',other_unit_field='other_unit',null_policy='pairwise')
    result = calculate(typed_source(rows),'correlation',**args)
    assert result.value == [{'value':1,'observation_count':2,'left_only_count':1,'right_only_count':1,'neither_count':0}]
    assert result.unit == '1'
    rows[1]['value'] = 1
    assert calculate(typed_source(rows),'correlation',**args).failure_reason == 'constant_series'
    rows[1]['other'] = None
    assert calculate(typed_source(rows),'correlation',**args).failure_reason == 'insufficient_sample'


def test_full_join_missing_fields_correlation_uses_real_evidence_and_counts():
    factory = LiveOperatorFactory(message='',session_id='join-series',profile='public',llm=None,history=[])
    left = source((10,20,30))
    right = source((3,6,9))
    right = replace(right,value=[{**r,'date':d,'unit':'t'} for r,d in zip(right.value,
                    ['2025-01-01','2025-02-01','2025-04-01'])],unit='t')
    joined = factory._derive(RequirementNode('join',Operator.JOIN,args={'join_key':'date','how':'full'}),
                             {'left':left,'right':right})
    result = calculate_series(joined, {'calculation':'correlation','time_field':'date','field':'left.value',
        'other_field':'right.value','unit_field':'left_unit','other_unit_field':'right_unit','null_policy':'pairwise'},resolve)
    assert result.status == ResultStatus.SUCCESS, result.failure_reason
    assert result.value == [{'value':pytest.approx(1),'observation_count':2,'left_only_count':1,
                             'right_only_count':1,'neither_count':0}]
    assert result.evidence == joined.evidence


@pytest.mark.parametrize('values', [(), (1,), (None,None)])
def test_empty_single_and_all_null_abstain(values):
    assert calculate(source(values)).status == ResultStatus.ABSTAINED


def test_overflow_is_never_a_success():
    assert calculate(source((1e-308,1e308))).failure_reason == 'invalid_numeric_result'


def test_calendar_month_transition_and_same_month_duplicates():
    src = source((100,110))
    src = replace(src,value=[{**row,'date':day} for row,day in zip(src.value,['2024-12','2025-01'])])
    assert calculate(src,'periodic_return',frequency='month').value[0]['value'] == 10
    src = replace(src,value=[{**row,'date':day} for row,day in zip(src.value,['2025-01-01','2025-01-20'])])
    assert calculate(src,'periodic_return',frequency='month').failure_reason == 'nonconsecutive_months'


@pytest.fixture(scope='module')
def synthetic_db():
    db = fixture()
    yield db
    db.close()


SERIES_CASES = [c for c in CASES if int(c['pattern_id'][4:]) in SUPPORTED]


@pytest.mark.parametrize('case', SERIES_CASES, ids=lambda c:c['id'])
def test_gold_plan_direct_helpers_against_independent_sql(case, synthetic_db):
    program, sources, expected = gold(case, synthetic_db)
    results = {}
    factory = LiveOperatorFactory(message='',session_id='direct-series',profile='public',llm=None,history=[])
    for node in program.nodes:
        if node.node_id in sources:
            result = typed_source(sources[node.node_id][0])
        else:
            inputs = {ref.node_id:results[ref.node_id] for ref in node.inputs}
            if node.operator == Operator.CALCULATE and node.args.get('calculation') in CALCULATIONS:
                result = calculate_series(next(iter(inputs.values())),node.args,resolve)
            else:
                result = factory._derive(node, inputs)
        assert result.status == ResultStatus.SUCCESS, (node, result.failure_reason)
        assert result.evidence
        results[node.node_id] = result
    for root, want in expected.items():
        assert_rows(results[root].value, want)


def delegate_installed():
    factory = LiveOperatorFactory(message='',session_id='delegate-probe',profile='public',llm=None,history=[])
    node = RequirementNode('calc', Operator.CALCULATE, args={
        'calculation':'endpoint_change','field':'value','time_field':'date'})
    # An installed but broken delegate must fail the runtime tests, not skip.
    return factory._derive(node, {'source':source()}).failure_reason != 'unsupported_calculation_contract'


@pytest.mark.parametrize('case', SERIES_CASES, ids=lambda c:c['id'])
def test_gold_real_live_factory_runtime_after_delegate(case, synthetic_db):
    assert delegate_installed(), 'Calculate runtime delegate must remain connected'
    result, expected = asyncio.run(execute(case, synthetic_db))
    for root, want in expected.items():
        actual = result.results[root]
        assert actual.status == ResultStatus.SUCCESS, actual.failure_reason
        assert actual.evidence
        assert_rows(actual.value, want)


def test_scope_accounting_and_uncontracted_semantics_are_explicit():
    assert len(SERIES_CASES) == 32
    assert len({c['id'] for c in SERIES_CASES}) == 32
    assert set(CONTRACT_GAPS) == {43,80}


@pytest.mark.parametrize('case',[c for c in SERIES_CASES if int(c['pattern_id'][4:]) == 63],ids=lambda c:c['id'])
def test_monthly_gold_includes_january_and_explicit_previous_december(case, synthetic_db):
    program, sources, expected = gold(case, synthetic_db)
    year = case['semantic_requirement']['parameter_bindings']['y']
    for node in program.nodes:
        if node.node_id in sources:
            assert node.args['period']['start'] == f'{year-1}-12-01'
    assert len(expected[program.roots[0]]) == 12
    assert expected[program.roots[0]][0]['date'] == f'{year}-01'
