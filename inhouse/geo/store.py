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


def load_events(source: str | None = None) -> pd.DataFrame:
    """이벤트 로드. source: 'file'(정본 parquet) | 'db'(publish된 geo_event 테이블) |
    None → env GEO_EVENT_SOURCE(기본 'file').

    'db'는 추정기(indexer·prob) 실행 시에만 쓰는 모드 — "전처리기가 DB에 넣고 추정기는
    DB에서 읽는" 배선(2026-07-12). 쓰기 함수들(append/remove/compact)은 파일 정본 전용이므로
    전처리(extract)·검증(gkg-verify) 단계에서는 이 env를 켜면 안 된다."""
    src = (source or os.environ.get("GEO_EVENT_SOURCE", "file")).lower()
    if src == "db":
        return _load_events_db()
    main = _read(C.EVENTS)
    d = C.STORE / "events_shards"
    shard_files = list(d.glob("*.parquet")) if d.exists() else []
    if not shard_files:
        return main
    parts = [main] if len(main) else []
    for f in shard_files:
        try:
            parts.append(pd.read_parquet(f))
        except Exception:
            pass
    if not parts:
        return main
    df = pd.concat(parts, ignore_index=True)
    if "event_id" in df.columns:
        df = df.drop_duplicates("event_id", keep="last").reset_index(drop=True)
    return df


def _load_events_db() -> pd.DataFrame:
    """publish된 geo_event 테이블에서 이벤트 로드(추정기의 DB 읽기 모드).
    대상은 GEO_PUBLISH_DB(전처리기가 적재한 곳과 동일 계약) — 미설정이면 조용히 파일로
    폴백하지 않고 명시적으로 실패한다(어느 원천을 읽었는지 모호해지는 것 방지)."""
    target = os.environ.get("GEO_PUBLISH_DB")
    if not target:
        raise RuntimeError("GEO_EVENT_SOURCE=db인데 GEO_PUBLISH_DB 미설정 — 읽을 DB를 지정하세요")
    if "://" in target:
        import sqlalchemy as sa
        df = pd.read_sql_table("geo_event", sa.create_engine(target))
    else:
        import duckdb
        con = duckdb.connect(target, read_only=True)
        df = con.execute("SELECT * FROM geo_event").df()
        con.close()
    # publish 계약(commodity_code, source '' 채움) → 내부 계약(commodity, source 결측=NaN)으로 복원
    df = df.rename(columns={"commodity_code": "commodity"})
    if "source" in df.columns:
        df["source"] = df["source"].replace("", pd.NA)
    print(f"[store] 이벤트 {len(df):,}건 로드 ← DB {target} (geo_event)")
    return df


def extracted_doc_ids() -> set:
    """추출을 '시도 완료'한 문서 집합 = 추출로그 ∪ 이벤트 보유 문서(하위호환).
    이벤트 0건 문서도 로그에 남아 매 실행 재추출(LLM 비용 반복)되지 않는다."""
    done = set()
    log = _read(C.EXTRACT_LOG)
    if len(log):
        done |= set(log["doc_id"])
    ev = load_events(source="file")   # 추출 부기는 파일 도메인 — DB(발행 스냅샷)는 지연될 수 있음
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
    # 쓰기 경로는 파일 정본 전용으로 고정 — env가 db인 채 여기로 오면 DB 스냅샷(publish 계약의
    # 축소 스키마: horizon_months·analyzed_at 등 없음)에 병합해 정본을 덮어써 버린다(스키마 파괴).
    cur = load_events(source="file")
    new = pd.DataFrame(records)
    df = pd.concat([cur, new], ignore_index=True) if len(cur) else new
    if "event_id" in df:
        df = df.drop_duplicates("event_id", keep="last").reset_index(drop=True)
    _write(df, C.EVENTS)


EVENTS_SHARD_DIR = None   # 지연 평가(C.STORE는 GEO_DATA env에 의존, 임포트 시점에 고정하면 안 됨)


def _shard_dir():
    d = C.STORE / "events_shards"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_events_sharded(records: list[dict]):
    """대용량(GKG 등, 수십만 파일급) 전용 — append_events()는 매 호출마다 전체 events.parquet를
    읽어 재작성해 누적량이 커질수록(O(n)) 갈수록 느려지고, 여러 워커가 동시에 호출하면 서로의
    변경을 덮어써 유실된다(read-modify-write 경합). 이 함수는 배치를 독립 parquet 파일로만
    저장(O(batch), 읽기 없음) — 파일명이 유니크해 멀티프로세스에서도 안전. `load_events()`는
    조각들을 자동 병합해 반환하되, 조각이 쌓이면 `compact_event_shards()`로 메인 파일에 합쳐야
    조회 성능이 유지된다."""
    if not records:
        return
    import time, uuid
    df = pd.DataFrame(records)
    fname = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}.parquet"
    df.to_parquet(_shard_dir() / fname, index=False)


def compact_event_shards():
    """events_shards/의 조각들을 메인 geo_events.parquet에 병합 후 조각 삭제.
    단일 프로세스(오케스트레이터)에서만 호출할 것 — 컴팩션 자체는 동시성 안전하지 않음."""
    d = _shard_dir()
    shard_files = sorted(d.glob("*.parquet"))
    if not shard_files:
        return 0
    parts = [_read(C.EVENTS)]
    for f in shard_files:
        try:
            parts.append(pd.read_parquet(f))
        except Exception:
            pass
    df = pd.concat([p for p in parts if len(p)], ignore_index=True)
    if "event_id" in df:
        df = df.drop_duplicates("event_id", keep="last").reset_index(drop=True)
    _write(df, C.EVENTS)
    for f in shard_files:
        f.unlink()
    return len(shard_files)


def remove_events(event_ids: set):
    """event_id 집합에 해당하는 행 제거(LLM 재검증에서 노이즈로 기각된 GKG 후보 삭제용).
    append_events는 추가/덮어쓰기만 가능해 삭제 전용 함수가 별도로 필요하다."""
    if not event_ids:
        return
    ev = load_events(source="file")   # 쓰기 경로 — DB 스냅샷으로 정본 덮어쓰기 방지(append_events 참조)
    if len(ev) == 0 or "event_id" not in ev:
        return
    before = len(ev)
    ev = ev[~ev["event_id"].isin(event_ids)].reset_index(drop=True)
    _write(ev, C.EVENTS)
    return before - len(ev)


def write_index(df: pd.DataFrame):
    C.STORE.mkdir(parents=True, exist_ok=True)
    _write(df, C.INDEX)
