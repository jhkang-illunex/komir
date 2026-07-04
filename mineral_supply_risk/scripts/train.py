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
    print("[train] 진단 — 주간마트(fact_price/indicator→mart) 재생성 후 학습(데이터 부족 시 스킵)")
    from msr.features import weekly_mart
    from msr.models import diagnosis
    weekly_mart.run(DB_PATH)          # 정본 팩트 → mart_weekly_diagnosis
    res = diagnosis.run(DB_PATH)
    if res:
        print("  ", "; ".join(f"{r['model']}:R2={r['R2']}" for r in res["results"]))
        print(f"   위기분류 AUC={res.get('auc_crisis')}")


def train_forecast():
    print("[train] 월간 수입 예측 — raw_customs_monthly 기반 (홀드아웃 백테스트 + 12개월 재귀예측)")
    from msr.models import forecast
    res = forecast.run(DB_PATH)
    print(f"  기준월={res['base_date']} · 광종={res['commodities']}")
    for tgt, m in res["metrics"].items():
        print(f"  [{tgt}] {m}")
    print(f"  → mart_monthly_forecast_input={res['mart_rows']}행, out_import_forecast={res['forecast_rows']}행")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    print(f"[train] DB={DB_PATH} · target={what}")
    if what in ("diagnosis", "all"):
        train_diagnosis()
    if what in ("forecast", "all"):
        train_forecast()
    print("[train] 완료. forecast=out_import_forecast · diagnosis=fact_price/indicator 존재 시 자동 학습(없으면 스킵).")


if __name__ == "__main__":
    main()
