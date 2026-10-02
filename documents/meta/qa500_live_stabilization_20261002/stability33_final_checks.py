"""Independent SQL checks; failed live responses remain failed checks."""
import json,math
from pathlib import Path
base=Path('/tmp/stability33-sse');sql=json.load(open('/tmp/stability33-sql-final.json'))
queries={q['name']:q['rows'] for q in sql['queries']};checks=[]
def req(n):return json.loads((base/(n+'.json')).read_text())
def turns(n):return [t for t in sql['isolated_history'] if t['session_id']==req(n)['request']['session_id']]
def root(t):return t['result_json']['results'][t['program_json']['roots'][0]]
def check(n,ok,detail):checks.append({'check':n,'pass':bool(ok),'detail':detail})
total=float(queries['production_country_aggregate'][0]['total_ton']);avg=float(queries['production_country_aggregate'][0]['mean_ton'])
for name in [f'{kind}-{suffix}' for suffix in ['r10','r10cold'] for kind in ['difference','sum','chile','price']]:
    r=req(name)
    if r['done'].get('abstained'):
        check(name,False,{'stage':'response','reason':r['done'].get('abstain_reason')});continue
    data=root(turns(name)[0])['value'][0]
    if name.startswith('difference'):
        ok=math.isclose(data['left_value'],total) and math.isclose(data['right_value'],avg) and math.isclose(data['difference'],total-avg)
        expected={'sum':total,'avg':avg,'difference':total-avg}
    elif name.startswith('sum'):
        expected=total;ok=any(isinstance(v,(float,int)) and math.isclose(v,total) for v in data.values())
    elif name.startswith('chile'):
        expected=float(next(r for r in queries['production_population'] if r['ntn_eng_cd']=='CL')['prdctn_quty_ton']);ok=math.isclose(float(data['production_volume']),expected)
    else:
        expected=float(queries['price502'][0]['cmerc_prc']);ok=math.isclose(float(data.get('price',data.get('value',data.get('cmerc_prc(통상가격)')))),expected)
    check(name,ok,{'actual':data,'sql':expected})
for suffix in ['r10','r10b','r10cold']:
    ts=turns('document-'+suffix)
    envelopes=[r for r in ts[0]['result_json']['results'].values() if isinstance(r.get('value'),list) and r['value'] and all(isinstance(x,dict) and 'mineral' in x and 'status' in x and 'value' in x for x in r['value'])]
    if not envelopes:
        check('document_'+suffix,False,'no per-item envelope');continue
    success={r['mineral']:r for r in envelopes[0]['value'] if r['status']=='success'}
    check('units_'+suffix,all(r.get('unit') for r in success.values()),{k:r.get('unit') for k,r in success.items()})
    for kind in ['reference','refresh']:
        r=req(kind+'-'+suffix)
        if r['done'].get('abstained'):
            check(kind+'_'+suffix,False,r['done']);continue
        candidates=[t for t in ts if any(n['operator']=='retrieve' for n in t['program_json']['nodes'])] if kind=='refresh' else ts[1:2]
        actual=root(candidates[-1])['value']
        check(kind+'_entities_'+suffix,{row['mineral'] for row in actual}==set(success),{'actual':actual,'expected_entities':list(success)})
        if kind=='refresh':
            expected={k:float(v['value'][0]['cmerc_prc(통상가격)']) for k,v in success.items()}
            observed={row['mineral']:float(row.get('price',row.get('value',row.get('cmerc_prc(통상가격)')))) for row in actual if row.get('price',row.get('value',row.get('cmerc_prc(통상가격)'))) is not None}
            check('refresh_values_'+suffix,observed==expected,{'actual':observed,'expected':expected})
if (base/'restored-r10cold.json').exists():
    t=turns('restored-r10cold')[-1]
    operations=[n['operator'] for n in t['program_json']['nodes']]
    check('restart_restored_entities', {r['mineral'] for r in root(t)['value']}==set(success), {'operations':operations,'value':root(t)['value']})
    check('restart_no_new_retrieval',not set(operations)&{'retrieve','retrieve_document','for_each'},operations)
Path('/tmp/stability33-final-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print({'checks':len(checks),'passed':sum(c['pass'] for c in checks),'failed':[c['check'] for c in checks if not c['pass']]})
