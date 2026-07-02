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

    recs = []; n_rel = 0
    for _, rec in todo.iterrows():
        text = _read_text(rec)
        if not is_relevant(text):
            continue
        n_rel += 1
        psg = passages(text)
        try:
            events = ex.extract(psg, rec.get("commodity_hint"))
        except Exception as e:
            print(f"  [warn] {rec.get('orig_name','?')}: {e}"); continue
        for i, e in enumerate(events):
            e = dict(e)
            if not e.get("obs_date"):
                e["obs_date"] = rec.get("pub_date")
            eid = hashlib.md5(f"{rec['doc_id']}|{i}|{e.get('event_type')}|{e.get('commodity')}".encode()).hexdigest()[:16]
            e.update(dict(event_id=eid, doc_id=rec["doc_id"], extractor=ex.name,
                          provider=ex.provider, model=getattr(ex, "model", ""),
                          prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION))
            try:
                recs.append(GeoEvent(**e).model_dump())
            except Exception as ve:
                print(f"  [skip invalid] {ve}")
    store.append_events(recs)
    print(f"[extract] 완료: 관련문서 {n_rel}건 → 이벤트 {len(recs)}건 적재")
    return len(recs)


if __name__ == "__main__":
    run()
