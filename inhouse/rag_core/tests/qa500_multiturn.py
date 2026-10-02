"""Offline gold-plan regression: real typed store, InputRef, lowering and runtime.

Only synthetic I/O is substituted. No Gemma, service, PostgreSQL or deployment.
PASS means a complete *gold backend* conversation, never natural-language parsing.
BLOCKED/GOLD_NOT_IMPLEMENTED is a fixture limitation, not a production capability.
Run: PYTHONPATH=inhouse python3 -m inhouse.rag_core.tests.qa500_multiturn
The CLI emits all 40 records and counts as JSON to stdout; run() returns the same.
"""
import asyncio
from collections import Counter
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
from types import SimpleNamespace

from inhouse.rag_core.tests.qa500_backend import CASES, fixture, query
from inhouse.rag_core.ragkit.action_results import ItemResult
from inhouse.rag_core.ragkit.history_context import InMemoryHistoryStore, Turn, UserUtterance
from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory, _resolve_history_references, _normalize_history_aliases, _action_slots
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, PipeRuntime, TypedResult, ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


MULTITURN_CASES = tuple(c for c in CASES if 'multiturn' in c['tags'])
COUNTRY_CODES = {'인도네시아': 'ID', '칠레': 'CL', '호주': 'AU', '콩고민주공화국': 'CD', '중국': 'CN', '한국': 'KR'}


def node(name, op, *refs, **args):
    return RequirementNode(name, op, tuple(r if isinstance(r, InputRef) else InputRef(r) for r in refs), args)


def typed(rows, case, *, metric='price', unit='USD/t', kind=ValueType.TIME_SERIES):
    b = case['semantic_requirement']['parameter_bindings']
    return TypedResult.success(kind, rows, entity=(b['m'],), metric=metric,
        period={'kind': 'calendar_year', 'calendar_year': b['y']}, unit=unit,
        source=('qa500:synthetic-sqlite',), provenance=('qa500:test-only',),
        evidence=(Evidence('structured', 'qa500:synthetic-sqlite', case['id'], json.dumps(rows, ensure_ascii=False)),))


def public(result):
    return asdict(result)


def assert_rows(actual, expected):
    assert actual.status == ResultStatus.SUCCESS, public(actual)
    assert len(actual.value) == len(expected), (actual.value, expected)
    for a, e in zip(actual.value, expected):
        assert a.keys() == e.keys(), (a, e)
        for k, v in e.items():
            if isinstance(v, (int, float)):
                assert isinstance(a[k], (int, float)) and math.isclose(a[k], v, rel_tol=1e-9, abs_tol=1e-8), (a, e)
            else:
                assert a[k] == v, (a, e)


class Conversation:
    """Fresh per-case real store; fixture sources cannot intercept history nodes."""
    def __init__(self, case):
        self.case = case
        self.session = case['id']
        self.store = InMemoryHistoryStore()
        self.turns = []
        self.source_calls = []
        self.action_calls = []
        self.common_path_gaps = []

    async def execute(self, number, nodes, roots, sources=None, action_reader=None):
        sources = sources or {}
        context = await self.store.get_context(self.session)
        raw = {'nodes': [n.to_dict() for n in nodes], 'roots': list(roots)}
        # Exercise the exact post-model entry order used by _parse_ast/run_live.
        # Do not conceal strict IR validation rejecting historical external IDs.
        try:
            common = SemanticProgram.from_dict(_normalize_history_aliases(raw, context))
            resolved = _resolve_history_references(common, context)
        except ValueError as exc:
            self.common_path_gaps.append({'turn': number, 'reason': str(exc),
                'raw_ast': raw, 'location': '_parse_ast: SemanticProgram.from_dict before _resolve_history_references'})
            # No test-only materialization fallback: regressions must fail at
            # the same entry boundary as production.
            raise
        owner = self

        class OfflineFactory(LiveOperatorFactory):
            async def _call_action(self, n, action_id, *, mineral=None, minerals=None):
                # Deliberately no fall-through to real tool I/O. Record binding
                # defects even where action execution cannot be completed.
                owner.action_calls.append({'node': n.node_id, 'action': action_id,
                    'mineral': mineral, 'slots': _action_slots(n, mineral=mineral, minerals=minerals).model_dump(mode='json')})
                if action_reader is not None:
                    owner.source_calls.append({'turn': number, 'node': n.node_id, 'mineral': mineral})
                    return action_reader(n, action_id, mineral)
                return TypedResult.empty(ValueType.FACT_SET, 'offline_action_boundary')

        factory = OfflineFactory(message='', session_id=self.session, profile='public', llm=None, history=[], context=context)

        def build(*, node, dependencies, bindings):
            if node.node_id in sources:
                assert node.operator in {Operator.RETRIEVE, Operator.RETRIEVE_DOCUMENT}
                def read(_context, _inputs):
                    self.source_calls.append({'turn': number, 'node': node.node_id})
                    return sources[node.node_id]
                return FunctionStep(node.node_id, node.operator.value, read, dependencies=dependencies, bindings=bindings)
            return factory.build(node=node, dependencies=dependencies, bindings=bindings)

        pipe = PipeLowerer(build).lower(resolved, pipe_id=f'{self.session}:t{number}')
        execution = await PipeRuntime().execute(pipe)
        turn_id = f't{number}'
        await self.store.append_turn(Turn(turn_id, self.session, UserUtterance(self.case['turns'][number-1]['question'])))
        await self.store.save_program(self.session, turn_id, resolved)
        await self.store.save_pipe(self.session, turn_id, pipe)
        await self.store.save_result(self.session, turn_id, execution)
        # Same ItemResult -> snapshot -> HistoryStore contract as action_results.
        snapshots = tuple(ItemResult((self.case['semantic_requirement']['parameter_bindings']['m'], r),
            value=execution.results[r].value, status='success' if execution.results[r].status == ResultStatus.SUCCESS else 'EXECUTION_FAILED',
            evidence=list(execution.results[r].evidence)).snapshot(turn_id=turn_id, result_id=f'{self.session}:{turn_id}') for r in roots)
        await self.store.save_result_snapshots(self.session, turn_id, f'{self.session}:{turn_id}', snapshots)
        assert await self.store.get_result_snapshots(self.session, turn_id) == snapshots
        assert await self.store.get_binding('other-session', turn_id, roots[0]) is None
        for r in roots:
            assert await self.store.get_binding(self.session, turn_id, r) is execution.results[r]
        # All materialized nodes must come from real typed store objects,
        # including metadata and failure state, rather than ENTITY args.
        for n in resolved.nodes:
            if n.node_id.startswith('ctx_'):
                assert execution.results[n.node_id] == factory.saved_results[n.node_id]
        self.turns.append({'turn': number, 'question': self.case['turns'][number-1]['question'],
            'gold_ast': raw, 'lowered_ast': resolved.to_dict(),
            'roots': {r: public(execution.results[r]) for r in roots},
            'stored_snapshot_count': len(snapshots), 'typed_references_verified': sum(n.node_id.startswith('ctx_') for n in resolved.nodes)})
        return execution.results


