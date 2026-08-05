# -*- coding: utf-8 -*-
"""GKG 관련성 LLM 재검증 — 이벤트추출용이 아닌 **관련성 판정 전용** 프롬프트(2026-07-20 /goal).

배경: gkg_verify.py의 기존 `_verify_one()`은 llm/base.py의 SYSTEM_PROMPT(문서 파이프라인과
공유하는 "수급·가격·생산에 영향을 주는 지정학/정책/공급 이벤트만 추출")를 그대로 쓴다.
소규모 시험(n=50, kept 집합 재검증)에서 이 프롬프트로는 "Freeport-McMoRan chairman steps
down"·"copper futures begin 2016 on weak note"·"Bougainville Copper Ltd" 언급처럼 명백히
관련 있는 문서도 "명시적 공급영향 이벤트가 아니다"라며 대량 거부(35/50)함을 확인 — 이벤트
추출(EXTRACTION)과 관련성 판정(RELEVANCE CLASSIFICATION)은 다른 과제이므로 같은 프롬프트를
쓰면 안 됨이 실측으로 확정됨(WORKLOG 2026-07-20 참조). 이 모듈은 후자만 전담하는 훨씬
관대한(회사뉴스·시장동향·가격 스냅샷도 관련 인정) 프롬프트를 쓴다.

CLI:
    python -m geo.gkg_relevance_llm --limit 500   # 소규모 시험
    python -m geo.gkg_relevance_llm               # kept 전체 재검증
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config as C, store
from .llm.base import get_extractor
from .llm.jsonutil import repair_json
from .schema import Commodity

RELEVANCE_SYSTEM_PROMPT = (
    "당신은 광물 데이터 큐레이터입니다. GDELT GKG(기사 본문 없이 URL·제목 단서만 있는 데이터)에서 "
    "특정 광종으로 태깅된 문서 단서가 실제로 그 광종과 관련 있는지 판정합니다.\n"
    "**관대하게 판정하세요** — 반드시 '공급 위기 이벤트'일 필요는 없습니다. 다음 중 하나라도 "
    "해당하면 관련 있음(relevant=true)입니다: 그 광종을 생산/탐사/거래하는 기업의 뉴스(임원 변동·"
    "실적·투자·계약 포함), 그 광종의 가격/선물/시장 동향(단순 스냅샷도 포함), 그 광종 프로젝트/"
    "광산의 개발·인허가·사고·정책, 그 광종의 수급/무역/정책 뉴스, 그 광종 관련 기술/제품.\n"
    "관련 없음(relevant=false)인 경우: 상품명이 지명·인명·브랜드·관용구·화폐속어·동전수집·"
    "장신구/생활용품 등 산업과 무관한 동음이의어로만 쓰인 경우, 실제로는 다른 원자재(금·석탄·"
    "다이아몬드 등)에 관한 내용인데 잘못 태깅된 경우, 정보가 너무 없어 어떤 상품과도 연관 짓기 "
    "어려운 경우.\n"
    "태깅된 상품이 아니라 5대 추적광종(CU=동,NI=니켈,LI=리튬,CO=코발트,REE=네오디뮴) 중 다른 "
    "것이 명백히 맞다면 correct_commodity에 그 코드를 넣으세요(모르면 null).\n"
    "반드시 JSON 객체 하나만 출력: "
    '{"relevant": true|false, "correct_commodity": "CU"|"NI"|"LI"|"CO"|"REE"|null}'
)


def _build_user(commodity: str, country: str | None, event_type, severity, evidence_quote: str) -> str:
    parts = [f"태깅된 광종: {commodity}", f"문서 단서: {evidence_quote}"]
    if country:
        parts.append(f"언급 지역/국가: {country}")
    parts.append(f"규칙기반 1차 판정(참고용): {event_type} (severity={severity})")
    return "\n".join(parts)


def classify_one(chat, event_id, commodity, country, event_type, severity, evidence_quote):
    user = _build_user(commodity, country, event_type, severity, evidence_quote)
    try:
        res = chat.complete(RELEVANCE_SYSTEM_PROMPT, user)
    except Exception as e:
        return event_id, None, str(e)
    parsed = repair_json(res.text)
    if not isinstance(parsed, dict):
        return event_id, None, f"unparseable: {res.text[:200]!r}"
    relevant = bool(parsed.get("relevant"))
    correct = parsed.get("correct_commodity")
    if correct not in Commodity.__args__:  # type: ignore[attr-defined]
        correct = None
    return event_id, {"relevant": relevant, "correct_commodity": correct}, None


GKG_DOCID_RE = re.compile(r"^\d{14}-\d+$")
STATE_DIR = Path(__file__).resolve().parent.parent / "mineral_supply_risk" / "outputs" / "model_opt" / "_gkg_relevance_llm_state"
STATE_PATH = STATE_DIR / "checked.txt"
REJECTED_PATH = STATE_DIR / "rejected.txt"
CORRECTED_PATH = STATE_DIR / "corrected.txt"  # "event_id,new_commodity" 줄들


def _load_state(p: Path) -> set:
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return set(line.strip().split(",")[0] for line in f if line.strip())
    return set()


def run(limit: int = 0, chunk_size: int = 2000, concurrency: int | None = None) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = C.llm_config()
    if (cfg.get("provider") or "rule").lower() in ("rule", "mock"):
        print("[relevance_llm] LLM_PROVIDER 미설정")
        return {}
    concurrency = concurrency or max(1, int(cfg.get("concurrency", 8) or 8))
    cfg["concurrency"] = concurrency
    ex = get_extractor(cfg)
    chat = ex.chat
    print(f"[relevance_llm] provider={ex.provider} model={getattr(ex, 'model', '')} concurrency={concurrency}")

    ev = store.load_events(source="file")
    is_gkg = ev["doc_id"].astype(str).str.match(GKG_DOCID_RE)
    cand_all = ev[is_gkg]
    print(f"[relevance_llm] kept GKG 전체 {len(cand_all):,}건")
    del ev

    done = _load_state(STATE_PATH)
    cand = cand_all[~cand_all["event_id"].isin(done)]
    if limit:
        cand = cand.head(limit)
    total = len(cand)
    print(f"[relevance_llm] 재검증 대상 {total:,}건 (기완료 {len(done):,}건 제외)")

    cols = ["event_id", "commodity", "country", "event_type", "severity", "evidence_quote"]
    records = cand[cols].to_dict("records")
    del cand, cand_all

    n_relevant = n_rejected = n_corrected = n_checked = n_err = 0
    for start in range(0, total, chunk_size):
        chunk = records[start:start + chunk_size]
        rejected_buf, corrected_buf, done_buf = [], [], []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(classify_one, chat, r["event_id"], r["commodity"], r["country"],
                                 r["event_type"], r["severity"], r["evidence_quote"]): r for r in chunk}
            for fut in as_completed(futs):
                eid, result, err = fut.result()
                if err is not None:
                    n_err += 1
                    continue  # state에 안 남겨 재시도
                done_buf.append(eid)
                if not result["relevant"]:
                    rejected_buf.append(eid)
                elif result["correct_commodity"] and result["correct_commodity"] != futs[fut]["commodity"]:
                    corrected_buf.append((eid, result["correct_commodity"]))

        if rejected_buf:
            with open(REJECTED_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(rejected_buf) + "\n")
            n_rejected += len(rejected_buf)
        if corrected_buf:
            with open(CORRECTED_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(f"{eid},{cc}" for eid, cc in corrected_buf) + "\n")
            n_corrected += len(corrected_buf)
        if done_buf:
            with open(STATE_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(done_buf) + "\n")
            n_checked += len(done_buf)
            n_relevant += len(done_buf) - len([1 for eid in done_buf if eid in set(rejected_buf)])
        print(f"  진행 {min(start+chunk_size,total):,}/{total:,} "
              f"(관련 {n_relevant:,} 기각 {n_rejected:,} 상품정정 {n_corrected:,} 오류 {n_err:,})")

    print(f"[relevance_llm] 완료: 검증 {n_checked:,}건, 관련 {n_relevant:,}건, 기각 {n_rejected:,}건, "
          f"상품정정 {n_corrected:,}건 — apply_results()로 store 반영 필요")
    return {"checked": n_checked, "relevant": n_relevant, "rejected": n_rejected,
            "corrected": n_corrected, "errors": n_err}


def apply_results(dry_run: bool = True) -> dict:
    """rejected.txt/corrected.txt를 store에 실제 반영(삭제/상품정정)."""
    rejected = set()
    if REJECTED_PATH.exists():
        with open(REJECTED_PATH, encoding="utf-8") as f:
            rejected = set(l.strip() for l in f if l.strip())
    corrections = {}
    if CORRECTED_PATH.exists():
        with open(CORRECTED_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                eid, cc = line.split(",")
                corrections[eid] = cc

    print(f"[relevance_llm] 기각 {len(rejected):,}건, 상품정정 {len(corrections):,}건")
    if dry_run:
        return {"rejected": len(rejected), "corrected": len(corrections), "dry_run": True}

    if corrections:
        import pandas as pd
        ev = store.load_events(source="file")
        mask = ev["event_id"].isin(corrections)
        rows = ev[mask].copy()
        rows["commodity"] = rows["event_id"].map(corrections)
        store.append_events_sharded(rows.to_dict("records"))
        print(f"[relevance_llm] 상품정정 {len(rows):,}건 반영")

    n_removed = 0
    if rejected:
        n_removed = store.remove_events(rejected) or 0
        print(f"[relevance_llm] 기각분 {n_removed:,}건 store에서 제거")

    return {"rejected": len(rejected), "corrected": len(corrections), "removed": n_removed, "dry_run": False}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--chunk-size", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--apply", action="store_true", help="run() 결과를 store에 실제 반영")
    ap.add_argument("--apply-dry-run", action="store_true", help="반영 통계만 출력")
    a = ap.parse_args()
    if a.apply or a.apply_dry_run:
        print(apply_results(dry_run=not a.apply))
    else:
        print(run(a.limit, a.chunk_size, a.concurrency))
