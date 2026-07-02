# -*- coding: utf-8 -*-
"""모델 학습 엔트리 (config 주도 3 템플릿 훅).
  python -m scripts.train [diagnosis|forecast|all]
피처 마트를 읽어 주간 진단(×5)·월간 예측(×10)을 학습/추론하고 결과를 DB(out_*)에 기록.
현재는 배선 스캐폴드 — 각 템플릿은 msr/models/ 에 구현하여 여기서 호출한다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from msr.config import DB_PATH

try:
    from db import dbio
except Exception:
    dbio = None


def _has(table):
    if dbio is None:
        return False
    try:
        dbio.read_sql(f"select 1 from {table} limit 1", DB_PATH); return True
    except Exception:
        return False


def train_diagnosis():
    print("[train] 주간 진단 ×5 — mart_weekly_diagnosis 필요:", _has("mart_weekly_diagnosis"))
    # TODO: from msr.models.diagnosis import run; run(DB_PATH) → out_diagnosis_alert
    print("  (훅) msr/models/diagnosis.py 구현 후 여기서 호출. 결과 → out_diagnosis_alert")


def train_forecast():
    print("[train] 월간 예측 ×10 — mart_monthly_forecast_input 필요:", _has("mart_monthly_forecast_input"))
    # TODO: from msr.models.forecast import run; run(DB_PATH) → out_import_forecast
    print("  (훅) msr/models/forecast.py 구현 후 여기서 호출. 결과 → out_import_forecast")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"[train] DB={DB_PATH} · target={what}")
    if what in ("diagnosis", "all"):
        train_diagnosis()
    if what in ("forecast", "all"):
        train_forecast()
    print("[train] 완료(스캐폴드). 템플릿 구현 시 out_* 테이블에 결과 적재.")


if __name__ == "__main__":
    main()