def retrieval(name, case, metric='price'):
    b = case['semantic_requirement']['parameter_bindings']
    return node(name, Operator.RETRIEVE, domain='price' if metric == 'price' else 'trade',
        metric=metric, mineral=b['m'], period={'kind': 'calendar_year', 'calendar_year': b['y']})


def hhi_plan(ref, prefix):
    return [node(prefix+'share', Operator.CALCULATE, ref, calculation='share', field='value'),
            node(prefix+'hhi', Operator.CALCULATE, ref, calculation='hhi', field='value')]


def hhi_oracle(rows):
    total = sum(r['value'] for r in rows)
    return sum((r['value']/total*100)**2 for r in rows)


async def metric_and_filter_case(c, db, conv):
    """083/122: preserve original population; recalculate denominator each turn."""
    b = c['semantic_requirement']['parameter_bindings']
    rows = query(db, "SELECT country,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country ORDER BY country", (b['m'], b['y']))
    p = c['pattern_id']
    source = typed(rows, c, metric='import_value', unit='USD', kind=ValueType.FACT_SET)
    t1 = await conv.execute(1, [retrieval('population', c, 'import_value'), *hhi_plan('population', 'a')], ['ashare', 'ahhi'], {'population': source})
    assert_rows(t1['ashare'], [{**r, 'value': r['value']/sum(x['value'] for x in rows)*100} for r in rows])
    assert_rows(t1['ahhi'], [{'value': hhi_oracle(rows)}])
    if p == 'PAT-083':
        # Explicit synthetic weight observations, NOT relabeled dollar values.
        # Values differ by country so an accidental reuse of the first HHI fails.
        weights = [{'country': r['country'], 'value': (i+1)**2*17.0} for i, r in enumerate(rows)]
        t2 = await conv.execute(2, [retrieval('weight', c, 'import_weight'), *hhi_plan('weight', 'b')], ['bhhi'],
            {'weight': typed(weights, c, metric='import_weight', unit='kg', kind=ValueType.FACT_SET)})
        assert_rows(t2['bhhi'], [{'value': hhi_oracle(weights)}])
        assert t2['weight'].period == source.period and t2['weight'].entity == source.entity
        assert hhi_oracle(weights) != hhi_oracle(rows)
        nodes = [node('comparison', Operator.COMPARE, 'history:t2:bhhi', 'history:t1:ahhi', field='value', operation='difference'),
                 node('answer', Operator.PROJECT, 'comparison', fields=['left_value', 'right_value', 'difference'])]
        t3 = await conv.execute(3, nodes, ['answer'])
        assert_rows(t3['answer'], [{'left_value': hhi_oracle(weights), 'right_value': hhi_oracle(rows), 'difference': hhi_oracle(weights)-hhi_oracle(rows)}])
        assert len(conv.source_calls) == 2
    else:
        remaining = [r for r in rows if r['country'] != '중국']
        t2 = await conv.execute(2, [node('without_china', Operator.FILTER, 'history:t1:population',
            predicate={'field': 'country', 'operator': 'not_equals', 'value': '중국'}), *hhi_plan('without_china', 'b')], ['bshare', 'bhhi'])
        assert_rows(t2['bhhi'], [{'value': hhi_oracle(remaining)}])
        assert_rows(t2['bshare'], [{**r, 'value': r['value']/sum(x['value'] for x in remaining)*100} for r in remaining])
        t3 = await conv.execute(3, [*hhi_plan('history:t1:population', 'restored'),
            node('equal', Operator.COMPARE, 'restoredhhi', 'history:t1:ahhi', field='value', operation='difference'),
            node('answer', Operator.PROJECT, 'equal', fields=['difference'])], ['restoredshare', 'restoredhhi', 'answer'])
        assert_rows(t3['restoredshare'], t1['ashare'].value)
        assert_rows(t3['restoredhhi'], t1['ahhi'].value)
        assert_rows(t3['answer'], [{'difference': 0.0}])
        assert len(conv.source_calls) == 1
    assert await conv.store.get_binding(conv.session, 't1', 'population') == source


