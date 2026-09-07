# -*- coding: utf-8 -*-
"""CLI: python -m scripts.run <stage>
stage: collect-customs | collect-ecos | normalize | features | all | ecos-search

2026-08-06 dmz/inhouse 물리분리: collect-customs·collect-ecos는 더 이상 라이브 수집이 아니라
DMZ(`dmz/msr_collectors/scripts/`)가 미리 만들어 둔 parquet 산출물의 "적재"다(자세한 실행
순서는 msr/pipeline.py의 각 함수 docstring 참고). ecos-search(ECOS 코드 탐색 개발용 헬퍼)는
라이브 API 호출이라 in-house에서 더 이상 실행할 수 없어 dmz 쪽으로 옮겼다 — 여기서는 안내만
출력한다."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from msr import pipeline

def main():
    cmd = sys.argv[1] if len(sys.argv)>1 else "all"
    if cmd=="collect-customs": pipeline.collect_customs(*sys.argv[2:])
    elif cmd=="collect-ecos": pipeline.collect_ecos()
    elif cmd=="normalize": pipeline.normalize()
    elif cmd=="features": pipeline.build_features()
    elif cmd=="all": pipeline.run_all()
    elif cmd=="ecos-search":  # 2026-08-06 dmz로 이전(라이브 API라 in-house 실행 불가)
        print("ecos-search는 dmz로 이전됨. 실행:\n"
              "  cd komir/dmz && ECOS_API_KEY=<키> "
              "python -m msr_collectors.scripts.ecos_search <키워드>")
    else: print("unknown:", cmd)

if __name__=="__main__": main()
