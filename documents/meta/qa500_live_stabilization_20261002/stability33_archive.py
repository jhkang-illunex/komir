"""Archive executed validation, including failed repetitions; no credentials."""
import gzip,json,re,subprocess
from pathlib import Path
from collections import Counter
out=Path('documents/meta/qa500_live_stabilization_20261002')
out.mkdir(parents=True,exist_ok=True)
def redact(s):
    s=re.sub(r'(?i)(postgres(?:ql)?(?:\+psycopg2)?://)[^\s"\']+',r'\1[REDACTED]',s)
    return re.sub(r'(?i)(Bearer\s+)\S+',r'\1[REDACTED]',s)
def save(p,destination):
    data=redact(p.read_text(errors='replace')).encode()
    target=destination/(p.name+('.gz' if len(data)>30000 else ''))
    target.write_bytes(gzip.compress(data,mtime=0) if len(data)>30000 else data)
for p in Path('/tmp').glob('stability33*'):
    if p.is_file() and p.suffix in {'.json','.log','.py'}:save(p,out)
for name in ['qa500_live_sse.py','qa500_sql_evidence.py','qa_live_repair.Containerfile']:
    save(Path('/tmp')/name,out)
sse=out/'sse';sse.mkdir(exist_ok=True)
records=[]
for p in Path('/tmp/stability33-sse').glob('*'):
    if p.is_file():save(p,sse)
    if p.suffix=='.json':
        r=json.loads(p.read_text());name=r['id'];reason=(r.get('done') or {}).get('abstain_reason')
        status='RESPONSE_COMPLETED'
        if r.get('cancelled_by_client') or name.startswith('cancel-'):status='CANCELLED'
        elif name.startswith('negative-'):status='UNSUPPORTED_CORRECT'
        elif name.startswith(('reserves-','metric-')):status='DATA_CONTRACT_BLOCKED'
        elif name.startswith('operation-'):status='EXPECTED_ABSTAIN_ZERO_DENOMINATOR'
        elif (r.get('done') or {}).get('abstained'):status='FAIL'
        elif name=='refresh-r8':status='SEMANTIC_MISMATCH_TARGET_SCOPE'
        elif name.startswith('document-') or '처리 불가' in r.get('text',''):status='PARTIAL'
        records.append({'id':name,'status':status,'reason':reason,'started_at':r['started_at'],'image':r.get('deployment',{}).get('image_id'),'wire_errors':r.get('protocol_errors',[])})
summary={'requests':len(records),'classification':dict(Counter(r['status'] for r in records)),'wire_error_requests':sum(bool(r['wire_errors']) for r in records),'records':records,'note':'Observed response accounting, not semantic PASS. Final SQL and typed-root checks stored in stability33-final-checks.json. Historical failed runs retained.'}
(out/'request-assessment.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
for suffix in ['-r1','-r2','-r3','-r4','-r5','-r6','-r7','-r8','-r9','']:
    name='komir-rag-chat-qa-sse33'+suffix
    p=subprocess.run(['docker','logs',name],capture_output=True,text=True)
    if p.returncode==0:(out/(name+'.log.gz')).write_bytes(gzip.compress(redact(p.stdout+p.stderr).encode(),mtime=0))
print(json.dumps({k:v for k,v in summary.items() if k!='records'},ensure_ascii=False))