async def refresh_case(c, db, conv):
    b = c['semantic_requirement']['parameter_bindings']
    as_of = c['semantic_requirement']['temporal_evaluation_as_of']
    rows = []
    for mineral in (b['m'], b['m2']):
        rows += query(db, "SELECT mineral,date,value,unit FROM observations WHERE domain='price' AND mineral=? AND date<=? ORDER BY date DESC LIMIT 1", (mineral, as_of))
    source = replace(typed(rows, c), entity=(b['m'], b['m2']), period={'as_of': as_of})
    await conv.execute(1, [retrieval('latest', c)], ['latest'], {'latest': source})
    t2 = await conv.execute(2, [node('list', Operator.PROJECT, f'result:{c["id"]}:t1', fields=['mineral'])], ['list'])
    assert_rows(t2['list'], [{'mineral': r['mineral']} for r in rows])
    assert len(conv.source_calls) == 1
    # Controlled I/O version change, no mutation of shared SQLite or old objects.
    refreshed = [{**r, 'value': r['value']+7.0} for r in rows]
    newer = replace(source, value=refreshed, provenance=('qa500:test-only:refresh',),
        evidence=(Evidence('structured', 'qa500:synthetic-refresh', c['id'], json.dumps(refreshed)),))
    t3 = await conv.execute(3, [retrieval('fresh', c),
        node('compare', Operator.COMPARE, 'fresh', 'history:t1:latest', field='value', operation='difference', join_key='mineral'),
        node('answer', Operator.PROJECT, 'compare', fields=['mineral', 'left_value', 'right_value', 'difference'])], ['answer'], {'fresh': newer})
    assert_rows(t3['answer'], [{'mineral': r['mineral'], 'left_value': r['value']+7.0, 'right_value': r['value'], 'difference': 7.0} for r in rows])
    assert len(conv.source_calls) == 2
    assert await conv.store.get_binding(conv.session, 't1', 'latest') == source
    context = await conv.store.get_context(conv.session)
    assert len({t.result_id for t in context.turns}) == 3
    assert (await conv.store.get_result_snapshots(conv.session, 't1'))[0]['value'] == rows


async def change_case(c, db, conv):
    """082: first/last monthly change, both declines and no-decline semantics."""
    b = c['semantic_requirement']['parameter_bindings']
    data = {}
    expected = {}
    for key, mineral in [('a', b['m']), ('b', b['m2'])]:
        data[key] = replace(typed(query(db, "SELECT date,month,value FROM observations WHERE domain='price' AND mineral=? AND year=? ORDER BY date", (mineral, b['y'])), c), entity=(mineral,))
        months = query(db, "SELECT month,AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month ORDER BY month", (mineral, b['y']))
        start, end = months[0]['value'], months[-1]['value']
        expected[key] = {'mineral': mineral, 'start': start, 'end': end, 'change': (end-start)/abs(start)*100}
    t1 = await conv.execute(1, [retrieval('daily', c), node('monthly', Operator.AGGREGATE, 'daily', field='value', aggregation='mean', group_by=['month'])], ['monthly'], {'daily': data['a']})
    assert_rows(t1['monthly'], query(db, "SELECT month,AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month ORDER BY month", (b['m'], b['y'])))
    nodes = [replace(retrieval('other', c), args={**retrieval('other', c).args, 'mineral': b['m2']}),
        node('other_monthly', Operator.AGGREGATE, 'other', field='value', aggregation='mean', group_by=['month'])]
    for key, ref in [('a', 'history:t1:monthly'), ('b', 'other_monthly')]:
        nodes += [node(key+'first', Operator.AGGREGATE, ref, field='value', aggregation='first', order_by='month'),
                  node(key+'last', Operator.AGGREGATE, ref, field='value', aggregation='last', order_by='month'),
                  node(key+'change', Operator.COMPARE, key+'last', key+'first', field='value', operation='percent_change')]
    t2 = await conv.execute(2, nodes, ['achange', 'bchange'], {'other': data['b']})
    for key in ('a', 'b'):
        row = t2[key+'change'].value[0]
        assert math.isclose(row['percent_change'], expected[key]['change'])
        assert row['left_value'] == expected[key]['end'] and row['right_value'] == expected[key]['start']
    nodes = [node('rates', Operator.COMPARE, 'history:t2:achange', 'history:t2:bchange', field='percent_change', operation='difference')]
    roots = []
    for key, side, comparison in [('a', 'left', 'lte'), ('b', 'right', 'gte')]:
        nodes += [node(key+'minimum', Operator.FILTER, 'rates', predicate={'field': 'difference', 'operator': comparison, 'value': 0}),
                  node(key+'declined', Operator.FILTER, key+'minimum', predicate={'field': side+'_value', 'operator': 'less_than', 'value': 0}),
                  node(key+'answer', Operator.PROJECT, key+'declined', fields=[side+'_entity', side+'.right_value', side+'.left_value'])]
        roots.append(key+'answer')
    t3 = await conv.execute(3, nodes, roots)
    for key, side in [('a', 'left'), ('b', 'right')]:
        e = expected[key]
        winner = e['change'] < 0 and e['change'] == min(x['change'] for x in expected.values())
        want = [{side+'_entity': [e['mineral']], side+'.right_value': e['start'], side+'.left_value': e['end']}] if winner else []
        assert_rows(t3[key+'answer'], want)
    assert len(conv.source_calls) == 2


