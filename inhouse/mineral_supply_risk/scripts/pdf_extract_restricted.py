# -*- coding: utf-8 -*-
"""비축월보/시장동향보고서(0807 발주처 제공, 진단모델 개발 전용) PDF -> 마크다운 ETL.

opendataloader-pdf(Java CLI, Apache 2.0, 오프라인 동작)로 표/텍스트를 마크다운으로
추출한다. 기존 ingest_reports.py의 pypdf.extract_text()는 표 구조를 보존하지 못해
(가격표·수입량표 등 숫자 데이터가 뭉개짐) 이 자료엔 부적합 — 실측 비교(2026-08-10
스모크테스트, NEW비축월보(1월호).pdf)로 opendataloader-pdf가 표를 실제 마크다운
표로 복원함을 확인(예: 니켈 연평균/월평균 가격표, 국가별 수입량표).

시장동향보고서 Vol.XX류(차트 위주 디자인 보고서)는 본문이 전부 래스터 이미지라
opendataloader 기본 모드에서 실제 텍스트가 거의 안 나옴 — pypdf→OCR(easyocr) 순
폴백으로 이어진다. 이 3단계 체인은 새로 만든 게 아니라 `inhouse/geo/extractors.py`의
`extract_with_fallback()`을 그대로 재사용(2026-07-07 geo 파이프라인에서 이미
검증된 로직, DRY). 초기 버전(2026-08-10 오전)은 raw markdown 길이(">200자")만으로
품질을 판정해 "이미지 태그·빈 표만 있어도 analyzed로 오판정"하는 버그가 있었음
(해외투자가이드 4개국 검증 중 발견) — 이 버전은 `md_to_text()`로 마크다운 잡음을
걷어낸 실제 글자 수(OCR_MIN_CHARS=50)로 판정해 수정됨.

**사용 제한(발주처 명시, documents/0807/메일내용_0807.txt)**: 이 산출물은 수급위기
진단지수 모델개발에만 사용 가능. RAG 코퍼스·대시보드·외부공개 절대 금지 — 그래서
출력 경로를 RAG가 읽는 트리(data_lake/semi_structure/pdf_extract/shareable/)와
물리적으로 분리했다(pdf_extract/restricted_diagnosis_only/). rag 쪽 코드는 이
경로를 참조하지 않는다(inhouse/rag/ragkit/ingest.py, inhouse/rag/ragkit/pdf_extract.py
어디에도 restricted_diagnosis_only 문자열이 없어야 함).

이 스크립트는 ETL(변환+저장+매니페스트)까지만 한다. 마크다운 텍스트를 진단모델
피처로 바꾸는 작업은 별도 모델링 사이클에서 CLAUDE.md §4 원칙대로
r10_retune_harness.py SERIES_SPEC 스크리닝을 거쳐야 한다(여기서 임의 채택 금지).

실행: cd inhouse/mineral_supply_risk && python -m scripts.pdf_extract_restricted
"""
import hashlib
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pandas as pd
import opendataloader_pdf
from msr.config import ROOT as MSR_ROOT

REPO_ROOT = MSR_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT / "inhouse"))
from geo.extractors import extract_with_fallback, md_to_text  # noqa: E402

SOURCES = [
    {"zip": REPO_ROOT / "documents/0807/2. 비축월보_시장동향보고서.zip",
     "label": "비축월보_시장동향보고서_0807"},
]
OUT_ROOT = MSR_ROOT.parent / "data_lake/semi_structure/pdf_extract/restricted_diagnosis_only"
MANIFEST = OUT_ROOT / "_manifest.parquet"
OCR_CACHE_DIR = str(OUT_ROOT / "_ocr_cache")

META_TEXT = """# 사용 제한 -- 진단모델 개발 전용 (RAG/대시보드/외부공개 절대 금지)

이 디렉토리(및 하위 전체)는 발주처(광해광업공단/KOMIS)가 2026-08-07 메일로 명시한
사용 제한이 적용된다: **수급위기 진단지수 모델개발에만 활용 가능.**

원본: `documents/0807/2. 비축월보_시장동향보고서.zip`(비축팀 자료)
근거: `documents/0807/메일내용_0807.txt` 2번 항목
반영계획: `documents/산출물/2026-W33_0810-0816/발주처_0807_제공자료_반영계획_260810.md`

RAG 코퍼스 확장 작업(inhouse/rag/ragkit/ingest.py 등) 시 이 경로를 절대 소스
루트에 추가하지 말 것.
"""

_DATE_RE = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월")


def _year_month(md_text: str) -> str:
    m = _DATE_RE.search(md_text[:3000])
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


def _iter_pdfs(zip_path: Path):
    """비축월보 zip은 cp949로 압축돼 Python zipfile 기본(cp437) 디코딩이 깨짐."""
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            try:
                name = info.filename.encode("cp437").decode("cp949")
            except UnicodeError:
                name = info.filename
            if not name.lower().endswith(".pdf"):
                continue
            yield name, z.read(info)


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT_ROOT / "META.md"
    if not meta_path.exists():
        meta_path.write_text(META_TEXT, encoding="utf-8")

    prev = pd.read_parquet(MANIFEST) if MANIFEST.exists() else None
    done_hash = set(prev["file_hash"]) if prev is not None else set()
    rows = []
    for src in SOURCES:
        if not src["zip"].exists():
            print(f"[skip] {src['zip']} 없음")
            continue
        label = src["label"]
        out_dir = OUT_ROOT / label
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, data in _iter_pdfs(src["zip"]):
            h = hashlib.md5(data).hexdigest()
            if h in done_hash:
                continue
            done_hash.add(h)
            with tempfile.TemporaryDirectory() as td:
                # 파일명 앞에 해시를 붙여 동명이인(zip 안에 같은 이름 다른 내용) 충돌 방지
                tmp_pdf = Path(td) / f"{h[:10]}_{name}"
                tmp_pdf.write_bytes(data)
                text, method, err = "", "error", ""
                try:
                    opendataloader_pdf.convert(
                        input_path=[str(tmp_pdf)], output_dir=str(out_dir),
                        format=["markdown", "json"], quiet=True,
                    )
                    md_path = out_dir / (tmp_pdf.stem + ".md")
                    md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
                    text, method = extract_with_fallback(str(tmp_pdf), data, md_text, OCR_CACHE_DIR)
                    if method != "opendataloader":
                        md_path.write_text(text, encoding="utf-8")  # 폴백 승리 시 산출물도 교체
                except Exception as e:
                    err = str(e)[:200]
            real_chars = len(md_to_text(text).strip())
            status = "analyzed" if real_chars >= 50 else "hold_low_text"
            rows.append(dict(
                doc_id=h[:16], file_hash=h, file_name=name, source=label,
                year_month=_year_month(text), n_chars=real_chars,
                status=status, method=method, error_msg=err,
            ))
            if len(rows) % 10 == 0:
                print(f"  +{len(rows)}건 처리", flush=True)

    if rows:
        df = (pd.concat([prev, pd.DataFrame(rows)], ignore_index=True)
              if prev is not None else pd.DataFrame(rows))
        df.to_parquet(MANIFEST, index=False)
        print(f"완료: 신규 {len(rows)}건, 누적 {len(df)}건")
        print("status:", df["status"].value_counts().to_dict())
    else:
        print("신규 없음(이미 전부 처리됨)")


if __name__ == "__main__":
    main()
