# -*- coding: utf-8 -*-
"""관세청 연간 '국가별' 재적재 → raw_customs_annual_bycountry (2026-07-15).

배경: 종전 수집이 country←statKor(품목명) 오매핑으로 국가 차원을 잃었음(합계는 정상).
국가 차원이 필요한 소비처: ① 지정학 지수 이중 노출 가중(글로벌 생산점유 × 한국 수입의존,
감사 B-1①) ② 수입국 HHI(진단 피처·경보 트리거 — 종전 값은 품목 구성 HHI였음, 결함).

연간(161 HS × 2013~2025 = 2,093콜)만으로 두 소비처 모두 충족(연 단위 비중이면 족함).
기존 raw_customs_annual은 보존(합계 소비처가 있음) — 별도 테이블에 적재.

2026-08-06 dmz/inhouse 물리분리: 실제 수집(HS단위 재개 상태파일 포함)은
`dmz/msr_collectors/scripts/collect_customs.py --resume-state`로 이전했다. 이 스크립트는
DMZ가 만든 parquet을 읽어 원래 _sink와 동일한 attach_commodity + del_where 적재만 재현한다.

실행 순서:
  1) cd komir/dmz && python -m msr_collectors.scripts.collect_customs \
       --strt 201301 --end 202512 --freq A --out-subdir annual_bycountry \
       --resume-state _state/bycountry_done.txt
  2) (parquet을 in-house $MSR_COLLECT_OUT으로 전달 후)
     MSR_DB=<warehouse> python -m scripts.collect_annual_bycountry
"""
from __future__ import annotations
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from msr import config, dmz_ingest                        # noqa: E402 (.env 로딩)
from msr.preprocess import hs_mapping                      # noqa: E402
from msr.storage import db                                # noqa: E402

TABLE = "raw_customs_annual_bycountry"
OUT_DIR = os.path.join(config.MSR_COLLECT_OUT, "customs", "annual_bycountry")


def run():
    files = dmz_ingest.list_pending(OUT_DIR, prefix="customs__")
    print(f"[bycountry-load] DMZ 산출물 {len(files)}개(HS단위) ← {OUT_DIR}")
    if not files:
        print("[bycountry-load] 산출물 없음 — 먼저 dmz 쪽 collect_customs를 실행할 것")
        return 0
    n = 0
    for path in files:
        df_hs = dmz_ingest.read_df(path)
        df_hs = hs_mapping.attach_commodity(df_hs)
        hs = str(df_hs["hs_query"].iloc[0])
        db.upsert_df(df_hs, TABLE, del_where=f"hs_query='{hs}'")
        n += len(df_hs)
        dmz_ingest.mark_loaded(path)
    print(f"[bycountry-load] 완료: +{n}행 → {TABLE}")
    return n


if __name__ == "__main__":
    run()
