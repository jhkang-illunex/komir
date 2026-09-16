# -*- coding: utf-8 -*-
"""문서-OKF 생성기 — 원문 전체+구조를 보존하는 신규 OKF 계열을 만든다.

`documents/meta/CONTAINER_ARCHITECTURE.md` §5-3의 "두 갈래로 기록" 중 ②번
(문서-OKF)의 구현. geo-OKF(`data_lake/semi_structure/okf/`)와 **같은 컨벤션**
(개념ID=파일경로, YAML 프론트매터)을 따르되, 내용이 "원문 포인터"가 아니라
"본문 전체"라는 점만 다르다. 산출물은 data_lake의 `okf_documents/`로 나간다
(ingest/paths.py — INGEST_DATA_LAKE_DIR, 레거시 기본 data_lake/semi_structure/okf_documents).

이 문서-OKF가 §5-4의 두 검색 도구(② pgvector 청킹, ③ PageIndex 트리)의 공통
소스가 된다.

입력 두 갈래:
  1. `rag_core.ragkit.ingest.load_documents()` — landing/incoming(레거시 inhouse/incoming)의
     md·docx + 외부공개 PDF 정제본(processing/shareable). 이미 텍스트라 재파싱하지 않는다.
  2. `ingest.pipeline.run_extraction()` — 대용량 PDF·xlsx 원본 그룹. 그룹 목록·원본 위치·
     출력명·정책은 **`ingest/registry.py`** 한 곳(2026-09-16 이전엔 그룹마다 이 파일의 함수).
     opendataloader-pdf→pypdf→OCR 폴백 체인으로 마크다운(표 포함) 추출.

실행:
    cd inhouse
    python -m ingest.okf.build_okf_documents --what all         # artifacts + in_all 그룹(원본 없는 그룹은 건너뜀)
    python -m ingest.okf.build_okf_documents --what artifacts   # 산출물만
    python -m ingest.okf.build_okf_documents --what usgs        # 그룹 하나(registry 키)
    python -m ingest.okf.build_okf_documents --what mines --group-root /mnt/nas/학습데이터   # 원본 루트 덮어쓰기
"""
from __future__ import annotations

import argparse
import json
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

from common.logging_config import configure_logging  # noqa: E402

from ingest import status as ingest_status  # noqa: E402
from ingest.paths import get_paths  # noqa: E402
from ingest.registry import BY_KEY, GROUPS, PDF_GROUPS, SourceGroup, get_group  # noqa: E402

# geo/extractors.py는 import 시점에 PDF_MAXPAGES(기본 40)를 읽어 opendataloader
# 변환 범위를 `1-40`으로 고정한다 — GKG 뉴스 PDF(수 페이지)엔 맞지만 연간 보고서엔
# 치명적이다(실측 2026-08-11: USGS_2026은 226쪽인데 40쪽까지만 추출돼 본문 82%가
# 잘려 있었다). 문서-OKF는 "원문 전체 보존"이 목적이므로 여기서 상향한다.
# OCR_MAXPAGES는 별도로 묶어 둔다 — 스캔본이 걸리면 CPU OCR이 페이지당 2~4초라
# 500쪽이면 문서 1건에 30분 가까이 잡아먹는다(폴백 경로 폭주 방지).
os.environ.setdefault("PDF_MAXPAGES", "500")
os.environ.setdefault("OCR_MAXPAGES", "60")

OKF_DOCUMENTS_ROOT = get_paths().okf_documents
OKF_VERSION = "0.1"

_SAFE_NAME_RE = re.compile(r"[^\w가-힣.\-]+", re.UNICODE)


def _safe_name(value: str, *, maxlen: int = 120) -> str:
    """파일/디렉토리명으로 쓸 수 있게 정규화(한글은 보존)."""

    normalized = unicodedata.normalize("NFC", value).strip()
    normalized = _SAFE_NAME_RE.sub("_", normalized).strip("._")
    return (normalized or "untitled")[:maxlen]


def _rel_to_repo(path: str | Path) -> str:
    """어떤 cwd에서 실행돼도 저장소 루트 기준 상대경로를 돌려준다.

    (`ingest.load_documents()`의 `source_path`는 `os.path.relpath(full, ".")`라 cwd 의존적이다
    — 여기서 절대경로로 되돌린 뒤 저장소 기준으로 다시 잡는다.) 저장소 밖(landing 마운트)이면
    절대경로 그대로.
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
    (cwd=inhouse/면 산출물 72건이 전부 week='산출물'로 뭉개짐; 실측 확인).
    """

    parts = Path(rel_path).parts
    if len(parts) >= 3 and parts[0] == "documents" and parts[1] == "산출물":
        week = parts[2] if len(parts) > 3 else ""
        if week:
            return f"산출물/{week}", ("산출물", _safe_name(week))
        return "산출물", ("산출물",)
    if "shareable" in parts:
        idx = parts.index("shareable")
        label = parts[idx + 1] if len(parts) > idx + 1 else "기타"
        return f"외부자료/{label}", ("외부자료", _safe_name(label))
    if "incoming" in parts:
        return "산출물", ("산출물",)
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


