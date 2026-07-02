# -*- coding: utf-8 -*-
"""parquet 저장소 R/W (manifest·events·index). 해시키 idempotent upsert."""
import os
import pandas as pd
from . import config as C


def _read(path):
    return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()


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
    df.to_parquet(C.MANIFEST, index=False)


def load_events() -> pd.DataFrame:
    return _read(C.EVENTS)


def extracted_doc_ids() -> set:
    df = load_events()
    return set(df["doc_id"]) if len(df) else set()


def append_events(records: list[dict]):
    if not records:
        return
    C.STORE.mkdir(parents=True, exist_ok=True)
    cur = load_events()
    new = pd.DataFrame(records)
    df = pd.concat([cur, new], ignore_index=True) if len(cur) else new
    if "event_id" in df:
        df = df.drop_duplicates("event_id", keep="last").reset_index(drop=True)
    df.to_parquet(C.EVENTS, index=False)


def write_index(df: pd.DataFrame):
    C.STORE.mkdir(parents=True, exist_ok=True)
    df.to_parquet(C.INDEX, index=False)
