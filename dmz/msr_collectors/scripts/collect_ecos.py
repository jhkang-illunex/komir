# -*- coding: utf-8 -*-
"""ECOS(한국은행) 수집 드라이버(DMZ 측, 2026-08-06 물리분리로 신설) — jobs.json 기반 범용 CLI.

2026-08-05 이전엔 in-house 3곳이 각자 `ecos_api.fetch_series(...)`를 직접 호출한 뒤 즉시 DB에
썼다: `msr/pipeline.py`(collect_ecos, raw_ecos행), `scripts/collect_tier2_feeds.py`
(collect_ecos, fact_series 5계열), `scripts/collect_tier4_feeds.py`(collect_ecos_ship,
fact_series 2계열). 세 곳 모두 fetch_series 시그니처는 같고 (stat,cycle,start,end,item1,item2)
조합만 다르므로, 이 스크립트 + jobs.json(계열 목록) 조합으로 통합했다 — DB 저장 형태(표 스키마·
unit·src 문자열)는 소비자마다 달라 in-house 로더 쪽에 그대로 남겨뒀다(정확성 우선, 여기서는
원시 TIME/DATA_VALUE만 그대로 저장).

jobs.json 형식: [{"name": "<series_code 등 식별자>", "stat": "901Y033", "cycle": "M",
                   "start": "201001", "end": "202512", "item1": "A00", "item2": "1"}, ...]

기본 제공 jobs(2026-08-06 분리 시점 스냅샷 — 원본 코드에서 그대로 옮김):
  data/ecos_jobs_pipeline.json    ← msr/pipeline.py ECOS_SERIES(KR_industrial_production·
                                     KR_gdp_real, raw_ecos 소비자용)
  data/ecos_jobs_tier2.json       ← collect_tier2_feeds.py ECOS_ITEMS(전자부품·자동차·
                                     전기장비·1차금속 생산/재고, fact_series 소비자용)
  data/ecos_jobs_tier4_ship.json  ← collect_tier4_feeds.py collect_ecos_ship 출하지수 2종

실행 예(반드시 dmz/에서):
  cd komir/dmz
  ECOS_API_KEY=<키> python -m msr_collectors.scripts.collect_ecos \
      --jobs msr_collectors/data/ecos_jobs_pipeline.json --out-subdir pipeline

출력: $MSR_COLLECT_OUT/ecos/<out-subdir>/ecos__<name>__<UTC타임스탬프>.parquet
      (컬럼 그대로: TIME, DATA_VALUE 등 ECOS 원응답 — 가공은 in-house 로더가)
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os

from .._file_sink import save_parquet
from ..ecos_api import fetch_series
from ..config import COLLECT_OUT


def run(jobs_path: str, out_subdir: str) -> int:
    with open(jobs_path, encoding="utf-8") as f:
        jobs = json.load(f)
    out_dir = os.path.join(str(COLLECT_OUT), "ecos", out_subdir)
    print(f"[collect_ecos] jobs={jobs_path}({len(jobs)}건) → {out_dir}")
    n_ok = 0
    for j in jobs:
        name = j["name"]
        end = j["end"]
        if end == "today":   # 원본 코드의 dt.date.today() 동적 종료월 재현(tier2/tier4류)
            end = dt.date.today().strftime("%Y%m")
        try:
            s = fetch_series(j["stat"], j["cycle"], j["start"], end,
                              item1=j.get("item1", ""), item2=j.get("item2", ""),
                              item3=j.get("item3", ""))
        except Exception as e:
            print(f"  [warn] {name} 실패: {e}")
            continue
        if s.empty:
            print(f"  [warn] {name}: 빈 결과 — 건너뜀")
            continue
        path = save_parquet(s, out_dir, "ecos", name)
        n_ok += 1
        print(f"  [saved] {name}: {len(s)}행 → {path}")
    print(f"[collect_ecos] 완료: {n_ok}/{len(jobs)} 계열 저장")
    return n_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", required=True, help="jobs.json 경로")
    ap.add_argument("--out-subdir", required=True,
                     help="출력 하위폴더명(pipeline/tier2/tier4_ship 등 소비자 구분)")
    a = ap.parse_args()
    run(a.jobs, a.out_subdir)


if __name__ == "__main__":
    main()
