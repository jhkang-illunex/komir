# -*- coding: utf-8 -*-
"""[1] 아카이브 이동(트랜잭션): 추출·기록 성공 후에만 이동. 실패/불명은 상태폴더."""
import hashlib, shutil
from pathlib import Path
from . import config as C, classify, date_resolve
from .extractors import extract_text
from .schema import ManifestRecord


def _rec(**kw) -> dict:
    """모든 반환 경로가 ManifestRecord 계약을 통과 — 컬럼 균일·ingested_at 기록·검증."""
    return ManifestRecord(**kw).model_dump()


def _safe_dest(dest_dir: Path, name: str, h: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.exists():
        stem, dot, ext = name.rpartition(".")
        dest = dest_dir / (f"{stem}__{h[:8]}.{ext}" if dot else f"{name}__{h[:8]}")
    return dest


def process_file(path: Path, known: set, precomputed: str = None) -> dict:
    """단일 파일 처리. 반환: manifest 레코드 dict(ManifestRecord 스키마).
    precomputed: ingest.py의 배치 PDF 사전추출(opendataloader/OCR) 결과 텍스트. None이면
    기존 방식(extract_text)으로 폴백 — hwp/xlsx/txt는 항상 이 경로를 탄다."""
    data = path.read_bytes()
    h = hashlib.md5(data).hexdigest()
    if h in known:                                   # 중복 재투척
        dest = _safe_dest(C.DUPLICATES, path.name, h)
        shutil.move(str(path), str(dest))
        return _rec(file_hash=h, orig_name=path.name, status="duplicate",
                    doc_id=h[:16], archive_path=str(dest), source="")
    # (2) 추출
    if precomputed is not None:
        fmt, text = "pdf", precomputed
    else:
        try:
            fmt, text = extract_text(str(path), data)
        except Exception as e:
            dest = _safe_dest(C.FAILED, path.name, h)
            shutil.move(str(path), str(dest))
            return _rec(file_hash=h, orig_name=path.name, status="failed",
                        doc_id=h[:16], archive_path=str(dest), source="",
                        error_msg=str(e)[:200])
    if not (text or "").strip():                     # 스캔/이미지 PDF 등 — 무증상 블랙홀 방지
        dest = _safe_dest(C.FAILED, path.name, h)
        shutil.move(str(path), str(dest))
        return _rec(file_hash=h, orig_name=path.name, status="empty",
                    doc_id=h[:16], archive_path=str(dest), source="",
                    fmt=fmt, error_msg="추출 텍스트 0자(스캔본/이미지 의심 — OCR 필요)")
    # (3) 분류
    source = classify.source_of(str(path))
    category = classify.category_of(str(path), text)
    pub, pub_method = date_resolve.resolve_date(str(path), path.name, text, source)
    commodity = classify.commodity_of(str(path), text)
    if source == "ETC" and pub is None:              # 판별 불가
        dest = _safe_dest(C.UNCLASSIFIED, path.name, h)
        shutil.move(str(path), str(dest))
        return _rec(file_hash=h, orig_name=path.name, status="unclassified",
                    doc_id=h[:16], archive_path=str(dest), source=source,
                    category=category, pub_date=pub, pub_date_method=pub_method,
                    commodity_hint=commodity, fmt=fmt, n_chars=len(text))
    # (5) 목적지 & 이동
    y = (pub or "0000-00")[:4]; m = (pub or "0000-00-00")[5:7] or "00"
    dest = _safe_dest(C.ARCHIVE / source / category / y / m, path.name, h)
    # 추출 텍스트도 아카이브 옆에 .txt 로 (에이전트 읽기용)
    dest.with_suffix(dest.suffix + ".txt").write_text(text, encoding="utf-8")
    shutil.move(str(path), str(dest))
    return _rec(file_hash=h, orig_name=path.name, status="archived",
                doc_id=h[:16], archive_path=str(dest), source=source,
                category=category, pub_date=pub, pub_date_method=pub_method,
                commodity_hint=commodity, fmt=fmt, n_chars=len(text))
