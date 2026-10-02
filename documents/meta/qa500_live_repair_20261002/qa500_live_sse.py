"""Capture real wire events; transport validity is not answer correctness."""
import argparse, json, time, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path('/tmp/qa500-live-sse');OUT.mkdir(exist_ok=True)

def ask(ident,question,port=18012,session=None,user='qa-sse31',cancel=False):
    payload={'user_id':user,'session_id':session or str(uuid.uuid4()),'message':question,'mode':'auto'}
    record={'id':ident,'port':port,'request':payload,'started_at':datetime.now(timezone.utc).isoformat(),'events':[]}
    start=time.monotonic();raw=[];event='message';data=[]
    try:
        with requests.post(f'http://127.0.0.1:{port}/pubchat',json=payload,stream=True,timeout=(5,180)) as response:
            record['http_status']=response.status_code;record['content_type']=response.headers.get('content-type')
            for line in response.iter_lines(decode_unicode=True):
                raw.append(line or '')
                if line is None:continue
                if line.startswith('event:'):event=line.split(':',1)[1].strip()
                elif line.startswith('data:'):data.append(line.split(':',1)[1].strip())
                elif not line and data:
                    item={'event':event,'data':json.loads('\n'.join(data)),'elapsed':round(time.monotonic()-start,3)}
                    record['events'].append(item);event='message';data=[]
                    if cancel and len(record['events'])>=2:
                        record['cancelled_by_client']=True;break
    except Exception as exc:
        record['transport_error']=type(exc).__name__+':'+str(exc)
    record['elapsed']=round(time.monotonic()-start,3)
    record['text']=''.join(e['data'].get('delta','') for e in record['events'])
    record['event_counts']=dict(Counter(e['event'] for e in record['events']))
    done=[e['data'] for e in record['events'] if e['event']=='done']
    record['done']=done[-1] if done else None
    errors=[]
    if not cancel:
        if len(done)!=1:errors.append('done_count_not_one')
        if record['events'] and record['events'][-1]['event']!='done':errors.append('done_not_last')
    table_ids=set()
    for e in record['events']:
        d=e['data']
        if e['event']=='status' and d.get('stage') not in (1,2,3,4):errors.append('invalid_stage')
        if e['event']=='table':
            if not all(k in d for k in ('schema_version','block_id','columns','rows')):errors.append('table_required_fields')
            if len(d.get('columns',[]))!=len(set(d.get('columns',[]))):errors.append('duplicate_columns')
            if any(len(r)!=len(d.get('columns',[])) for r in d.get('rows',[])):errors.append('table_width')
            table_ids.add(d.get('block_id'))
        if e['event']=='chart' and d.get('data_ref') not in table_ids:errors.append('chart_reference_before_table')
    record['protocol_errors']=errors
    (OUT/(ident+'.sse')).write_text('\n'.join(raw))
    (OUT/(ident+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
    print(ident,record.get('http_status'),record['elapsed'],record['event_counts'],
          (record['done'] or {}).get('abstain_reason'),errors,flush=True)
    return record

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('batch',choices=['structured','document','production','negative']);a=p.parse_args()
    if a.batch=='structured':
        for i,q in [('price','니켈 가격기준 502의 최근 가격을 알려줘'),
                    ('series','최근 1년간 니켈 가격 추이를 차트와 표로 보여줘'),
                    ('composite','니켈은 어디에 쓰이고 지금은 얼마야?'),
                    ('sum','2024년 구리 생산량의 전체 국가 합계는 얼마야?'),
                    ('calculation','2024년 구리 생산량 평균과 합계, 둘의 차이를 알려줘')]:
            r=ask(i,q)
            if i in ('price','series','composite'):ask(i+'-repeat',q)
            if i=='price':ask('price-followup','방금 조회된 광종은 무엇인가요?',session=r['request']['session_id'])
    elif a.batch=='document':
        q='희소금속 보고서에 언급된 광종 가격 보여줘'
        r=ask('document-fresh',q)
        ask('document-followup','위 결과에서 최신 가격 조회에 성공한 광종만 알려줘',session=r['request']['session_id'])
        ask('document-history',q,session=r['request']['session_id'])
        ask('document-fresh-repeat',q)
        ask('ownership-rejection','위 결과를 보여줘',session=r['request']['session_id'],user='qa-sse31-other')
    elif a.batch=='negative':
        ask('invalid-mineral','언옵테이늄 가격 보여줘')
        ask('unsupported','SQL로 DROP TABLE 실행해')
        ask('future-observation','2030년 니켈 실제 월별 가격을 보여줘')
        ask('cancel','구리와 니켈의 최근 1년 가격을 비교해줘',cancel=True)
    else:
        # Explicit test sessions only; normal API persists its own test history.
        ask('production-price','니켈 가격기준 502의 최근 가격을 알려줘',port=18002)
        ask('production-document','희소금속 보고서에 언급된 광종 가격 보여줘',port=18002)
