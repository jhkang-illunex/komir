# -*- coding: utf-8 -*-
"""[2] 이벤트 추출 엔트리: manifest 미추출 문서 → provider 추출 → geo_events."""
import hashlib
from pathlib import Path
from . import config as C, store
from .schema import GeoEvent
from . import SCHEMA_VERSION
from .extract_lib import is_relevant, passages
from .llm.base import get_extractor, PROMPT_VERSION


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
    print(f"[extract] provider={ex.provider} model={getattr(ex,'model','')}")

    man = store.load_manifest()
    if len(man) == 0:
        print("[extract] manifest 비어있음 (먼저 ingest)"); return
    man = man[man["status"] == "archived"]
    done = store.extracted_doc_ids()
    todo = man[~man["doc_id"].isin(done)]
    print(f"[extract] 대상 {len(todo)}건 (기추출 {len(done)})")

    recs = []; n_rel = 0; done_log = []
    for _, rec in todo.iterrows():
        text = _read_text(rec)
        if not is_relevant(text):
            done_log.append((rec["doc_id"], 0))     # 비관련도 '시도 완료'로 기록(재스캔 방지)
            continue
        n_rel += 1
        psg = passages(text)
        try:
            events = ex.extract(psg, rec.get("commodity_hint"))
        except Exception as e:
            print(f"  [warn] {rec.get('orig_name','?')}: {e}"); continue   # 실패는 미기록 → 다음 실행 재시도
        n_doc = 0
        for i, e in enumerate(events):
            e = dict(e)
            if not e.get("obs_date"):
                # 폴백 사슬: 문서 발행일 → 수집일(ingested_at). 둘 다 없으면 지수에서
                # 조용히 탈락하므로 마지막 보루로 수집일을 쓴다(M4).
                ing = str(rec.get("ingested_at") or "")[:10]
                e["obs_date"] = rec.get("pub_date") or (ing or None)
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
