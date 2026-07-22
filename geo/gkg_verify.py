# -*- coding: utf-8 -*-
"""GKG 규칙기반 후보(geo_events, provider="gkg", extractor="rule")를 실제 LLM으로 재검증.

GKG는 기사 본문이 없어 테마코드·톤만으로는 정밀도에 한계가 있다(실측: REE 표본 오탐률 100%,
CU/NI "분쟁" 표본도 절반 이상 오탐 — documens/claude_output/진단예측모델_요구사항대조_코드감사_260706.md
§11 참고). gkg_parse.py의 오프셋 근접성·2차 신호어 게이트로 1차 개선했지만, 근본적으로는 문맥을 읽는
게 아니라 규칙 매칭이라 한계가 있다.

이 모듈은 후보 각각을 (URL·매칭 국가·1차 판정)으로 구성한 짧은 passage로 만들어, 기존
`geo/llm/`(rule.py와 동일 인터페이스의 openai_compat/anthropic — extract.py가 PDF 문서에 쓰는 것과
동일한 경로)에 넣어 재확인한다.
  - LLM이 이벤트를 반환 → 후보를 LLM 결과로 교체(extractor="llm", provider=<실제 provider>)
  - LLM이 0건 반환 → 노이즈로 판정, 후보를 geo_events에서 제거(store.remove_events)

인증·provider 선택은 extract.py와 동일하게 config.llm_config()(env가 models.yaml보다 우선)를 그대로
쓴다. rule/mock provider로는 재검증 의미가 없어(이미 규칙으로 판정한 걸 다시 규칙으로 보는 셈) 실행을
막는다 — 반드시 실제 LLM(openai_compat: OpenAI/vLLM/Ollama/Gemini호환, anthropic)을 지정해야 한다.

규모 설계(2026-07-08, 200만 건 전량 재검증 대응):
  - 짧은 passage라 호출당 0.06~0.15초로 빠름(실측) — 그래도 200만 건 순차면 며칠 걸려 반드시 동시성
    필요. extract.py와 동일하게 ThreadPoolExecutor로 동시 요청.
  - 확정(confirmed) 결과는 store.append_events_sharded()로 기록(O(batch), 전체 재작성 없음).
    gkg_parse.py에서 겪은 것과 동일한 이유로 append_events()는 이 규모에 부적합.
  - 기각(rejected) ID는 러닝 중엔 파일에만 누적하고, store.remove_events()(O(n), 전체 재작성)는 실행
    끝에 한 번만 호출 — 매 배치마다 부르면 배치 수만큼 O(n) 재작성이 반복돼 갈수록 느려짐.
  - 청크 단위(chunk_size)로 제출·플러시해 메모리 상한을 두고, 중간에 죽어도 상태파일로 재개 가능.

CLI:
    export LLM_PROVIDER=openai_compat LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen2.5:32b
    python -m geo gkg-verify --bulk-root /mnt/.../bulk/gdelt --limit 500 --min-severity 1
    # 전량 재검증(제한 없음): --limit 생략 또는 0
"""
from __future__ import annotations
import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from . import config as C, store
from .llm.base import get_extractor
from .schema import GeoEvent
from .gkg_relevance import is_relevant, COMMODITY_NAMES


def _build_passage(row: pd.Series) -> str:
    """GKG 후보 1건 → LLM에 줄 짧은 텍스트. 본문이 없어 메타데이터로 근사한다."""
    parts = [f"문서 URL/제목 단서: {row.get('evidence_quote', '')}"]
    if row.get("country"):
        parts.append(f"언급 지역/국가: {row['country']}")
    parts.append(f"규칙기반 1차 판정(참고용, 그대로 믿지 말 것): "
                 f"{row.get('event_type')} (severity={row.get('severity')})")
    return "\n".join(parts)


