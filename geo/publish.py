# -*- coding: utf-8 -*-
"""geo 산출물을 공유/운영 DB에 publish.
  python -m geo publish [--db <target>] [--what events|index|all]
  target: env GEO_PUBLISH_DB 또는 --db. 파일경로=DuckDB, '://' 포함=SQLAlchemy URL.

what으로 아키텍처 단계를 분리(2026-07-12, "전처리기→DB 적재→추정기가 DB에서 읽기" 배선):
  events  전처리기(ingest·extract) 산출 geo_event만 적재 — index 산출 *전*에 실행
  index   추정기(indexer·prob) 산출 geo_index·geo_prob만 적재
  all     전부(기존 사후 발행과 호환)
"""
import argparse, os
from datetime import datetime, timezone
import pandas as pd
from . import config as C, store


def _write(df, table, target):
    if "://" in target:                       # 서버DB(SQLAlchemy)
        import sqlalchemy as sa
        df.to_sql(table, sa.create_engine(target), if_exists="replace", index=False, chunksize=1000)
    else:                                      # DuckDB
        import duckdb
        con = duckdb.connect(target); con.register("_d", df)
        exists = con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name=?", [table]).fetchone()[0]
        if exists:
            # DDL 보존: CREATE OR REPLACE는 스키마 정의(PK·타입)를 추론 스키마로 덮어쓰므로
            # DELETE+INSERT(명시 컬럼, 단일 트랜잭션)로 계약 유지. 단, 신규 컬럼이 생기면
            # (예: 2026-07-12 provider·extractor 추가) 기존 DDL에 없어 INSERT가 죽음 → 재생성.
            have = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")').fetchall()}
            if set(df.columns) - have:
                con.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM _d')
            else:
                cols = ",".join(f'"{c}"' for c in df.columns)
                con.execute("BEGIN")
                con.execute(f'DELETE FROM "{table}"')
                con.execute(f'INSERT INTO "{table}" ({cols}) SELECT {cols} FROM _d')
                con.execute("COMMIT")
        else:
            con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM _d')
        con.unregister("_d"); con.close()


def publish_events(target: str, now: str) -> int:
    """전처리기 산출(geo_event) → DB. 항상 파일 정본에서 읽는다(GEO_EVENT_SOURCE 무관 —
    DB 모드로 읽어 되쓰면 순환이라 무의미)."""
    ev = store.load_events(source="file")
    if len(ev) == 0:
        print("[publish] 이벤트 없음(먼저 extract)"); return 0
    man = store.load_manifest()
    src = man.set_index("doc_id")["source"].to_dict() if len(man) else {}
    e = ev.rename(columns={"commodity": "commodity_code"}).copy()
    e["source"] = e["doc_id"].map(src).fillna("")
    # 방어: LLM 불량 날짜가 남아있으면 DATE 캐스팅에서 전체 publish가 죽음(실측 2026-07-08:
    # "202X-09-01" placeholder, "2023-02-29" 달력상 불가능 날짜) — 형식+달력 검증을 한 번에
    # (pd.to_datetime coerce), 불량은 NULL로 밀어내고 계속 진행.
    parsed = pd.to_datetime(e["obs_date"], format="%Y-%m-%d", errors="coerce")
    n_bad = int((parsed.isna() & e["obs_date"].notna()).sum())
    if n_bad:
        print(f"  [publish] obs_date 형식/달력 불량 {n_bad}건 → NULL 처리")
    e["obs_date"] = parsed.dt.strftime("%Y-%m-%d")
    e["obs_date"] = e["obs_date"].where(parsed.notna(), None)
    e["evidence_quote"] = e["evidence_quote"].astype(str).str.slice(0, 600)
    e["published_at"] = now
    # provider·extractor는 indexer의 GKG '뉴스' 티어 제외에 필수 — 빠지면 DB 모드 추정기에서
    # 규칙기반 노이즈가 지수에 섞이는 조용한 회귀가 생긴다(2026-07-12).
    for c in ("provider", "extractor"):
        if c not in e.columns:
            e[c] = None
    e = e[["event_id", "doc_id", "commodity_code", "obs_date", "country", "event_type",
           "direction", "target", "severity", "confidence", "evidence_quote",
           "source", "provider", "extractor", "published_at"]]
    _write(e, "geo_event", target)
    print(f"[publish] geo_event {len(e)}행 → {target} (테이블 geo_event)")
    return len(e)


def publish_index(target: str, now: str) -> int:
    """추정기 산출(geo_index·geo_prob) → DB."""
    idx = store._read(C.INDEX)
    if len(idx) == 0:
        print("[publish] geo_index 없음(먼저 index)"); return 0
    out = idx.rename(columns={"commodity": "commodity_code", "index": "idx_value"}).copy()
    out["index_config_version"] = os.environ.get("GEO_INDEX_VERSION", "v2")  # v2: 2026-07-15 정밀화 3종+재앵커
    out["generated_at"] = now
    out = out[["commodity_code", "freq", "period", "raw_score", "n_events",
               "idx_value", "index_config_version", "generated_at"]]
    _write(out, "geo_index", target)
    print(f"[publish] geo_index {len(out)}행 → {target} (테이블 geo_index)")
    n_pr = 0
    prob_f = C.STORE / "geo_prob.parquet"
    if prob_f.exists():
        pr = pd.read_parquet(prob_f)
        pr = pr.rename(columns={"commodity": "commodity_code", "week": "period"})
        # 요일앵커 보정(2026-07-16, 외부감사/사용자 지시): prob_model.py._weekly_panel()의
        # 주간 그리드는 pd.date_range(freq="W") 기본값(W-SUN, 일요일)으로 산출된다 — 이는
        # indexer.py의 geo_index(마찬가지로 W-SUN)와 내부적으로 정확일치 조인해야 하는
        # _attach_geo_idx()가 있어서 필요한 내부 정합이므로 prob_model.py 자체는 건드리지
        # 않는다. 문제는 외부(mart_weekly_diagnosis 등, 월요일 앵커) 소비자가 geo_prob를
        # 정확일치로 조인할 때만 발생(실측: diagnosis_retrain_answer.py에서 100% 미매칭
        # 확인) — geo_index는 ASOF 조인으로 소비되어 무해함이 확인됐으므로 그대로 둔다.
        # 따라서 geo_prob "만" DB 발행 경계에서 +1일(일요일→월요일) 보정한다 — 내부 계산
        # (parquet 정본)은 원래 그대로 유지, DB로 나가는 값만 외부 규약에 맞춘다.
        pr["period"] = (pd.to_datetime(pr["period"]) + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
        pr["generated_at"] = now
        _write(pr, "geo_prob", target)
        n_pr = len(pr)
        print(f"[publish] geo_prob {n_pr}행 → {target} (테이블 geo_prob, period +1일 월요일 보정)")
    return len(out) + n_pr


def run(target=None, what: str = "all"):
    target = target or os.environ.get("GEO_PUBLISH_DB") or str(C.STORE / "geo_published.duckdb")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    if what in ("events", "all"):
        n += publish_events(target, now)
    if what in ("index", "all"):
        n += publish_index(target, now)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--what", default="all", choices=["events", "index", "all"])
    a = ap.parse_args()
    run(a.db, a.what)
