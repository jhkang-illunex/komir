"""Offline conversation conformance; a passed test can assert a reproduced gap."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from inhouse.rag_core.tests import qa500_multiturn as qa
from inhouse.rag_core.ragkit.history_context import _execution_to_dict, _execution_from_dict, _json_dump
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus


@pytest.fixture(scope='module')
def report():
    return asyncio.run(qa.run())


@pytest.mark.parametrize('case', qa.MULTITURN_CASES, ids=lambda c: c['id'])
def test_registered_conversation(case, report):
    r = next(r for r in report['records'] if r['id'] == case['id'])
    assert r['question'] == case['question'] and r['turns'] == case['turns']
    assert r['backend_executed'] and not r['parser_executed'] and not r['physical_tool_executed']
    assert not r['errors'], r
    assert not r['common_path_gaps'], r
    if case['pattern_id'] != 'PAT-121':
        assert r['status'] == 'PASS', r
        assert r['gold_backend_verified']
        assert len(r['executions']) == 3 and r['typed_reference_count'] > 0
        assert r['reason'] is None and r['complete_conversation_verified']
    else:
        assert r['status'] == 'CAPABILITY_GAP', r
        assert r['contract_gap']['required'] and r['contract_gap']['observed']
        assert not r['gold_backend_verified'] and r['partial_coverage']
        assert r['reason'] == 'ITEM_SNAPSHOT_INPUTREF_BRIDGE_MISSING'


def test_numeric_accounting_and_json_contract(report):
    assert report['TOTAL_CORPUS'] == report['REGISTERED'] == sum(report['counts'].values()) == 40
    assert report['counts'] == {'PASS': 36, 'FAILED': 0, 'CAPABILITY_GAP': 4, 'UNSUPPORTED': 0, 'BLOCKED': 0, 'PENDING': 0}
    assert report['patterns'] == 10 and report['duplicate_questions'] == 0
    assert report['order_counts'] == {'3rd-order': 16, '4th-order': 24}
    assert sum(r['gold_backend_verified'] for r in report['records']) == 36
    # Uses exactly the CLI serializer; every individual record is JSON-safe.
    serialized = json.dumps(report, ensure_ascii=False, default=lambda o: o.value if hasattr(o, 'value') else qa.asdict(o))
    assert len(json.loads(serialized)['records']) == 40


@pytest.mark.parametrize('state', [ResultStatus.SUCCESS, ResultStatus.PARTIAL])
def test_latest_alias_uses_typed_store_without_retrieval_or_text(state):
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        conv = qa.Conversation(c)
        source = replace(qa.typed([{'month': '01', 'value': 0}, {'month': '02', 'value': None}], c),
                         status=state, warnings=('fixture-warning',))
        await conv.execute(1, [qa.retrieval('series', c)], ['series'], {'series': source})
        # No prior request text is passed to LiveOperatorFactory.
        result = await conv.execute(2, [qa.node('project', qa.Operator.PROJECT, 'previous', fields=['month', 'value']),
            qa.node('sum', qa.Operator.AGGREGATE, 'project', field='value', aggregation='sum')], ['project', 'sum'])
        restored = result['project']
        assert restored.value == source.value
        for key in ('status', 'entity', 'metric', 'period', 'unit', 'source', 'evidence', 'provenance', 'warnings', 'sufficient'):
            assert getattr(restored, key) == getattr(source, key)
        assert not conv.common_path_gaps  # Actual latest alias common path works.
        assert len(conv.source_calls) == 1
        if state == ResultStatus.PARTIAL:
            assert result['sum'].failure_reason == 'incomplete_population'
        assert (await conv.store.get_binding(conv.session, 't1', 'series')) == source
        # Offline PostgreSQL serialization helpers, no PostgreSQL connection.
        old = (await conv.store.get_context(conv.session)).turns[0].result
        persisted = _execution_from_dict(json.loads(_json_dump(_execution_to_dict(old))))
        assert persisted.results['series'].value == source.value
        assert persisted.results['series'].status == state
        assert persisted.results['series'].period == source.period
        assert persisted.results['series'].unit == source.unit
    asyncio.run(scenario())


def test_missing_history_does_not_substitute_latest():
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        conv = qa.Conversation(c)
        await conv.execute(1, [qa.retrieval('series', c)], ['series'], {'series': qa.typed([{'value': 10}], c)})
        context = await conv.store.get_context(conv.session)
        raw = {'nodes': [qa.node('x', qa.Operator.PROJECT, 'history:absent:series', fields=['value']).to_dict()], 'roots': ['x']}
        assert qa._normalize_history_aliases(raw, context) == raw
        with pytest.raises(ValueError, match='unresolved semantic history reference'):
            qa._resolve_history_references(SimpleNamespace(nodes=(qa.node('x', qa.Operator.PROJECT, 'history:absent:series'),), roots=('x',)), context)
    asyncio.run(scenario())


@pytest.mark.parametrize('reference_kind', ['history', 'result'])
@pytest.mark.parametrize('scope', ['outside_context_window', 'other_session_same_user', 'unknown'])
def test_context_outside_references_rejected_before_strict_ir(reference_kind, scope):
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        conv = qa.Conversation(c)
        await conv.execute(1, [qa.retrieval('series', c)], ['series'], {'series': qa.typed([{'value': 11}], c)})
        newer = await conv.execute(2, [qa.retrieval('latest', c)], ['latest'], {'latest': qa.typed([{'value': 99}], c)})
        assert newer['latest'].value == [{'value': 99}]
        full = await conv.store.get_context(conv.session)
        if scope == 'outside_context_window':
            context = await conv.store.get_context(conv.session, limit=1)
            turn_id, result_id, step = 't1', f'{c["id"]}:t1', 'series'
            assert await conv.store.get_binding(conv.session, turn_id, step) is not None
        elif scope == 'other_session_same_user':
            # HistoryStore has no user identity field: same-user session
            # membership must never widen the supplied ConversationContext.
            foreign = replace(full.turns[0], session_id='same-user:other-session',
                              turn_id='foreign-turn', result_id='foreign-result')
            await conv.store.append_turn(foreign)
            assert await conv.store.get_binding(foreign.session_id, foreign.turn_id, 'series') is not None
            context = full
            turn_id, result_id, step = foreign.turn_id, foreign.result_id, 'series'
        else:
            context = full
            turn_id, result_id, step = 'never-stored', 'never-stored-result', 'series'
        ref = f'history:{turn_id}:{step}' if reference_kind == 'history' else f'result:{result_id}'
        raw = {'nodes': [qa.node('valid', qa.Operator.PROJECT, 'previous', fields=['value']).to_dict(),
                         qa.node('forbidden', qa.Operator.PROJECT, ref, fields=['value']).to_dict()],
               'roots': ['valid', 'forbidden']}
        normalized = qa._normalize_history_aliases(raw, context)
        forbidden = next(n for n in normalized['nodes'] if n['node_id'] == 'forbidden')
        assert forbidden['inputs'][0]['node_id'] == ref  # No latest retargeting.
        valid = next(n for n in normalized['nodes'] if n['node_id'] == 'valid')
        assert valid['inputs'][0]['node_id'].startswith('ctx_')
        with pytest.raises(ValueError, match='references unknown node'):
            qa.SemanticProgram.from_dict(normalized)
    asyncio.run(scenario())


@pytest.mark.parametrize('reference_kind', ['history', 'result'])
@pytest.mark.parametrize('state', [ResultStatus.SUCCESS, ResultStatus.PARTIAL])
def test_explicit_old_context_reference_keeps_original_typed_state(reference_kind, state):
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        conv = qa.Conversation(c)
        source = replace(qa.typed([{'value': 17}], c), status=state, warnings=('old-state',))
        await conv.execute(1, [qa.retrieval('series', c)], ['series'], {'series': source})
        newer = await conv.execute(2, [qa.retrieval('latest', c)], ['latest'], {'latest': qa.typed([{'value': 99}], c)})
        assert newer['latest'].value == [{'value': 99}]
        ref = 'history:t1:series' if reference_kind == 'history' else f'result:{c["id"]}:t1'
        result = await conv.execute(3, [qa.node('old', qa.Operator.PROJECT, ref, fields=['value'])], ['old'])
        assert result['old'] == replace(source, upstream_step_ids=result['old'].upstream_step_ids)
        assert len(result['old'].upstream_step_ids) == 1
        assert result['old'].upstream_step_ids[0] in result
        assert result[result['old'].upstream_step_ids[0]] == source
        assert not conv.common_path_gaps and len(conv.source_calls) == 2
    asyncio.run(scenario())


def test_strict_ir_failure_is_not_bypassed_by_gold_adapter(monkeypatch):
    original = qa._normalize_history_aliases
    def reject_history(payload, context):
        if context.turns:
            raise ValueError('injected strict history rejection')
        return original(payload, context)
    monkeypatch.setattr(qa, '_normalize_history_aliases', reject_history)
    db = qa.fixture()
    try:
        record = asyncio.run(qa.validate_case(qa.MULTITURN_CASES[0], db))
    finally:
        db.close()
    assert record['status'] == 'FAILED' and len(record['executions']) == 1
    assert record['common_path_gaps'] and not record['gold_backend_verified']
    assert 'injected strict history rejection' in record['errors'][0]


@pytest.mark.parametrize('expected_count', [3, 12])
@pytest.mark.parametrize('invalidity', ['missing_member', 'null_value', 'partial'])
def test_above_mean_gold_refuses_incomplete_population(expected_count, invalidity):
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        rows = [{'value': float(i + 1)} for i in range(expected_count)]
        if invalidity == 'missing_member':
            rows.pop()
        elif invalidity == 'null_value':
            rows[-1]['value'] = None
        source = qa.typed(rows, c)
        if invalidity == 'partial':
            source = replace(source, status=ResultStatus.PARTIAL)
        conv = qa.Conversation(c)
        result = await conv.execute(1, [qa.retrieval('observations', c),
            *qa.above_mean_plan('observations', 'value', expected_count)], ['above_mean'], {'observations': source})
        assert result['deviation'].status != ResultStatus.SUCCESS
        assert result['above_mean'].status != ResultStatus.SUCCESS
        if invalidity == 'missing_member':
            assert result['complete_mean'].value == []
            assert result['deviation'].failure_reason == 'broadcast_requires_typed_scalar'
        assert not conv.action_calls
    asyncio.run(scenario())


def test_implicit_broadcast_still_rejected_and_equal_mean_not_selected():
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        conv = qa.Conversation(c)
        result = await conv.execute(1, [qa.retrieval('observations', c),
            *qa.above_mean_plan('observations', 'value', 3),
            qa.node('implicit', qa.Operator.COMPARE, 'observations', 'complete_mean', field='value', operation='difference')],
            ['above_mean', 'implicit'], {'observations': qa.typed([{'value': 7.0}]*3, c)})
        assert result['above_mean'].status == ResultStatus.SUCCESS and result['above_mean'].value == []
        assert result['implicit'].failure_reason == 'comparison_alignment_required'
    asyncio.run(scenario())


def test_both_prices_rise_does_not_select_a_decline():
    async def scenario():
        # Local test fixture only; common fixture remains untouched.
        db = qa.fixture()
        try:
            db.execute("UPDATE observations SET value=value+100 WHERE domain='price' AND month='12'")
            db.execute('PRAGMA query_only=ON')
            c = qa.MULTITURN_CASES[0]
            conv = qa.Conversation(c)
            await qa.change_case(c, db, conv)
            assert all(r['value'] == [] for r in conv.turns[-1]['roots'].values())
        finally:
            db.close()
    asyncio.run(scenario())


def test_runtime_failures_cannot_be_reported_as_gold_success(monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError('injected runtime failure')
    monkeypatch.setattr(qa.PipeRuntime, 'execute', broken)
    db = qa.fixture()
    try:
        record = asyncio.run(qa.validate_case(qa.MULTITURN_CASES[0], db))
    finally:
        db.close()
    assert record['status'] == 'FAILED'
    assert not record['gold_backend_verified'] and not record['complete_conversation_verified']
    assert 'injected runtime failure' in record['errors'][0]


@pytest.mark.parametrize('target', ['reporter_country', 'partner_country', 'resource_country', 'bound_date'])
@pytest.mark.parametrize('mode', ['valid', 'ambiguous', 'conflicting'])
def test_explicit_role_binding_and_fail_closed_boundaries(target, mode):
    async def scenario():
        c = qa.MULTITURN_CASES[0]
        conv = qa.Conversation(c)
        value = '2025-12-05' if target == 'bound_date' else 'CL'
        values = [{'selected': value}] * (2 if mode == 'ambiguous' else 1)
        await conv.execute(1, [qa.retrieval('source', c)], ['source'], {'source': qa.typed(values, c)})
        args = {'domain': 'resource' if target == 'resource_country' else 'trade',
                'metric': 'production' if target == 'resource_country' else 'import_value'}
        if mode == 'conflicting':
            args[target] = '2024-01-01' if target == 'bound_date' else 'KR'
        op = qa.Operator.RETRIEVE_DOCUMENT if target == 'bound_date' else qa.Operator.RETRIEVE
        result = await conv.execute(2, [qa.node('role', qa.Operator.PROJECT, 'history:t1:source',
            fields=['selected'], aliases={'selected': target}),
            qa.node('lookup', op, qa.InputRef('role', 'field', target), **args)], ['lookup'])
        if mode == 'valid':
            assert len(conv.action_calls) == 1
            slots = conv.action_calls[0]['slots']
            assert slots[target] == value
            assert all(slots[name] is None for name in ('reporter_country', 'partner_country', 'resource_country', 'bound_date') if name != target)
            assert result['lookup'].failure_reason == 'offline_action_boundary'
        else:
            assert not conv.action_calls
            assert result['lookup'].failure_reason == ('conflicting_slot_binding' if mode == 'conflicting' else 'ambiguous_or_missing_slot_binding')
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['decline', 'missing_production'])
def test_country_conditional_price_gold_uses_saved_comparison(mode):
    async def scenario():
        c = next(c for c in qa.MULTITURN_CASES if c['pattern_id'] == 'PAT-120')
        b = c['semantic_requirement']['parameter_bindings']
        db = qa.fixture()
        try:
            if mode == 'decline':
                db.execute("UPDATE observations SET value=value*0.25 WHERE domain='production' AND mineral=? AND year=?", (b['m'], b['y']))
            else:
                db.execute("DELETE FROM observations WHERE domain='production' AND mineral=? AND year=?", (b['m'], b['y']))
            db.execute('PRAGMA query_only=ON')
            conv = qa.Conversation(c)
            await qa.country_case(c, db, conv)
            assert len(conv.turns) == 3 and not conv.common_path_gaps
            assert conv.turns[-1]['gold_planner_decision']['production_declined'] == (mode == 'decline')
            assert sum(call['action'] == 'price.series' for call in conv.action_calls) == (2 if mode == 'decline' else 0)
        finally:
            db.close()
    asyncio.run(scenario())


def test_missing_bound_date_news_does_not_invent_other_minerals():
    async def scenario():
        c = next(c for c in qa.MULTITURN_CASES if c['pattern_id'] == 'PAT-124')
        db = qa.fixture()
        try:
            db.execute("DELETE FROM documents WHERE kind='news'")
            db.execute('PRAGMA query_only=ON')
            conv = qa.Conversation(c)
            status, reason, _ = await qa.partial_case(c, db, conv)
            assert status == 'PASS' and reason is None  # Expected no-data behavior.
            assert len(conv.turns) == 3
            assert conv.turns[-1]['roots']['leaders']['status'] != 'success'
            assert len(conv.action_calls) == 1 and conv.action_calls[0]['action'] == 'document.retrieve'
        finally:
            db.close()
    asyncio.run(scenario())
