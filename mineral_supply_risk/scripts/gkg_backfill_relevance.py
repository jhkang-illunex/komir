# -*- coding: utf-8 -*-
"""GKG 기존 데이터 소급 정제(2026-07-20 /goal) — geo/gkg_relevance.is_relevant()를
geo_data/store/geo_events.parquet(파일 정본)의 GKG 원천 행 전체에 적용해 무관 이벤트 제거.

배경: 단순임의표본(n=200) 재추정 결과 오염률 71.4%(정정후, WORKLOG 2026-07-20) — gkg_parse.py의
CU/NI 관련성 게이트 공백 + gkg_verify.py의 상품고정·확인편향 프롬프트가 원인으로 확정됨.
두 파이프라인 코드는 이미 수정했으나(geo/gkg_parse.py, geo/gkg_verify.py, geo/llm/llm_extractor.py)
그건 향후 재처리에만 적용되고, 이미 적재된 1,808,504건(전체의 99.6%)은 손대지 않으므로
별도 소급 정제가 필요.

범위 판별: doc_id가 GKG 원문 ID 형식(YYYYMMDDHHMMSS-N)인 행만 대상 — 이 패턴은 KOMIS/Argus/
WoodMac 등 구조화 수집기(source 필드 있음) 문서와 완전히 배타적임(실측 확인, 교차사례 0건).

실행:
    python -m scripts.gkg_backfill_relevance --dry-run   # 삭제 없이 통계만
    python -m scripts.gkg_backfill_relevance             # 실제 삭제(store.remove_events)
    python -m scripts.gkg_backfill_relevance --publish-db warehouse/minerals.duckdb
        # 삭제 후 DB에도 반영(geo publish --what events)
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # komir root

import pandas as pd
from geo import store
from geo.gkg_relevance import is_relevant

GKG_DOCID_RE = re.compile(r"^\d{14}-\d+$")


def run(dry_run: bool = True, publish_db: str | None = None) -> dict:
    ev = store.load_events(source="file")
    print(f"[backfill] 전체 이벤트 {len(ev):,}건 로드")

    is_gkg = ev["doc_id"].astype(str).str.match(GKG_DOCID_RE)
    gkg = ev[is_gkg]
    other = ev[~is_gkg]
    print(f"[backfill] GKG 원천(doc_id 패턴 매칭) {len(gkg):,}건 / 그 외(구조화 수집기) {len(other):,}건")
    assert len(other) < 10_000, "GKG 외 행이 예상보다 많음 — doc_id 패턴 가정 재확인 필요"

    text = gkg["evidence_quote"].fillna("").astype(str)
    commodity = gkg["commodity"].astype(str)
    relevant = [is_relevant(t, c) for t, c in zip(text, commodity)]
    keep_mask = pd.Series(relevant, index=gkg.index)

    n_drop = int((~keep_mask).sum())
    n_keep = int(keep_mask.sum())
    drop_by_commodity = gkg.loc[~keep_mask, "commodity"].value_counts().to_dict()
    keep_by_commodity = gkg.loc[keep_mask, "commodity"].value_counts().to_dict()
    print(f"[backfill] GKG {len(gkg):,}건 중 관련 {n_keep:,}건 유지 / 무관 {n_drop:,}건 제거 대상"
          f" ({n_drop / len(gkg):.1%})")
    print(f"  제거 대상 상품별: {drop_by_commodity}")
    print(f"  유지 상품별: {keep_by_commodity}")

    if dry_run:
        print("[backfill] --dry-run: 실제 삭제 없이 통계만 출력하고 종료")
        return {"total": len(ev), "gkg": len(gkg), "kept": n_keep, "dropped": n_drop, "dry_run": True}

    drop_ids = set(gkg.loc[~keep_mask, "event_id"])
    n_removed = store.remove_events(drop_ids)
    print(f"[backfill] store.remove_events() 실제 삭제: {n_removed:,}건")

    if publish_db:
        from geo import publish as geo_publish
        geo_publish.run(publish_db, "events")
        print(f"[backfill] DB 재발행 완료: {publish_db}")

    return {"total": len(ev), "gkg": len(gkg), "kept": n_keep, "dropped": n_drop,
            "removed": n_removed, "dry_run": False}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="삭제 없이 통계만 출력")
    ap.add_argument("--publish-db", default=None, help="삭제 후 이 DB에 geo publish --what events 실행")
    a = ap.parse_args()
    summary = run(dry_run=a.dry_run, publish_db=a.publish_db)
    print(f"[backfill] 완료: {summary}")
