# -*- coding: utf-8 -*-
"""[1] 입력·정리·구조화 엔트리: inbox 스캔 → 처리 → manifest → 이동.
PDF는 opendataloader-pdf로 배치 사전추출(+스캔본 OCR 폴백) 후 per-file 분류/아카이빙."""
import os
from pathlib import Path
from collections import defaultdict
from . import config as C, store

PDF_TEXT_LOG = None   # 배치 실행 시 성공률 리포트용(text_extraction_report.py에서 사용)


def _chunk_no_collision(paths: list, chunk_size: int) -> list:
    """basename 충돌(다른 폴더, 같은 파일명) 회피: 충돌분은 별도 1건짜리 청크로 분리.
    실측(2026-07-07): 2016+ 대상 PDF 1,805건 중 6건만 충돌 — 드문 케이스라 단순 처리로 충분."""
    chunks, cur, seen = [], [], set()
    for p in paths:
        name = os.path.basename(p)
        if name in seen or len(cur) >= chunk_size:
            if cur:
                chunks.append(cur)
            cur, seen = [], set()
        cur.append(p); seen.add(name)
    if cur:
        chunks.append(cur)
    return chunks


def _ocr_cache_path(p: str) -> Path:
    import hashlib
    h = hashlib.md5(open(p, "rb").read()).hexdigest()
    d = C.GEO_DATA / "_ocr_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.txt"


def _ocr_with_cache(p: str, ocr_pdf_text) -> str:
    """OCR은 비용이 커서 크래시/재실행 시 잃으면 안 됨 — 파일해시 키로 디스크 캐시."""
    cache = _ocr_cache_path(p)
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="ignore")
    text = ocr_pdf_text(p)
    try:
        cache.write_text(text or "", encoding="utf-8")
    except Exception:
        pass
    return text


def precompute_pdf_texts(pdf_files: list, chunk_size: int = 150) -> dict:
    """PDF 목록 → {path(str): text}. 순서: opendataloader 배치 → (텍스트 부족 시) OCR(디스크
    캐시) → (그래도 실패 시) 기존 pypdf. 반환 dict의 값은 항상 str(빈 문자열 가능, 완전 실패 시)."""
    from .extractors import (opendataloader_batch_convert, ocr_pdf_text,
                              pdf_text, OCR_MIN_CHARS)
    paths = [str(p) for p in pdf_files]
    result = {}
    method = {}   # 성공률 리포트용: path -> "opendataloader"|"ocr"|"pypdf_fallback"|"failed"
    odl_out_root = str(C.GEO_DATA / "_odl_tmp")
    chunks = _chunk_no_collision(paths, chunk_size)
    print(f"[ingest] PDF {len(paths)}건 → opendataloader 배치 {len(chunks)}청크")
    for ci, chunk in enumerate(chunks):
        out_dir = os.path.join(odl_out_root, f"chunk{ci:04d}")
        try:
            converted = opendataloader_batch_convert(chunk, out_dir)
        except Exception as e:
            print(f"  [warn] chunk{ci} opendataloader 실패: {e}")
            converted = {p: None for p in chunk}
        need_fallback = [p for p in chunk
                         if not (converted.get(p) and len(converted[p].strip()) >= OCR_MIN_CHARS)]
        if len(chunk) >= 20 and len(need_fallback) > len(chunk) * 0.2:
            print(f"  [warn] chunk{ci}: {len(need_fallback)}/{len(chunk)}건 opendataloader "
                  f"실패/부족(pypdf·OCR 폴백 예정) — 비정상적으로 높은 비율. 계속 진행.")
        for p in chunk:
            text = converted.get(p)
            if text and len(text.strip()) >= OCR_MIN_CHARS:
                result[p] = text; method[p] = "opendataloader"
                continue
            # opendataloader 실패/텍스트 부족 → 먼저 pypdf 시도(거의 무료). 실측(2026-07-07):
            # opendataloader가 내부 버그("Parallel page processing failed")로 죽는 디지털 PDF도
            # 있어, 이런 경우 굳이 느린 OCR을 돌릴 필요 없이 pypdf로 바로 해결됨. OCR은 pypdf도
            # 실패하는 진짜 스캔본에만 최후 수단으로 적용.
            try:
                data = open(p, "rb").read()
                py_text = pdf_text(data)
            except Exception:
                py_text = ""
            if py_text and len(py_text.strip()) >= OCR_MIN_CHARS:
                result[p] = py_text; method[p] = "pypdf_fallback"
                continue
            # pypdf도 부족 → 스캔본 의심 → OCR 폴백(디스크 캐시로 크래시 대비)
            try:
                ocr_text = _ocr_with_cache(p, ocr_pdf_text)
            except Exception as e:
                ocr_text = ""
                print(f"  [warn] OCR 실패 {os.path.basename(p)}: {e}")
            if ocr_text and len(ocr_text.strip()) >= OCR_MIN_CHARS:
                result[p] = ocr_text; method[p] = "ocr"
            else:
                result[p] = text or py_text or ocr_text or ""
                method[p] = "failed" if not result[p].strip() else "partial"
        n_done = min((ci + 1) * chunk_size, len(paths))
        print(f"  ... {n_done}/{len(paths)}건 (이번 청크 폴백대상 {len(need_fallback)}건)")
    global PDF_TEXT_LOG
    PDF_TEXT_LOG = method
    return result


def run():
    C.ensure_dirs()
    from .archive import process_file
    known = store.known_hashes()
    files = [p for p in C.INBOX.rglob("*") if p.is_file()]
    pdf_files = [p for p in files if p.suffix.lower() == ".pdf"]
    pdf_set = set(pdf_files)
    other_files = [p for p in files if p.suffix.lower() != ".pdf"]
    print(f"[ingest] inbox {len(files)}건 처리 시작 (기존 {len(known)}건, pdf {len(pdf_files)} / 기타 {len(other_files)})")

    precomputed = precompute_pdf_texts(pdf_files) if pdf_files else {}

    n, cnt = 0, {"archived": 0, "failed": 0, "unclassified": 0, "duplicate": 0}
    for p in files:
        pre = precomputed.get(str(p)) if p in pdf_set else None
        try:
            rec = process_file(p, known, precomputed=pre)
        except Exception as e:
            print(f"  [error] {p.name}: {e}"); continue
        known.add(rec["file_hash"])
        store.upsert_manifest([rec])
        n += 1
        cnt[rec.get("status", "archived")] = cnt.get(rec.get("status", "archived"), 0) + 1
        if n % 50 == 0: print(f"  ... {n}건")
    print(f"[ingest] 완료: {cnt}")

    # 텍스트 추출 방법론별 성공률 리포트(삭제하지 않고 store에 영속화)
    if PDF_TEXT_LOG:
        from collections import Counter
        method_cnt = Counter(PDF_TEXT_LOG.values())
        print(f"[ingest] PDF 텍스트추출 방법 분포: {dict(method_cnt)}")
        try:
            import pandas as pd
            rows = [{"path": k, "method": v} for k, v in PDF_TEXT_LOG.items()]
            df = pd.DataFrame(rows)
            df.to_parquet(C.STORE / "pdf_extract_method.parquet", index=False)
        except Exception as e:
            print(f"  [warn] pdf_extract_method 저장 실패: {e}")
    return cnt


if __name__ == "__main__":
    run()
