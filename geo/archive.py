# -*- coding: utf-8 -*-
"""[1] 아카이브 이동(트랜잭션): 추출·기록 성공 후에만 이동. 실패/불명은 상태폴더."""
import hashlib, shutil
from pathlib import Path
from . import config as C, classify
from .extractors import extract_text


def _safe_dest(dest_dir: Path, name: str, h: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if dest.exists():
        stem, dot, ext = name.rpartition(".")
        dest = dest_dir / (f"{stem}__{h[:8]}.{ext}" if dot else f"{name}__{h[:8]}")
    return dest


def process_file(path: Path, known: set) -> dict:
    """단일 파일 처리. 반환: manifest 레코드 dict (또는 상태만)."""
    data = path.read_bytes()
    h = hashlib.md5(data).hexdigest()
    if h in known:                                   # 중복 재투척
        _safe_dest(C.DUPLICATES, path.name, h)
        shutil.move(str(path), str(_safe_dest(C.DUPLICATES, path.name, h)))
        return {"file_hash": h, "orig_name": path.name, "status": "duplicate",
                "doc_id": h[:16], "archive_path": "", "source": "", "n_chars": 0}
    # (2) 추출
    try:
        fmt, text = extract_text(str(path), data)
    except Exception as e:
        shutil.move(str(path), str(_safe_dest(C.FAILED, path.name, h)))
        return {"file_hash": h, "orig_name": path.name, "status": "failed",
                "doc_id": h[:16], "archive_path": str(C.FAILED / path.name),
                "source": "", "fmt": "", "n_chars": 0, "error_msg": str(e)[:200]}
    # (3) 분류
    source = classify.source_of(str(path))
    category = classify.category_of(str(path), text)
    pub = classify.date_of(path.name)
    commodity = classify.commodity_of(str(path), text)
    if source == "ETC" and pub is None:              # 판별 불가
        shutil.move(str(path), str(_safe_dest(C.UNCLASSIFIED, path.name, h)))
        return {"file_hash": h, "orig_name": path.name, "status": "unclassified",
                "doc_id": h[:16], "archive_path": str(C.UNCLASSIFIED / path.name),
                "source": source, "category": category, "pub_date": pub,
                "commodity_hint": commodity, "fmt": fmt, "n_chars": len(text)}
    # (5) 목적지 & 이동
    y = (pub or "0000-00")[:4]; m = (pub or "0000-00-00")[5:7] or "00"
    dest = _safe_dest(C.ARCHIVE / source / category / y / m, path.name, h)
    # 추출 텍스트도 아카이브 옆에 .txt 로 (에이전트 읽기용)
    dest.with_suffix(dest.suffix + ".txt").write_text(text, encoding="utf-8")
    shutil.move(str(path), str(dest))
    return {"file_hash": h, "orig_name": path.name, "status": "archived",
            "doc_id": h[:16], "archive_path": str(dest), "source": source,
            "category": category, "pub_date": pub, "commodity_hint": commodity,
            "fmt": fmt, "n_chars": len(text)}
