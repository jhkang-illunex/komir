"""실 KOMIS 덤프와 기존 수동 입력의 출력 지문을 저장·비교한다.

저장소 루트에서 실행:
  PYTHONHASHSEED=0 python3 inhouse/report_gen/scripts/capture_output_contract.py /tmp/before.json
  PYTHONHASHSEED=0 python3 inhouse/report_gen/scripts/capture_output_contract.py /tmp/after.json /tmp/before.json

DB/LLM/운영 서버에 접속하지 않는다. Markdown, 내부 응답, OpenAPI, 기본 프롬프트를
비교한다. 철광석·에너지/기타는 희소금속 덤프를 동일 스키마에 재생해 경로를 검사한다.
이는 해당 광종의 실제 데이터 검증을 대신하지 않는다. 기존 광물지도 동률 선택이
set 순서에 의존하므로 PYTHONHASHSEED=0을 두 실행에 동일하게 지정해야 한다.
REPORT_GEN_APP_ROOT로 이전 소스트리의 report_gen 디렉터리를 지정할 수 있다.
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, os.environ.get('REPORT_GEN_APP_ROOT', str(Path.cwd() / 'inhouse/report_gen')))
from app.analysis.summary import AnalysisSummaryService
from app.analysis.models import AnalysisSummaryRequest
from app.analysis.report_render import render_markdown_report
from app.analysis.prompts import summary_instructions, resolve_page_config
from app.main import app
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
parser.add_argument("baseline", type=Path, nargs="?")
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
logging.disable(logging.CRITICAL)
assert os.environ.get('PYTHONHASHSEED') == '0', 'Set PYTHONHASHSEED=0 for reproducible comparisons'
results = {}
counts = Counter()
paths = {'price_base_metals': 'prices/base-metals', 'price_minor_metals': 'prices/minor-metals', 'price_iron_energy': 'prices/iron-energy', 'price_other': 'prices/other', 'indicator_market': 'indicators/market', 'indicator_supply': 'indicators/supply', 'indicator_composite': 'indicators/composite-index', 'map_mineral': 'maps/mineral', 'map_korea': 'maps/domestic-trade', 'map_global': 'maps/global-trade'}
service = AnalysisSummaryService(None, llm=None)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

def run(key, req):
    try:
        response = service.analyze(AnalysisSummaryRequest(request_id='regression', **req))
        body = response.model_dump(mode='json')
        body.pop('generated_at', None)
        value = {'response': body, 'report': render_markdown_report(response)}
        counts[req['page_id'] + ':ok'] += 1
    except Exception as e:
        value = {'error': type(e).__name__, 'message': str(e)}
        counts[req['page_id'] + ':' + type(e).__name__] += 1
    results[key] = digest(value)
for file in sorted(Path('income_data/komis').glob('komis_*.json')):
    for (i, row) in enumerate(json.loads(file.read_text())['results']):
        endpoint = row['endpoint'].split('/')[-1]
        p = row['params']
        raw = row['response']
        base = {'komis_response': raw, 'mineral': p.get('srchMnrkndUnqCd')}
        pages = []
        if endpoint == 'getMnrlPrcByMnrkndUnqCd':
            pages = ['price_base_metals'] if '01_' in file.name else ['price_minor_metals', 'price_iron_energy', 'price_other']
            base.update(srch_avg_opt=p.get('srchAvgOpt'), srch_field=p.get('srchField'), srch_start_date=p.get('srchStartDate'), srch_end_date=p.get('srchEndDate'))
            if p.get('srchCompareMnrkndUnqCd'):
                base['compare_mineral'] = p['srchCompareMnrkndUnqCd']
        elif endpoint in ('getListIndcMnrk', 'getListIndxSplyBalncMnrk'):
            pages = ['indicator_market' if endpoint == 'getListIndcMnrk' else 'indicator_supply']
        elif endpoint == 'getLineChartIndx':
            pages = ['indicator_composite']
            base.pop('mineral')
        elif endpoint == 'getListKoreaData':
            pages = ['map_korea']
        elif endpoint == 'getListDataNation':
            pages = ['map_global']
        elif endpoint == 'getListMapMnrlChartData':
            pages = ['map_mineral']
            base['measure'] = 'reserves' if p.get('selectedTab') == 'burudg' else 'production'
        for page in pages:
            run(f'{file.name}:{i}:{page}', dict(base, page_id=page))
sys.path.insert(0, str(Path.cwd() / 'inhouse/report_gen/scripts'))
import komis_dump_smoke_test as smoke
legacy = smoke.run_all(args.output.with_suffix('.legacy.json'), False)
for (page, rows) in legacy['per_page'].items():
    for (i, row) in enumerate(rows):
        run(f'legacy:{page}:{i}', row['request'])
results['openapi'] = digest(app.openapi())
for page in paths:
    results['prompt:' + page] = digest([summary_instructions(page), resolve_page_config(page)])
    run('empty:' + page, {'page_id': page, 'mineral': 'MNRL0024', 'measure': 'reserves'} if page == 'map_mineral' else {'page_id': page, 'mineral': 'MNRL0024'})
path = args.output
path.write_text(json.dumps({'results': results, 'counts': dict(counts)}, indent=2))
print(json.dumps({'cases': len(results), 'counts': dict(counts)}, ensure_ascii=False))
if args.baseline is not None:
    before = json.loads(args.baseline.read_text())['results']
    changed = [k for k in before.keys() | results.keys() if before.get(k) != results.get(k)]
    print('Changed:', len(changed), changed[:30])
    sys.exit(bool(changed))
