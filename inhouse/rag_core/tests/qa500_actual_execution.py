"""Offline replay of ACTUAL Gemma outputs, not a production E2E or semantic PASS.

python3 -m inhouse.rag_core.tests.qa500_actual_execution --inputs before.jsonl
    after.jsonl after2.jsonl --output /tmp/qa500-actual.json
python3 -m inhouse.rag_core.tests.qa500_actual_execution --self-test

Later input files/complete duplicate records override earlier ones, even failures.
Reparse the last raw attempt, or (only without a saved semantic_plan) replay raw
attempts in order through today's schema to recover old-schema rejections. No Gold nodes,
filters, fields, roots, entity bindings or document scopes enter the adapter.
Composite is only a root set; Select(argmax/argmin) is the only mode translation.
Explicit relational keys/fields are translated without supplying missing keys
or operations. The current live contract uses join_key (string OR list), not
join_keys. Fixture/IR adapter gaps are not evidence of a production capability gap.
Unrepresentable nodes remain visible failed steps; independent branches still run.
Actual ActionCall slots drive read_fixture at execution time (never a source-ID
data dictionary). Only the existing mineral alias registry can normalize values.
Gold is used AFTER execution, only as an independent SQL oracle. Root matching
uses structural signatures before values; numeric coincidence cannot select roots.
COMPONENT_PASS does not prove the natural-language question was answered.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from inhouse.common.llm_client import parse_json_object
from inhouse.rag_core.ragkit.action_contract import MINERAL_ALIASES, REQUIRED
from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory, _action_slots
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, PipeRuntime, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType
from inhouse.rag_core.ragkit.semantic_v2 import (
    InputRefV2, LegacyActionLowerer, LogicalNodeV2, LogicalProgramV2, Primitive, SemanticRequirementPlanV2,
    logical_program_from_requirements,
)
from inhouse.rag_core.retrieval.evidence import Evidence
from inhouse.rag_core.tests import qa500_backend as backend
from inhouse.rag_core.tests.qa500_semantic_audit import read_snapshot


OPERATOR_MAP = {
    Primitive.AGGREGATE: Operator.AGGREGATE, Primitive.CALCULATE: Operator.CALCULATE,
    Primitive.FILTER: Operator.FILTER, Primitive.SORT: Operator.SORT,
    Primitive.TOP_K: Operator.TOP_K, Primitive.JOIN: Operator.JOIN,
    Primitive.COMPARE: Operator.COMPARE, Primitive.PROJECT: Operator.PROJECT,
}
ACTION_DOMAINS = {'price.series':'price', 'trade.monthly':'trade',
                  'resource.rank':'resource', 'inventory.latest':'inventory',
                  'inventory.series':'inventory', 'indicator.series':'indicator'}
GAP_LAYERS = ('ACTUAL_PLAN_CONTRACT_GAP', 'IR_ADAPTER_GAP', 'FIXTURE_ADAPTER_GAP')


def relation_arguments(operator, arguments):
    """Lossless spelling/cardinality translation of EXPLICIT operands only.