# ────────────────────────────── 갈래 1: artifacts(md·docx + shareable 정제본) ──────────────────────────────


def build_from_artifacts(out_root: Path = OKF_DOCUMENTS_ROOT, limit: int | None = None) -> list[Path]:
    """`rag_core.ragkit.ingest.load_documents()` 결과를 문서-OKF로 렌더링."""

    from rag_core.ragkit.ingest import load_documents

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


# ────────────────────────── 갈래 2: 대용량 PDF·xlsx 그룹(registry.PDF_GROUPS) ──────────────────────────


def _extract_group(group: SourceGroup, root: Path, *, force: bool = False) -> Path:
    """그룹 1개를 추출 파이프라인(ingest.pipeline.run_extraction)에 태워 documents.jsonl 경로 반환.

    `run_extraction(data_root, source_groups=(name,))`는 data_root 바로 아래 폴더명을 그룹으로
    받으므로 root의 부모를 data_root, root.name을 그룹명으로 넘긴다."""

    from ingest.pipeline import run_extraction

    def _progress(index: int, total: int, path: Path) -> None:
        print(f"  [{index}/{total}] {path.name}", flush=True)

    summary = run_extraction(
        root.parent,
        group.extract_dir(),
        source_groups=(root.name,),
        force=force,
        progress=_progress,
        allow_paid_sources=group.allow_paid,
    )
    print(f"  추출 요약: {summary.as_dict()}", flush=True)
    return summary.documents_jsonl_path


def _resource_of(group: SourceGroup, root: Path, source_relative_path: str) -> str:
    """OKF `resource`(= doc_chunk.source_path). 저장소 안이면 저장소 기준 상대경로(레거시와 동일),
    저장소 밖(landing 마운트·NAS 심볼릭링크)이면 `<group.key>/<원본 상대경로>` — 마운트 위치와
    무관하게 안정적인 식별자. 원본 실체 경로는 프론트매터 `source_relative_path`+그룹 루트로 복원."""

    rel_in_group = Path(source_relative_path).relative_to(root.name).as_posix()
    candidate = root / rel_in_group
    try:
        return candidate.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        pass
    try:  # nas_document 심볼릭링크처럼 resolve 전 경로가 저장소 안이면 그 표기를 유지
        return Path(os.path.normpath(candidate)).relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return f"{group.key}/{rel_in_group}"


def _build_from_jsonl(group: SourceGroup, root: Path, jsonl_path: Path, out_root: Path) -> list[Path]:
    """추출된 documents.jsonl → 문서-OKF 마크다운(그룹 공통 렌더링)."""

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
                rel = _resource_of(group, root, record["source_relative_path"])
                rel_in_group = Path(record["source_relative_path"]).relative_to(root.name).as_posix()
                sub_parts = Path(rel_in_group).parts
                sub = _safe_name(sub_parts[0]) if group.subdir_from_path and len(sub_parts) > 1 else ""
                if record.get("status") != "extracted" or not (record.get("text") or "").strip():
                    print(f"  [skip] {record.get('source_relative_path')} — status={record.get('status')}")
                    ingest_status.upsert_source_file(
                        fid, file_name=Path(rel).name, file_ext=record.get("extension", "").lstrip("."),
                        source_path=rel, source_group=group.out_dirname, con=status_con,
                    )
                    ingest_status.upsert_file_stage_status(
                        fid, "extract",
                        "failed" if record.get("status") == "parse_failed" else "skipped",
                        error_message=f"extract status={record.get('status')}", con=status_con,
                    )
                    continue
                text = render_okf(
                    title=record["title"],
                    description=f"{group.out_dirname} · {group.description}" + (f" · {sub}" if sub else ""),
                    resource=rel,
                    doc_id=record["document_id"],
                    source_group=group.out_dirname,
                    fmt=record["extension"].lstrip("."),
                    body=record["text"],
                    tags=list(group.tags) + ([sub] if sub else []),
                    extra={
                        "content_sha256": record.get("content_sha256"),
                        "parser": record.get("parser_name"),
                        "table_count": record.get("table_count"),
                        "commodity_hint": sub or None,
                        "group_key": group.key,
                        "source_relative_path": rel_in_group,  # prune이 landing 존재 여부를 이걸로 판정
                    },
                )
                stem = _safe_name(Path(rel).stem)
                out_dir = out_root / group.out_dirname / sub if sub else out_root / group.out_dirname
                path = _unique_path(out_dir / f"{stem}.md", used)
                _write(path, text)
                written.append(path)
                ingest_status.upsert_source_file(
                    fid, file_name=Path(rel).name, file_ext=record["extension"].lstrip("."),
                    source_path=rel, source_group=group.out_dirname, commodity_hint=sub or None, con=status_con,
                )
                ingest_status.upsert_file_stage_status(fid, "extract", "success", con=status_con)
                ingest_status.upsert_file_stage_status(
                    fid, "okf", "success", n_chars=len(record["text"]), con=status_con,
                )
    finally:
        ingest_status.commit_close_safe(status_con)
    return written


