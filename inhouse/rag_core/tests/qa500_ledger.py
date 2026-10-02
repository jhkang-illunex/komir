"""Join QA500 evidence by ID; never promotes a component result to question PASS."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def build(directory,actual_path,audit_path,manual_path):
    corpus=read(Path(__file__).with_name('qa_build_order2_4_500.json'))['cases']
    actual={r['id']:r for r in read(actual_path)['records']}
    audited={r['id']:r for r in read(audit_path)['cases']}
    manual={r['id']:r for r in read(manual_path)['records']}
    gold={r['id']:r for r in read(directory/'gold_backend.json.gz')}
    gold.update({r['id']:r for r in read(directory/'gold_series.json.gz')})
    gold.update({r['id']:r for r in read(directory/'gold_multiturn.json.gz')['records']})
    assert len(actual)==len(audited)==len(corpus)==500
    rows=[]
    for case in corpus:
        ident=case['id'];a=actual[ident];s=audited[ident]
        findings=[f for f in s['findings'] if f['status']=='SEMANTIC_MISMATCH']
        state=a['status']
        reviewed=manual.get(ident)
        if reviewed:
            assert [t.get('raw_sha256') for t in a['turns']]==[t['raw_sha256'] for t in reviewed['turns']]
        defects=[d for t in (reviewed or {}).get('turns',[]) for d in t['defects']]
        if findings:
            status='FAILED';reason='SEMANTIC_MISMATCH'
        elif reviewed and reviewed.get('full_semantic_pass') and a['all_turns_runtime_executed']:
            status='PASS';reason='ACTUAL_GEMMA_AND_INDEPENDENT_SQL_CONFORMANCE'
        elif state in {'PARSER_OR_SCHEMA_FAIL','PLANNER_FAIL','RUNTIME_FAILURE','ADAPTER_OR_RUNTIME_FAIL','ACTUAL_PLAN_CONTRACT_GAP'}:
            status='FAILED';reason=state
        elif reviewed and defects:
            status='FAILED';reason=defects[0]['code']
        elif reviewed and not defects:
            status='CAPABILITY_GAP';reason='EVALUATION_ORACLE_GAP'
        elif a['gold_status']=='INVARIANT_FAIL':
            status='FAILED';reason='RESULT_INVARIANT_FAIL'
        elif state in {'IR_ADAPTER_GAP','FIXTURE_ADAPTER_GAP'}:
            status='CAPABILITY_GAP';reason=state
        elif state=='DATA_UNAVAILABLE':
            status='BLOCKED';reason='SYNTHETIC_DATA_SCOPE_GAP_NOT_PRODUCTION_DATA_ABSENCE'
        elif state=='UNSUPPORTED':
            status='UNSUPPORTED';reason='MODEL_REJECTION_NOT_VERIFIED_AS_CORRECT'
        elif state=='RUNTIME_SUCCESS_NOT_SEMANTIC_PASS':
            # No backend success is a full-question proof: roots/projection and
            # semantic constraints still require an executable contract.
            status='CAPABILITY_GAP';reason='OUTPUT_OR_SEMANTIC_CONFORMANCE_CONTRACT_GAP'
        else:
            raise AssertionError(f'Unclassified execution status: {ident} {state}')
        turns=a['turns'];g=gold.get(ident)
        rows.append({'id':ident,'question':case['question'],'pattern_id':case['pattern_id'],
            'order':case['order'],'status':status,'reason':reason,
            'gemma_called':True,'runtime_executed':a['runtime_executed'],
            'all_turns_runtime_executed':a['all_turns_runtime_executed'],
            'selected_model_record':a.get('input'),
            'actual_execution_status':state,'gold_oracle_status':a['gold_status'],
            'semantic_findings':findings,
            'independent_manual_review':reviewed,
            'remaining_conformance_checks':[f for f in s['findings'] if f['status']=='REVIEW_NEEDED'],
            'failure_layers':a.get('failure_layers',[]),
            'gold_backend_status':g['status'] if g else 'NO_EXECUTABLE_GOLD_PLAN',
            'gold_backend_executed':bool(g and g.get('backend_executed',True)),
            'production_http_sse_executed':False,
            'turn_failures':[{'turn':t.get('turn'),'status':t['status'],'reason':t.get('reason'),
                'adapter_gaps':t.get('adapter_gaps',{}),
                'failed_roots':{k:v for k,v in t.get('roots',{}).items() if v['status']!='success'}} for t in turns],
            'trace_artifact':actual_path.name+'.gz',
            'semantic_audit_artifact':'qa500-semantic-current.json.gz'})
    counts={key:sum(r['status']==key for r in rows) for key in
            ('PASS','FAILED','CAPABILITY_GAP','UNSUPPORTED','BLOCKED','PENDING')}
    assert sum(counts.values())==500 and len({r['id'] for r in rows})==500
    result={'scope':'Real Gemma shadow + offline current-plan replay. NOT deployed HTTP SSE E2E.',
        'TOTAL_CORPUS':500,'REGISTERED':500,**counts,
        'gold_backend_status_counts':dict(Counter(r['gold_backend_status'] for r in rows)),
        'reason_counts':dict(Counter(r['reason'] for r in rows)),
        'interpretation':'PENDING=0 means every QA was attempted and classified, not all semantics supported. '
            'IR/FIXTURE_ADAPTER_GAP is a testing boundary, not evidence of absent production capability. '
            'UNSUPPORTED is an observed model rejection, not UNSUPPORTED_CORRECT.',
        'records':rows}
    (directory/'corpus_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    with (directory/'corpus_results.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        fields=['id','pattern_id','order','question','status','reason','gemma_called',
                'runtime_executed','all_turns_runtime_executed','actual_execution_status',
                'gold_oracle_status','gold_backend_status','production_http_sse_executed']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--actual',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--manual',type=Path,required=True)
    args=parser.parse_args()
    build(args.directory,args.actual,args.audit,args.manual)
