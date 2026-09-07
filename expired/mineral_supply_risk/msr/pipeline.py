# -*- coding: utf-8 -*-
"""엔드투엔드 오케스트레이션: collect → preprocess → features → train
각 단계는 독립 실행 가능(멱등). 실패해도 다음 실행에서 이어서.

2026-08-06 dmz/inhouse 물리분리: DMZ 격리 원칙(LLM 없음·DB 직접 접근 없음 — 원본은 파일로만
전달)에 따라 관세청·ECOS 라이브 API 호출은 `dmz/msr_collectors/scripts/`로 이전했다. 이
파일의 collect_customs·collect_customs_incremental·collect_ecos는 더 이상 API를 직접
호출하지 않고, DMZ가 미리 만들어 둔 parquet 산출물을 읽어 원래 _sink가 하던 것과 동일한
attach_commodity + db.upsert_df(del_where=...)만 재현한다("수집"이 아니라 "적재"로 의미가
바뀌었다 — 실제 수집은 DMZ 쪽을 먼저 실행해야 함, 각 함수 docstring 참고)."""
import os

import pandas as pd
from . import config, dmz_ingest
from .preprocess import hs_mapping
from .features import builders, normalize as normalize_mod
from .storage import db

# ---- 1) 적재(DMZ 산출물 로드 — 2026-08-06 이전엔 여기서 직접 API를 호출했음) ----
def collect_customs(strt="201301", end="202512", freq="A"):
    """freq: 'A' 연간(→raw_customs_annual) | 'M' 월간(→raw_customs_monthly).
    ⚠️ 먼저 DMZ에서 다음을 실행해 parquet을 만들어 둬야 한다(strt/end/freq 동일하게):
      cd dmz && python -m msr_collectors.scripts.collect_customs --strt {strt} --end {end} \\
          --freq {freq} --out-subdir pipeline_full_{freq}
    이 함수는 그 산출물을 $MSR_COLLECT_OUT/customs/pipeline_full_<freq>/에서 읽어
    attach_commodity 후 적재한다. 원본 설계(첫 파일에서만 테이블 전삭제하는 clean recollect)
    그대로 보존."""
    table = "raw_customs_monthly" if freq == "M" else "raw_customs_annual"
    out_dir = os.path.join(config.MSR_COLLECT_OUT, "customs", f"pipeline_full_{freq}")
    files = dmz_ingest.list_pending(out_dir, prefix="customs__")
    print(f"[load] 관세청 DMZ 산출물 {len(files)}개(HS단위) ← {out_dir} → {table}")
    n, first = 0, True
    for path in files:
        df_hs = dmz_ingest.read_df(path)
        df_hs = hs_mapping.attach_commodity(df_hs)
        db.upsert_df(df_hs, table, del_where="1=1" if first else None)
        first = False
        n += len(df_hs)
        dmz_ingest.mark_loaded(path)
    print(f"  적재 {n} 행 → {table}")
    return n

def collect_customs_incremental(strt: str, end: str, freq: str = "M"):
    """최근 구간만 갱신하는 보존형 적재(월간 정기용, 2026-07-12 도입).
    collect_customs는 첫 파일에서 테이블 전삭제(clean recollect)라 백필분이 유실될 수 있어,
    이 함수는 HS 단위로 [strt,end] 연도 구간만 삭제 후 삽입(멱등, 구간 밖 보존).
    ⚠️ 먼저 DMZ에서: cd dmz && python -m msr_collectors.scripts.collect_customs \\
        --strt {strt} --end {end} --freq {freq} --out-subdir pipeline_incremental_{freq}"""
    table = "raw_customs_monthly" if freq == "M" else "raw_customs_annual"
    yr_lo, yr_hi = strt[:4], end[:4]
    out_dir = os.path.join(config.MSR_COLLECT_OUT, "customs", f"pipeline_incremental_{freq}")
    files = dmz_ingest.list_pending(out_dir, prefix="customs__")
    print(f"[load-incr] 관세청 DMZ 산출물 {len(files)}개 ← {out_dir} → {table}(구간 밖 보존)")
    n = 0
    for path in files:
        df_hs = dmz_ingest.read_df(path)
        df_hs = hs_mapping.attach_commodity(df_hs)
        h = str(df_hs["hs_query"].iloc[0])
        db.upsert_df(df_hs, table,
                     del_where=f"hs_query='{h}' AND q_year>='{yr_lo}' AND q_year<='{yr_hi}'")
        n += len(df_hs)
        dmz_ingest.mark_loaded(path)
    print(f"  적재 {n} 행 → {table}")
    return n

def collect_ecos():
    """⚠️ 먼저 DMZ에서: cd dmz && ECOS_API_KEY=<키> python -m msr_collectors.scripts.collect_ecos
        --jobs msr_collectors/data/ecos_jobs_pipeline.json --out-subdir pipeline
    그 산출물($MSR_COLLECT_OUT/ecos/pipeline/*.parquet, 파일명의 name==ECOS_SERIES 키)을
    모아 원본과 동일하게 raw_ecos에 전량 재적재(del_where='1=1')한다."""
    out_dir = os.path.join(config.MSR_COLLECT_OUT, "ecos", "pipeline")
    files = dmz_ingest.list_pending(out_dir, prefix="ecos__")
    frames = []
    for path in files:
        # 파일명: ecos__<name>__<ts>.parquet — name(= ECOS_SERIES 키)을 복원
        name = os.path.basename(path).split("__")[1]
        s = dmz_ingest.read_df(path)
        if not s.empty:
            s = s.copy(); s["series"] = name
            frames.append(s[["series", "TIME", "DATA_VALUE"]])
            print(f"  [ecos] {name}: {len(s)}행")
    if frames:
        out = pd.concat(frames)
        db.upsert_df(out, "raw_ecos", del_where="1=1")
        for path in files:
            dmz_ingest.mark_loaded(path)
        return out
    print("  [ecos] DMZ 산출물 없음 — 먼저 dmz 쪽 collect_ecos를 실행할 것")
    return pd.DataFrame()

# ---- 2) 정규화(raw→fact) ----
def normalize():
    """랜딩(raw_customs_*) → 정본 팩트(fact_trade_*) + agg_trade_annual."""
    return normalize_mod.run()

# ---- 3) 피처(정본 팩트 기반) ----
def build_features():
    from db.dbio import connect_ro  # msr/storage/db.py::connect()는 duckdb 전용이라 postgres cutover 후 크래시(msr/storage/db.py 상단 docstring 참고) — connect_ro로 우회
    con=connect_ro(config.DB_PATH)
    # raw가 아닌 정본 팩트에서 읽음(단일 소스). 없으면 먼저 normalize.
    try: trade=con.execute("SELECT commodity_code, yr AS year, country, imp_usd FROM fact_trade_monthly").df()
    except Exception: trade=pd.DataFrame()
    con.close()
    if trade.empty: print("[features] fact_trade_monthly 비어있음(먼저 collect→normalize)"); return
    hhi=builders.import_hhi(trade); grw=builders.import_growth(trade)
    db.upsert_df(hhi,"feat_import_hhi",del_where="1=1")
    db.upsert_df(grw,"feat_import_growth",del_where="1=1")
    print(f"[features] HHI {len(hhi)} · growth {len(grw)}")

def run_all():
    collect_customs(); collect_ecos(); normalize(); build_features()
    print("[pipeline] 완료")