async def partial_case(c, db, conv):
    """Complete broadcast golds and partial boundary probes, kept distinct."""
    b = c['semantic_requirement']['parameter_bindings']
    p = c['pattern_id']
    rows = query(db, "SELECT date,month,value,unit FROM observations WHERE domain='price' AND mineral=? AND year=? ORDER BY date", (b['m'], b['y']))
    if p == 'PAT-123':
        minerals = (b['m'], b['m2'], '아연')
        current, previous = [], []
        for mineral in minerals:
            for year, target in [(b['y'], current), (b['y']-1, previous)]:
                target.extend(query(db, "SELECT mineral,date,value FROM observations WHERE domain='price' AND mineral=? AND year=?", (mineral, year)))
        nodes = [retrieval('current', c), retrieval('previous', c),
            node('annual', Operator.AGGREGATE, 'current', field='value', aggregation='mean', group_by=['mineral']),
            node('previous_annual', Operator.AGGREGATE, 'previous', field='value', aggregation='mean', group_by=['mineral']),
            node('yoy', Operator.COMPARE, 'annual', 'previous_annual', field='value', operation='percent_change', join_key='mineral'),
            node('yoy_values', Operator.PROJECT, 'yoy', fields=['mineral', 'percent_change'])]
        sources = {'current': replace(typed(current, c), entity=minerals),
            'previous': replace(typed(previous, c), entity=minerals, period={'kind': 'calendar_year', 'calendar_year': b['y']-1})}
        nodes[1] = replace(nodes[1], args={**nodes[1].args, 'period': sources['previous'].period})
        t1 = await conv.execute(1, nodes, ['yoy_values'], sources)
        expected = []
        for mineral in minerals:
            a = sum(r['value'] for r in current if r['mineral'] == mineral)/24
            z = sum(r['value'] for r in previous if r['mineral'] == mineral)/24
            expected.append({'mineral': mineral, 'percent_change': (a-z)/abs(z)*100})
        assert_rows(t1['yoy_values'], expected)
        t2 = await conv.execute(2, [*above_mean_plan('history:t1:yoy_values', 'percent_change', 3),
            node('selected', Operator.PROJECT, 'above_mean', fields=['left.mineral', 'left.percent_change'])], ['selected'])
        mean = sum(r['percent_change'] for r in expected)/3
        selected = [r for r in expected if r['percent_change'] > mean]
        assert_rows(t2['selected'], [{'left.mineral': r['mineral'], 'left.percent_change': r['percent_change']} for r in selected])
        selected_minerals = [r['mineral'] for r in selected]
        assert list(t2['selected'].entity) == selected_minerals

        def read_trade(n, action_id, mineral):
            assert action_id == 'trade.monthly' and mineral in selected_minerals
            assert n.args['reporter_country'] == 'KR'
            assert n.args['period']['calendar_year'] == b['y']
            data = query(db, "SELECT mineral,value,unit FROM observations WHERE domain='trade' AND mineral=? AND year=?", (mineral, b['y']))
            return replace(typed(data, c, metric='import_value', unit='USD', kind=ValueType.FACT_SET), entity=(mineral,))

        t3 = await conv.execute(3, [node('imports', Operator.RETRIEVE, 'history:t2:selected', domain='trade',
            metric='import_value', reporter_country='KR', period={'kind': 'calendar_year', 'calendar_year': b['y']}),
            node('totals', Operator.AGGREGATE, 'imports', field='value', aggregation='sum', group_by=['mineral']),
            node('ranked_imports', Operator.SORT, 'totals', field='value', order='desc', tie_breaker='mineral')],
            ['ranked_imports'], action_reader=read_trade)
        totals = [query(db, "SELECT mineral,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY mineral", (mineral, b['y']))[0] for mineral in selected_minerals]
        assert_rows(t3['ranked_imports'], sorted(totals, key=lambda r: (-r['value'], r['mineral'])))
        assert sorted(call['mineral'] for call in conv.action_calls) == sorted(selected_minerals)
        assert len(conv.source_calls) == 2 + len(selected_minerals)
        return 'PASS', None, None
    if p in {'PAT-085', 'PAT-120'}:
        await country_case(c, db, conv)
        return 'PASS', None, None
    if p == 'PAT-121':
        docs = query(db, "SELECT date,title,mineral_list FROM documents WHERE kind='monthly' AND year=? AND EXISTS(SELECT 1 FROM json_each(documents.mineral_list) WHERE value=?) ORDER BY date DESC LIMIT 1", (b['y'], b['m']))
        docs[0]['mineral_list'] = [m for m in json.loads(docs[0]['mineral_list']) if m != b['m']]
        t1 = await conv.execute(1, [node('doc', Operator.RETRIEVE_DOCUMENT, topic='희소금속 월간동향'),
            node('minerals', Operator.PROJECT, 'doc', field='minerals')], ['minerals'],
            {'doc': typed(docs, c, metric='document', unit=None, kind=ValueType.DOCUMENT_EVIDENCE)})
        assert t1['minerals'].value == docs[0]['mineral_list']
        # Test legacy per-output snapshots independently from live execution.
        # A snapshot-only turn does NOT have a typed execution binding.
        snaps = tuple(ItemResult((m, output), value=[{'value': 10}], status=status).snapshot(turn_id='snapshot', result_id='snapshot-id')
            for i, m in enumerate(docs[0]['mineral_list'])
            for output, status in [('latest_value', 'success'), ('time_series', 'success' if i == 0 else 'DATA_UNAVAILABLE')])
        await conv.store.append_turn(Turn('snapshot', conv.session, UserUtterance('synthetic output statuses')))
        await conv.store.save_result_snapshots(conv.session, 'snapshot', 'snapshot-id', snaps)
        context = await conv.store.get_context(conv.session)
        assert len(context.project_snapshots(output_id='latest_value')) == len(docs[0]['mineral_list'])
        assert [s['mineral_id'] for s in context.project_snapshots(output_id='time_series')] == docs[0]['mineral_list'][:1]
        unresolved = SimpleNamespace(nodes=(node('use', Operator.PROJECT, 'result:snapshot-id', fields=['mineral_id']),), roots=('use',))
        try:
            _resolve_history_references(unresolved, context)
        except ValueError as exc:
            assert 'unresolved semantic history reference' in str(exc)
            return 'CAPABILITY_GAP', 'ITEM_SNAPSHOT_INPUTREF_BRIDGE_MISSING', {
                'required': 'result_snapshots(output_id,status) -> typed InputRef', 'observed': str(exc),
                'location': 'live_multihop._resolve_history_references skips turns without Turn.result',
                'snapshot_filter_verified': True, 'two_output_foreach_gold_executed': False,
                'remaining': 'full two-output document/price conversation; snapshot filtering alone is not a PASS'}
        raise AssertionError('snapshot bridge changed: reassess gold coverage')
    if p == 'PAT-124':
        # Use the newly wired production Calculate contract, not the old
        # unregistered lag_percent_change spelling.
        t1 = await conv.execute(1, [retrieval('series', c),
            node('returns', Operator.CALCULATE, 'series', calculation='periodic_return',
                 field='value', time_field='date', frequency='observation'),
            node('peak', Operator.ARG_MAX, 'returns', field='value', ties='all')], ['peak'], {'series': typed(rows, c)})
        oracle = query(db, "WITH obs AS (SELECT date,value,LAG(value) OVER (ORDER BY date) previous_value,LAG(date) OVER (ORDER BY date) start_date FROM observations WHERE domain='price' AND mineral=? AND year=?) SELECT date,start_date,(value-previous_value)/ABS(previous_value)*100 value FROM obs WHERE previous_value IS NOT NULL ORDER BY date", (b['m'], b['y']))
        assert_rows(t1['returns'], oracle)
        peaks = [r for r in oracle if r['value'] == max(x['value'] for x in oracle)]
        assert_rows(t1['peak'], peaks)
        await date_followup(c, db, conv, peaks)
        return 'PASS', None, None
    # The initial actual series and subsequent stored-state aggregation are
    # shared subgraphs, not substitutes for each question's complete first turn.
    await conv.execute(1, [retrieval('series', c)], ['series'], {'series': typed(rows, c)})
    monthly = query(db, "SELECT month,AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year=? GROUP BY month ORDER BY month", (b['m'], b['y']))
    t2 = await conv.execute(2, [node('monthly', Operator.AGGREGATE, 'history:t1:series', field='value', aggregation='mean', group_by=['month'])], ['monthly'])
    assert_rows(t2['monthly'], monthly)
    assert len(conv.source_calls) == 1
    if p == 'PAT-084':
        t3 = await conv.execute(3, [*above_mean_plan('history:t2:monthly', 'value', 12),
            node('selected', Operator.PROJECT, 'above_mean', fields=['left.month', 'left.value'])], ['selected'])
        mean = sum(r['value'] for r in monthly)/12
        assert_rows(t3['selected'], [{'left.month': r['month'], 'left.value': r['value']} for r in monthly if r['value'] > mean])
        assert len(conv.source_calls) == 1
        return 'PASS', None, None
    raise AssertionError(f'unregistered multi-turn gold: {p}')


