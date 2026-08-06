# -*- coding: utf-8 -*-
"""관세청 월간 2013~2022 백필 — 기존(2023~25) 보존형 증분 적재.

collect_customs(pipeline)는 첫 배치에서 테이블 전삭제(clean recollect 설계)라 백필에 쓰면
기존 61,291행이 유실됨 — 이 래퍼는 HS 단위로 '해당 HS의 백필 구간만' 삭제 후 삽입(멱등)한다.

2026-08-06 dmz/inhouse 물리분리: 실제 수집(QuotaExceeded 대응·HS단위 재개 상태파일)은
`dmz/msr_collectors/scripts/collect_customs.py --resume-state`로 이전했다(그 상태파일이
"어느 HS까지 수집 완료"를 추적 — 이 파일과 동일한 이름·의미의 상태파일이지만 지금은 DMZ
쪽에 있다). 이 스크립트는 DMZ가 만든 parquet을 읽어 원래 _sink가 하던 attach_commodity +
구간한정 del_where 적재만 재현한다(적재 완료 파일은 _loaded/로 이동해 재적재 방지).

실행 순서:
  1) cd komir/dmz && python -m msr_collectors.scripts.collect_customs \
       --strt 201301 --end 202212 --freq M --out-subdir backfill_monthly \
       --resume-state _state/backfill_monthly_done.txt
  2) (parquet을 in-house $MSR_COLLECT_OUT으로 전달 후)
     MSR_DB=<warehouse> python -m scripts.backfill_customs_monthly [--to 202212]
"""
from __future__ import annotations
import argparse, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr import config, dmz_ingest                        # noqa: E402 (.env 로딩)
from msr.preprocess import hs_mapping                      # noqa: E402
from msr.storage import db                                # noqa: E402

OUT_DIR = os.path.join(config.MSR_COLLECT_OUT, "customs", "backfill_monthly")


def run(end="202212"):
    yr_hi = end[:4]
    files = dmz_ingest.list_pending(OUT_DIR, prefix="customs__")
    print(f"[backfill-load] DMZ 산출물 {len(files)}개(HS단위) ← {OUT_DIR}, 구간 상한 {yr_hi}")
    if not files:
        print("[backfill-load] 산출물 없음 — 먼저 dmz 쪽 collect_customs를 실행할 것")
        return 0

    n_rows = 0
    for path in files:
        df_hs = dmz_ingest.read_df(path)
        df_hs = hs_mapping.attach_commodity(df_hs)
        hs = str(df_hs["hs_query"].iloc[0])
        # 멱등: 이 HS의 백필 구간만 삭제 후 삽입(기존 2023~25는 건드리지 않음)
        db.upsert_df(df_hs, "raw_customs_monthly",
                     del_where=f"hs_query='{hs}' AND q_year<='{yr_hi}'")
        n_rows += len(df_hs)
        dmz_ingest.mark_loaded(path)
    print(f"[backfill-load] 완료: +{n_rows}행")
    return n_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", dest="end", default="202212",
                     help="적재 구간 상한(del_where의 q_year<= 기준). --from은 2026-08-06"
                          "부로 제거됨 — 실제 수집 구간은 이제 dmz 쪽 collect_customs.py의 "
                          "--strt/--end가 결정하고, 여기선 로더가 이미 만들어진 parquet을 "
                          "전부 읽으므로 하한을 걸 이유가 없음(원본 del_where도 상한만 있었음)")
    a = ap.parse_args()
    run(a.end)
