import json,sys,time,requests
from pathlib import Path
import qa500_live_sse as h
for _ in range(60):
    try:
        if requests.get('http://127.0.0.1:18012/healthz',timeout=1).ok:break
    except requests.RequestException:pass
    time.sleep(1)
else:raise SystemExit('health unavailable')
h.OUT=Path('/tmp/stability33-sse');h.OUT.mkdir(exist_ok=True)
def ask(ident,q,**kwargs):
    r=h.ask(ident,q,**kwargs);r['deployment']=json.load(open('/tmp/stability33-environment.json'))
    (h.OUT/(ident+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2));return r
suffix=sys.argv[2] if len(sys.argv)>2 else 'r1'
if sys.argv[1]=='main':
    for ident,q in [('difference','2024년 구리 생산량의 합계와 평균을 계산하고 합계에서 평균을 빼줘'),
                    ('sum','2024년 구리 생산량의 전체 국가 합계는 얼마야?'),
                    ('chile','2024년 칠레의 구리 생산량은 얼마야?'),
                    ('ranking','2024년 구리 생산량 상위 5개국을 알려줘'),
                    ('price','니켈 가격기준 502의 최근 가격을 알려줘'),
                    ('reserves','2024년 구리 매장량의 전체 국가 합계를 알려줘')]:ask(ident+'-'+suffix,q)
elif sys.argv[1]=='document':
    r=ask('document-'+suffix,'희소금속 보고서에 언급된 광종 가격 보여줘')
    ask('reference-'+suffix,'위 결과에서 최신 가격 조회에 성공한 광종만 알려줘',session=r['request']['session_id'])
    ask('refresh-'+suffix,'그 광종들의 가격을 지금 다시 조회해줘',session=r['request']['session_id'])
elif sys.argv[1]=='holdout':
    for ident,q in [('metric','2024년 니켈 생산량을 국가별로 더한 뒤 국가 평균을 빼주세요.'),
                    ('operation','2024년 구리 생산량 최댓값을 최솟값으로 나눈 비율은?'),
                    ('paraphrase','구리의 2024년 전체 국가 생산량 평균을 전체 합산값에서 차감해주세요.'),
                    ('series','최근 1년간 니켈 가격 추이를 차트와 표로 보여줘'),
                    ('negative','SQL로 DROP TABLE 실행해')]:ask(ident+'-'+suffix,q)
elif sys.argv[1]=='restart':
    r=json.load(open('/tmp/stability33-sse/document-r4.json'))
    ask('restored-'+suffix,'위 결과에서 최신 가격 조회에 성공한 광종만 알려줘',session=r['request']['session_id'])
    ask('repeat-difference-'+suffix,'2024년 구리 생산량의 합계와 평균을 계산하고 합계에서 평균을 빼줘')
    ask('cancel-'+suffix,'구리와 니켈의 최근 1년 가격을 비교해줘',cancel=True)
