# -*- coding: utf-8 -*-
"""parquet 저장소 R/W (manifest·events·index·extract_log). 해시키 idempotent upsert."""
import os
import pandas as pd
from . import config as C


def _read(path):
    return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()


def _write(df: pd.DataFrame, path):
    """원자적 쓰기: 임시파일 → os.replace. 중간 크래시로 스토어가 깨지는 것 방지."""
    tmp = str(path) + ".tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def load_manifest() -> pd.DataFrame:
    return _read(C.MANIFEST)


def known_hashes() -> set:
    df = load_manifest()
    return set(df["file_hash"]) if len(df) else set()


def upsert_manifest(records: list[dict]):
    if not records:
        return
    C.STORE.mkdir(parents=True, exist_ok=True)
    cur = load_manifest()
    new = pd.DataFrame(records)
    df = pd.concat([cur, new], ignore_index=True) if len(cur) else new
    df = df.drop_duplicates("file_hash", keep="last").reset_index(drop=True)
    _write(df, C.MANIFEST)


def load_events() -> pd.DataFrame:
    return _read(C.EVENTS)


def extracted_doc_ids() -> set:
    """추출을 '시도 완료'한 문서 집합 = 추출로그 ∪ 이벤트 보유 문서(하위호환).
    이벤트 0건 문서도 로그에 남아 매 실행 재추출(LLM 비용 반복)되지 않는다."""
    done = set()
    log = _read(C.EXTRACT_LOG)
    if len(log):
        done |= set(log["doc_id"])
    ev = load_events()
    if len(ev):
        done |= set(ev["doc_id"])
    return done


def log_extracted(doc_ids_with_counts: list[tuple]):
    """추출 시도 성공 기록: [(doc_id, n_events)]. 실패(예외) 문서는 기록하지 않아 재시도됨."""
    if not doc_ids_with_counts:
        return
    C.STORE.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = _read(C.EXTRACT_LOG)
    new = pd.DataFrame(doc_ids_with_counts, columns=["doc_id", "n_events"])
    new["extracted_at"] = now
    df = pd.concat([cur, new], ignore_index=True) if len(cur) else new
    df = df.drop_duplicates("doc_id", keep="last").reset_index(drop=True)
    _write(df, C.EXTRACT_LOG)


def append_events(records: list[dict]):
    if not records:
        return
    C.STORE.mkdir(parents=True, exist_ok=True)
    cur = load_events()
    new = pd.DataFrame(records)
    df = pd.concat([cur, new], ignore_index=True) if len(cur) else new
    if "event_id" in df:
        df = df.drop_duplicates("event_id", keep="last").reset_index(drop=True)
    _write(df, C.EVENTS)


def write_index(df: pd.DataFrame):
    C.STORE.mkdir(parents=True, exist_ok=True)
    _write(df, C.INDEX)
