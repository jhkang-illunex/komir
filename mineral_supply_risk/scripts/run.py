# -*- coding: utf-8 -*-
"""CLI: python -m scripts.run <stage>
stage: collect-customs | collect-ecos | normalize | features | all | ecos-search"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from msr import pipeline
from msr.collectors import ecos_api

def main():
    cmd = sys.argv[1] if len(sys.argv)>1 else "all"
    if cmd=="collect-customs": pipeline.collect_customs(*sys.argv[2:])
    elif cmd=="collect-ecos": pipeline.collect_ecos()
    elif cmd=="normalize": pipeline.normalize()
    elif cmd=="features": pipeline.build_features()
    elif cmd=="all": pipeline.run_all()
    elif cmd=="ecos-search":  # 코드 탐색 헬퍼: python -m scripts.run ecos-search 생산
        kw = sys.argv[2] if len(sys.argv)>2 else ""
        print(ecos_api.search_tables(kw).to_string())
    else: print("unknown:", cmd)

if __name__=="__main__": main()