Never infer an operation, default key, missing field, alignment or scope.
Conflicting explicit spellings are rejected instead of overwriting an operand.
Retain fields so malformed cardinality still reaches the actual live rejection.
"""
    args = dict(arguments)
    if operator not in {Primitive.JOIN, Primitive.COMPARE, Operator.JOIN, Operator.COMPARE}:
        return args
    if isinstance(args.get('join_key'), str) and args['join_key']:
        args['join_key'] = [args['join_key']]
    if operator not in {Primitive.COMPARE, Operator.COMPARE}:
        return args
    fields = args.get('fields')
    if not isinstance(fields, list) or len(fields) not in {1, 2} or not all(isinstance(f,str) and f for f in fields):
        return args
    left, right = fields[0], fields[-1]
    for key, value in (('left_field',left),('right_field',right)):
        if key in args and args[key] != value:
            raise ValueError('ACTUAL_PLAN_CONTRACT_GAP: conflicting_explicit_compare_fields')
    if 'field' in args and (args['field'] != left or args['field'] != right):
        raise ValueError('ACTUAL_PLAN_CONTRACT_GAP: conflicting_explicit_compare_fields')
    if len(fields) == 1:
        args['field'] = left
    else:
        args['left_field'], args['right_field'] = left, right
    return args


def failure_layer(reason):
    reason = reason or ''
    for layer in GAP_LAYERS:
        if reason.startswith(layer+':'):
            return layer
    if reason == 'DATA_UNAVAILABLE' or reason.startswith('DATA_UNAVAILABLE:'):
        return 'DATA_UNAVAILABLE'
    if reason.startswith('upstream step failed:'):
        return 'DEPENDENCY_FAILURE'
    return 'CURRENT_RUNTIME_FAILURE' if reason else None


def runtime_outcome(roots):
    """EMPTY alone is not evidence of data absence: require the reader reason."""
    values=list(roots.values())
    if any(r['status'] not in {'success','empty'} or
           r['status']=='empty' and failure_layer(r.get('reason'))!='DATA_UNAVAILABLE' for r in values):
        return 'RUNTIME_FAILURE'
    if any(r['status']=='empty' for r in values):
        return 'DATA_UNAVAILABLE'
    return 'RUNTIME_SUCCESS_NOT_SEMANTIC_PASS' if values else 'RUNTIME_FAILURE'


def canonical(value):
    return MINERAL_ALIASES.get(value.strip().casefold(), value) if isinstance(value, str) else value


def merged_inputs(paths):
    merged, diagnostics = {}, []
    for path in paths:
        path = Path(path)
        rows, info = read_snapshot(path)
        info = {**info, 'path':str(path), 'records':len(rows)}
        diagnostics.append(info)
        for ident, (line, record) in rows.items():
            merged[ident] = {'record':record,'path':str(path),'line':line,
                            'previous_input':merged.get(ident, {}).get('path')}
    return merged, diagnostics


def current_plan(turn):
    attempts = (turn.get('record') or {}).get('attempts') or []
    if not attempts:
        raise ValueError('ORIGINAL_RAW_MISSING: no fallback to stored semantic_plan')
    candidates = list(enumerate(attempts)) if not turn.get('semantic_plan') else [(len(attempts)-1,attempts[-1])]
    rejected=[]
    for index,attempt in candidates:
        raw=attempt.get('raw_content')
        if not isinstance(raw,str):
            rejected.append({'attempt_index':index,'reason':'ORIGINAL_RAW_MISSING'});continue
        try:
            plan=SemanticRequirementPlanV2.model_validate(parse_json_object(raw))
            return plan, {'raw_sha256':sha256(raw.encode()).hexdigest(),'raw_attempt_index':index,
                'raw_replay':True,'recovered_without_saved_plan':not bool(turn.get('semantic_plan')),
                'rejected_attempts':rejected}
        except ValueError as exc:
            rejected.append({'attempt_index':index,'reason':str(exc)})
    raise ValueError('CURRENT_SCHEMA_REPLAY_FAILED: '+json.dumps(rejected,ensure_ascii=False))


def retrieve_node(node_id, call, semantic_metric=None):
    """Represent lowerer slots without restoring semantic annotations it dropped."""
    args = call.slots.model_dump(mode='json', exclude_none=True)
    if args.get('mineral'):
        args['mineral'] = canonical(args['mineral'])
    if args.get('minerals'):
        args['minerals'] = [canonical(v) for v in args['minerals']]
    if call.action_id == 'document.retrieve':
        return RequirementNode(node_id, Operator.RETRIEVE_DOCUMENT, args=args)
    if call.action_id not in ACTION_DOMAINS:
        raise ValueError('FIXTURE_ADAPTER_GAP: fixture action '+call.action_id)
    args['domain'] = ACTION_DOMAINS[call.action_id]
    # Live IR declares row types with metric; physical price/inventory slots
    # intentionally omit it. Copy only the metric ALREADY in this logical node;
    # _action_slots round-trip must still equal the actual lowerer slots.
    if 'metric' not in args and semantic_metric:
        args['metric'] = semantic_metric
    return RequirementNode(node_id, Operator.RETRIEVE, args=args)


def fixture_contract(node, call):
    """Fail visibly when the common reader cannot honor a meaningful slot."""
    slots = call.slots.model_dump(mode='json', exclude_none=True)
    if slots.get('minerals'):
        raise ValueError('IR_ADAPTER_GAP: ENTITY_SET_FOREACH_V2')
    # The shared structured reader binds exactly ONE fixture mineral. An empty
    # binding must not become WHERE mineral=NULL and masquerade as no data.
    # This closed registry check does not split strings or inspect the question.
    mineral=canonical(slots.get('mineral'))
    if node.operator != Operator.RETRIEVE_DOCUMENT and not mineral:
        if 'mineral' in REQUIRED.get(call.action_id,()):
            raise ValueError('ACTUAL_PLAN_CONTRACT_GAP: MISSING_REQUIRED_SINGLE_MINERAL')
        raise ValueError('IR_ADAPTER_GAP: UNBOUND_SINGLE_MINERAL_FIXTURE_INPUT')
    if mineral is not None and mineral not in backend.MINERALS:
        raise ValueError('IR_ADAPTER_GAP: INVALID_STATIC_ENTITY_BINDING_NOT_IN_FIXTURE_REGISTRY')
    if call.action_id == 'trade.monthly' and (slots.get('flow') not in {None,'import'} or
                                             slots.get('metric') != 'import_amount'):
        raise ValueError('FIXTURE_ADAPTER_GAP: fixture_trade_metric_or_flow_not_supported')
    if call.action_id == 'indicator.series' and slots.get('indicator') and not slots.get('indicator_variant'):
        raise ValueError('FIXTURE_ADAPTER_GAP: fixture_indicator_slot_not_consumed')
    consumed = {'mineral','metric','flow','period','criterion_mode','resource_country','indicator_variant','topic',
                'requested_outputs','indicator'}
    unhandled = [key for key, value in slots.items() if key not in consumed and value not in (None, [], {})]
    if unhandled:
        raise ValueError('FIXTURE_ADAPTER_GAP: fixture_unconsumed_slots '+','.join(sorted(unhandled)))
    roundtrip = _action_slots(node).model_dump(mode='json', exclude_none=True)
    for key in ('mineral','metric','flow','period','criterion_mode','resource_country','indicator_variant','indicator','topic'):
        expected = canonical(slots.get(key)) if key == 'mineral' else slots.get(key)
        if roundtrip.get(key) != expected:
            raise ValueError('IR_ADAPTER_GAP: fixture_slot_roundtrip_changed '+key)


def adapt(logical):
    """One executable node per actual non-Composite node; no hidden repair."""
    logical.validate_structure()
    calls, errors, notes = {}, {}, []
    lowerer = LegacyActionLowerer()
    try:
        calls = {call.requirement_id:call for call in lowerer.lower(logical)}
    except Exception as exc:
        notes.append({'code':'WHOLE_LOWERING_FAILED','reason':str(exc)})
        # A failed sibling must not prevent other actual Retrieve nodes running.
        for node in logical.nodes:
            if node.op != Primitive.RETRIEVE:
                continue
            try:
                sub = LogicalProgramV2(nodes=[node.model_copy(update={'inputs':[]})], roots=[node.node_id])
                calls.update({call.requirement_id:call for call in lowerer.lower(sub)})
            except Exception as error:
                errors[node.node_id] = 'ACTUAL_PLAN_CONTRACT_GAP: lowering '+str(error)
    by_id = {n.node_id:n for n in logical.nodes}
    composites = {n.node_id for n in logical.nodes if n.op == Primitive.COMPOSITE}
    def flatten(ident):
        node = by_id[ident]
        if ident in composites:
            return [root for ref in node.inputs for root in flatten(ref.node_id)]
        return [ident]
    roots = tuple(dict.fromkeys(root for ident in logical.roots for root in flatten(ident)))
    nodes = []
    for original in logical.nodes:
        ident, args = original.node_id, dict(original.arguments)
        try:
            translated = relation_arguments(original.op, args)
            if translated != args:
                notes.append({'node':ident,'code':'EXPLICIT_RELATION_CONTRACT_TRANSLATION',
                              'before':args,'after':translated})
            args = translated
        except ValueError as exc:
            errors[ident] = str(exc)
        if original.op == Primitive.COMPOSITE:
            notes.append({'node':ident,'code':'COMPOSITE_ROOT_SET_ONLY','roots':flatten(ident)})
            continue
        refs = tuple(InputRef(ref.node_id, ref.selector, ref.value) for ref in original.inputs
                     if ref.node_id not in composites)
        if any(ref.node_id in composites for ref in original.inputs):
            errors[ident] = 'IR_ADAPTER_GAP: COMPOSITE_INPUT_NOT_A_VALUE'
        if original.output_type == 'EntitySet':
            errors[ident] = 'IR_ADAPTER_GAP: ENTITY_SET_FOREACH_V2'
        if original.op == Primitive.RETRIEVE:
            entity = args.get('entity') or {}
            if entity.get('source_node') or entity.get('field') or entity.get('entity_type','mineral') != 'mineral':
                errors[ident] = 'IR_ADAPTER_GAP: ENTITY_SET_OR_BINDING_INPUT_UNSUPPORTED'
            if original.inputs:
                errors[ident] = 'IR_ADAPTER_GAP: RETRIEVE_BINDING_INPUT_UNSUPPORTED'
            if ident in calls:
                try:
                    node = retrieve_node(ident, calls[ident], args.get('metric'))
                except ValueError as exc:
                    errors[ident] = str(exc)
                    node = RequirementNode(ident, Operator.RETRIEVE, args=args)
            else:
                errors.setdefault(ident, 'IR_ADAPTER_GAP: ACTION_CALL_MISSING')
                node = RequirementNode(ident, Operator.RETRIEVE, args=args)
            nodes.append(replace(node, inputs=refs))
            continue
        operator = OPERATOR_MAP.get(original.op)
        if original.op == Primitive.SELECT:
            operator = {'argmax':Operator.ARG_MAX,'argmin':Operator.ARG_MIN}.get(args.get('mode'))
        if operator is None:
            errors[ident] = 'IR_ADAPTER_GAP: unsupported '+original.op.value+' mode '+str(args.get('mode'))
            # Opaque failed-step label, not a made-up live calculation.
            operator = original.op
        nodes.append(RequirementNode(ident, operator, inputs=refs, args=args))
    # Contract failures become opaque failed steps at the same node ID, so a
    # malformed sibling does not prevent valid dataflow from being executed.
    # No validator bypass, added operator, inferred arguments or repaired edge.
    pending={n.node_id:n for n in nodes};ordered=[]
    def order(ident):
        if ident not in pending:return
        node=pending.pop(ident)
        for ref in node.inputs:order(ref.node_id)
        ordered.append(node)
    for node in nodes:order(node.node_id)
    validated=[]
    for node in ordered:
        try:
            SemanticProgram(tuple(validated+[node]),(node.node_id,))
        except ValueError as exc:
            errors.setdefault(node.node_id,'ACTUAL_PLAN_CONTRACT_GAP: LIVE_IR_CONTRACT '+str(exc))
            node=replace(node,operator=by_id[node.node_id].op)
        validated.append(node)
    return SemanticProgram(tuple(validated), roots), calls, errors, notes


def serialize_result(result):
    return {'status':result.status.value,'value':result.value,'unit':result.unit,
            'reason':result.failure_reason,'sufficient':result.sufficient,
            'failure_layer':failure_layer(result.failure_reason),
            'result_type':result.result_type.value,'evidence_count':len(result.evidence),
            'source':list(result.source),'provenance':list(result.provenance),
            'upstream_step_ids':list(result.upstream_step_ids),'warnings':list(result.warnings)}


async def run_program(logical, db):
    program, calls, errors, notes = adapt(logical)
    io_calls = []
    factory = LiveOperatorFactory(message='',session_id='offline-actual',profile='public',llm=None,history=[])
    def build(node, dependencies, bindings):
        async def invoke(_context, inputs):
            if node.node_id in errors:
                return TypedResult.abstain(errors[node.node_id])
            if node.operator in {Operator.RETRIEVE,Operator.RETRIEVE_DOCUMENT}:
                call = calls[node.node_id]
                entry = {'node':node.node_id,'action':call.action_id,
                         'slots':call.slots.model_dump(mode='json',exclude_none=True),'reader_executed':False}
                io_calls.append(entry)
                try:
                    fixture_contract(node, call)
                    entry['reader_executed']=True
                    data, sql, params = backend.read_fixture(db, node)
                    entry.update(sql=sql,params=params,row_count=len(data),status='READ')
                    result_type = ValueType.DOCUMENT_EVIDENCE if node.operator == Operator.RETRIEVE_DOCUMENT else ValueType.FACT_SET
                    metadata = dict(source=('synthetic-sqlite',),provenance=('actual-replay:'+node.node_id,),
                        evidence=(Evidence('structured','synthetic-sqlite',node.node_id,json.dumps(data,ensure_ascii=False)),),
                        period=node.args.get('period'),entity=(node.args['mineral'],) if node.args.get('mineral') else ())
                    if not data:
                        entry['status'] = 'DATA_UNAVAILABLE'
                        return TypedResult.empty(result_type, 'DATA_UNAVAILABLE', **metadata)
                    units = {r.get('unit') for r in data}
                    return TypedResult.success(result_type,data,unit=next(iter(units)) if len(units)==1 else None,**metadata)
                except (ValueError, KeyError, TypeError) as exc:
                    reason=str(exc) if any(str(exc).startswith(layer+':') for layer in GAP_LAYERS) else 'FIXTURE_ADAPTER_GAP: '+str(exc)
                    entry.update(status=failure_layer(reason),reason=reason)
                    if 'fixture_document_scope_unavailable' in str(exc):
                        entry['gap_kind']='SCOPE_UNSUPPORTED'
                    return TypedResult.abstain(reason)
            # Even zero-input derive nodes cannot fall through to real retrieval.
            if node.operator not in set(OPERATOR_MAP.values()) | {Operator.ARG_MAX,Operator.ARG_MIN}:
                return TypedResult.abstain('IR_ADAPTER_GAP: unsupported_live_operator')
            empty=[r for r in inputs.values() if r.status==ResultStatus.EMPTY]
            failed_empty=[r for r in empty if failure_layer(r.failure_reason)!='DATA_UNAVAILABLE']
            if failed_empty:
                return TypedResult.abstain('empty_upstream_contract_failure: '+str(failed_empty[0].failure_reason))
            if empty:
                return TypedResult.empty(ValueType.UNKNOWN, 'DATA_UNAVAILABLE: empty upstream')
            return await factory.build(
                node=node, dependencies=dependencies, bindings=bindings,
            ).execute(_context, inputs)
        return FunctionStep(node.node_id,node.operator.value,invoke,dependencies=dependencies,bindings=bindings)
    pipe = PipeLowerer(build).lower(program,pipe_id='actual-offline')
    # Hard tripwire: neither ActionTool nor a network fallback is allowed here.
    with patch.object(LiveOperatorFactory,'_retrieve',side_effect=AssertionError('REAL_IO_FORBIDDEN')), \
         patch.object(LiveOperatorFactory,'_call_action',side_effect=AssertionError('REAL_IO_FORBIDDEN')), \
         patch('socket.socket.connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
        executed = await PipeRuntime().execute(pipe)
    results = {ident:serialize_result(r) for ident,r in executed.results.items()}
    return {'live_program':program.to_dict(),'lowered':[c.model_dump(mode='json') for c in calls.values()],
            'adapter_notes':notes,'adapter_gaps':errors,'fixture_calls':io_calls,
            'runtime_executed':True,'results':results,'roots':{r:results[r] for r in program.roots},
            'node_status_counts':dict(Counter(r['status'] for r in results.values()))}, program, executed.results


def period_signature(period):
    period = period or {}
    if period.get('kind') == 'calendar_year':
        year = period['calendar_year']
        return ('interval',f'{year}-01-01',f'{year}-12-31')
    if period.get('kind') == 'range':
        return ('interval',period.get('start'),period.get('end'))
    return ('other',json.dumps(period,sort_keys=True))


def fingerprint(program, ident):
    """Match operators/scopes without value-based matching or question inference."""
    nodes = {n.node_id:n for n in program.nodes}
    def visit(key):
        node = nodes[key]
        args = relation_arguments(node.operator, node.args)
        if node.operator == Operator.PROJECT and len(node.inputs) == 1:
            return visit(node.inputs[0].node_id)
        if node.operator in {Operator.RETRIEVE,Operator.RETRIEVE_DOCUMENT}:
            slots = _action_slots(node).model_dump(mode='json',exclude_none=True)
            return ('retrieve',args.get('domain'),slots.get('metric'),canonical(slots.get('mineral')),
                    period_signature(slots.get('period')),slots.get('resource_country'),slots.get('indicator'),
                    slots.get('indicator_variant'),slots.get('topic'),slots.get('flow'))
        if node.operator in {Operator.ARG_MAX,Operator.ARG_MIN}:
            # Tie behavior is checked against ALL oracle rows, not assumed equal.
            parameters = {'field':args.get('field')}
        else:
            parameters = {k:v for k,v in args.items() if k not in {'mode','output_field','include_count'}}
        return (node.operator.value,json.dumps(parameters,sort_keys=True,ensure_ascii=False),
                tuple((ref.selector,ref.selector_value,visit(ref.node_id)) for ref in node.inputs))
    return visit(ident)


def expected_unit(program, ident):
    nodes = {n.node_id:n for n in program.nodes}
    def unit(key):
        n=nodes[key]
        if n.operator == Operator.RETRIEVE:
            return {'price':'USD/t','trade':'USD','resource':'t','inventory':'t','indicator':'index'}[n.args['domain']]
        if n.operator in {Operator.RETRIEVE_DOCUMENT,Operator.FOR_EACH}:
            return None
        if n.operator == Operator.AGGREGATE and n.args['aggregation']=='count':
            return None
        if n.operator == Operator.CALCULATE:
            return 'HHI(0-10000)' if n.args['calculation']=='hhi' else '%'
        if n.operator == Operator.COMPARE and n.args.get('operation')=='percent_change':
            return '%'
        values=[unit(ref.node_id) for ref in n.inputs]
        return values[0] if values and len(set(values))==1 else None
    return unit(ident)


def compare_rows(actual, expected, *, ordered=False):
    """Comparison-only projection; never changes actual runtime results/roots."""
    if not isinstance(actual,list) or not isinstance(expected,list) or len(actual)!=len(expected):
        return ['row_count_or_shape_mismatch']
    if not expected:
        return []
    if not all(isinstance(row,dict) for row in expected+actual):
        return [] if actual==expected else ['scalar_rows_mismatch']
    fields=set().union(*(row.keys() for row in expected))
    if any(not fields <= row.keys() for row in actual):
        return ['required_output_fields_missing']
    candidates=[{k:r[k] for k in fields} for r in actual]
    stable=lambda rows: rows if ordered else sorted(rows,key=lambda r:json.dumps(r,sort_keys=True,ensure_ascii=False))
    def same(a,b):
        if isinstance(b,(float,int)) and not isinstance(b,bool):
            return not isinstance(a,bool) and isinstance(a,(float,int)) and math.isfinite(a) and math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8)
        return type(a) is type(b) and a==b
    return [] if all(all(same(a[k],b[k]) for k in b) for a,b in zip(stable(candidates),stable(expected))) else ['numeric_or_dimension_mismatch']


def gold_check(case, db, program, results):
    if int(case['pattern_id'][4:]) not in backend.SUPPORTED:
        return {'status':'NO_GOLD_ORACLE','roots':[]}
    gold_program, _unused_sources, oracles = backend.gold(case,db)
    # Source arrays are never read/executed. Only final SQL oracles are compared.
    checks=[]
    signatures={root:fingerprint(program,root) for root in program.roots}
    gold_signatures={root:fingerprint(gold_program,root) for root in gold_program.roots}
    gold_nodes={n.node_id:n for n in gold_program.nodes}
    used=set()
    for gold_root, signature in gold_signatures.items():
        matches=[root for root,value in signatures.items() if value==signature]
        entry={'gold_root':gold_root,'candidate_actual_roots':matches}
        if len(matches)!=1 or list(gold_signatures.values()).count(signature)!=1:
            entry.update(status='REVIEW_NEEDED',reason='NO_UNAMBIGUOUS_ROOT_CORRESPONDENCE')
        elif not isinstance(oracles[gold_root],list):
            entry.update(status='REVIEW_NEEDED',reason='NON_NUMERIC_OR_FAILURE_ORACLE')
        else:
            root=matches[0];used.add(root);result=results[root];errors=[]
            if result.status!=ResultStatus.SUCCESS or not result.sufficient:
                errors.append('actual_root_not_success:'+str(result.failure_reason))
            else:
                head=gold_nodes[gold_root]
                while head.operator in {Operator.PROJECT,Operator.TOP_K,Operator.FILTER} and head.inputs:
                    head=gold_nodes[head.inputs[0].node_id]
                errors.extend(compare_rows(result.value,oracles[gold_root],ordered=head.operator in {Operator.SORT,Operator.RANK}))
                if result.unit!=expected_unit(gold_program,gold_root):errors.append('unit_mismatch')
                if not result.evidence or not result.source or not result.provenance:errors.append('evidence_source_provenance_missing')
                if any(w in result.warnings for w in ('incomplete_population','truncated')):errors.append('incomplete_population')
            entry.update(actual_root=root,status='INVARIANT_FAIL' if errors else 'COMPONENT_PASS',errors=errors)
        checks.append(entry)
    unmatched=sorted(set(program.roots)-used)
    status='INVARIANT_FAIL' if any(c['status']=='INVARIANT_FAIL' for c in checks) else (
        'COMPONENT_PASS' if checks and not unmatched and all(c['status']=='COMPONENT_PASS' for c in checks) else 'REVIEW_NEEDED')
    return {'status':status,'roots':checks,'unmatched_actual_roots':unmatched,'full_semantic_pass':False}


async def replay_turn(turn, case, db):
    record={'turn':turn.get('turn'),'runtime_executed':False,'full_semantic_pass':False}
    try:
        plan,replay=current_plan(turn)
        record.update(**replay,semantic_plan=plan.model_dump(mode='json'))
    except Exception as exc:
        return {**record,'status':'PARSER_OR_SCHEMA_FAIL','reason':str(exc)}
    if plan.request_class!='DATA_QUERY':
        return {**record,'status':'UNSUPPORTED','reason':plan.unsupported_reason}
    try:
        logical=logical_program_from_requirements(plan)
        record['logical_program']=logical.to_dict()
    except Exception as exc:
        return {**record,'status':'PLANNER_FAIL','reason':str(exc)}
    record['unexecuted_semantic_constraints']=[{'requirement':r.requirement_id,'constraints':r.constraints}
                                                for r in plan.requirements if r.constraints]
    try:
        execution,program,results=await run_program(logical,db)
        record.update(execution)
        reasons=list(record['adapter_gaps'].values())+[r.get('reason') or '' for r in record['results'].values()]
        record['failure_layers']=sorted({failure_layer(reason) for reason in reasons if reason})
        record['status']=next((layer for layer in GAP_LAYERS if layer in record['failure_layers']),
            runtime_outcome(record['roots']))
        try:
            record['gold_validation']=gold_check(case,db,program,results)
        except Exception as exc:
            record['gold_validation']={'status':'REVIEW_NEEDED','roots':[],
                                       'reason':'ORACLE_CORRESPONDENCE_ERROR: '+str(exc)}
    except Exception as exc:
        record.update(status='ADAPTER_OR_RUNTIME_FAIL',reason=f'{type(exc).__name__}: {exc}')
    return record


async def build_report(paths, *, cases=None, audit_path=None, progress=True):
    cases=backend.CASES if cases is None else cases
    merged,diagnostics=merged_inputs(paths)
    audit={}
    if audit_path:
        audit={c['id']:c for c in json.loads(Path(audit_path).read_text())['cases']}
    db=backend.fixture();records=[]
    try:
        for case in cases:
            selected=merged.get(case['id'])
            row={'id':case['id'],'pattern_id':case['pattern_id'],'status':'MISSING_INPUT',
                 'full_semantic_pass':False,'production_e2e':False,'physical_io_executed':False,'turns':[]}
            if selected:
                row['input']={k:v for k,v in selected.items() if k!='record'}
                actual=selected['record']; turns={t.get('turn'):t for t in actual.get('turns',[]) if isinstance(t,dict)}
                row['input_identity_issues']=[]
                if actual.get('pattern_id')!=case['pattern_id']:row['input_identity_issues'].append('PATTERN_ID_MISMATCH')
                for expected in case['turns']:
                    turn=turns.get(expected['turn'])
                    if turn is None:
                        row['turns'].append({'turn':expected['turn'],'status':'MISSING_INPUT','runtime_executed':False})
                        continue
                    if turn.get('question')!=expected['question']:row['input_identity_issues'].append('QUESTION_MISMATCH:'+str(expected['turn']))
                    row['turns'].append(await replay_turn(turn,case,db))
                statuses=[t['status'] for t in row['turns']]
                precedence=['MISSING_INPUT','PARSER_OR_SCHEMA_FAIL','PLANNER_FAIL','ADAPTER_OR_RUNTIME_FAIL',
                            *GAP_LAYERS,'RUNTIME_FAILURE','DATA_UNAVAILABLE','UNSUPPORTED','RUNTIME_SUCCESS_NOT_SEMANTIC_PASS']
                row['status']=next(s for s in precedence if s in statuses)
            row['runtime_executed']=any(t.get('runtime_executed') for t in row['turns'])
            row['all_turns_runtime_executed']=bool(row['turns']) and all(t.get('runtime_executed') for t in row['turns'])
            row['failure_layers']=sorted({layer for t in row['turns'] for layer in t.get('failure_layers',[])})
            if len(case['turns'])>1:
                row['multiturn_status']='IR_ADAPTER_GAP: previous_requirements_only_no_snapshot_binding'
            if case['id'] in audit:
                a=audit[case['id']]
                row['semantic_audit']={k:a.get(k) for k in ('status','evaluation_eligibility','definite_semantic_mismatch_count')}
            records.append(row)
            if progress and (len(records)%25==0 or len(records)==len(cases)):
                print(f'completed={len(records)}/{len(cases)} PENDING={len(cases)-len(records)}',file=sys.stderr,flush=True)
    finally:
        db.close()
    all_turns=[t for r in records for t in r['turns']]
    nodes=[n for t in all_turns for n in t.get('results',{}).values()]
    checks=[c for t in all_turns for c in t.get('gold_validation',{}).get('roots',[])]
    for row in records:
        validations=[t['gold_validation']['status'] for t in row['turns'] if 'gold_validation' in t]
        row['gold_status']=next((s for s in ('INVARIANT_FAIL','REVIEW_NEEDED','COMPONENT_PASS','NO_GOLD_ORACLE')
                                 if s in validations),'NOT_EXECUTED')
    summary={'TOTAL':len(cases),'COMPLETED':len(records),'PENDING':len(cases)-len(records),
        'runtime_cases':sum(r['runtime_executed'] for r in records),
        'all_turns_runtime_cases':sum(r['all_turns_runtime_executed'] for r in records),
        'runtime_turns':sum(t.get('runtime_executed',False) for t in all_turns),
        'case_status':dict(Counter(r['status'] for r in records)),
        'turn_status':dict(Counter(t['status'] for t in all_turns)),
        'node_status':dict(Counter(n['status'] for n in nodes)),
        'failure_layer_case_counts_overlapping':dict(Counter(layer for r in records for layer in r['failure_layers'])),
        'explicit_relation_translations':sum(n.get('code')=='EXPLICIT_RELATION_CONTRACT_TRANSLATION'
            for t in all_turns for n in t.get('adapter_notes',[])),
        'gold_supported_cases':sum(int(c['pattern_id'][4:]) in backend.SUPPORTED for c in cases),
        'gold_case_status':dict(Counter(r['gold_status'] for r in records)),
        'gold_root_invariants':dict(Counter(c['status'] for c in checks)),
        'full_semantic_pass':0,'production_e2e_pass':0,'physical_io_calls':0}
    if audit:
        review=[r for r in records if r.get('semantic_audit',{}).get('status')=='REVIEW_NEEDED'
                and r['semantic_audit'].get('evaluation_eligibility')=='COMPLETE_TYPED_LOG']
        summary['review_typed_complete']={'total':len(review),'runtime':sum(r['runtime_executed'] for r in review),
                                        'status':dict(Counter(r['status'] for r in review))}
    modules={obj.__module__ for obj in (LegacyActionLowerer,LiveOperatorFactory,SemanticProgram,PipeRuntime,backend.gold)}
    code_hashes={name:sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest() for name in modules}
    return {'version':'qa500-actual-execution-v2','summary':summary,'inputs':diagnostics,'code_sha256':code_hashes,
            'classification_contract':{'ACTUAL_PLAN_CONTRACT_GAP':'Current planner/lowerer or live IR rejects explicit actual plan; not proof of absent physical capability',
                'IR_ADAPTER_GAP':'Test-only V2/live IR bridge cannot represent or execute this construct',
                'FIXTURE_ADAPTER_GAP':'Synthetic reader lacks action/data/slot/period/scope support; production capability untested',
                'RUNTIME_FAILURE':'Current live operator failed on fixture data; inspect exact reason before attributing a production gap',
                'DATA_UNAVAILABLE':'Validated eligible fixture read returned zero rows, or propagation of that exact reason; never inferred from EMPTY alone',
                'primary_status_precedence':list(GAP_LAYERS),'failure_layers':'Overlapping per-QA evidence; primary status is not exhaustive'},
            'unknown_input_ids':sorted(set(merged)-{c['id'] for c in backend.CASES}),
            'adapter_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Actual raw -> current V2 planner/lowerer -> test-only IR adapter -> SQLite/PipeRuntime; not production E2E',
            'records':records}


class ActualExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.db=backend.fixture()
    @classmethod
    def tearDownClass(cls):cls.db.close()

    def plan(self, **kwargs):
        return SemanticRequirementPlanV2.model_validate({'requirements':[{
            'requirement_id':'actual','metric':'price','entity':{'value':'니켈'},
            'time_range':{'kind':'calendar_year','value':2025},**kwargs}]})

    def run_plan(self,plan):
        return asyncio.run(run_program(logical_program_from_requirements(plan),self.db))

    def test_scalar_mean_real_runtime_independent_sql(self):
        record,program,results=self.run_plan(self.plan(aggregation='mean'))
        result=results[program.roots[0]]
        expected=self.db.execute("SELECT AVG(value) FROM observations WHERE domain='price' AND mineral='니켈' AND year=2025").fetchone()[0]
        self.assertEqual(result.status,ResultStatus.SUCCESS)
        self.assertAlmostEqual(result.value[0]['value'],expected)
        self.assertTrue(result.evidence and result.provenance)
        self.assertEqual(record['fixture_calls'][0]['slots']['mineral'],'니켈')

    def test_extremum_all_ties_and_gold_sql_match(self):
        _,program,results=self.run_plan(self.plan(selection={'mode':'argmax','field':'high_price','ties':'all'}))
        result=results[program.roots[0]]
        expected=backend.query(self.db,"SELECT date,high_price FROM observations WHERE domain='price' AND mineral='니켈' AND year=2025 AND high_price=(SELECT MAX(high_price) FROM observations WHERE domain='price' AND mineral='니켈' AND year=2025)")
        self.assertEqual(compare_rows(result.value,expected),[])
        case=next(c for c in backend.CASES if c['pattern_id']=='PAT-001' and c['variant_id']=='V1')
        self.assertEqual(gold_check(case,self.db,program,results)['status'],'COMPONENT_PASS')

    def test_different_metric_does_not_match_by_numeric_coincidence(self):
        _,program,results=self.run_plan(self.plan(selection={'mode':'argmax','field':'value','ties':'all'}))
        case=next(c for c in backend.CASES if c['pattern_id']=='PAT-001' and c['variant_id']=='V1')
        self.assertEqual(gold_check(case,self.db,program,results)['status'],'REVIEW_NEEDED')

    def test_future_observations_are_empty_never_sufficient(self):
        for mineral in ('니켈','구리','리튬','코발트'):
            with self.subTest(mineral=mineral):
                record,_,results=self.run_plan(self.plan(entity={'value':mineral},time_range={'kind':'year','value':2030}))
                self.assertEqual(record['fixture_calls'][0]['row_count'],0)
                self.assertEqual(results['actual'].status,ResultStatus.EMPTY)
                self.assertFalse(results['actual'].sufficient)
                self.assertEqual(results['actual'].failure_reason,'DATA_UNAVAILABLE')

    def test_no_gold_operation_or_constraint_injection(self):
        plan=self.plan(constraints=[{'field':'country','value':'중국'}])
        record,program,_=self.run_plan(plan)
        self.assertEqual(len(program.nodes),1)
        self.assertEqual(len(program.roots),1)
        self.assertNotIn('country=?',record['fixture_calls'][0]['sql'])

    def test_unknown_selection_failure_does_not_block_sibling(self):
        plan=self.plan(selection={'mode':'latest'})
        other=self.plan(aggregation='mean').requirements[0].model_copy(update={'requirement_id':'other'})
        plan.requirements.append(other)
        record,program,results=self.run_plan(plan)
        self.assertEqual(set(program.roots),{'actual_select','other_aggregate'})
        self.assertEqual(results['actual_select'].status,ResultStatus.ABSTAINED)
        self.assertEqual(results['other_aggregate'].status,ResultStatus.SUCCESS)
        self.assertEqual(len(record['fixture_calls']),2)

    def test_missing_raw_does_not_fall_back_to_stored_plan(self):
        with self.assertRaisesRegex(ValueError,'ORIGINAL_RAW_MISSING'):
            current_plan({'semantic_plan':self.plan().model_dump(mode='json')})

    def test_latest_failed_attempt_does_not_fall_back_to_earlier_success(self):
        with self.assertRaises(ValueError):
            current_plan({'semantic_plan':self.plan().model_dump(mode='json'),
                'record':{'attempts':[{'raw_content':self.plan().model_dump_json()}, {'raw_content':'broken'}]}})

    def test_old_schema_failure_can_replay_first_raw_with_current_year_contract(self):
        plan,trace=current_plan({'record':{'attempts':[{'raw_content':self.plan().model_dump_json()}, {'raw_content':'broken'}]}})
        self.assertEqual(plan.requirements[0].time_range.value,2025)
        self.assertEqual(trace['raw_attempt_index'],0)
        self.assertTrue(trace['recovered_without_saved_plan'])

    def test_bound_entity_is_not_filled_from_gold(self):
        # An unresolved external reference is now rejected before the adapter,
        # rather than emitted as a static lookup and blocked during execution.
        with patch.object(backend,'read_fixture',wraps=backend.read_fixture) as reader:
            with self.assertRaisesRegex(ValueError,'unresolved_entity_reference:previous'):
                self.run_plan(self.plan(entity={'source_node':'previous','field':'mineral'}))
            reader.assert_not_called()

    def test_calls_read_fixture_with_lowered_slots_at_runtime(self):
        with patch.object(backend,'read_fixture',wraps=backend.read_fixture) as reader:
            self.run_plan(self.plan(entity={'value':'nickel'}))
            self.assertEqual(reader.call_count,1)
            self.assertEqual(reader.call_args.args[1].args['mineral'],'니켈')

    def test_overlay_order_including_failure_is_not_cherry_picked(self):
        snapshots=[({'X':(1,{'id':'X','status':s})},{}) for s in ('before','after','after2','failed')]
        with patch(__name__+'.read_snapshot',side_effect=snapshots):
            merged,_=merged_inputs(['before','after','after2','recovered'])
        self.assertEqual(merged['X']['record']['status'],'failed')
        self.assertEqual(merged['X']['path'],'recovered')

    def test_unknown_scope_is_scope_unsupported_not_empty_or_monthly(self):
        record,program,results=self.run_plan(self.plan(metric='document_evidence',
            document_requirement={'topic':'unknown report'}))
        result=results[program.roots[0]]
        self.assertEqual(result.status,ResultStatus.ABSTAINED)
        self.assertIn('FIXTURE_ADAPTER_GAP: fixture_document_scope_unavailable',result.failure_reason)
        self.assertEqual(record['fixture_calls'][0]['status'],'FIXTURE_ADAPTER_GAP')
        self.assertEqual(record['fixture_calls'][0]['gap_kind'],'SCOPE_UNSUPPORTED')

    def test_exact_shared_document_scopes_are_used_without_alias_repair(self):
        for topic in ('monthly','news','희소금속 월간동향','일일 자원뉴스'):
            with self.subTest(topic=topic):
                record,program,results=self.run_plan(self.plan(metric='document_evidence',document_requirement={'topic':topic}))
                self.assertEqual(results[program.roots[0]].status,ResultStatus.SUCCESS)
                self.assertEqual(record['fixture_calls'][0]['slots']['topic'],topic)

    def test_unknown_calculation_remains_a_real_runtime_failure(self):
        record,program,results=self.run_plan(self.plan(operation='invented_calculation'))
        self.assertEqual(results[program.roots[0]].failure_reason,'unsupported_calculation_contract')
        self.assertEqual(len(record['live_program']['nodes']),2)

    def test_gold_invariants_detect_numeric_unit_evidence_and_date_damage(self):
        _,program,results=self.run_plan(self.plan(selection={'mode':'argmax','field':'high_price','ties':'all'}))
        case=next(c for c in backend.CASES if c['pattern_id']=='PAT-001' and c['variant_id']=='V1')
        root=program.roots[0];original=results[root]
        variants=[replace(original,unit='wrong'),replace(original,evidence=()),
                  replace(original,value=[{**r,'high_price':r['high_price']+1} for r in original.value]),
                  replace(original,value=[{**r,'date':'1900-01-01'} for r in original.value])]
        for result in variants:
            with self.subTest(result=result):
                self.assertEqual(gold_check(case,self.db,program,{**results,root:result})['status'],'INVARIANT_FAIL')

    def test_empty_source_is_not_promoted_by_downstream_aggregate(self):
        _,program,results=self.run_plan(self.plan(aggregation='mean',time_range={'kind':'year','value':2030}))
        self.assertEqual(results[program.roots[0]].status,ResultStatus.EMPTY)
        self.assertFalse(results[program.roots[0]].sufficient)

    def relation_program(self, op, arguments):
        plan=self.plan()
        plan.requirements.append(self.plan(entity={'value':'구리'}).requirements[0].model_copy(update={'requirement_id':'right'}))
        retrieves=[n for n in logical_program_from_requirements(plan).nodes if n.op==Primitive.RETRIEVE]
        node=LogicalNodeV2(node_id='relation',op=op,inputs=[InputRefV2(node_id=n.node_id) for n in retrieves],
                           arguments=arguments,output_type='FactSet')
        return LogicalProgramV2(nodes=retrieves+[node],roots=['relation'])

    def test_explicit_join_key_list_translation_executes_live_join(self):
        logical=self.relation_program(Primitive.JOIN,{'join_key':'date'})
        record,program,results=asyncio.run(run_program(logical,self.db))
        self.assertEqual(program.nodes[-1].args,{'join_key':['date']})
        self.assertEqual(logical.nodes[-1].arguments,{'join_key':'date'})
        self.assertEqual(results['relation'].status,ResultStatus.SUCCESS)
        expected=backend.query(self.db,"SELECT p.date FROM observations p JOIN observations q ON p.date=q.date WHERE p.domain='price' AND q.domain='price' AND p.mineral='니켈' AND q.mineral='구리' AND p.year=2025")
        self.assertEqual(compare_rows(results['relation'].value,expected),[])
        self.assertTrue(any(n['code']=='EXPLICIT_RELATION_CONTRACT_TRANSLATION' for n in record['adapter_notes']))

    def test_explicit_compare_one_and_two_fields_against_sql(self):
        for fields in (['value'],['high_price','low_price']):
            with self.subTest(fields=fields):
                logical=self.relation_program(Primitive.COMPARE,{'join_key':'date','fields':fields,'operation':'difference'})
                _,program,results=asyncio.run(run_program(logical,self.db))
                result=results['relation'];self.assertEqual(result.status,ResultStatus.SUCCESS)
                args=program.nodes[-1].args
                if len(fields)==1:self.assertEqual(args['field'],'value')
                else:self.assertEqual((args['left_field'],args['right_field']),tuple(fields))
                expected=backend.query(self.db,f"SELECT p.date,p.{fields[0]}-q.{fields[-1]} difference FROM observations p JOIN observations q ON p.date=q.date WHERE p.domain='price' AND q.domain='price' AND p.mineral='니켈' AND q.mineral='구리' AND p.year=2025")
                self.assertEqual(compare_rows(result.value,expected),[])

    def test_translation_never_adds_operation_or_default_key(self):
        for fields in (['value'],['high_price','low_price']):
            translated=relation_arguments(Primitive.COMPARE,{'fields':fields})
            self.assertNotIn('operation',translated)
            self.assertNotIn('join_key',translated)
        for args in ({},{'join_key':None,'fields':[]},{'fields':['a','b','c']}):
            self.assertEqual(relation_arguments(Primitive.COMPARE,args),args)
        _,program,results=asyncio.run(run_program(self.relation_program(Primitive.COMPARE,
            {'join_key':'date','fields':['value']}),self.db))
        self.assertNotIn('operation',program.nodes[-1].args)
        self.assertEqual(results['relation'].status,ResultStatus.SUCCESS)
        self.assertNotIn('difference',results['relation'].value[0])

    def test_missing_relation_operands_remain_actual_plan_contract_gaps(self):
        for op,args in ((Primitive.JOIN,{'join_key':None}),(Primitive.COMPARE,{'fields':[]})):
            with self.subTest(op=op):
                record,_,results=asyncio.run(run_program(self.relation_program(op,args),self.db))
                self.assertEqual(results['relation'].status,ResultStatus.ABSTAINED)
                self.assertEqual(record['results']['relation']['failure_layer'],'ACTUAL_PLAN_CONTRACT_GAP')
                self.assertEqual(record['results']['actual']['status'],'success')

    def test_conflicting_explicit_fields_are_not_overwritten(self):
        for args in ({'fields':['a'],'field':'b'},{'fields':['a','b'],'left_field':'b'},
                     {'fields':['a','b'],'right_field':'a'},{'fields':['a','b'],'field':'a'}):
            with self.assertRaisesRegex(ValueError,'conflicting_explicit_compare_fields'):
                relation_arguments(Primitive.COMPARE,args)

    def test_concentration_exists_in_lowerer_but_is_a_fixture_adapter_gap(self):
        record,_,results=self.run_plan(self.plan(metric='concentration'))
        self.assertEqual(record['lowered'][0]['action_id'],'trade.concentration')
        self.assertEqual(record['results']['actual']['failure_layer'],'FIXTURE_ADAPTER_GAP')
        self.assertEqual(results['actual'].failure_reason,'FIXTURE_ADAPTER_GAP: fixture action trade.concentration')

    def test_layer_classification_distinguishes_fixture_bridge_plan_and_runtime(self):
        for reason,expected in (
            ('FIXTURE_ADAPTER_GAP: fixture requires explicit supported period','FIXTURE_ADAPTER_GAP'),
            ('IR_ADAPTER_GAP: ENTITY_SET_FOREACH_V2','IR_ADAPTER_GAP'),
            ('ACTUAL_PLAN_CONTRACT_GAP: missing comparison operands','ACTUAL_PLAN_CONTRACT_GAP'),
            ('unsupported_calculation_contract','CURRENT_RUNTIME_FAILURE')):
            self.assertEqual(failure_layer(reason),expected)

    def test_invalid_static_or_missing_required_mineral_never_queries_fixture(self):
        for mineral in (None,'','니켈, 구리, 아연','all','not-in-fixture'):
            with self.subTest(mineral=mineral), patch.object(backend,'read_fixture',wraps=backend.read_fixture) as reader:
                record,_,results=self.run_plan(self.plan(entity={'value':mineral}))
                reader.assert_not_called()
                self.assertEqual(results['actual'].status,ResultStatus.ABSTAINED)
                self.assertNotEqual(results['actual'].failure_reason,'DATA_UNAVAILABLE')
                self.assertFalse(record['fixture_calls'][0]['reader_executed'])
                expected='MISSING_REQUIRED_SINGLE_MINERAL' if not mineral else 'INVALID_STATIC_ENTITY_BINDING_NOT_IN_FIXTURE_REGISTRY'
                self.assertIn(expected,results['actual'].failure_reason)

    def test_unbound_global_trade_is_bridge_gap_not_missing_production_capability(self):
        with patch.object(backend,'read_fixture',wraps=backend.read_fixture) as reader:
            record,_,results=self.run_plan(self.plan(metric='import_value',entity=None))
        reader.assert_not_called()
        self.assertEqual(results['actual'].failure_reason,'IR_ADAPTER_GAP: UNBOUND_SINGLE_MINERAL_FIXTURE_INPUT')
        self.assertFalse(record['fixture_calls'][0]['reader_executed'])

    def test_optional_document_entity_can_remain_unbound(self):
        record,_,results=self.run_plan(self.plan(metric='document_evidence',entity=None,
                                               document_requirement={'topic':'monthly'}))
        self.assertEqual(results['actual'].status,ResultStatus.SUCCESS)
        self.assertTrue(record['fixture_calls'][0]['reader_executed'])

    def test_actual_inventory_rows_then_missing_field_empty_is_runtime_failure(self):
        record,_,results=self.run_plan(self.plan(metric='inventory',selection={'mode':'argmax','field':'inventory'}))
        self.assertEqual(record['fixture_calls'][0]['row_count'],24)
        self.assertEqual(results['actual_select'].status,ResultStatus.EMPTY)
        self.assertEqual(results['actual_select'].failure_reason,'arg field unavailable: inventory')
        self.assertEqual(runtime_outcome(record['roots']),'RUNTIME_FAILURE')

    def test_empty_field_failure_is_not_laundered_by_downstream_aggregate(self):
        logical=logical_program_from_requirements(self.plan(metric='inventory',selection={'mode':'argmax','field':'inventory'}))
        logical.nodes.append(LogicalNodeV2(node_id='followup',op=Primitive.AGGREGATE,
            inputs=[InputRefV2(node_id=logical.roots[0])],arguments={'aggregation':'mean','field':'value'},output_type='FactSet'))
        logical.roots=['followup']
        record,_,results=asyncio.run(run_program(logical,self.db))
        self.assertEqual(results['followup'].status,ResultStatus.ABSTAINED)
        self.assertIn('empty_upstream_contract_failure',results['followup'].failure_reason)
        self.assertEqual(runtime_outcome(record['roots']),'RUNTIME_FAILURE')

    def test_true_empty_cannot_mask_other_root_failure(self):
        empty={'status':'empty','reason':'DATA_UNAVAILABLE'}
        self.assertEqual(runtime_outcome({'source':empty}),'DATA_UNAVAILABLE')
        self.assertEqual(runtime_outcome({'source':empty,'bad':{'status':'abstained','reason':'invalid_numeric_operand'}}),'RUNTIME_FAILURE')
        self.assertEqual(runtime_outcome({'bad':{'status':'empty','reason':'field unavailable'}}),'RUNTIME_FAILURE')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs','--input',nargs='+',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--audit',type=Path)
    parser.add_argument('--baseline',type=Path,help='Read-only earlier report for archived before/after counts')
    parser.add_argument('--summary-output',type=Path,help='Compact counts and one classification per QA')
    parser.add_argument('--patterns',nargs='+',type=int,help='Small smoke selection; omit for all 500')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ActualExecutionTests))
        return 0 if result.wasSuccessful() else 1
    if not args.inputs or not args.output:parser.error('--inputs and --output required')
    cases=[c for c in backend.CASES if not args.patterns or int(c['pattern_id'][4:]) in args.patterns]
    report=asyncio.run(build_report(args.inputs,cases=cases,audit_path=args.audit))
    if args.baseline:
        previous_bytes=args.baseline.read_bytes();previous=json.loads(previous_bytes)
        before={r['id']:r for r in previous['records']}
        transitions=Counter((before[r['id']]['status'],r['status']) for r in report['records'] if r['id'] in before)
        report['baseline_comparison']={'path':str(args.baseline),'sha256':sha256(previous_bytes).hexdigest(),
            'summary':previous['summary'],'transitions':[{'before':a,'after':b,'cases':count}
                for (a,b),count in sorted(transitions.items())],
            'interpretation':'Layer relabeling does not imply an execution improvement; compare runtime/node and Gold counts separately'}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n')
    if args.summary_output:
        compact={k:v for k,v in report.items() if k!='records'}
        compact['full_report']=str(args.output)
        compact['full_report_sha256']=sha256(args.output.read_bytes()).hexdigest()
        compact['records']=[{k:r.get(k) for k in ('id','pattern_id','status','failure_layers','gold_status',
                           'runtime_executed','all_turns_runtime_executed','semantic_audit')} for r in report['records']]
        args.summary_output.write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))
    return 0 if report['summary']['PENDING']==0 else 1


if __name__=='__main__':
    raise SystemExit(main())
