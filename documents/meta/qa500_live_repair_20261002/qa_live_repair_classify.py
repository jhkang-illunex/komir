import json
from collections import Counter
from pathlib import Path
base=Path('documents/meta/qa500_live_repair_20261002')
failures={
 'price-followup-r1':'static planning ENTITY selected; evidence validation failed',
 'chile-r1':'country restriction lost; entire population returned',
 'ranking-r1':'invalid resource reporter_country/projection planning',
 'document-followup-r1':'filter expression string; parser validation exhausted',
 'chile-r2':'English country alias did not match Korean source field',
 'document-followup-r2':'projected mineral rows retained Composite type; presentation unavailable',
 'composition-paraphrase-r3':'Gemma aggregate without upstream retrieval after three attempts',
 'composition-paraphrase-r4':'Gemma aggregate without upstream retrieval after three attempts',
 'reserves-r3':'retrieval validation_failed; aggregate_input_incomplete, not proven data absence',
 'reserves-r4':'retrieval validation_failed; aggregate_input_incomplete, not proven data absence',
 'requery-r4-restart':'Gemma projection requests unavailable period field after three attempts',
}
records=[]
for p in sorted((base/'sse').glob('*.json')):
 r=json.loads(p.read_text());ident=r['id'];detail=None
 if ident in failures:status='FAIL';detail=failures[ident]
 elif ident.startswith('cancel-'):status='CANCELLED'
 elif ident.startswith('ownership-'):status='ACCESS_DENIED_CORRECT'
 elif ident.startswith('negative-'):status='UNSUPPORTED_CORRECT'
 elif ident.startswith('calculation-'):status='ARITHMETIC_PASS_DIRECTION_AMBIGUOUS';detail='SQL operands and subtraction match; difference sign varies across rounds'
 elif ident in {'document-r1','document-r2','document-r3','document-r4'}:status='PARTIAL';detail='Item status preservation verified; not all mineral prices or units validated'
 else:status='PASS'
 records.append({'id':ident,'status':status,'detail':detail,'request':r['request'],'started_at':r['started_at'],'wire_errors':r['protocol_errors'],'evidence':'sse/'+p.name})
payload={'total':len(records),'counts':dict(Counter(r['status'] for r in records)),'records':records,'scope':'Targeted live regression; not all QA500. PASS followup denotes projection against stored output, not full-population price availability.'}
(base/'semantic-summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
print(payload['counts'])
