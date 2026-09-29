# -*- coding: utf-8 -*-
"""PageIndex 문서에서 재사용할 파생 사실 sidecar 생성기.

원문 OKF와 ``*.tree.json``을 덮어쓰지 않고 같은 PageIndex 디렉터리에
``*.facts.json``을 만든다. 첫 버전은 문서에서 반복적으로 요구되는 두 사실,
광종 목록과 문서 요약을 결정적으로 추출한다. 각 사실에는 원문 줄 범위와
본문 SHA-256을 남겨 다음 ingest 실행에서 원문 변경을 감지하고 재생성한다.

실행 예::

    cd inhouse
    python -m ingest.pageindex.build_derived_facts
    python -m ingest.pageindex.build_derived_facts --pattern 희소금속 --force

LLM을 호출하지 않는 ingest 단계이므로 air-gapped 환경에서도 재현 가능하다.
향후 위험도·주요 주장 같은 추출기를 추가할 때도 ``facts`` 배열에 같은
``source_span`` 계약으로 확장한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest.pageindex.build_pageindex_trees import split_frontmatter  # noqa: E402
from ingest.paths import get_paths  # noqa: E402


OKF_DOCUMENTS_ROOT = get_paths().okf_documents
PAGEINDEX_TREES_ROOT = get_paths().pageindex_trees
EXTRACTOR_VERSION = "document_facts_v1"
MONTHLY_SOURCE_GROUPS = frozenset({"희소금속 월간동향", "전략광종 월간동향"})

# 긴 이름을 먼저 검사한다. ``동``은 ``동향``·``동향에``의 일부로 잡히지
# 않도록 별도 경계 정규식을 쓴다.
_MINERAL_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("희토류", ("희토류", "희로류", "Rare Earth")),
    ("네오디뮴", ("네오디뮴", "네오디움", "Neodymium")),
    ("철광석", ("철광석", "Iron Ore")),
    ("유연탄", ("유연탄", "Coal")),
    ("알루미늄", ("알루미늄", "Aluminium", "Aluminum")),
    ("몰리브덴", ("몰리브덴", "올리브데", "Molybdenum")),
    ("안티모니", ("안티모니", "Antimony")),
    ("마그네슘", ("마그네슘", "마그네숨", "Magnesium")),
    ("티타늄", ("티타늄", "Titanium")),
    ("텅스텐", ("텅스텐", "텅스템", "Tungsten")),
    ("니오븀", ("니오븀", "나오움", "Niobium")),
    ("셀레늄", ("셀레늄", "실레늄", "Selenium")),
    ("갈륨", ("갈륨", "갈룹", "Gallium", "Galliur")),
    ("크롬", ("크롬", "크름", "Chromium", "Chromiur")),
    ("인듐", ("인듐", "인문", "Indium")),
    ("우라늄", ("우라늄", "Uranium")),
    ("망간", ("망간", "Manganese")),
    ("코발트", ("코발트", "Cobalt")),
    ("리튬", ("리튬", "리듬", "리툼", "Lithium")),
    ("니켈", ("니켈", "Nickel")),
    ("아연", ("아연", "Zinc")),
    ("흑연", ("흑연", "Graphite")),
    ("구리", ("구리", "Copper")),
    ("동", ("동",)),
)
_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})[-._/](0?[1-9]|1[0-2])(?!\d)")
_KOREAN_MONTH_RE = re.compile(r"(?<!\d)(20\d{2})년\s*(0?[1-9]|1[0-2])월")


def _body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _month_label(front: dict[str, Any], okf_path: Path) -> str | None:
    for value in (front.get("document_date"), okf_path.name, str(front.get("title", ""))):
        match = _MONTH_RE.search(str(value or "")) or _KOREAN_MONTH_RE.search(str(value or ""))
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    return None


def _term_pattern(term: str) -> re.Pattern[str]:
    aliases = next(aliases for canonical, aliases in _MINERAL_ALIASES if canonical == term)
    patterns = []
    for alias in aliases:
        if alias == "동":
            patterns.append(r"(?<![가-힣])동(?!향|[가-힣])")
        else:
            patterns.append(re.escape(alias))
    return re.compile("(?:" + "|".join(patterns) + ")", re.IGNORECASE)


def _extract_minerals(front: dict[str, Any], body: str) -> tuple[list[str], dict[str, int]]:
    """목차/초반 절에서 광종을 추출하고 대표 source span을 반환한다."""

    lines = body.splitlines()
    # 월간 보고서는 표보다 앞의 목차에 광종 전체가 있다. 목차가 없는 OCR
    # 문서도 있으므로 앞 220행을 fallback 범위로 사용한다.
    # OCR 문서는 목차가 ``월간 가격 동향`` 표지 다음 줄에 이어지는 경우가
    # 있어 그 표지에서 자르면 유연탄·우라늄 같은 앞부분 광종을 놓친다. 첫
    # 220행은 목차와 가격표의 초반부뿐이므로 이 범위 전체를 검사한다.
    toc_lines = lines[:220]
    positions: list[tuple[int, int, str, int]] = []
    for term, _aliases in _MINERAL_ALIASES:
        pattern = _term_pattern(term)
        hit = next(((i, pattern.search(line)) for i, line in enumerate(toc_lines) if pattern.search(line)), None)
        if hit is not None and hit[1] is not None:
            positions.append((hit[0], hit[1].start(), term, hit[0] + 1))
    # frontmatter는 OCR 목차가 누락된 문서에서만 보완한다. 순서는 문서 본문
    # 위치를 우선하고, frontmatter에만 있는 값은 뒤에 붙인다.
    found = [term for _, _, term, _ in sorted(positions)]
    front_values = front.get("minerals") or []
    for value in front_values:
        label = str(value).strip()
        if label == "구리" and "동" in found:
            # 전략광종 문서의 본문 표기는 ``동``, OKF 메타는 ``구리``인
            # 경우가 있어 같은 광종을 두 번 표시하지 않는다.
            continue
        if label and label not in found:
            found.append(label)
    spans = {term: line for _, _, term, line in positions}
    if not found:
        # 마지막 안전망: 본문 전체에서 명시된 frontmatter만 사용한다.
        found = [str(value).strip() for value in front_values if str(value).strip()]
    return found, spans


def _summary(body: str) -> tuple[str, dict[str, int]]:
    """주요 이슈/개요 절의 앞부분을 재사용 가능한 짧은 요약으로 만든다."""

    lines = body.splitlines()
    anchors = ("시장주요이슈", "시장동향", "월간개요", "요약", "주요이슈", "광물종합지수")
    start = next((i for i, line in enumerate(lines)
                  if any(anchor in re.sub(r"\s+", "", line) for anchor in anchors)), None)
    if start is None:
        start = next((i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith("#")), 0)
    selected: list[str] = []
    end = start
    for index in range(start, len(lines)):
        raw = lines[index].strip()
        end = index + 1
        if not raw or raw.startswith("![") or raw.startswith("|"):
            if selected and len(selected) >= 3:
                break
            continue
        if raw.startswith("#"):
            if selected:
                break
            continue
        raw = re.sub(r"^[-*▷]+\s*", "", raw)
        raw = re.sub(r"\s+", " ", raw)
        if raw:
            if len(raw) > 500:
                selected.append(raw[:900])
                break
            selected.append(raw)
        if len(" ".join(selected)) >= 900 or len(selected) >= 5:
            break
    text = re.sub(r"\s+", " ", " ".join(selected)).strip()
    return text[:1200], {"line_start": start + 1, "line_end": max(start + 1, end)}


def extract_document_facts(okf_path: Path, *, okf_root: Path = OKF_DOCUMENTS_ROOT) -> dict[str, Any]:
    """OKF 1건에서 sidecar payload를 만든다. 파일에는 쓰지 않는다."""

    okf_path = okf_path.expanduser().resolve()
    okf_root = okf_root.expanduser().resolve()
    text = okf_path.read_text(encoding="utf-8")
    front, body, body_offset = split_frontmatter(text)
    minerals, mineral_lines = _extract_minerals(front, body)
    summary, summary_span = _summary(body)
    rel = okf_path.relative_to(okf_root).as_posix()
    month = _month_label(front, okf_path)
    facts: list[dict[str, Any]] = [{
        "fact_type": "mineral_list",
        "value": minerals,
        "source_span": {
            "line_start": min(mineral_lines.values()) if mineral_lines else body_offset + 1,
            "line_end": max(mineral_lines.values()) if mineral_lines else body_offset + 1,
            "line_number_is_body_relative": True,
        },
    }, {
        "fact_type": "summary",
        "value": summary,
        "source_span": {**summary_span, "line_number_is_body_relative": True},
    }]
    return {
        "schema_version": 1,
        "extractor_version": EXTRACTOR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "doc_id": str(front.get("doc_id", "")),
        "title": str(front.get("title", okf_path.stem)),
        "source_group": str(front.get("source_group", "")),
        "resource": str(front.get("resource", "")),
        "document_month": month,
        "okf_path": rel,
        "pageindex_path": Path(rel).with_suffix(".tree.json").as_posix(),
        "okf_body_sha256": _body_sha256(body),
        "body_line_offset": body_offset,
        "mineral_list": minerals,
        "summary": summary,
        "facts": facts,
    }


def _facts_path(okf_path: Path, *, okf_root: Path, trees_root: Path) -> Path:
    return trees_root / okf_path.relative_to(okf_root).with_suffix(".facts.json")


def _is_monthly(front: dict[str, Any], path: Path) -> bool:
    return str(front.get("source_group", "")) in MONTHLY_SOURCE_GROUPS or "월간동향" in path.as_posix()


def build_all(
    *, okf_root: Path = OKF_DOCUMENTS_ROOT, trees_root: Path = PAGEINDEX_TREES_ROOT,
    pattern: str | None = None, limit: int | None = None, force: bool = False,
    all_documents: bool = False,
) -> dict[str, int]:
    candidates: list[Path] = []
    for path in sorted(okf_root.rglob("*.md")):
        if pattern and pattern not in path.as_posix():
            continue
        try:
            front, _, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if all_documents or _is_monthly(front, path):
            candidates.append(path)
    if limit is not None:
        candidates = candidates[:limit]
    done = skipped = failed = stale = 0
    for okf_path in candidates:
        out_path = _facts_path(okf_path, okf_root=okf_root, trees_root=trees_root)
        if out_path.is_file() and not force:
            try:
                old = json.loads(out_path.read_text(encoding="utf-8"))
                current = extract_document_facts(okf_path, okf_root=okf_root)
                if old.get("okf_body_sha256") == current["okf_body_sha256"] and old.get("extractor_version") == EXTRACTOR_VERSION:
                    skipped += 1
                    continue
                stale += 1
            except (OSError, json.JSONDecodeError):
                stale += 1
        try:
            payload = extract_document_facts(okf_path, okf_root=okf_root)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out_path.parent,
                                             prefix=out_path.name + ".", suffix=".tmp", delete=False) as tmp:
                tmp.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                tmp_path = Path(tmp.name)
            os.replace(tmp_path, out_path)
            done += 1
        except Exception:
            failed += 1
    return {"candidate_count": len(candidates), "done": done, "skipped": skipped, "stale": stale, "failed": failed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OKF/PageIndex 파생 사실 sidecar 생성")
    parser.add_argument("--okf-root", default=str(OKF_DOCUMENTS_ROOT))
    parser.add_argument("--trees-root", default=str(PAGEINDEX_TREES_ROOT))
    parser.add_argument("--pattern", default=None, help="경로 부분문자열 필터")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--all-documents", action="store_true", help="월간동향 외 OKF도 처리")
    args = parser.parse_args(argv)
    result = build_all(
        okf_root=Path(args.okf_root).expanduser().resolve(),
        trees_root=Path(args.trees_root).expanduser().resolve(),
        pattern=args.pattern, limit=args.limit, force=args.force, all_documents=args.all_documents,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
