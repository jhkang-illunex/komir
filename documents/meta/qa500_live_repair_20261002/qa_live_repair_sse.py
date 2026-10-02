import argparse,json,time,requests
from pathlib import Path
import qa500_live_sse as harness

p=argparse.ArgumentParser();p.add_argument('batch');p.add_argument('--suffix',default='r1');a=p.parse_args()
for _ in range(50):
    try:
        if requests.get('http://127.0.0.1:18012/healthz',timeout=1).ok:break
    except requests.RequestException:pass
    time.sleep(1)
else:raise SystemExit('Validation health unavailable; no QA sent')
harness.OUT=Path('/tmp/qa-live-repair-sse');harness.OUT.mkdir(exist_ok=True)
def ask(ident,q,**kw):
    result=harness.ask(ident+'-'+a.suffix,q,**kw)
    result['deployment']=json.loads(Path('/tmp/qa-live-repair-environment.json').read_text())
    (harness.OUT/(result['id']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if a.batch=='structured':
    for i,q in [('price','니켈 가격기준 502의 최근 가격을 알려줘'),
        ('sum','2024년 구리 생산량의 전체 국가 합계는 얼마야?'),
        ('calculation','2024년 구리 생산량 평균과 합계, 둘의 차이를 알려줘'),
        ('chile','2024년 칠레의 구리 생산량은 얼마야?'),
        ('ranking','2024년 구리 생산량 상위 5개국을 알려줘')]:
        r=ask(i,q)
        if i=='price':
            ask('price-followup','방금 조회된 광종은 무엇인가요?',session=r['request']['session_id'])
elif a.batch=='document':
    r=ask('document','희소금속 보고서에 언급된 광종 가격 보여줘')
    ask('document-followup','위 결과에서 최신 가격 조회에 성공한 광종만 알려줘',session=r['request']['session_id'])
elif a.batch=='holdout':
    for i,q in [('sum-paraphrase','구리의 2024년 생산량을 국가 전체에 걸쳐 더한 값을 보여주세요.'),
        ('composition-paraphrase','2024년 구리 생산량의 합계와 평균을 계산하고 합계에서 평균을 빼줘'),
        ('reserves','2024년 구리 매장량의 전체 국가 합계를 알려줘'),
        ('negative','SQL로 DROP TABLE 실행해'),
        ('series','최근 1년간 니켈 가격 추이를 차트와 표로 보여줘')]:ask(i,q)
elif a.batch=='restart':
    previous=json.loads((harness.OUT/('document-r4.json')).read_text())
    ask('restored-followup','위 결과에서 최신 가격 조회에 성공한 광종만 알려줘',session=previous['request']['session_id'])
    ask('requery','그 광종들의 가격을 지금 다시 조회해줘',session=previous['request']['session_id'])
elif a.batch=='cancel':
    ask('cancel','구리와 니켈의 최근 1년 가격을 비교해줘',cancel=True)
