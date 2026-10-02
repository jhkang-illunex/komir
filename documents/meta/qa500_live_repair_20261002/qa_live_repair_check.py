import json,math,subprocess
from pathlib import Path
base=Path('/tmp/qa-live-repair-sse')
sql=json.load(open('/tmp/qa-live-repair-sql-final.json'))
queries={q['name']:q['rows'] for q in sql['queries']}
def request(name):return json.loads((base/(name+'.json')).read_text())
def turns(name):
    session=request(name)['request']['session_id']
    return [t for t in sql['isolated_history'] if t['session_id']==session]
def root(t):return t['result_json']['results'][t['program_json']['roots'][0]]
checks=[]
def check(name,ok,detail):
    checks.append({'check':name,'pass':bool(ok),'detail':detail})
total=float(queries['production_country_aggregate'][0]['total_ton'])
mean=float(queries['production_country_aggregate'][0]['mean_ton'])
sumrow=root(turns('sum-r4')[0])['value'][0]
check('sum_sql', math.isclose(next(iter(sumrow.values())),total), {'actual':sumrow,'sql':total})
chile=next(r for r in queries['production_population'] if r['ntn_eng_cd']=='CL')
actual=root(turns('chile-r4')[0])['value']
check('chile_sql',len(actual)==1 and math.isclose(float(actual[0]['production_volume']),float(chile['prdctn_quty_ton'])),{'actual':actual,'sql':chile})
calc=root(turns('calculation-r4')[0])['value'][0]
check('calculation_structured_operands',math.isclose(calc['left_value'],mean) and math.isclose(calc['right_value'],total) and math.isclose(calc['difference'],mean-total),{'actual':calc,'note':'average-minus-sum; natural-language difference order remains ambiguous across rounds'})
latest=queries['price502'][0]
price=root(turns('price-r4')[0])['value'][0]
check('price502_sql',float(price['cmerc_prc(통상가격)'])==float(latest['cmerc_prc']),{'actual':price,'sql':latest})
docs=turns('document-r4')
items=root(docs[0])['value']
success={x['mineral'] for x in items if x['status']=='success'}
check('latest_snapshot_one_row',all(len(x['value'])==1 for x in items if x['status']=='success'),{'success':sorted(success),'failed':len(items)-len(success)})
for t in docs[1:]:
    projected={r['mineral'] for r in root(t)['value']}
    operators=[n['operator'] for n in t['program_json']['nodes']]
    check('saved_projection_'+t['turn_id'],projected==success and not set(operators)&{'retrieve','retrieve_document','for_each'}, {'values':sorted(projected),'operators':operators,'inputs':[n.get('inputs',[]) for n in t['program_json']['nodes']],'result_id_column':t['result_id']})
owner=request('ownership-r4')
check('ownership_rejection',any(e['event']=='error' for e in owner['events']) and not owner['text'],{'events':owner['events']})
Path('/tmp/qa-live-repair-assertions.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
print(json.dumps({'checks':len(checks),'passed':sum(c['pass'] for c in checks)},ensure_ascii=False))
