# -*- coding: utf-8 -*-
"""문서-OKF 생성기 — 원문 전체+구조를 보존하는 신규 OKF 계열을 만든다.

`documents/meta/CONTAINER_ARCHITECTURE.md` §5-3의 "두 갈래로 기록" 중 ②번
(문서-OKF)의 구현. geo-OKF(`data_lake/semi_structure/okf/`)와 **같은 컨벤션**
(개념ID=파일경로, YAML 프론트매터)을 따르되, 내용이 "원문 포인터"가 아니라
"본문 전체"라는 점만 다르다. 산출물은 별도 계열인
`data_lake/semi_structure/okf_documents/`로 나간다(geo-OKF를 오염시키지 않음).

이 문서-OKF가 §5-4의 두 검색 도구(② Qdrant 청킹, ③ PageIndex 트리)의 공통
소스가 된다.

**왜 ingest/ 패키지에 두는가**: §5-3이 문서-OKF를 in-house ingestion(공용
LLM ETL 엔진)의 산출물로 정의하고, 대용량 원본(PDF/HWP) 경로가 이미 여기
`ingest.pipeline.run_extraction()`이라 입력 두 갈래 중 하나가 이 패키지 안에 있다.
(rag/ragkit/ 쪽은 "RAG 인덱스 전용" 경로라 Report 생성기도 쓰는 산출물의
생산자로는 맞지 않다.) 2026-08-27 services/ingestion/ → inhouse/ingest/okf/로
이동(파일 기반 문서 ETL을 서빙 레이어에서 떼어 독립 패키지화, ingest/README.md).

입력 두 갈래:
  1. `rag.ragkit.ingest.load_documents()` — documents/산출물(md·docx) + 외부공개
     PDF ETL 산출물. 이미 텍스트로 펼쳐져 있으므로 재파싱하지 않는다.
  2. `ingest.pipeline.run_extraction()` — 대용량 PDF 원본
     (현재는 USGS 8건). opendataloader-pdf→pypdf→OCR 폴백 체인으로 마크다운
     (표 포함) 추출.

실행:
    cd inhouse
    python -m ingest.okf.build_okf_documents --what all
    python -m ingest.okf.build_okf_documents --what artifacts   # 산출물만
    python -m ingest.okf.build_okf_documents --what usgs        # USGS만
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _INHOUSE_ROOT.parent
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest import status as ingest_status  # noqa: E402

# geo/extractors.py는 import 시점에 PDF_MAXPAGES(기본 40)를 읽어 opendataloader
# 변환 범위를 `1-40`으로 고정한다 — GKG 뉴스 PDF(수 페이지)엔 맞지만 연간 보고서엔
# 치명적이다(실측 2026-08-11: USGS_2026은 226쪽인데 40쪽까지만 추출돼 본문 82%가
# 잘려 있었다). 문서-OKF는 "원문 전체 보존"이 목적이므로 여기서 상향한다.
# OCR_MAXPAGES는 별도로 묶어 둔다 — 스캔본이 걸리면 CPU OCR이 페이지당 2~4초라
# 500쪽이면 문서 1건에 30분 가까이 잡아먹는다(폴백 경로 폭주 방지).
os.environ.setdefault("PDF_MAXPAGES", "500")
os.environ.setdefault("OCR_MAXPAGES", "60")

OKF_DOCUMENTS_ROOT = _INHOUSE_ROOT / "data_lake/semi_structure/okf_documents"
OKF_VERSION = "0.1"

#: 대용량 PDF 원본 갈래. USGS는 2026-08-11, 조달청보고서·Argus는 2026-08-12
#: 사용자 승인으로 추가.
USGS_SOURCE_GROUP = "3. 생산매장량(USGS)"
USGS_OUT_DIRNAME = "생산매장량_USGS"
USGS_EXTRACT_DIR = _INHOUSE_ROOT / "data_lake/semi_structure/pdf_extract/usgs"

JODALCHEONG_SOURCE_GROUP = "조달청보고서"
JODALCHEONG_OUT_DIRNAME = "조달청보고서"
JODALCHEONG_EXTRACT_DIR = _INHOUSE_ROOT / "data_lake/semi_structure/pdf_extract/jodalcheong"

# Argus는 documents/보고서_2/ 아래 있어(USGS·조달청과 달리 documents/ 바로 밑이
# 아님) data_root 자체를 한 단 더 내려서 잡는다. **유료 구독 원문**이라
# source_policy.py가 기본적으로 차단한다(Argus Media 라이선스, 재색인·파생DB화
# 금지가 일반적) — 2026-08-12 사용자가 "라이선스상 내부 파생 DB 구축 허용"을
# 직접 확인하고 이번 내부 전용 인덱스 구축에 한해 우회를 명시적으로 지시했다.
# `allow_paid_sources=True`는 이 갈래에서만 켠다 — source_policy.py 자체나
# 다른 호출자(특히 공개 RAG 코퍼스 rag/ragkit/ingest.py)는 그대로 차단 유지.
ARGUS_DATA_ROOT = _REPO_ROOT / "documents/보고서_2"
ARGUS_SOURCE_GROUP = "Argus Metal_비철금속_2023~2026_일일 (1)"
ARGUS_OUT_DIRNAME = "Argus_비철금속_일일"
ARGUS_EXTRACT_DIR = _INHOUSE_ROOT / "data_lake/semi_structure/pdf_extract/argus"

_SAFE_NAME_RE = re.compile(r"[^\w가-힣.\-]+", re.UNICODE)


def _safe_name(value: str, *, maxlen: int = 120) -> str:
    """파일/디렉토리명으로 쓸 수 있게 정규화(한글은 보존)."""

    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = _SAFE_NAME_RE.sub("_", normalized).strip("._")
    return (normalized or "untitled")[:maxlen]


def _rel_to_repo(path: str | Path) -> str:
    """어떤 cwd에서 실행돼도 저장소 루트 기준 상대경로를 돌려준다.

    (`ingest.load_documents()`의 `source_path`는 `os.path.relpath(full, ".")`라
    cwd 의존적이다 — 여기서 절대경로로 되돌린 뒤 저장소 기준으로 다시 잡는다.)
    """

    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _classify(rel_path: str, fallback_week: str) -> tuple[str, tuple[str, ...]]:
    """저장소 기준 상대경로 → (source_group, 출력 하위 디렉토리 경로).

    `ingest.DocRecord.week`를 쓰지 않고 경로에서 직접 뽑는다 — `week`는
    `os.path.relpath(full, ".").split(os.sep)[2]`라 cwd에 따라 값이 달라진다
    (cwd=inhouse/면 산출물 72건이 전부 week='산출물'로 뭉개짐; 오늘 실측 확인).
    """

    parts = Path(rel_path).parts
    if len(parts) >= 3 and parts[0] == "documents" and parts[1] == "산출물":
        week = parts[2] if len(parts) > 3 else ""
        if week:
            return f"산출물/{week}", ("산출물", _safe_name(week))
        return "산출물", ("산출물",)
    if "pdf_extract" in parts and "shareable" in parts:
        idx = parts.index("shareable")
        label = parts[idx + 1] if len(parts) > idx + 1 else "기타"
        return f"외부자료/{label}", ("외부자료", _safe_name(label))
    # 알 수 없는 레이아웃 — DocRecord.week를 최후 폴백으로.
    group = fallback_week or "기타"
    return group, tuple(_safe_name(p) for p in group.split(":") if p) or ("기타",)


def _body_starts_with_heading(text: str) -> bool:
    for line in text.splitlines():
        if line.strip():
            return line.lstrip().startswith("#")
    return False


def render_okf(
    *,
    title: str,
    description: str,
    resource: str,
    doc_id: str,
    source_group: str,
    fmt: str,
    body: str,
    tags: list[str],
    extra: dict | None = None,
) -> str:
    """문서-OKF 마크다운 1건을 렌더링(YAML 프론트매터 + 원문 본문).

    본문이 이미 헤딩으로 시작하면 `# <제목>`을 덧붙이지 않는다 — 중복 헤딩은
    PageIndex 트리에 빈 루트 노드를 하나 더 만들 뿐이라 구조를 흐린다.
    """

    body = body.strip("\n")
    if not _body_starts_with_heading(body):
        body = f"# {title}\n\n{body}"

    front = {
        "type": "document",
        "title": title,
        "description": description,
        "resource": resource,
        "doc_id": doc_id,
        "source_group": source_group,
        "fmt": fmt,
        "n_chars": len(body),
        "okf_version": OKF_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tags": tags,
    }
    for key, value in (extra or {}).items():
        if value not in (None, ""):
            front[key] = value

    # 한글 제목·콜론·따옴표가 섞여도 깨지지 않게 항상 safe_dump로 직렬화.
    header = yaml.safe_dump(front, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{header}---\n\n{body}\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _unique_path(base: Path, used: set[Path]) -> Path:
    """같은 파일명이 다른 원본에서 나온 경우 접미사로 분리."""

    if base not in used:
        used.add(base)
        return base
    for i in range(2, 100):
        candidate = base.with_name(f"{base.stem}__{i}{base.suffix}")
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise RuntimeError(f"파일명 충돌 해소 실패: {base}")


# ────────────────────────────── 갈래 1: documents/산출물 ──────────────────────────────


def build_from_artifacts(out_root: Path = OKF_DOCUMENTS_ROOT, limit: int | None = None) -> list[Path]:
    """`rag.ragkit.ingest.load_documents()` 결과를 문서-OKF로 렌더링."""

    from rag.ragkit.ingest import load_documents

    docs = load_documents()
    if limit:
        docs = docs[:limit]
    used: set[Path] = set()
    written: list[Path] = []
    status_con = ingest_status.pg_connect_safe()
    try:
        for rec in docs:
            rel = _rel_to_repo(rec.source_path)
            source_group, subdirs = _classify(rel, rec.week)
            description = f"{source_group} · {rec.series_key}" if rec.series_key else source_group
            text = render_okf(
                title=rec.title,
                description=description,
                resource=rel,
                doc_id=rec.doc_id,
                source_group=source_group,
                fmt=rec.ext,
                body=rec.raw_text,
                tags=["document-source", "산출물" if source_group.startswith("산출물") else "외부자료"],
                extra={"series_key": rec.series_key, "doc_date": rec.doc_date},
            )
            stem = _safe_name(Path(rel).stem)
            path = _unique_path(out_root.joinpath(*subdirs) / f"{stem}.md", used)
            _write(path, text)
            written.append(path)
            ingest_status.upsert_source_file(
                rec.doc_id, file_name=Path(rec.source_path).name, file_ext=rec.ext,
                source_path=rel, source_group=source_group,
                doc_date=ingest_status.parse_yymmdd_date(rec.doc_date), con=status_con,
            )
            ingest_status.upsert_file_stage_status(
                rec.doc_id, "okf", "success", n_chars=len(text), con=status_con,
            )
    finally:
        ingest_status.commit_close_safe(status_con)
    return written


# ────────────────────────── 갈래 2: 대용량 PDF(USGS·조달청보고서·Argus) ──────────────────────────


def _extract_pdf_group(
    *,
    data_root: Path,
    source_group: str,
    extract_dir: Path,
    force: bool = False,
    allow_paid_sources: bool = False,
) -> Path:
    """대용량 PDF 원본 그룹 1개를 기존 ingestion 파이프라인으로 추출(documents.jsonl 반환).

    USGS·조달청보고서·Argus가 전부 같은 경로(ingest.pipeline.run_extraction)를
    탄다 — 그룹별 위치·정책만 다르다."""

    from ingest.pipeline import run_extraction

    def _progress(index: int, total: int, path: Path) -> None:
        print(f"  [{index}/{total}] {path.name}", flush=True)

    summary = run_extraction(
        data_root,
        extract_dir,
        source_groups=(source_group,),
        force=force,
        progress=_progress,
        allow_paid_sources=allow_paid_sources,
    )
    print(f"  추출 요약: {summary.as_dict()}", flush=True)
    return summary.documents_jsonl_path


def _build_from_pdf_group(
    *,
    jsonl_path: Path,
    data_root: Path,
    out_root: Path,
    out_dirname: str,
    description_suffix: str,
    tags: list[str],
) -> list[Path]:
    """추출된 documents.jsonl → 문서-OKF 마크다운(그룹 공통 렌더링 로직).

    2026-08-12 버그수정: `rel`을 `f"documents/{record['source_relative_path']}"`로
    하드코딩했었는데, `source_relative_path`는 `run_extraction()`에 넘긴
    `data_root` 기준 상대경로다 — USGS·조달청은 data_root가 `documents/`라 우연히
    맞았지만, Argus는 `documents/보고서_2/`라 "보고서_2/" 세그먼트가 통째로
    빠진 존재하지 않는 경로가 저장됐다(실측 확인: Argus 690건 전부).
    `data_root`를 받아 저장소 루트 기준으로 다시 계산해 모든 갈래에서 맞게 한다."""

    import json

    used: set[Path] = set()
    written: list[Path] = []
    status_con = ingest_status.pg_connect_safe()
    try:
        with jsonl_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                fid = ingest_status.normalize_file_id(record["document_id"])
                rel = (data_root / record["source_relative_path"]).resolve().relative_to(_REPO_ROOT).as_posix()
                if record.get("status") != "extracted" or not (record.get("text") or "").strip():
                    print(f"  [skip] {record.get('source_relative_path')} — status={record.get('status')}")
                    ingest_status.upsert_source_file(
                        fid, file_name=Path(rel).name, file_ext=record.get("extension", "").lstrip("."),
                        source_path=rel, source_group=out_dirname, con=status_con,
                    )
                    ingest_status.upsert_file_stage_status(
                        fid, "extract",
                        "failed" if record.get("status") == "parse_failed" else "skipped",
                        error_message=f"extract status={record.get('status')}", con=status_con,
                    )
                    continue
                text = render_okf(
                    title=record["title"],
                    description=f"{out_dirname} · {description_suffix}",
                    resource=rel,
                    doc_id=record["document_id"],
                    source_group=out_dirname,
                    fmt=record["extension"].lstrip("."),
                    body=record["text"],
                    tags=tags,
                    extra={
                        "content_sha256": record.get("content_sha256"),
                        "parser": record.get("parser_name"),
                        "table_count": record.get("table_count"),
                    },
                )
                stem = _safe_name(Path(rel).stem)
                path = _unique_path(out_root / out_dirname / f"{stem}.md", used)
                _write(path, text)
                written.append(path)
                ingest_status.upsert_source_file(
                    fid, file_name=Path(rel).name, file_ext=record["extension"].lstrip("."),
                    source_path=rel, source_group=out_dirname, con=status_con,
                )
                ingest_status.upsert_file_stage_status(fid, "extract", "success", con=status_con)
                ingest_status.upsert_file_stage_status(
                    fid, "okf", "success", n_chars=len(record["text"]), con=status_con,
                )
    finally:
        ingest_status.commit_close_safe(status_con)
    return written


def build_from_usgs(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False) -> list[Path]:
    """USGS PDF 8건 → 문서-OKF."""

    data_root = _REPO_ROOT / "documents"
    jsonl_path = _extract_pdf_group(
        data_root=data_root,
        source_group=USGS_SOURCE_GROUP,
        extract_dir=USGS_EXTRACT_DIR,
        force=force,
    )
    return _build_from_pdf_group(
        jsonl_path=jsonl_path,
        data_root=data_root,
        out_root=out_root,
        out_dirname=USGS_OUT_DIRNAME,
        description_suffix="USGS Mineral Commodity Summaries",
        tags=["document-source", "USGS", "생산매장량"],
    )


def build_from_jodalcheong(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False) -> list[Path]:
    """조달청보고서(비철금속 시장동향 등) 887건 → 문서-OKF."""

    data_root = _REPO_ROOT / "documents"
    jsonl_path = _extract_pdf_group(
        data_root=data_root,
        source_group=JODALCHEONG_SOURCE_GROUP,
        extract_dir=JODALCHEONG_EXTRACT_DIR,
        force=force,
    )
    return _build_from_pdf_group(
        jsonl_path=jsonl_path,
        data_root=data_root,
        out_root=out_root,
        out_dirname=JODALCHEONG_OUT_DIRNAME,
        description_suffix="조달청 비철금속 시장동향·전망 보고서",
        tags=["document-source", "조달청보고서"],
    )


def build_from_argus(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False) -> list[Path]:
    """Argus 비철금속 일일 시황 690건 → 문서-OKF.

    ⚠ 유료 구독 원문 — allow_paid_sources=True로 source_policy.py 차단을
    이 호출에서만 우회한다(2026-08-12 사용자가 라이선스상 내부 파생 DB 구축
    허용을 확인하고 명시적으로 지시, 모듈 상단 ARGUS_* 주석 참고)."""

    jsonl_path = _extract_pdf_group(
        data_root=ARGUS_DATA_ROOT,
        source_group=ARGUS_SOURCE_GROUP,
        extract_dir=ARGUS_EXTRACT_DIR,
        force=force,
        allow_paid_sources=True,
    )
    return _build_from_pdf_group(
        jsonl_path=jsonl_path,
        data_root=ARGUS_DATA_ROOT,
        out_root=out_root,
        out_dirname=ARGUS_OUT_DIRNAME,
        description_suffix="Argus Non-Ferrous Markets(비철금속 일일 시황, 유료구독 원문 — 내부 전용)",
        tags=["document-source", "Argus", "유료구독-내부전용"],
    )


_WHAT_CHOICES = ("artifacts", "usgs", "jodalcheong", "argus", "all")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="문서-OKF 생성기")
    parser.add_argument("--what", choices=_WHAT_CHOICES, default="all")
    parser.add_argument("--out", default=str(OKF_DOCUMENTS_ROOT))
    parser.add_argument("--limit", type=int, default=None, help="artifacts 갈래만: 앞 N건")
    parser.add_argument("--force", action="store_true", help="PDF 갈래: 캐시 무시 재추출")
    args = parser.parse_args(argv)

    with ingest_status.pipeline_run("okf.build_okf_documents", args=vars(args)) as run:
        out_root = Path(args.out).expanduser().resolve()
        total = 0
        if args.what in ("artifacts", "all"):
            print("documents/산출물 → 문서-OKF", flush=True)
            written = build_from_artifacts(out_root, limit=args.limit)
            print(f"  {len(written)}건 생성 → {out_root}", flush=True)
            total += len(written)
            run.metrics["artifacts"] = len(written)
        if args.what in ("usgs", "all"):
            print(f"{USGS_SOURCE_GROUP} → 문서-OKF", flush=True)
            written = build_from_usgs(out_root, force=args.force)
            print(f"  {len(written)}건 생성 → {out_root / USGS_OUT_DIRNAME}", flush=True)
            total += len(written)
            run.metrics["usgs"] = len(written)
        if args.what in ("jodalcheong", "all"):
            print(f"{JODALCHEONG_SOURCE_GROUP} → 문서-OKF", flush=True)
            written = build_from_jodalcheong(out_root, force=args.force)
            print(f"  {len(written)}건 생성 → {out_root / JODALCHEONG_OUT_DIRNAME}", flush=True)
            total += len(written)
            run.metrics["jodalcheong"] = len(written)
        if args.what in ("argus", "all"):
            print(f"{ARGUS_SOURCE_GROUP}(유료구독, 내부전용) → 문서-OKF", flush=True)
            written = build_from_argus(out_root, force=args.force)
            print(f"  {len(written)}건 생성 → {out_root / ARGUS_OUT_DIRNAME}", flush=True)
            total += len(written)
            run.metrics["argus"] = len(written)
        run.metrics["total"] = total
        print(f"완료: 문서-OKF {total}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
