# -*- coding: utf-8 -*-
"""관세청 월간 2013~2022 백필 — 기존(2023~25) 보존형 증분 수집.

pipeline.collect_customs는 첫 배치에서 테이블 전삭제(clean recollect 설계)라 백필에 쓰면
기존 61,291행이 유실됨 — 이 래퍼는 HS 단위로 '해당 HS의 백필 구간만' 삭제 후 삽입(멱등)한다.

일 한도(≈1만 콜) 대응: QuotaExceeded 시 안전 종료(그때까지 HS 단위 적재분 보존),
완료 HS를 상태파일에 기록 → 다음 실행(자정 리셋 후)에서 이어서. 필요 콜 ≈ 161 HS × 120개월
중 잔여분. 전체 약 15,500콜 → 2일 내 완료 예상.

실행: MSR_DB=<warehouse> python -m scripts.backfill_customs_monthly [--from 201301 --to 202212]
"""
from __future__ import annotations
import argparse, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr import config                                    # noqa: E402 (.env 로딩)
from msr.collectors import customs_api                    # noqa: E402
from msr.preprocess import hs_mapping                     # noqa: E402
from msr.storage import db                                # noqa: E402

STATE = os.path.join(os.path.dirname(config.DB_PATH), "backfill_monthly_done.txt")


def _load_done() -> set:
    if os.path.exists(STATE):
        return set(l.strip() for l in open(STATE) if l.strip())
    return set()


def run(strt="201301", end="202212"):
    hs_all = hs_mapping.core_hs_list()
    done = _load_done()
    todo = [h for h in hs_all if h not in done]
    print(f"[backfill] HS {len(hs_all)}개 중 잔여 {len(todo)}개, 구간 {strt}~{end} (월간)")
    if not todo:
        print("[backfill] 완료 상태 — 할 일 없음")
        return 0

    n_rows = 0
    yr_hi = end[:4]

    def _sink(df_hs):
        nonlocal n_rows
        df_hs = hs_mapping.attach_commodity(df_hs)
        hs = str(df_hs["hs_query"].iloc[0])
        # 멱등: 이 HS의 백필 구간만 삭제 후 삽입(기존 2023~25는 건드리지 않음)
        db.upsert_df(df_hs, "raw_customs_monthly",
                     del_where=f"hs_query='{hs}' AND q_year<='{yr_hi}'")
        n_rows += len(df_hs)
        with open(STATE, "a") as f:
            f.write(hs + "\n")

    try:
        customs_api.collect(todo, strt, end, freq="M", sink=_sink)
        print(f"[backfill] 전체 완료: +{n_rows}행")
    except customs_api.QuotaExceeded as e:
        print(f"[backfill] 일 한도 도달 — 안전 중단(+{n_rows}행 보존, 자정 리셋 후 재실행): {e}")
    return n_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="strt", default="201301")
    ap.add_argument("--to", dest="end", default="202212")
    a = ap.parse_args()
    run(a.strt, a.end)
