# -*- coding: utf-8 -*-
"""관세청 수집 드라이버(DMZ 측, 2026-08-06 물리분리로 신설) — 범용 CLI.

2026-08-05 이전엔 in-house `msr/pipeline.py`(collect_customs·collect_customs_incremental)와
`scripts/backfill_customs_monthly.py`·`scripts/collect_annual_bycountry.py` 4곳이 각자
`customs_api.collect(..., sink=<DB upsert>)`를 직접 호출했다. dmz/·inhouse/ 물리분리 후
DB는 DMZ에서 접근 불가하므로, 이 스크립트가 "수집"만 맡고 sink는 로컬 parquet 저장으로
바뀐다 — 4곳 모두 HS 목록 소스(core_hs_list)가 동일하고 차이는 (strt,end,freq,재개상태파일)
뿐이라 스크립트 하나 + CLI 인자로 충분(중복 스크립트 4개 대신).

DB upsert(del_where 포함)는 원래 각 in-house 스크립트의 _sink가 하던 것과 동일한 로직을
그대로 옮겨 담당하는 in-house 로더가 수행한다(정확한 대응은 각 in-house 스크립트 상단 주석
참고: msr/pipeline.py·scripts/backfill_customs_monthly.py·scripts/collect_annual_bycountry.py).

실행 예(반드시 dmz/에서, msr_collectors의 부모 디렉터리) — out-subdir 이름은 in-house
`msr/dmz_ingest.py` 기반 로더들이 그대로 기대하는 값이니 바꾸지 말 것:
  cd komir/dmz
  # msr/pipeline.py collect_customs(freq=A) 대체(연간, 전량 클린 재수집)
  python -m msr_collectors.scripts.collect_customs --strt 201301 --end 202512 --freq A \
      --out-subdir pipeline_full_A
  # msr/pipeline.py collect_customs(freq=M) 대체(월간, 전량 클린 재수집)
  python -m msr_collectors.scripts.collect_customs --strt 201301 --end 202512 --freq M \
      --out-subdir pipeline_full_M
  # msr/pipeline.py collect_customs_incremental 대체(월간, 최근 구간만 보존형)
  python -m msr_collectors.scripts.collect_customs --strt 202601 --end 202607 --freq M \
      --out-subdir pipeline_incremental_M
  # scripts/backfill_customs_monthly.py 대체(월간 백필, 재개 가능)
  python -m msr_collectors.scripts.collect_customs --strt 201301 --end 202212 --freq M \
      --out-subdir backfill_monthly --resume-state _state/backfill_monthly_done.txt
  # scripts/collect_annual_bycountry.py 대체(연간·국가별, 재개 가능)
  python -m msr_collectors.scripts.collect_customs --strt 201301 --end 202512 --freq A \
      --out-subdir annual_bycountry --resume-state _state/bycountry_done.txt

출력: $MSR_COLLECT_OUT/customs/<out-subdir>/customs__<HS>__<UTC타임스탬프>.parquet
      (HS 단위 1파일 — 원본의 "HS 단위 증분 sink"와 동일한 손실 최소화 단위)
"""
from __future__ import annotations
import argparse
import os

from .. import hs_list
from .._file_sink import save_parquet, load_done, mark_done
from ..customs_api import collect, QuotaExceeded
from ..config import COLLECT_OUT


def run(strt: str, end: str, freq: str, out_subdir: str, resume_state: str | None,
        sleep: float = 0.3) -> int:
    hs_all = hs_list.core_hs_list()
    out_dir = os.path.join(str(COLLECT_OUT), "customs", out_subdir)
    done = load_done(resume_state) if resume_state else set()
    todo = [h for h in hs_all if h not in done]
    print(f"[collect_customs] HS {len(hs_all)}개 중 대상 {len(todo)}개, {strt}~{end} "
          f"freq={freq} → {out_dir}"
          + (f" (재개상태={resume_state}, 완료 {len(done)}건 스킵)" if resume_state else ""))
    if not todo:
        print("[collect_customs] 할 일 없음(전부 완료 상태)")
        return 0

    n_rows = {"n": 0}

    def _sink(df_hs):
        hs = str(df_hs["hs_query"].iloc[0])
        path = save_parquet(df_hs, out_dir, "customs", hs)
        n_rows["n"] += len(df_hs)
        if resume_state:
            mark_done(resume_state, hs)
        print(f"  [saved] hs={hs} {len(df_hs)}행 → {path}")

    try:
        collect(todo, strt, end, freq=freq, sleep=sleep, sink=_sink)
        print(f"[collect_customs] 전체 완료: +{n_rows['n']}행 저장")
    except QuotaExceeded as e:
        print(f"[collect_customs] 일 한도 도달 — 안전 중단(그때까지 +{n_rows['n']}행 저장됨, "
              f"자정 리셋 후 재실행): {e}")
    return n_rows["n"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strt", required=True, help="YYYYMM")
    ap.add_argument("--end", required=True, help="YYYYMM")
    ap.add_argument("--freq", choices=["A", "M"], default="A")
    ap.add_argument("--out-subdir", required=True,
                     help="출력 하위폴더명(어느 in-house 소비자용인지 구분 — 예: "
                          "pipeline_annual/pipeline_incremental/backfill_monthly/"
                          "annual_bycountry)")
    ap.add_argument("--resume-state", default=None,
                     help="재개 상태파일 경로(지정 시 이미 완료된 HS 스킵 + 완료마다 append). "
                          "생략하면 매 실행 전체 HS 재수집(pipeline.collect_customs류 패턴).")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()
    run(a.strt, a.end, a.freq, a.out_subdir, a.resume_state, a.sleep)


if __name__ == "__main__":
    main()
