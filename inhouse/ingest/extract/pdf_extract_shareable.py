# -*- coding: utf-8 -*-
"""외부공개 가능 PDF -> 마크다운 ETL (RAG 코퍼스 편입용).

opendataloader-pdf(Java CLI, Apache 2.0, 오프라인 동작)로 1차 변환하고, 텍스트가
부족하면(스캔형 PDF) pypdf → OCR(easyocr) 순으로 폴백한다 — 이 3단계 체인은 새로
만든 게 아니라 `inhouse/geo/extractors.py`의 `extract_with_fallback()`을 그대로
재사용한다(2026-07-07 geo 파이프라인에서 이미 검증된 로직 — DRY, 재발명 금지).
결과는 data_lake/semi_structure/pdf_extract/shareable/<label>/ 아래 저장하면,
ingest.py의 load_documents()가 documents/산출물과 함께 자동으로 읽어들인다.

**여기서 다루는 소스는 발주처가 "외부공개 가능"이라 명시한 것만.** 진단모델 전용
(RAG 금지) 자료는 이 파일이 아니라 같은 디렉토리의 pdf_extract_restricted.py가
별도 물리 경로(pdf_extract/restricted_diagnosis_only/)로 처리한다 — 이 파일은 그
경로를 참조하지 않는다(두 파일이 한 패키지에 있어도 출력 트리는 계속 분리).

2026-08-27 rag/ragkit/pdf_extract.py → inhouse/ingest/extract/pdf_extract_shareable.py로
이동(ETL 전용이라 서빙 패키지에서 분리, ingest/README.md).

실행: cd inhouse && python -m ingest.extract.pdf_extract_shareable
"""
import hashlib
import sys
import tempfile
import zipfile
from pathlib import Path

import opendataloader_pdf

REPO_ROOT = Path(__file__).resolve().parents[3]  # ingest/extract/x.py → inhouse/ingest → inhouse → komir
if str(REPO_ROOT / "inhouse") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "inhouse"))
from geo.extractors import extract_with_fallback  # noqa: E402
from ingest import status as ingest_status  # noqa: E402
from rag.ragkit.ingest import _real_content_len  # noqa: E402

SHAREABLE_ROOT = REPO_ROOT / "inhouse/data_lake/semi_structure/pdf_extract/shareable"
OCR_CACHE_DIR = str(SHAREABLE_ROOT / "_ocr_cache")

SOURCES = [
    {"zip": REPO_ROOT / "documents/0807/3. 해외투자실무가이드(4개국).zip",
     "label": "komis_해외투자가이드_4개국"},
]


def _iter_pdfs(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            yield info.filename, z.read(info)


def main():
    with ingest_status.pipeline_run("extract.pdf_extract_shareable") as run:
        status_con = ingest_status.pg_connect_safe()
        n_ok = n_skip = 0
        try:
            for src in SOURCES:
                if not src["zip"].exists():
                    print(f"[skip] {src['zip']} 없음")
                    n_skip += 1
                    continue
                out_dir = SHAREABLE_ROOT / src["label"]
                out_dir.mkdir(parents=True, exist_ok=True)
                for name, data in _iter_pdfs(src["zip"]):
                    md_path = out_dir / (Path(name).stem + ".md")
                    h = hashlib.md5(data).hexdigest()[:10]
                    fid = hashlib.md5(data).hexdigest()[:16]
                    with tempfile.TemporaryDirectory() as td:
                        tmp_pdf = Path(td) / name
                        tmp_pdf.write_bytes(data)
                        print(f"  변환 중: {name} ({len(data)/1e6:.0f}MB, hash={h})", flush=True)
                        opendataloader_pdf.convert(
                            input_path=[str(tmp_pdf)], output_dir=str(out_dir),
                            format=["markdown", "json"], quiet=True,
                        )
                        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
                        # geo.extractors.md_to_text()는 <br> 태그를 안 걷어내 "빈 표 뼈대만
                        # 있는" 스캔 PDF를 실제 텍스트로 오판정할 수 있다(2026-08-10 실측:
                        # CANADA/CHINA/Mongolia 전부 opendataloader "충분함" 오판정으로 폴백을
                        # 건너뜀). geo의 공유 코드는 안 건드리고, 여기서 더 엄격한
                        # _real_content_len()으로 먼저 판정해 부족하면 빈 문자열을 넘겨
                        # extract_with_fallback이 무조건 pypdf/OCR로 넘어가게 강제한다.
                        effective_md = md_text if _real_content_len(md_text) >= 300 else ""
                        text, method = extract_with_fallback(str(tmp_pdf), data, effective_md, OCR_CACHE_DIR)
                        if method != "opendataloader":
                            # OCR/pypdf 폴백이 이겼으면 md 파일 자체를 평문으로 교체
                            # (ingest.py는 .md 파일만 읽으므로, 폴백 결과를 여기 반영해야 RAG에 들어감)
                            md_path.write_text(text, encoding="utf-8")
                    print(f"    -> {md_path.name} ({len(text)}자, method={method})")
                    rel = str(md_path.relative_to(REPO_ROOT)) if md_path.is_relative_to(REPO_ROOT) else str(md_path)
                    n_ok += 1
                    ingest_status.upsert_source_file(
                        fid, file_name=md_path.name, file_ext="md", source_path=rel,
                        source_group=src["label"], con=status_con,
                    )
                    ingest_status.upsert_file_stage_status(
                        fid, "extract", "success", n_chars=len(text), con=status_con,
                    )
        finally:
            ingest_status.commit_close_safe(status_con)
        run.metrics.update({"processed": n_ok, "skipped_groups": n_skip})
        print("완료")


if __name__ == "__main__":
    main()
