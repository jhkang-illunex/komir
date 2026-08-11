# -*- coding: utf-8 -*-
"""승인된 문서 소스에 대한 추출 파이프라인.

출처: komis-report-generator-main(외부 repo, 2026-08-11 확인)의
document_ingestion/pipeline.py를 이식(해시 기반 중복제거·재사용(unchanged)·원자적
쓰기·매니페스트 관리 로직은 그대로 — 병합계획 결정②). 원본 대비 바뀐 점 2가지:

1. `discover_source_files`에서 원본 repo 고유의 "보고서_1/<소스그룹>" 강제 하위
   경로(REPORT_ROOT_NAME)를 제거 — komir의 실제 문서 루트(documents/산출물/,
   documents/0807/ 등)는 그런 레이아웃이 아니므로 `data_root` 바로 아래에서
   `source_groups`를 찾도록 일반화했다. source_groups 기본값(KOMIS 정기간행물
   5종)도 komir엔 안 맞아 제거 — 호출자가 명시.
2. PDF 배치 사전변환(_preload_pdf_batch) 추가 — opendataloader-pdf는 "호출마다
   JVM이 뜨므로 파일 하나씩 부르면 느림"(inhouse/geo/extractors.py 주석, 2026-07-07
   실측: 배치 없이 돌리면 CPU 212분 낭비 사례 있음). 원본 파이프라인은 파일을
   1건씩 순회하며 parser.parse()를 부르는 구조라 이 배치 요구사항과 충돌 —
   실제 파싱이 필요한(재사용 불가) PDF만 골라 루프 진입 전에 한 번에
   opendataloader에 태우는 사전 패스를 추가해 해결했다(파서 자체나 원본 루프
   구조는 그대로 둠, CLAUDE.md §4 "최소·외과적 변경").

실행 예: python -m services.ingestion.pipeline 대신, 서비스 코드에서 run_extraction()을
직접 호출하는 라이브러리 모듈로 쓴다(§5-3 in-house ingestion 설계 참고).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from .models import DocumentRecord, ExtractionManifest, ManifestEntry
from .parsers import DEFAULT_PARSERS, DocumentParser, ParseResult
from .source_policy import is_excluded_paid_source

SUPPORTED_EXTENSIONS = (".hwp", ".pdf")


class ExtractionConfigurationError(ValueError):
    """추출 경로·파서·매니페스트가 안전하지 않거나 잘못됐을 때 발생."""

    pass


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    """추출 실행이 만든 경로·집계."""

    manifest_path: Path
    documents_jsonl_path: Path
    source_file_count: int
    unique_document_count: int
    action_counts: dict[str, int]
    status_counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "manifest_path": str(self.manifest_path),
            "documents_jsonl_path": str(self.documents_jsonl_path),
            "source_file_count": self.source_file_count,
            "unique_document_count": self.unique_document_count,
            "action_counts": self.action_counts,
            "status_counts": self.status_counts,
        }


@dataclass(frozen=True, slots=True)
class _CanonicalDocument:
    document_id: str
    status: str
    error: str | None


def discover_source_files(
    data_root: Path,
    *,
    source_groups: tuple[str, ...],
) -> list[Path]:
    """승인된 PDF/HWP 소스를 찾는다(경로 정책 강제 포함)."""

    data_root = data_root.expanduser().resolve()
    group_roots: list[Path] = []
    missing: list[str] = []
    for group in source_groups:
        _validate_source_group(group)
        group_root = (data_root / group).resolve()
        if not group_root.is_relative_to(data_root):
            raise ExtractionConfigurationError(f"source group escapes data root: {group!r}")
        if not group_root.is_dir():
            missing.append(group)
        else:
            group_roots.append(group_root)
    if missing:
        names = ", ".join(missing)
        raise ExtractionConfigurationError(f"required source directories are missing: {names}")

    paths: list[Path] = []
    for group_root in group_roots:
        for path in group_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(group_root):
                raise ExtractionConfigurationError(f"source file escapes its source group: {path}")
            relative_path = path.relative_to(data_root).as_posix()
            if is_excluded_paid_source(relative_path):
                raise ExtractionConfigurationError(
                    f"excluded paid source was found under an approved group: {relative_path}"
                )
            paths.append(path)
    if not paths:
        raise ExtractionConfigurationError("no supported PDF/HWP source files were found")
    return sorted(paths, key=lambda path: path.relative_to(data_root).as_posix())


def _validate_source_group(group: str) -> None:
    raw = group.strip()
    candidate = Path(raw)
    if (
        not raw
        or raw in {".", ".."}
        or candidate.is_absolute()
        or "/" in raw
        or "\\" in raw
        or len(candidate.parts) != 1
    ):
        raise ExtractionConfigurationError(f"unsafe source group: {group!r}")
    if is_excluded_paid_source(raw):
        raise ExtractionConfigurationError("excluded paid source group was requested")


def run_extraction(
    data_root: Path,
    output_dir: Path,
    *,
    source_groups: tuple[str, ...],
    parsers: Mapping[str, DocumentParser] | None = None,
    force: bool = False,
    progress: Callable[[int, int, Path], None] | None = None,
) -> ExtractionSummary:
    """승인된 문서를 추출하고 산출물·매니페스트를 원자적으로 갱신한다."""

    data_root = data_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    parser_registry = dict(parsers or DEFAULT_PARSERS)
    source_paths = discover_source_files(data_root, source_groups=source_groups)
    _validate_parser_registry(parser_registry)

    previous_manifest = _load_previous_manifest(output_dir / "manifest.json")
    previous_entries = (
        {entry.source_relative_path: entry for entry in previous_manifest.entries}
        if previous_manifest
        else {}
    )
    document_dir = output_dir / "documents"
    text_dir = output_dir / "texts"
    document_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    _preload_pdf_batch(
        source_paths,
        data_root=data_root,
        parser_registry=parser_registry,
        previous_entries=previous_entries,
        output_dir=output_dir,
        force=force,
    )

    entries: list[ManifestEntry] = []
    canonical_by_hash: dict[str, _CanonicalDocument] = {}

    total = len(source_paths)
    for index, source_path in enumerate(source_paths, start=1):
        if progress:
            progress(index, total, source_path)
        relative_path = source_path.relative_to(data_root).as_posix()
        content_hash = _sha256(source_path)
        own_document_id = _document_id(relative_path)
        parser = parser_registry[source_path.suffix.lower()]

        if content_hash in canonical_by_hash:
            canonical = canonical_by_hash[content_hash]
            entries.append(
                ManifestEntry(
                    source_relative_path=relative_path,
                    content_sha256=content_hash,
                    document_id=own_document_id,
                    status=canonical.status,
                    action="duplicate",
                    parser_signature=parser.signature,
                    duplicate_of=canonical.document_id,
                    error=canonical.error,
                )
            )
            continue

        document_output = Path("documents") / f"{own_document_id}.json"
        text_output = Path("texts") / f"{own_document_id}.txt"
        previous_entry = previous_entries.get(relative_path)
        record = None
        action = "processed"
        if not force and _can_reuse(
            previous_entry,
            content_hash=content_hash,
            parser_signature=parser.signature,
            output_dir=output_dir,
        ):
            record = _load_document_record(output_dir / document_output)
            if record is not None:
                action = "unchanged"

        if record is None:
            parse_result = parser.parse(source_path)
            source_group = source_path.relative_to(data_root).parts[0]
            record = _build_document_record(
                source_path=source_path,
                relative_path=relative_path,
                source_group=source_group,
                document_id=own_document_id,
                content_hash=content_hash,
                parser=parser,
                result=parse_result,
            )
            _atomic_write_json(output_dir / document_output, record.model_dump(mode="json"))
            if record.status == "extracted":
                _atomic_write_text(output_dir / text_output, _render_text_artifact(record))
            else:
                (output_dir / text_output).unlink(missing_ok=True)

        canonical_by_hash[content_hash] = _CanonicalDocument(
            document_id=record.document_id,
            status=record.status,
            error=record.error,
        )
        entries.append(
            ManifestEntry(
                source_relative_path=relative_path,
                content_sha256=content_hash,
                document_id=record.document_id,
                status=record.status,
                action=action,  # type: ignore[arg-type]
                parser_signature=parser.signature,
                document_output=document_output.as_posix(),
                text_output=text_output.as_posix() if record.status == "extracted" else None,
                error=record.error,
            )
        )

    entries.sort(key=lambda entry: entry.source_relative_path)
    _remove_stale_generated_files(output_dir, previous_manifest, entries)
    documents_jsonl_path = output_dir / "documents.jsonl"
    _write_documents_jsonl(documents_jsonl_path, output_dir, entries)

    action_counts = dict(sorted(Counter(entry.action for entry in entries).items()))
    status_counts = dict(sorted(Counter(entry.status for entry in entries).items()))
    manifest = ExtractionManifest(
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_root=str(data_root),
        source_groups=list(source_groups),
        supported_extensions=list(SUPPORTED_EXTENSIONS),
        source_file_count=len(source_paths),
        unique_document_count=len(canonical_by_hash),
        action_counts=action_counts,
        status_counts=status_counts,
        entries=entries,
    )
    manifest_path = output_dir / "manifest.json"
    _atomic_write_json(manifest_path, manifest.model_dump(mode="json"))
    return ExtractionSummary(
        manifest_path=manifest_path,
        documents_jsonl_path=documents_jsonl_path,
        source_file_count=len(source_paths),
        unique_document_count=len(canonical_by_hash),
        action_counts=action_counts,
        status_counts=status_counts,
    )


def _preload_pdf_batch(
    source_paths: list[Path],
    *,
    data_root: Path,
    parser_registry: Mapping[str, DocumentParser],
    previous_entries: Mapping[str, ManifestEntry],
    output_dir: Path,
    force: bool,
) -> None:
    """실제 파싱이 필요한 PDF만 골라 opendataloader-pdf를 배치 1회로 사전변환한다.

    parser_registry[".pdf"]가 preload_batch를 지원하지 않으면(다른 PdfParser 구현
    등) 조용히 건너뛴다 — 본 루프는 어차피 개별 parse() 폴백으로 정상 동작한다.
    """

    pdf_parser = parser_registry.get(".pdf")
    preload = getattr(pdf_parser, "preload_batch", None)
    if preload is None:
        return

    need_parse: list[str] = []
    for source_path in source_paths:
        if source_path.suffix.lower() != ".pdf":
            continue
        if not force:
            relative_path = source_path.relative_to(data_root).as_posix()
            content_hash = _sha256(source_path)
            previous_entry = previous_entries.get(relative_path)
            if _can_reuse(
                previous_entry,
                content_hash=content_hash,
                parser_signature=getattr(pdf_parser, "signature", ""),
                output_dir=output_dir,
            ):
                continue
        need_parse.append(str(source_path))

    if need_parse:
        preload(need_parse)


def _validate_parser_registry(parsers: Mapping[str, DocumentParser]) -> None:
    missing = [extension for extension in SUPPORTED_EXTENSIONS if extension not in parsers]
    if missing:
        raise ExtractionConfigurationError(f"parser is missing for: {', '.join(missing)}")


def _build_document_record(
    *,
    source_path: Path,
    relative_path: str,
    source_group: str,
    document_id: str,
    content_hash: str,
    parser: DocumentParser,
    result: ParseResult,
) -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id,
        content_sha256=content_hash,
        title=source_path.stem,
        source_group=source_group,
        source_relative_path=relative_path,
        extension=source_path.suffix.lower(),
        file_size=source_path.stat().st_size,
        parser_name=parser.name,
        parser_version=parser.parser_version,
        parser_signature=parser.signature,
        status=result.status,
        unit_count=len(result.units),
        table_count=sum(len(unit.tables) for unit in result.units),
        text=result.text,
        units=result.units,
        warnings=result.warnings,
        error=result.error,
    )


def _can_reuse(
    entry: ManifestEntry | None,
    *,
    content_hash: str,
    parser_signature: str,
    output_dir: Path,
) -> bool:
    if entry is None or entry.action == "duplicate" or entry.document_output is None:
        return False
    if entry.content_sha256 != content_hash or entry.parser_signature != parser_signature:
        return False
    document_path = output_dir / entry.document_output
    if not document_path.is_file():
        return False
    if entry.status == "extracted":
        return entry.text_output is not None and (output_dir / entry.text_output).is_file()
    return True


def _load_previous_manifest(path: Path) -> ExtractionManifest | None:
    """이전 매니페스트가 있으면 읽고 검증한다."""

    if not path.exists():
        return None
    try:
        return ExtractionManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ExtractionConfigurationError(f"invalid existing manifest: {path}: {exc}") from exc


def _load_document_record(path: Path) -> DocumentRecord | None:
    """재사용 가능한 문서 레코드를 읽는다 — 무효면 None."""

    try:
        return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def _remove_stale_generated_files(
    output_dir: Path,
    previous_manifest: ExtractionManifest | None,
    current_entries: list[ManifestEntry],
) -> None:
    """매니페스트가 더는 참조하지 않는 생성 산출물을 삭제한다."""

    if previous_manifest is None:
        return
    active = {
        value
        for entry in current_entries
        for value in (entry.document_output, entry.text_output)
        if value
    }
    for entry in previous_manifest.entries:
        for relative_output in (entry.document_output, entry.text_output):
            if relative_output and relative_output not in active:
                _safe_generated_path(output_dir, relative_output).unlink(missing_ok=True)


def _safe_generated_path(output_dir: Path, relative_output: str) -> Path:
    relative_path = Path(relative_output)
    if relative_path.is_absolute() or relative_path.parts[:1] not in {("documents",), ("texts",)}:
        raise ExtractionConfigurationError(f"unsafe generated artifact path: {relative_output}")
    resolved = (output_dir / relative_path).resolve()
    if output_dir.resolve() not in resolved.parents:
        raise ExtractionConfigurationError(f"unsafe generated artifact path: {relative_output}")
    return resolved


def _render_text_artifact(record: DocumentRecord) -> str:
    parts = [
        f"제목: {record.title}",
        f"출처: {record.source_relative_path}",
        f"문서 ID: {record.document_id}",
    ]
    for unit in record.units:
        parts.append(f"\n[{unit.locator_type} {unit.locator}]")
        if unit.text:
            parts.append(unit.text)
        for table in unit.tables:
            parts.append(f"\n[table {table.index}]")
            parts.append(table.text)
    return normalize_output_text("\n".join(parts))


def normalize_output_text(value: str) -> str:
    """산출 텍스트가 개행 하나로 끝나도록 보장한다."""

    return value.rstrip() + "\n"


def _document_id(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    return f"doc_{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:24]}"


def _sha256(path: Path) -> str:
    """원천 파일을 스트리밍하며 SHA-256 다이제스트를 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: object) -> None:
    """JSON을 원자적 텍스트 쓰기로 직렬화한다."""

    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _write_documents_jsonl(
    path: Path,
    output_dir: Path,
    entries: list[ManifestEntry],
) -> None:
    """고유 문서 레코드의 JSONL 스트림을 원자적으로 재생성한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as destination:
            for entry in entries:
                if entry.document_output is None:
                    continue
                document_path = _safe_generated_path(output_dir, entry.document_output)
                value = json.loads(document_path.read_text(encoding="utf-8"))
                destination.write(json.dumps(value, ensure_ascii=False))
                destination.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_text(path: Path, value: str) -> None:
    """텍스트 산출물을 원자적으로 교체하고 임시파일을 정리한다."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