def _state_path(bulk_root: str) -> str:
    p = os.path.join(bulk_root, "_logs", "gkg_verified.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _rejected_path(bulk_root: str) -> str:
    p = os.path.join(bulk_root, "_logs", "gkg_rejected.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def _load_state(bulk_root: str) -> set:
    p = _state_path(bulk_root)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def _verify_one(ex, event_id, commodity, country, event_type, severity, obs_date, doc_id, evidence_quote):
    # 2026-07-20 /goal: is_relevant() 사전필터 — LLM 호출 전에 명백히 무관한 후보는 즉시 기각.
    # 원 후보의 commodity 하나만이 아니라 "추적 5종 중 아무거나와도" 무관한지 확인한다(any) —
    # 원 commodity 하나만 검사하면 진짜 오태깅(예: CU로 잘못 태깅된 리튬 기사)까지 LLM 호출 전에
    # 걸러져 아래 LLM 정정 경로 자체가 무력화되기 때문(2026-07-20 첫 구현에서 유닛테스트로 발견).
    if not any(is_relevant(evidence_quote, cc) for cc in COMMODITY_NAMES):
        return event_id, [], None
    passage = "\n".join([
        f"문서 URL/제목 단서: {evidence_quote}",
        *([f"언급 지역/국가: {country}"] if country else []),
        f"규칙기반 1차 판정(참고용, 그대로 믿지 말 것): {event_type} (severity={severity})",
    ])
    try:
        events = ex.extract(passage, commodity)
    except Exception as e:
        return event_id, None, str(e)
    if not events:
        return event_id, [], None
    e = events[0]
    # 2026-07-20 /goal 수정: 기존엔 commodity=commodity로 하드코딩되어 있어 LLM이 오태깅을
    # 발견해도 원 후보의 상품코드를 그대로 써버리는 구조적 버그였다(상품 오태깅 33건 조사,
    # WORKLOG 2026-07-20의 근본원인 2/2). LLM이 실제로 판정한 commodity를 우선 채택하고,
    # 미기재시에만 원 후보값으로 보정(fallback) — llm_extractor.py도 동일 규칙.
    ev_commodity = e.get("commodity") or commodity
    row = dict(
        event_id=event_id, doc_id=doc_id, commodity=ev_commodity,
        country=e.get("country") or country, event_type=e.get("event_type", event_type),
        direction=e.get("direction", "neutral"), target=e.get("target", "mixed"),
        severity=float(e.get("severity", severity) or 0), horizon_months=e.get("horizon_months"),
        obs_date=obs_date, confidence=float(e.get("confidence", 0.6) or 0.6),
        evidence_quote=str(e.get("evidence_quote", evidence_quote))[:300],
        extractor="llm", provider=ex.provider, model=getattr(ex, "model", ""),
        prompt_version="geo-extract-v1", schema_version="1.0",
    )
    # extract.py(문서 파이프라인)와 동일하게 pydantic 검증 — GKG는 본문 없이 메타데이터만
    # 주므로 LLM이 간혹 프롬프트의 필드형식 설명을 그대로 echo하거나("[supply_down|...]")
    # 플레이스홀더를 반환("[Quote from text]")하는 실패 모드가 있음(실측 9건, 2026-07-18
    # A-5 라벨 검수 중 발견). 검증 실패는 "이벤트 없음"과 동일하게 기각(노이즈) 처리 —
    # err 경로(재시도 대상)가 아니라 events가 빈 경우와 같은 분기로 보내 무한 재시도를 피한다.
    try:
        row = GeoEvent(**row).model_dump()
    except Exception as ve:
        print(f"  [gkg_verify skip invalid] event_id={event_id}: {ve}")
        return event_id, [], None
    return event_id, [row], None


def run(bulk_root: str, provider: str | None = None, limit: int = 0,
        min_severity: float = 0.0, event_types: tuple = (),
        concurrency: int | None = None, chunk_size: int = 5000) -> dict:
    cfg = C.llm_config()
    if provider:
        cfg["provider"] = provider
    if (cfg.get("provider") or "rule").lower() in ("rule", "mock"):
        print(f"[gkg_verify] provider={cfg.get('provider')!r} — 규칙기반은 재검증 의미 없음"
              f"(이미 규칙으로 판정한 걸 같은 규칙으로 다시 보는 셈). "
              f"LLM_PROVIDER=openai_compat(+LLM_BASE_URL·LLM_MODEL) 또는 anthropic으로 지정 필요.")
        return {"verified": 0, "confirmed": 0, "rejected": 0}
    concurrency = concurrency or max(1, int(cfg.get("concurrency", 8) or 8))
    cfg["concurrency"] = concurrency   # OpenAICompatChat이 커넥션풀 크기를 여기서 읽음(순서 중요)
    ex = get_extractor(cfg)
    print(f"[gkg_verify] provider={ex.provider} model={getattr(ex, 'model', '')} concurrency={concurrency}")

    ev = store.load_events()
    if len(ev) == 0:
        print("[gkg_verify] 이벤트 없음"); return {"verified": 0, "confirmed": 0, "rejected": 0}

    done = _load_state(bulk_root)
    cand = ev[(ev["provider"] == "gkg") & (ev["extractor"] == "rule")
              & (~ev["event_id"].isin(done))].copy()
    if min_severity:
        cand = cand[cand["severity"].astype(float) >= min_severity]
    if event_types:
        cand = cand[cand["event_type"].isin(event_types)]
    if limit:
        cand = cand.head(limit)
    total = len(cand)
    print(f"[gkg_verify] 검증 대상 {total}건")
    del ev  # 대형 프레임 조기 해제(2백만행급에서 메모리 절약)

    state_path = _state_path(bulk_root)
    rejected_path = _rejected_path(bulk_root)
    n_confirmed = n_rejected = n_verified = 0
    cols = ["event_id", "commodity", "country", "event_type", "severity",
            "obs_date", "doc_id", "evidence_quote"]
    records = cand[cols].to_dict("records")
    del cand

    for start in range(0, total, chunk_size):
        chunk = records[start:start + chunk_size]
        confirmed_buf, rejected_buf, done_buf = [], [], []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(_verify_one, ex, r["event_id"], r["commodity"], r["country"],
                                 r["event_type"], r["severity"], r["obs_date"], r["doc_id"],
                                 r["evidence_quote"]): r for r in chunk}
            for fut in as_completed(futs):
                eid, result, err = fut.result()
                if err is not None:
                    continue   # 실패는 state에 안 남겨 다음 실행에서 재시도
                done_buf.append(eid)
                if result:
                    confirmed_buf.extend(result)
                else:
                    rejected_buf.append(eid)

        if confirmed_buf:
            store.append_events_sharded(confirmed_buf)
            n_confirmed += len(confirmed_buf)
        if rejected_buf:
            with open(rejected_path, "a", encoding="utf-8") as f:
                f.write("\n".join(rejected_buf) + "\n")
            n_rejected += len(rejected_buf)
        if done_buf:
            with open(state_path, "a", encoding="utf-8") as f:
                f.write("\n".join(done_buf) + "\n")
            n_verified += len(done_buf)
        print(f"  진행 {min(start+chunk_size,total)}/{total} "
              f"(확정 {n_confirmed} 기각 {n_rejected} 검증 {n_verified})")

    print(f"[gkg_verify] 검증 루프 완료: {n_verified}건 중 확정 {n_confirmed}건, 기각표시 {n_rejected}건"
          f" — 기각분은 아직 store에서 실제 삭제 안 됨, compact_rejections() 별도 호출 필요")
    return {"verified": n_verified, "confirmed": n_confirmed, "rejected": n_rejected}


def compact_rejections(bulk_root: str) -> int:
    """gkg_rejected.txt에 누적된 기각 event_id를 실제로 store에서 제거(O(n), 1회성).
    검증 루프 중에 매번 부르면 배치 수만큼 반복돼 느려지므로 별도 호출로 분리."""
    p = _rejected_path(bulk_root)
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8") as f:
        ids = set(line.strip() for line in f if line.strip())
    if not ids:
        return 0
    n = store.remove_events(ids)
    return n or 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk-root", required=True)
    ap.add_argument("--provider", default=None, help="openai_compat|anthropic (rule/mock은 무의미)")
    ap.add_argument("--limit", type=int, default=0, help="0=제한 없음(전량)")
    ap.add_argument("--min-severity", type=float, default=0.0)
    ap.add_argument("--event-types", default=None, help="쉼표구분, 예: 정책,분쟁,제재")
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--chunk-size", type=int, default=5000)
    ap.add_argument("--compact-rejections", action="store_true",
                     help="검증 대신 누적된 기각분을 store에서 실삭제만 수행")
    a = ap.parse_args()
    if a.compact_rejections:
        n = compact_rejections(a.bulk_root)
        print(f"[gkg_verify] 기각분 {n}건 store에서 제거 완료")
    else:
        et = tuple(a.event_types.split(",")) if a.event_types else ()
        summary = run(a.bulk_root, a.provider, a.limit, a.min_severity, et, a.concurrency, a.chunk_size)
        print(summary)
