# -*- coding: utf-8 -*-
"""[2] 이벤트 추출 엔트리: manifest 미추출 문서 → provider 추출 → geo_events.
LLM 호출은 I/O 바운드라 ThreadPoolExecutor로 동시 실행(cfg['concurrency'], 기본 8) —
룰기반은 원래도 빨라 동시성 이득이 없으므로 provider=='rule'|'mock'일 때는 순차 실행 유지."""
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from . import config as C, store
from .schema import GeoEvent
from . import SCHEMA_VERSION
from .extract_lib import is_relevant, passages
from .llm.base import get_extractor, PROMPT_VERSION


def _extract_with_retry(ex, psg, hint):
    """LLM 경로에서 간헐적 빈 응답 관측(2026-07-07, vLLM 연속배치 추정) — 1회 재시도."""
    events = ex.extract(psg, hint)
    if not events and ex.provider not in ("rule", "mock"):
        events = ex.extract(psg, hint)
    return events


def _read_text(rec) -> str:
    """아카이브 원본 옆 .txt 우선, 없으면 원본 재추출."""
    ap = rec.get("archive_path") or ""
    txt = Path(ap + ".txt")
    if txt.exists():
        return txt.read_text(encoding="utf-8", errors="ignore")
    if ap and Path(ap).exists():
        from .extractors import extract_text
        try: return extract_text(ap)[1]
        except Exception: return ""
    return ""


def run(provider_override: str = None):
    C.ensure_dirs()
    cfg = C.llm_config()
    if provider_override:
        cfg["provider"] = provider_override
    ex = get_extractor(cfg)
    concurrency = max(1, int(cfg.get("concurrency", 8) or 8))
    print(f"[extract] provider={ex.provider} model={getattr(ex,'model','')} concurrency={concurrency}")

    man = store.load_manifest()
    if len(man) == 0:
        print("[extract] manifest 비어있음 (먼저 ingest)"); return
    man = man[man["status"] == "archived"]
    done = store.extracted_doc_ids()
    todo = man[~man["doc_id"].isin(done)]
    print(f"[extract] 대상 {len(todo)}건 (기추출 {len(done)})")

    # 1단계: 관련도 필터 + 발췌(경량, 순차) — LLM 호출 전 후보 확정
    candidates = []   # (rec, passages_text)
    done_log = []
    for _, rec in todo.iterrows():
        text = _read_text(rec)
        if not is_relevant(text):
            done_log.append((rec["doc_id"], 0))     # 비관련도 '시도 완료'로 기록(재스캔 방지)
            continue
        candidates.append((rec, passages(text)))
    print(f"[extract] 관련문서 {len(candidates)}건 → 추출 시작")

    # 2단계: 추출(룰기반은 순차, LLM은 동시 요청)
    extracted = []   # (rec, events|None, error|None)
    use_pool = concurrency > 1 and ex.provider not in ("rule", "mock")
    if use_pool:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = {pool.submit(_extract_with_retry, ex, psg, rec.get("commodity_hint")): rec
                    for rec, psg in candidates}
            n_done = 0
            for fut in as_completed(futs):
                rec = futs[fut]
                try:
                    events = fut.result()
                except Exception as e:
                    print(f"  [warn] {rec.get('orig_name','?')}: {e}")
                    events = None
                extracted.append((rec, events))
                n_done += 1
                if n_done % 50 == 0:
                    print(f"  ... {n_done}/{len(candidates)}건")
    else:
        for rec, psg in candidates:
            try:
                events = _extract_with_retry(ex, psg, rec.get("commodity_hint"))
            except Exception as e:
                print(f"  [warn] {rec.get('orig_name','?')}: {e}")
                events = None
            extracted.append((rec, events))

    # 3단계: 후처리(이벤트ID·검증·clamp) — 순차, 부작용 없음
    recs = []; n_rel = 0
    for rec, events in extracted:
        if events is None:
            continue   # 호출 실패(예외) — done_log에 안 남겨 다음 실행에서 재시도
        n_rel += 1
        n_doc = 0
        for i, e in enumerate(events):
            e = dict(e)
            # LLM이 준 obs_date도 검증(실측 2026-07-08: 연도 미상 시 "202X-09-01" 같은
            # placeholder를 그대로 출력하는 사례 확인 — DB DATE 캐스팅에서 터짐).
            # 형식·달력 불량이면 버리고 폴백 사슬을 태운다.
            if e.get("obs_date"):
                from .classify import _valid
                parts = str(e["obs_date"])[:10].split("-")
                e["obs_date"] = _valid(*parts) if len(parts) == 3 else None
            if not e.get("obs_date"):
                # 폴백 사슬: 문서 발행일 → 수집일(ingested_at). 둘 다 없으면 지수에서
                # 조용히 탈락하므로 마지막 보루로 수집일을 쓴다(M4).
                ing = str(rec.get("ingested_at") or "")[:10]
                e["obs_date"] = rec.get("pub_date") or (ing or None)
            # 미래 obs_date 교정(실측 2026-07-09): LLM이 전망 문장("2028년부터 생산 확대")의
            # 미래 시점을 사건 관측일로 뽑는 사례 확인 — 관측일은 문서 발행일로 되돌리고
            # 시점 정보는 horizon_months(전망 지평)로 옮긴다. 미래 이벤트가 지수/확률모델의
            # 미래 주차를 오염시키는 것 방지.
            pub = rec.get("pub_date")
            if e.get("obs_date") and pub and str(e["obs_date"]) > str(pub):
                try:
                    import datetime as _dt
                    d_obs = _dt.date.fromisoformat(str(e["obs_date"])[:10])
                    d_pub = _dt.date.fromisoformat(str(pub)[:10])
                    gap_m = (d_obs.year - d_pub.year) * 12 + (d_obs.month - d_pub.month)
                    if gap_m > 1:                     # 1개월 초과 미래 = 전망으로 간주
                        if not e.get("horizon_months"):
                            e["horizon_months"] = gap_m
                        e["obs_date"] = pub
                except ValueError:
                    pass
            # LLM이 범위 밖 수치를 내도 이벤트 전체를 버리지 않도록 clamp
            if e.get("severity") is not None:
                try: e["severity"] = min(3.0, max(0.0, float(e["severity"])))
                except (TypeError, ValueError): pass
            if e.get("confidence") is not None:
                try: e["confidence"] = min(1.0, max(0.0, float(e["confidence"])))
                except (TypeError, ValueError): pass
            eid = hashlib.md5(f"{rec['doc_id']}|{i}|{e.get('event_type')}|{e.get('commodity')}".encode()).hexdigest()[:16]
            e.update(dict(event_id=eid, doc_id=rec["doc_id"], extractor=ex.name,
                          provider=ex.provider, model=getattr(ex, "model", ""),
                          prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION))
            try:
                recs.append(GeoEvent(**e).model_dump()); n_doc += 1
            except Exception as ve:
                print(f"  [skip invalid] {ve}")
        done_log.append((rec["doc_id"], n_doc))     # 0건이어도 기록 → 무한 재추출 방지
    store.append_events(recs)
    store.log_extracted(done_log)
    print(f"[extract] 완료: 관련문서 {n_rel}건 → 이벤트 {len(recs)}건 적재 (시도기록 {len(done_log)}건)")
    return len(recs)


if __name__ == "__main__":
    run()
