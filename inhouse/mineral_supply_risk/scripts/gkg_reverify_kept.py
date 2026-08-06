# -*- coding: utf-8 -*-
"""GKG 소급 정제(4라운드) 후 kept 집합 LLM 재검증 — 2026-07-20 /goal.

배경: 규칙기반 is_relevant() 필터의 이론적 상한이 실측(정제 후 SRS n=200) 약 82~83%로
확인됨(WORKLOG 2026-07-20 "GKG 소급 정제 4라운드..." 항목) — 잔여 무관 사례의 절반은 GDELT
테마코드 자체의 상품 오태깅(정규식으로 해소 불가), 나머지 절반은 GKG 본문 부재로 인한
근본적 모호성(신호 자체가 없음)이라 규칙기반으로는 90% 달성이 구조적으로 불가능. 사용자
선택("LLM 재검증 실행")에 따라 geo/gkg_verify.py의 `_verify_one()`(commodity 정정 반영+
is_relevant() 사전필터 + 확인편향 완화 프롬프트, 전부 이미 수정됨)을 kept 집합 전체에 실제
LLM로 재적용한다.

기존 gkg_verify.py.run()은 provider=="gkg" & extractor=="rule" 후보만 선택하는데, 현재 kept
집합은 이미 예전(확인편향 있던) LLM 검증을 거쳐 provider=="openai_compat"·extractor=="llm"로
되어 있어 그 필터에 안 걸린다 — 이 스크립트는 doc_id가 GKG 원문 ID 패턴인 행 전체를 대상으로
별도 후보선택을 한다(gkg_backfill_relevance.py와 동일한 스코프 판별 방식).

CLI:
    export LLM_PROVIDER=openai_compat LLM_BASE_URL=http://localhost:52302/v1 LLM_MODEL=gemma-4-26b-a4b
    python -m scripts.gkg_reverify_kept --limit 500          # 소규모 시험
    python -m scripts.gkg_reverify_kept                       # 전량(kept 332,474건)
    python -m scripts.gkg_reverify_kept --compact-rejections  # 기각분 store 실삭제만
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # komir root

import pandas as pd
from geo import config as C, store
from geo.gkg_verify import _verify_one
from geo.llm.base import get_extractor

GKG_DOCID_RE = re.compile(r"^\d{14}-\d+$")
STATE_DIR = Path(__file__).resolve().parent.parent / "outputs" / "model_opt" / "_gkg_reverify_state"
STATE_PATH = STATE_DIR / "reverified.txt"
REJECTED_PATH = STATE_DIR / "rejected.txt"


def _load_state(p: Path) -> set:
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def run(limit: int = 0, chunk_size: int = 2000, concurrency: int | None = None) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = C.llm_config()
    if (cfg.get("provider") or "rule").lower() in ("rule", "mock"):
        print("[reverify] LLM_PROVIDER 미설정 — 재검증 의미 없음")
        return {}
    concurrency = concurrency or max(1, int(cfg.get("concurrency", 8) or 8))
    cfg["concurrency"] = concurrency
    ex = get_extractor(cfg)
    print(f"[reverify] provider={ex.provider} model={getattr(ex, 'model', '')} concurrency={concurrency}")

    ev = store.load_events(source="file")
    is_gkg = ev["doc_id"].astype(str).str.match(GKG_DOCID_RE)
    cand_all = ev[is_gkg]
    print(f"[reverify] kept GKG 전체 {len(cand_all):,}건")
    del ev

    done = _load_state(STATE_PATH)
    cand = cand_all[~cand_all["event_id"].isin(done)]
    if limit:
        cand = cand.head(limit)
    total = len(cand)
    print(f"[reverify] 재검증 대상 {total:,}건 (기완료 {len(done):,}건 제외)")

    cols = ["event_id", "commodity", "country", "event_type", "severity",
            "obs_date", "doc_id", "evidence_quote"]
    records = cand[cols].to_dict("records")
    del cand, cand_all

    n_confirmed = n_corrected = n_rejected = n_verified = 0
    for start in range(0, total, chunk_size):
        chunk = records[start:start + chunk_size]
        confirmed_buf, rejected_buf, done_buf = [], [], []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(_verify_one, ex, r["event_id"], r["commodity"], r["country"],
                                 r["event_type"], r["severity"], r["obs_date"], r["doc_id"],
                                 r["evidence_quote"]): r for r in chunk}
            for fut in as_completed(futs):
                orig = futs[fut]
                eid, result, err = fut.result()
                if err is not None:
                    continue
                done_buf.append(eid)
                if result:
                    confirmed_buf.extend(result)
                    if result[0]["commodity"] != orig["commodity"]:
                        n_corrected += 1
                else:
                    rejected_buf.append(eid)

        if confirmed_buf:
            store.append_events_sharded(confirmed_buf)
            n_confirmed += len(confirmed_buf)
        if rejected_buf:
            with open(REJECTED_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(rejected_buf) + "\n")
            n_rejected += len(rejected_buf)
        if done_buf:
            with open(STATE_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(done_buf) + "\n")
            n_verified += len(done_buf)
        print(f"  진행 {min(start+chunk_size,total):,}/{total:,} "
              f"(확정 {n_confirmed:,} 상품정정 {n_corrected:,} 기각 {n_rejected:,} 검증 {n_verified:,})")

    print(f"[reverify] 완료: {n_verified:,}건 중 확정 {n_confirmed:,}건(상품정정 {n_corrected:,}건 포함), "
          f"기각표시 {n_rejected:,}건 — compact_rejections()로 실삭제 필요")
    return {"verified": n_verified, "confirmed": n_confirmed, "corrected": n_corrected,
            "rejected": n_rejected}


def compact_rejections() -> int:
    if not REJECTED_PATH.exists():
        return 0
    with open(REJECTED_PATH, encoding="utf-8") as f:
        ids = set(line.strip() for line in f if line.strip())
    if not ids:
        return 0
    n = store.remove_events(ids)
    return n or 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--chunk-size", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--compact-rejections", action="store_true")
    a = ap.parse_args()
    if a.compact_rejections:
        n = compact_rejections()
        print(f"[reverify] 기각분 {n:,}건 store에서 제거 완료")
    else:
        summary = run(a.limit, a.chunk_size, a.concurrency)
        print(summary)
