# -*- coding: utf-8 -*-
"""DMZ(`dmz/msr_collectors/`)가 만든 parquet 산출물을 in-house에서 읽는 공용 헬퍼
(2026-08-06 물리분리 리팩터). `msr/pipeline.py`(collect_customs·collect_customs_incremental·
collect_ecos)와 `scripts/backfill_customs_monthly.py`·`scripts/collect_annual_bycountry.py`·
`scripts/collect_tier2_feeds.py`·`scripts/collect_tier4_feeds.py`가 공유한다.

⚠️ dmz/와 inhouse/는 물리적으로 분리된 트리(장차 별도 서버)라 Python 모듈을 직접 공유
import할 수 없다 — `dmz/msr_collectors/_file_sink.py`의 list_pending/mark_loaded와 로직만
대칭으로 재구현했다(코드는 중복이지만 계약은 "파일명 규칙"뿐이라 의도적 — collector/README의
"코드 의존 없음, 파일 형식만 공유" 원칙과 동일).

파일 전달: DMZ가 로컬에 쓴 $MSR_COLLECT_OUT를 공유 마운트/rsync로 in-house의
$MSR_COLLECT_OUT 경로에 그대로 복제해온다는 전제(운영 방식은 dmz/collector/README.md 패턴
참고) — 이 저장소 안에서는 같은 파일시스템이라 두 COLLECT_OUT 경로를 동일하게 두면 코드
변경 없이 그대로 동작한다.
"""
from __future__ import annotations
import os
import shutil

import pandas as pd


def list_pending(out_dir: str, prefix: str = "") -> list:
    """out_dir 바로 아래(하위 _loaded/ 제외)의 미처리 parquet 경로 목록(정렬됨)."""
    if not os.path.isdir(out_dir):
        return []
    names = sorted(n for n in os.listdir(out_dir)
                    if n.endswith(".parquet") and (not prefix or n.startswith(prefix)))
    return [os.path.join(out_dir, n) for n in names]


def read_df(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


def mark_loaded(path: str) -> None:
    """적재 완료 parquet을 같은 out_dir의 _loaded/ 하위로 이동(재적재 낭비 방지 — upsert
    자체는 멱등이라 정합성엔 무관, 순수 효율 목적)."""
    d = os.path.join(os.path.dirname(path), "_loaded")
    os.makedirs(d, exist_ok=True)
    shutil.move(path, os.path.join(d, os.path.basename(path)))
