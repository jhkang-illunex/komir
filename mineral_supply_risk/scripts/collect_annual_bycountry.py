# -*- coding: utf-8 -*-
"""관세청 연간 '국가별' 재수집 → raw_customs_annual_bycountry (2026-07-15).

배경: 종전 수집이 country←statKor(품목명) 오매핑으로 국가 차원을 잃었음(합계는 정상).
국가 차원이 필요한 소비처: ① 지정학 지수 이중 노출 가중(글로벌 생산점유 × 한국 수입의존,
감사 B-1①) ② 수입국 HHI(진단 피처·경보 트리거 — 종전 값은 품목 구성 HHI였음, 결함).

연간(161 HS × 2013~2025 = 2,093콜)만으로 두 소비처 모두 충족(연 단위 비중이면 족함).
기존 raw_customs_annual은 보존(합계 소비처가 있음) — 별도 테이블에 적재.

실행: MSR_DB=<warehouse> python -m scripts.collect_annual_bycountry
"""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr import config                                    # noqa: E402 (.env 로딩)
from msr.collectors import customs_api                    # noqa: E402
from msr.preprocess import hs_mapping                     # noqa: E402
from msr.storage import db                                # noqa: E402

TABLE = "raw_customs_annual_bycountry"
STATE = os.path.join(os.path.dirname(config.DB_PATH), "bycountry_done.txt")


def _done() -> set:
    return set(l.strip() for l in open(STATE)) if os.path.exists(STATE) else set()


def run(strt="201301", end="202512"):
    hs_all = hs_mapping.core_hs_list()
    todo = [h for h in hs_all if h not in _done()]
    print(f"[bycountry] HS {len(hs_all)}개 중 잔여 {len(todo)}개 × 13년 (연간, 국가별)")
    if not todo:
        print("[bycountry] 완료 상태 — 할 일 없음"); return 0
    n = {"rows": 0}

    def _sink(df_hs):
        df_hs = hs_mapping.attach_commodity(df_hs)
        hs = str(df_hs["hs_query"].iloc[0])
        db.upsert_df(df_hs, TABLE, del_where=f"hs_query='{hs}'")
        n["rows"] += len(df_hs)
        with open(STATE, "a") as f:
            f.write(hs + "\n")

    try:
        customs_api.collect(todo, strt, end, freq="A", sink=_sink)
        print(f"[bycountry] 전체 완료: +{n['rows']}행 → {TABLE}")
    except customs_api.QuotaExceeded as e:
        print(f"[bycountry] 일 한도 — 안전 중단(+{n['rows']}행 보존): {e}")
    return n["rows"]


if __name__ == "__main__":
    run()