def build_from_group(group: SourceGroup | str, out_root: Path = OKF_DOCUMENTS_ROOT, *,
                     force: bool = False, root: Path | None = None) -> list[Path] | None:
    """registry 그룹 1개 → 문서-OKF. 원본 루트가 없으면 None(경고 후 건너뜀 — 컨테이너 주간
    체인처럼 일부 그룹 원본이 마운트되지 않은 환경을 위해 예외로 멈추지 않는다)."""

    if isinstance(group, str):
        group = get_group(group)
    if group.kind != "pdf_group":
        raise ValueError(f"{group.key}는 PDF 그룹이 아님(kind={group.kind})")
    root = (root or group.landing_root())
    if root is None or not Path(root).is_dir():
        print(f"  [skip] {group.key}: 원본 루트 없음 — {root}", flush=True)
        return None
    root = Path(root)
    jsonl_path = _extract_group(group, root, force=force)
    return _build_from_jsonl(group, root, jsonl_path, out_root)


# 이전 이름(2026-09-16 이전 호출자 호환) — 본체는 registry 기반 build_from_group.
def build_from_usgs(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False) -> list[Path]:
    return build_from_group("usgs", out_root, force=force) or []


def build_from_jodalcheong(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False) -> list[Path]:
    return build_from_group("jodalcheong", out_root, force=force) or []


def build_from_argus(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False) -> list[Path]:
    return build_from_group("argus", out_root, force=force) or []


def build_from_mines(out_root: Path = OKF_DOCUMENTS_ROOT, force: bool = False,
                     data_root: Path | None = None) -> list[Path]:
    root = Path(data_root) / "학습데이터" if data_root else None
    return build_from_group("mines", out_root, force=force, root=root) or []


_WHAT_CHOICES = tuple(g.key for g in GROUPS) + ("all",)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="문서-OKF 생성기")
    parser.add_argument("--what", choices=_WHAT_CHOICES, default="all",
                        help="registry 그룹 키 또는 all(artifacts + in_all 그룹, 원본 없는 그룹은 건너뜀)")
    parser.add_argument("--out", default=str(OKF_DOCUMENTS_ROOT))
    parser.add_argument("--limit", type=int, default=None, help="artifacts 갈래만: 앞 N건")
    parser.add_argument("--force", action="store_true", help="PDF 갈래: 캐시 무시 재추출")
    parser.add_argument("--group-root", default=None,
                        help="--what <그룹> 하나일 때 원본 루트 덮어쓰기(기본: registry/landing 규칙)")
    args = parser.parse_args(argv)

    configure_logging()
    with ingest_status.pipeline_run("okf.build_okf_documents", args=vars(args)) as run:
        out_root = Path(args.out).expanduser().resolve()
        total = 0
        print(f"경로: {get_paths().as_dict()}", flush=True)
        if args.what in ("artifacts", "all"):
            print("artifacts(incoming md·docx + shareable) → 문서-OKF", flush=True)
            written = build_from_artifacts(out_root, limit=args.limit)
            print(f"  {len(written)}건 생성 → {out_root}", flush=True)
            total += len(written)
            run.metrics["artifacts"] = len(written)
        targets = [g for g in PDF_GROUPS if g.in_all] if args.what == "all" else \
            ([BY_KEY[args.what]] if args.what != "artifacts" else [])
        for g in targets:
            print(f"{g.key}({g.out_dirname}) → 문서-OKF", flush=True)
            root = Path(args.group_root).expanduser() if (args.group_root and args.what == g.key) else None
            written = build_from_group(g, out_root, force=args.force, root=root)
            if written is None:
                run.metrics[g.key] = "skipped(no root)"
                continue
            print(f"  {len(written)}건 생성 → {out_root / g.out_dirname}", flush=True)
            total += len(written)
            run.metrics[g.key] = len(written)
        run.metrics["total"] = total
        print(f"완료: 문서-OKF {total}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