async def country_case(c, db, conv):
    b = c['semantic_requirement']['parameter_bindings']
    year, mineral = b['y'], b['m']
    trade = query(db, "SELECT country,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country", (mineral, year))
    trade = [{**r, 'country_code': COUNTRY_CODES[r['country']]} for r in trade]
    k = 5 if c['pattern_id'] == 'PAT-085' else 3
    t1 = await conv.execute(1, [retrieval('population', c, 'import_value'),
        node('rank', Operator.SORT, 'population', field='value', order='desc', tie_breaker='country_code'),
        node('top', Operator.TOP_K, 'rank', k=k)], ['top'],
        {'population': typed(trade, c, metric='import_value', unit='USD', kind=ValueType.FACT_SET)})
    expected = sorted(trade, key=lambda r: (-r['value'], r['country_code']))[:k]
    assert_rows(t1['top'], expected)
    selected = expected[1]
    target = 'partner_country' if k == 5 else 'resource_country'
    role = node('role', Operator.PROJECT, InputRef('history:t1:top', 'index', 1),
                fields=['country_code'], aliases={'country_code': target})

    def read(n, action, bound_mineral):
        assert bound_mineral == mineral
        slots = _action_slots(n, mineral=bound_mineral).model_dump(mode='json')
        y = n.args['period']['calendar_year']
        if action == 'trade.monthly':
            assert slots['reporter_country'] == 'KR' and y == year
            country = next((name for name, code in COUNTRY_CODES.items() if code == slots['partner_country']), None)
            assert slots['partner_country'] in {None, selected['country_code']}
            sql = "SELECT month,value,unit FROM observations WHERE domain='trade' AND mineral=? AND year=?"
            params = (mineral, y)
            if country:
                sql += ' AND country=?'; params += (country,)
            return typed(query(db, sql, params), c, metric='import_value', unit='USD', kind=ValueType.FACT_SET)
        if action == 'resource.rank':
            assert slots['resource_country'] == selected['country_code']
            assert slots['partner_country'] is None and slots['reporter_country'] is None
            data = query(db, "SELECT value,unit FROM observations WHERE domain='production' AND mineral=? AND year=? AND country=?", (mineral, y, selected['country']))
            if not data:
                return TypedResult.empty(ValueType.FACT_SET, 'no_data')
            return replace(typed(data, c, metric='production', unit='t', kind=ValueType.FACT_SET), period=n.args['period'])
        assert action == 'price.series'
        assert slots['resource_country'] is None and slots['partner_country'] is None
        data = query(db, "SELECT date,value,unit FROM observations WHERE domain='price' AND mineral=? AND year=?", (mineral, y))
        return replace(typed(data, c), period=n.args['period'])

    if k == 5:
        t2 = await conv.execute(2, [role,
            node('target', Operator.RETRIEVE, InputRef('role', 'field', target), domain='trade', metric='import_value',
                 reporter_country='KR', mineral=mineral, period={'kind': 'calendar_year', 'calendar_year': year}),
            node('world', Operator.RETRIEVE, domain='trade', metric='import_value', reporter_country='KR', mineral=mineral,
                 period={'kind': 'calendar_year', 'calendar_year': year}),
            node('numerator', Operator.AGGREGATE, 'target', field='value', aggregation='sum', group_by=['month']),
            node('denominator', Operator.AGGREGATE, 'world', field='value', aggregation='sum', group_by=['month']),
            node('share', Operator.COMPARE, 'numerator', 'denominator', field='value', operation='ratio', join_key='month'),
            node('monthly_share', Operator.PROJECT, 'share', fields=['month', 'ratio'])], ['monthly_share'], action_reader=read)
        shares = query(db, "SELECT month,SUM(CASE WHEN country=? THEN value ELSE 0 END)*1.0/SUM(value) ratio FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY month ORDER BY month", (selected['country'], mineral, year))
        assert_rows(t2['monthly_share'], shares)
        assert t2['monthly_share'].unit == 'ratio'  # Fraction, never mislabeled %.
        t3 = await conv.execute(3, [node('peak', Operator.ARG_MAX, 'history:t2:monthly_share', field='ratio', ties='all'),
            node('answer', Operator.PROJECT, 'peak', fields=['month', 'ratio'])], ['answer'])
        assert_rows(t3['answer'], [r for r in shares if r['ratio'] == max(x['ratio'] for x in shares)])
        assert len(conv.action_calls) == 2
    else:
        nodes = [role]
        for name, y in [('before', year-1), ('after', year)]:
            nodes.append(node(name, Operator.RETRIEVE, InputRef('role', 'field', target), domain='resource', metric='production',
                mineral=mineral, period={'kind': 'calendar_year', 'calendar_year': y}))
        nodes.append(node('production_change', Operator.COMPARE, 'after', 'before', field='value', operation='difference'))
        t2 = await conv.execute(2, nodes, ['production_change'], action_reader=read)
        actual = t2['production_change']
        amounts = query(db, "SELECT year,value FROM observations WHERE domain='production' AND mineral=? AND country=? AND year IN (?,?) ORDER BY year", (mineral, selected['country'], year-1, year))
        decline = len(amounts) == 2 and amounts[1]['value'] < amounts[0]['value']
        if len(amounts) == 2:
            assert actual.status == ResultStatus.SUCCESS
            assert actual.value[0]['difference'] == amounts[1]['value']-amounts[0]['value']
        else:
            assert actual.status != ResultStatus.SUCCESS
        # Explicit test-only planner decision from the real stored comparison.
        # This is gold planning, not a claim of automatic NL conditional parsing.
        saved = await conv.store.get_binding(conv.session, 't2', 'production_change')
        assert decline == (saved.status == ResultStatus.SUCCESS and saved.value[0]['difference'] < 0)
        if decline:
            nodes = []
            for name, y in [('before_price', year-1), ('after_price', year)]:
                nodes += [node(name, Operator.RETRIEVE, domain='price', metric='price', mineral=mineral,
                    period={'kind': 'calendar_year', 'calendar_year': y}),
                    node(name+'_mean', Operator.AGGREGATE, name, field='value', aggregation='mean')]
            nodes += [node('price_change', Operator.COMPARE, 'after_price_mean', 'before_price_mean', field='value', operation='difference'),
                node('answer', Operator.PROJECT, 'price_change', fields=['left_value', 'right_value', 'difference'])]
            t3 = await conv.execute(3, nodes, ['answer'], action_reader=read)
            values = query(db, "SELECT year,AVG(value) value FROM observations WHERE domain='price' AND mineral=? AND year IN (?,?) GROUP BY year ORDER BY year", (mineral, year-1, year))
            assert_rows(t3['answer'], [{'left_value': values[1]['value'], 'right_value': values[0]['value'], 'difference': values[1]['value']-values[0]['value']}])
        else:
            # A failed comparison has no numeric columns to project. Preserve
            # the typed failure instead of manufacturing an answer row.
            final = (node('condition_not_met', Operator.PROJECT, 'history:t2:production_change',
                          fields=['left_value', 'right_value', 'difference']) if len(amounts) == 2 else
                     node('condition_not_met', Operator.VALIDATE_EVIDENCE, 'history:t2:production_change'))
            t3 = await conv.execute(3, [final], ['condition_not_met'])
            if len(amounts) == 2:
                assert_rows(t3['condition_not_met'], [{'left_value': amounts[1]['value'], 'right_value': amounts[0]['value'], 'difference': amounts[1]['value']-amounts[0]['value']}])
            else:
                assert t3['condition_not_met'].status != ResultStatus.SUCCESS
            assert not any(call['action'] == 'price.series' for call in conv.action_calls)
        conv.turns[-1]['gold_planner_decision'] = {'production_declined': decline,
            'condition_not_met': not decline, 'based_on': 'history:t2:production_change', 'natural_language_parser_verified': False}
    assert_rows(t2['role'], [{target: selected['country_code']}])
    assert await conv.store.get_binding(conv.session, 't1', 'top') == t1['top']


