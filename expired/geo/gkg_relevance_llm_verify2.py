# -*- coding: utf-8 -*-
"""GKG 관련성 2차 검증(적대적 재확인) — 2026-07-20 /goal 추가 정제.

배경: 1차 LLM 관련성 재검증(geo/gkg_relevance_llm.py)으로 유효성 92.9%(95% CI 87.7~96.0%)
달성 확인 후, 사용자가 "더 디테일하게" 추가 개선을 요청. 99.99%는 측정·달성 둘 다 비현실적
(GDELT 원천 태깅 오류·n=200 표본의 통계적 한계)이라 설명 후, 사용자가 "다수결 합의 투표"
방식을 선택.

**설계 참고**: 사용된 로컬 모델은 temperature=0(config 기본값)이라 **동일 프롬프트를 여러 번
반복해도 항상 같은 답**이 나와 진짜 "다수결"이 되지 않는다(순수 반복은 다양성 0). 그래서
서로 다른 **적대적 관점(lens)**의 프롬프트로 독립적인 2차 의견을 얻는 방식으로 구현했다 —
1차 판정(geo/gkg_relevance_llm.py, 관대한 관점)이 "관련 있다"고 한 것을 2차(이 모듈,
의심하는 관점 — "정말 다른 상품이거나 동음이의어일 근거를 최대한 찾아보라")가 재확인하는
구조. 1차 SRS 리뷰에서 남은 오류가 거의 다 "잘못 유지된 것"(false positive)이었으므로,
2차는 특히 그 방향(과다포함 축소)에 집중한다.

CLI:
    python -m geo.gkg_relevance_llm_verify2 --limit 500
    python -m geo.gkg_relevance_llm_verify2               # 현재 kept 전체 재확인
    python -m geo.gkg_relevance_llm_verify2 --apply       # 결과 store 반영
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

ADVERSARIAL_SYSTEM_PROMPT = (
    "당신은 깐깐한 데이터 감사관입니다. GDELT GKG 문서 단서가 특정 광종으로 태깅되어 있는데, "
    "이 태깅이 **틀렸을 만한 구체적 근거를 최대한 의심하며 찾으세요**. 1차 검토에서는 관련 "
    "있다고 판정된 것들이니, 여기서는 그 판정을 뒤집을 근거가 있는지 재확인하는 역할입니다.\n"
    "다음 중 하나라도 명백히 해당하면 문제 있음(problem=true)으로 판정하세요:\n"
    "1. 실제로는 태깅된 광종이 아니라 다른 원자재(금·은·석탄·철광석·다이아몬드·우라늄·아연·"
    "납·주석·희토류 등 무엇이든, 추적 5종 중 다른 것 포함)에 관한 내용이다.\n"
    "2. 상품명 단어가 지명·인명·회사브랜드(산업과 무관한)·관용구·화폐속어·동전수집·장신구/"
    "생활용품 등 산업과 무관하게 쓰였다.\n"
    "3. 내용이 너무 없어(빈 URL, 의미 없는 해시값 등) 애초에 어떤 상품과도 연관짓기 어렵다.\n"
    "위에 해당하지 않고 실제로 그 광종의 생산/탐사/거래/가격/정책/기업활동과 관련 있다면 "
    "problem=false로 판정하세요. **의심스럽지만 확신이 없으면 problem=false**로 판정하세요 "
    "(1차 판정을 함부로 뒤집지 말 것 — 명백한 근거가 있을 때만 뒤집으세요).\n"
    '반드시 JSON 객체 하나만 출력: {"problem": true|false, "correct_commodity": "CU"|"NI"|"LI"|"CO"|"REE"|null}'
)


def _build_user(commodity: str, evidence_quote: str) -> str:
    return f"태깅된 광종: {commodity}\n문서 단서: {evidence_quote}"


def check_one(chat, event_id, commodity, evidence_quote):
    user = _build_user(commodity, evidence_quote)
    try:
        res = chat.complete(ADVERSARIAL_SYSTEM_PROMPT, user)
    except Exception as e:
        return event_id, None, str(e)
    parsed = repair_json(res.text)
    if not isinstance(parsed, dict):
        return event_id, None, f"unparseable: {res.text[:200]!r}"
    problem = bool(parsed.get("problem"))
    correct = parsed.get("correct_commodity")
    if correct not in Commodity.__args__:  # type: ignore[attr-defined]
        correct = None
    return event_id, {"problem": problem, "correct_commodity": correct}, None


GKG_DOCID_RE = re.compile(r"^\d{14}-\d+$")
STATE_DIR = Path(__file__).resolve().parent.parent / "mineral_supply_risk" / "outputs" / "model_opt" / "_gkg_relevance_verify2_state"
STATE_PATH = STATE_DIR / "checked.txt"
PROBLEM_PATH = STATE_DIR / "problem.txt"
CORRECTED_PATH = STATE_DIR / "corrected.txt"


def _load_state(p: Path) -> set:
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return set(line.strip().split(",")[0] for line in f if line.strip())
    return set()


def run(limit: int = 0, chunk_size: int = 2000, concurrency: int | None = None) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cfg = C.llm_config()
    if (cfg.get("provider") or "rule").lower() in ("rule", "mock"):
        print("[verify2] LLM_PROVIDER 미설정")
        return {}
    concurrency = concurrency or max(1, int(cfg.get("concurrency", 8) or 8))
    cfg["concurrency"] = concurrency
    ex = get_extractor(cfg)
    chat = ex.chat
    print(f"[verify2] provider={ex.provider} model={getattr(ex, 'model', '')} concurrency={concurrency}")

    ev = store.load_events(source="file")
    is_gkg = ev["doc_id"].astype(str).str.match(GKG_DOCID_RE)
    cand_all = ev[is_gkg]
    print(f"[verify2] kept GKG 전체 {len(cand_all):,}건")
    del ev

    done = _load_state(STATE_PATH)
    cand = cand_all[~cand_all["event_id"].isin(done)]
    if limit:
        cand = cand.head(limit)
    total = len(cand)
    print(f"[verify2] 재확인 대상 {total:,}건 (기완료 {len(done):,}건 제외)")

    cols = ["event_id", "commodity", "evidence_quote"]
    records = cand[cols].to_dict("records")
    del cand, cand_all

    n_ok = n_problem = n_corrected = n_checked = n_err = 0
    for start in range(0, total, chunk_size):
        chunk = records[start:start + chunk_size]
        problem_buf, corrected_buf, done_buf = [], [], []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(check_one, chat, r["event_id"], r["commodity"], r["evidence_quote"]): r
                    for r in chunk}
            for fut in as_completed(futs):
                eid, result, err = fut.result()
                if err is not None:
                    n_err += 1
                    continue
                done_buf.append(eid)
                if result["problem"]:
                    problem_buf.append(eid)
                    if result["correct_commodity"] and result["correct_commodity"] != futs[fut]["commodity"]:
                        corrected_buf.append((eid, result["correct_commodity"]))

        if problem_buf:
            with open(PROBLEM_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(problem_buf) + "\n")
            n_problem += len(problem_buf)
        if corrected_buf:
            with open(CORRECTED_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(f"{eid},{cc}" for eid, cc in corrected_buf) + "\n")
            n_corrected += len(corrected_buf)
        if done_buf:
            with open(STATE_PATH, "a", encoding="utf-8") as f:
                f.write("\n".join(done_buf) + "\n")
            n_checked += len(done_buf)
        n_ok = n_checked - n_problem
        print(f"  진행 {min(start+chunk_size,total):,}/{total:,} "
              f"(문제없음 {n_ok:,} 문제발견 {n_problem:,} 상품정정후보 {n_corrected:,} 오류 {n_err:,})")

    print(f"[verify2] 완료: 재확인 {n_checked:,}건, 문제발견 {n_problem:,}건 "
          f"(정정가능 {n_corrected:,}건 포함) — apply_results()로 store 반영 필요")
    return {"checked": n_checked, "ok": n_ok, "problem": n_problem, "corrected": n_corrected, "errors": n_err}


def apply_results(dry_run: bool = True) -> dict:
    """problem.txt(상품정정 없는 것)는 삭제, corrected.txt는 상품코드 갱신."""
    problem = set()
    if PROBLEM_PATH.exists():
        with open(PROBLEM_PATH, encoding="utf-8") as f:
            problem = set(l.strip() for l in f if l.strip())
    corrections = {}
    if CORRECTED_PATH.exists():
        with open(CORRECTED_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                eid, cc = line.split(",")
                corrections[eid] = cc

    to_remove = problem - set(corrections)  # 정정 가능한 건 삭제 대신 상품코드만 교정
    print(f"[verify2] 문제발견 {len(problem):,}건 (그중 상품정정 {len(corrections):,}건, "
          f"순수삭제 {len(to_remove):,}건)")
    if dry_run:
        return {"problem": len(problem), "corrected": len(corrections),
                "to_remove": len(to_remove), "dry_run": True}

    if corrections:
        ev = store.load_events(source="file")
        mask = ev["event_id"].isin(corrections)
        rows = ev[mask].copy()
        rows["commodity"] = rows["event_id"].map(corrections)
        store.append_events_sharded(rows.to_dict("records"))
        print(f"[verify2] 상품정정 {len(rows):,}건 반영")

    n_removed = 0
    if to_remove:
        n_removed = store.remove_events(to_remove) or 0
        print(f"[verify2] 문제건 {n_removed:,}건 store에서 제거")

    return {"problem": len(problem), "corrected": len(corrections), "removed": n_removed, "dry_run": False}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--chunk-size", type=int, default=2000)
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--apply-dry-run", action="store_true")
    a = ap.parse_args()
    if a.apply or a.apply_dry_run:
        print(apply_results(dry_run=not a.apply))
    else:
        print(run(a.limit, a.chunk_size, a.concurrency))
