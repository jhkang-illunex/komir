import json,math,subprocess
from pathlib import Path
base=Path('/tmp/stability33-sse')
sql=json.load(open('/tmp/stability33-sql-final.json'))
queries={q['name']:q['rows'] for q in sql['queries']}
def req(name):return json.loads((base/(name+'.json')).read_text())
def turns(name):return [t for t in sql['isolated_history'] if t['session_id']==req(name)['request']['session_id']]
def root(t):return t['result_json']['results'][t['program_json']['roots'][0]]
checks=[]
def check(name,ok,detail):checks.append({'check':name,'pass':bool(ok),'detail':detail})
total=float(queries['production_country_aggregate'][0]['total_ton']);avg=float(queries['production_country_aggregate'][0]['mean_ton'])
for suffix in ['r8']:
    if not (base/('difference-'+suffix+'.json')).exists():continue
    data=root(turns('difference-'+suffix)[0])['value'][0]
    check('explicit_difference_'+suffix,math.isclose(data['left_value'],total) and math.isclose(data['right_value'],avg) and math.isclose(data['difference'],total-avg),{'actual':data,'sql_sum':total,'sql_avg':avg})
    sumrow=root(turns('sum-'+suffix)[0])['value'][0]
    check('sum_'+suffix,math.isclose(next(iter(sumrow.values())),total),sumrow)
    actual=root(turns('chile-'+suffix)[0])['value'][0]
    expected=next(r for r in queries['production_population'] if r['ntn_eng_cd']=='CL')['prdctn_quty_ton']
    check('chile_'+suffix,math.isclose(float(actual['production_volume']),float(expected)),{'actual':actual,'sql':expected})
    expected=queries['price502'][0]['cmerc_prc'];actual=root(turns('price-'+suffix)[0])['value'][0]
    actual_price=actual.get('price',actual.get('cmerc_prc(통상가격)'))
    check('price_'+suffix,float(actual_price)==float(expected),{'actual':actual,'sql':expected})
doc_case='document-r8'
doc_turns=turns(doc_case)
initial=next(r for r in doc_turns[0]['result_json']['results'].values() if isinstance(r.get('value'),list) and r['value'] and all(isinstance(x,dict) and 'mineral' in x and 'status' in x and 'value' in x for x in r['value']))
success={r['mineral']:r for r in initial['value'] if r['status']=='success'}
check('price_units',all(r['unit'] for r in success.values()),{k:r['unit'] for k,r in success.items()})
for t in doc_turns[1:]:
    ops=[n['operator'] for n in t['program_json']['nodes']]
    value=root(t)['value']
    if 'retrieve' not in ops and 'for_each' not in ops:
        check('projection_'+t['turn_id'],{r['mineral'] for r in value}==set(success),{'minerals':[r['mineral'] for r in value],'operators':ops})
    else:
        expected={k:float(next(iter(r['value']))['cmerc_prc(통상가격)']) for k,r in success.items()}
        actual={r['mineral']:float(r.get('price',r.get('cmerc_prc(통상가격)'))) for r in value if r.get('price',r.get('cmerc_prc(통상가격)')) is not None} if isinstance(value,list) else {}
        check('refresh_'+t['turn_id'],actual==expected,{'actual':actual,'expected_from_prior_observations':expected,'operators':ops})
for name in ['refresh-r8','refresh-r8b']:
    if (base/(name+'.json')).exists():
        response=req(name)
        check(name+'_completion', not response['done'].get('abstained') and response['event_counts'].get('table',0)>0, response['done'])
Path('/tmp/stability33-assertions.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print({'checks':len(checks),'passed':sum(x['pass'] for x in checks)})