async def date_followup(c, db, conv, peaks):
    b = c['semantic_requirement']['parameter_bindings']
    assert len(peaks) == 1, 'ambiguous dates require explicit selection, never pick implicitly'
    day = peaks[0]['date']
    expected_docs = query(db, "SELECT date,title,mineral_list FROM documents WHERE kind='news' AND date=? AND EXISTS(SELECT 1 FROM json_each(documents.mineral_list) WHERE value=?)", (day, b['m']))
    for doc in expected_docs:
        doc['mineral_list'] = json.loads(doc['mineral_list'])

    def read_news(n, action, mineral):
        assert action == 'document.retrieve' and mineral == b['m']
        slots = _action_slots(n, mineral=mineral).model_dump(mode='json')
        assert slots['bound_date'] == day
        docs = query(db, "SELECT date,title,mineral_list FROM documents WHERE kind='news' AND date=? AND EXISTS(SELECT 1 FROM json_each(documents.mineral_list) WHERE value=?)", (slots['bound_date'], mineral))
        for doc in docs:
            doc['mineral_list'] = json.loads(doc['mineral_list'])
        if not docs:
            return TypedResult.empty(ValueType.DOCUMENT_EVIDENCE, 'no_data')
        return typed(docs, c, metric='news', unit=None, kind=ValueType.DOCUMENT_EVIDENCE)

    t2 = await conv.execute(2, [node('date_role', Operator.PROJECT, 'history:t1:peak', fields=['date'], aliases={'date': 'bound_date'}),
        node('news', Operator.RETRIEVE_DOCUMENT, InputRef('date_role', 'field', 'bound_date'), topic='일일 자원뉴스', mineral=b['m']),
        node('titles', Operator.PROJECT, 'news', fields=['date', 'title']),
        node('mentions', Operator.PROJECT, 'news', fields=['minerals']),
        node('others', Operator.FILTER, 'mentions', predicate={'field': 'mineral', 'operator': 'not_equals', 'value': b['m']})],
        ['titles', 'others'], action_reader=read_news)
    assert_rows(t2['date_role'], [{'bound_date': day}])
    others = list(dict.fromkeys(m for d in expected_docs for m in d['mineral_list'] if m != b['m']))
    if expected_docs:
        assert_rows(t2['titles'], [{'date': d['date'], 'title': d['title']} for d in expected_docs])
        assert t2['others'].status == ResultStatus.SUCCESS and t2['others'].value == others
        assert t2['others'].entity == tuple(others)
    else:
        assert t2['others'].status != ResultStatus.SUCCESS

    def read_trade(n, action, mineral):
        assert action == 'trade.country_rank' and mineral in others
        assert n.args['reporter_country'] == 'KR' and n.args['period']['calendar_year'] == b['y']
        assert n.args['top_n'] == 1
        rows = query(db, "SELECT country,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country", (mineral, b['y']))
        rows.sort(key=lambda r: (-r['value'], COUNTRY_CODES[r['country']]))
        return replace(typed(rows[:1], c, metric='import_value', unit='USD', kind=ValueType.FACT_SET), entity=(mineral,))

    t3 = await conv.execute(3, [node('leaders', Operator.FOR_EACH, 'history:t2:others', domain='trade', metric='country_rank',
        reporter_country='KR', top_n=1, period={'kind': 'calendar_year', 'calendar_year': b['y']})], ['leaders'], action_reader=read_trade)
    if expected_docs:
        assert t3['leaders'].status == ResultStatus.SUCCESS
        assert [r['mineral'] for r in t3['leaders'].value] == others
        for item in t3['leaders'].value:
            totals = query(db, "SELECT country,SUM(value) value FROM observations WHERE domain='trade' AND mineral=? AND year=? GROUP BY country", (item['mineral'], b['y']))
            winner = min(totals, key=lambda r: (-r['value'], COUNTRY_CODES[r['country']]))
            assert item['value'] == [winner] and item['status'] == 'success'
        assert len(conv.action_calls) == 1 + len(others)
    else:
        assert t3['leaders'].status != ResultStatus.SUCCESS
        assert len(conv.action_calls) == 1  # No invented mineral and no trade I/O.


