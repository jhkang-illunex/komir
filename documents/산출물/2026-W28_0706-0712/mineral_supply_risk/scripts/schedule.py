# -*- coding: utf-8 -*-
"""간단 스케줄러(운영: cron/Airflow 권장).
 - 주간(진단): 가격·지정학 갱신 → 진단·경보
 - 월간(예측): 관세청·ECOS 갱신 → 피처 → 예측
예) cron:
   0 6 * * 1   python -m scripts.schedule weekly   # 매주 월 06:00
   0 7 1 * *   python -m scripts.schedule monthly   # 매월 1일 07:00
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from msr import pipeline

def weekly():
    print("[schedule] weekly: (가격·지정학 갱신 → 진단·경보)")
    pipeline.build_features()  # + 진단/경보 모듈 연결 지점

def monthly():
    print("[schedule] monthly: 관세청·ECOS 수집 → 피처 → 예측")
    pipeline.collect_customs(); pipeline.collect_ecos(); pipeline.build_features()

if __name__=="__main__":
    {"weekly":weekly, "monthly":monthly}.get(sys.argv[1] if len(sys.argv)>1 else "monthly", monthly)()
