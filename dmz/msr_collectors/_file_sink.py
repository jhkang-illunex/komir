# -*- coding: utf-8 -*-
"""공용 헬퍼: fetch 드라이버들이 공유하는 "DataFrame → 로컬 parquet 저장" +
"재개 가능(resumable) 상태파일" 로직. DB upsert 콜백(_sink) 대신 파일 계약으로 넘기는
전환의 핵심 — 여러 스크립트(customs 4종·ecos 3종)가 이 모듈 하나로 중복 없이 재사용한다.

파일명 규칙: <prefix>__<key>__<UTC타임스탬프>.parquet
  - prefix: 이 배치가 속한 수집 종류(예: customs_monthly, ecos_pipeline)
  - key: 배치를 식별하는 값(HS코드·series명 등) — 같은 key라도 재실행 시 새 파일이
    쌓이므로(타임스탬프로 유일) in-house 로더가 여러 스냅샷을 모두 소비해도 안전(멱등
    upsert이므로 중복 로드해도 최종 상태는 같음).
"""
from __future__ import annotations
import datetime as dt
import os
import shutil

import pandas as pd


def save_parquet(df: pd.DataFrame, out_dir, prefix: str, key: str) -> str:
    """df를 out_dir/<prefix>__<key>__<ts>.parquet 로 저장하고 경로를 반환."""
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    safe_key = str(key).replace("/", "_").replace(" ", "_").replace("\\", "_")
    path = os.path.join(out_dir, f"{prefix}__{safe_key}__{ts}.parquet")
    df.to_parquet(path, index=False)
    return path


# ---------- 재개 가능(resumable) 상태파일: "이미 수집 완료된 key" 추적 ----------
# backfill_customs_monthly.py·collect_annual_bycountry.py 원본의 done.txt 패턴과 동일
# (한 줄에 완료 key 하나, append-only) — QuotaExceeded로 중단해도 다음 실행에서 이어감.

def load_done(state_path) -> set:
    if state_path and os.path.exists(state_path):
        return set(l.strip() for l in open(state_path) if l.strip())
    return set()


def mark_done(state_path, key: str) -> None:
    if not state_path:
        return
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with open(state_path, "a") as f:
        f.write(str(key) + "\n")


# ---------- in-house 로더 측: 처리 완료 파일을 _loaded/로 이동(재로드 방지) ----------
# upsert 자체는 멱등이라 재로드해도 최종 상태는 동일하지만, 매 실행마다 이미 적재한
# parquet까지 다시 읽어 upsert하는 낭비를 피하기 위한 부기(효율 목적, 정합성과 무관).

def list_pending(out_dir, prefix: str = "") -> list:
    """out_dir 바로 아래(하위 _loaded/ 제외)의 미처리 parquet 경로 목록(정렬됨)."""
    out_dir = str(out_dir)
    if not os.path.isdir(out_dir):
        return []
    names = sorted(n for n in os.listdir(out_dir)
                    if n.endswith(".parquet") and (not prefix or n.startswith(prefix)))
    return [os.path.join(out_dir, n) for n in names]


def mark_loaded(path: str) -> None:
    """처리 완료 parquet을 같은 out_dir의 _loaded/ 하위로 이동."""
    d = os.path.join(os.path.dirname(path), "_loaded")
    os.makedirs(d, exist_ok=True)
    shutil.move(path, os.path.join(d, os.path.basename(path)))