def above_mean_plan(ref, field, expected_count):
    """Gold composition: completeness guard before explicit scalar broadcast."""
    return [node('mean', Operator.AGGREGATE, ref, field=field, aggregation='mean', include_count=True),
            node('complete_mean', Operator.FILTER, 'mean', predicate={'field': 'observation_count', 'operator': 'equals', 'value': expected_count}),
            node('deviation', Operator.COMPARE, ref, 'complete_mean', field=field, operation='difference', broadcast='right'),
            node('above_mean', Operator.FILTER, 'deviation', predicate={'field': 'difference', 'operator': 'greater_than', 'value': 0})]


async def validate_case(case, db):
    record = {key: case[key] for key in ('id', 'pattern_id', 'question', 'turns', 'order', 'semantic_requirement', 'operation_graph', 'expected_ast', 'expected_lowering')}
    record.update(parser_executed=False, physical_tool_executed=False, backend_executed=False,
        validation_scope='test-only gold backend; no natural-language parser', errors=[], partial_coverage=False)
    conv = Conversation(case)
    try:
        if case['pattern_id'] in {'PAT-083', 'PAT-122'}:
            await metric_and_filter_case(case, db, conv)
            record.update(status='PASS', reason=None)
        elif case['pattern_id'] == 'PAT-125':
            await refresh_case(case, db, conv)
            record.update(status='PASS', reason=None)
        elif case['pattern_id'] == 'PAT-082':
            await change_case(case, db, conv)
            record.update(status='PASS', reason=None)
        else:
            status, reason, detail = await partial_case(case, db, conv)
            record.update(status=status, reason=reason, partial_coverage=status != 'PASS')
            if detail is not None:
                record['contract_gap'] = detail
    except Exception as exc:
        record.update(status='FAILED', reason='SEMANTIC_OR_EXECUTION_FAIL', errors=[f'{type(exc).__name__}: {exc}'])
    gold_verified = record['status'] == 'PASS'
    if gold_verified and conv.common_path_gaps:
        record.update(status='CAPABILITY_GAP', reason='HISTORY_REF_REJECTED_BEFORE_MATERIALIZATION',
            contract_gap={'required': 'historical InputRef resolution before strict local-node validation',
                'observed': conv.common_path_gaps, 'gold_runtime_verified': True})
    record.update(backend_executed=bool(conv.turns), executions=conv.turns,
        source_calls=conv.source_calls, action_calls=conv.action_calls,
        common_path_gaps=conv.common_path_gaps, gold_backend_verified=gold_verified,
        typed_reference_count=sum(t['typed_references_verified'] for t in conv.turns),
        complete_conversation_verified=record['status'] == 'PASS')
    return record


async def run():
    db = fixture()
    try:
        # Prohibit even accidental mutation of the common synthetic fixture.
        db.execute('PRAGMA query_only=ON')
        records = [await validate_case(c, db) for c in MULTITURN_CASES]
    finally:
        db.close()
    counts = {k: sum(r['status'] == k for r in records) for k in ('PASS', 'FAILED', 'CAPABILITY_GAP', 'UNSUPPORTED', 'BLOCKED', 'PENDING')}
    assert len(records) == sum(counts.values()) == 40
    return {'TOTAL_CORPUS': 40, 'REGISTERED': len(records), 'counts': counts,
        'patterns': len({r['pattern_id'] for r in records}),
        'order_counts': dict(Counter(r['order'] for r in records)),
        'duplicate_questions': len(records)-len({r['question'] for r in records}),
        'parser_executed': False, 'records': records}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Create a new JSON report; existing files are never overwritten.')
    args = parser.parse_args()
    report = asyncio.run(run())
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=lambda obj: obj.value if hasattr(obj, 'value') else asdict(obj))
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(encoded + '\n')
        print(json.dumps({'output': str(args.output), 'counts': report['counts']}, ensure_ascii=False))
    else:
        print(encoded)


if __name__ == '__main__':
    main()
