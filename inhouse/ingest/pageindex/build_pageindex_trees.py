# -*- coding: utf-8 -*-
"""문서-OKF → PageIndex 목차 트리(JSON) 생성기.

`documents/meta/CONTAINER_ARCHITECTURE.md` §5-4의 "③ PageIndex 조회"가 쓸
백킹 데이터를 만든다. 트리 생성 자체는 `services/shared/pageindex_client.
build_tree_from_markdown()`만 통해 호출한다(vendored `pageindex_lib` 직접 import
금지 — airgap 하드닝이 그 래퍼 안에만 있다, `pageindex_vendor/README.md`).

산출물: `data_lake/semi_structure/pageindex_trees/<okf와 동일한 상대경로>.tree.json`
  — 트리 JSON을 okf_documents/ 안에 섞지 않는다. 그 디렉토리는 Qdrant 청킹(§5-4 ②)이
    통째로 훑는 마크다운 전용 저장소라, JSON이 섞이면 청커가 걸러내야 할 예외가 생긴다.

**프론트매터는 트리 입력에서 제거한다**: `md_to_tree()`는 원시 마크다운을 헤딩
기준으로만 자르므로 YAML 프론트매터가 본문 앞에 남으면 첫 노드의 text에 메타데이터가
섞여 들어가 노드 요약(LLM)이 그걸 문서 내용으로 착각한다. 대신 몇 줄을 걷어냈는지
`body_line_offset`으로 남겨, 트리의 `line_num`을 OKF 파일 줄 번호로 되돌릴 수 있게 한다
(OKF 파일 줄번호 = line_num + body_line_offset).

실행(주의: `.env`의 LLM_BASE_URL이 컨테이너 기준 host.docker.internal이라 호스트
셸에서 돌릴 땐 환경변수로 덮어써야 한다 — 환경변수가 env_file보다 우선;
2026-08-27 services/ingestion/ → ingest/pageindex/ 이동):
    cd inhouse
    LLM_BASE_URL=http://localhost:52302/v1 \
      python3 -m ingest.pageindex.build_pageindex_trees --limit 10
    LLM_BASE_URL=http://localhost:52302/v1 \
      python3 -m ingest.pageindex.build_pageindex_trees --no-summary   # LLM 없이 구조만
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest import status as ingest_status  # noqa: E402
from common.logging_config import configure_logging  # noqa: E402

from ingest.paths import get_paths  # noqa: E402

# data_lake/{okf_documents,pageindex_trees} — INGEST_DATA_LAKE_DIR(.env), 미설정 시 레거시 위치.
OKF_DOCUMENTS_ROOT = get_paths().okf_documents
PAGEINDEX_TREES_ROOT = get_paths().pageindex_trees

logger = logging.getLogger(__name__)

# 트리가 실제로 참조하는 입력은 프론트매터를 제외한 본문이다. 프론트매터는
# ``--sync-metadata``로 안전하게 별도 동기화할 수 있으므로, 본문 checksum만으로
# 재생성 여부를 판정한다. OCR 재처리처럼 본문이 바뀐 경우에는 반드시 달라진다.
_OKF_BODY_SHA256_KEY = "okf_body_sha256"


def split_frontmatter(text: str) -> tuple[dict, str, int]:
    """OKF 마크다운 → (프론트매터 dict, 본문, 본문 시작 줄 offset).

    프론트매터가 없으면 ({}, 원문, 0). offset은 "본문 1행 앞에 몇 행이 있었는가".
    """

    if not text.startswith("---\n"):
        return {}, text, 0
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}, text, 0
    header = text[4:end + 1]
    rest = text[end + len("\n---\n"):]
    offset = text[: end + len("\n---\n")].count("\n")
    stripped = rest.lstrip("\n")
    offset += len(rest) - len(stripped)
    try:
        front = yaml.safe_load(header) or {}
    except yaml.YAMLError:
        front = {}
    return front, stripped, offset


def okf_body_sha256(okf_path: Path) -> str:
    """PageIndex 입력 본문의 SHA-256을 계산한다.

    기존 트리에는 이 필드가 없을 수 있다. 그 경우 freshness 판정은 거짓으로
    처리해 한 번 재생성하며, 조회부는 기존 JSON 구조를 그대로 읽을 수 있다.
    """

    _, body, _ = split_frontmatter(okf_path.read_text(encoding="utf-8"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def tree_is_fresh_for_okf(tree_path: Path, okf_path: Path) -> bool:
    """트리가 현재 OKF 본문으로 만들어졌는지 확인한다.

    손상된 JSON과 checksum 없는 이전 형식 트리는 stale로 보고 재생성한다.
    """

    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(tree, dict) or not isinstance(tree.get("structure"), list):
        return False
    return tree.get(_OKF_BODY_SHA256_KEY) == okf_body_sha256(okf_path)


_HEADING_RE = re.compile(r"^#{1,6}\s")
_BLANK_TITLE_HEADING_RE = re.compile(r"^#{1,6}\s*$")
_HEADING_MARKER_AND_TITLE_RE = re.compile(r"^(#{1,6})\s+(.+)$")
#: 통화·퍼센트·단위·구두점만으로 이뤄진 "제목"을 걷어내기 위한 토큰. 순서 중요
#: (긴 토큰 먼저) — 예: "US$1.19/lb"·"kt"·"bn"·"koz". 실측(2026-09-17, BHP
#: Escondida 보고서)에서 본 표기 전부 포함.
_NUMERIC_HEADING_UNIT_RE = re.compile(
    r"(?:US\$|A\$|C\$|NT\$|\$|%|kt|Mt|wmt|dmt|koz|Mlb|klb|lbs?|oz|bn|mm|ktpa|mtpa|/lb)",
    re.IGNORECASE,
)
_NUMERIC_HEADING_NUMBER_RE = re.compile(r"[\d,.\-–()/]+")


def _is_numeric_only_title(title: str) -> bool:
    """제목에서 통화·단위·숫자·구두점을 다 걷어내고도 알파벳 단어(3자 이상)가
    하나도 안 남으면 "숫자만 있는 제목"으로 판정한다."""

    residue = _NUMERIC_HEADING_UNIT_RE.sub(" ", title)
    residue = _NUMERIC_HEADING_NUMBER_RE.sub(" ", residue)
    return not any(len(word) >= 3 for word in residue.split())


def demote_numeric_only_headings(text: str) -> str:
    """제목 텍스트가 숫자·통화·퍼센트·단위 표기뿐인 헤딩(`#`)을 평문으로
    강등한다(헤딩 마커만 제거, 줄 수는 그대로 유지 — `fix_blank_heading_titles`
    와 같은 이유로 `body_line_offset`/`line_num`을 안 깨기 위함).

    실측 발견(2026-09-17, `mine_aggregate.py` 라이브 검증 — BHP Escondida
    연차보고서): PDF→마크다운 변환이 굵은 글씨로 강조된 큰 수치("1,305 kt 16%
    US$1.19/lb 18% US$8.6 bn 49%", "US$9.0 bn 14%" 등)를 본문이 아니라 `#`
    헤딩으로 잘못 인식한다 — 원본 PDF가 "라벨 텍스트 + 큰 숫자 강조박스"
    레이아웃을 쓰는 재무 하이라이트 페이지에서 반복적으로 나타나는 패턴이다
    (같은 문서에서 4곳 이상 확인). 이 결함은 `page_index_md.
    extract_nodes_from_markdown()`(vendored, 직접 수정 금지)가 `#`이 붙은
    줄을 무조건 헤딩으로 신뢰하는 순수 정규식 파서라 그대로 승계된다.

    영향: 이 수치-헤딩이 진짜 절 제목("### Escondida") 바로 다음 줄에 오면,
    `read_node_text()`(다음 동급 헤딩 직전까지만 읽음)가 그 절 제목 헤딩의
    본문을 사실상 텅 빈 것으로 만들어(값이 바로 다음 "헤딩" 취급된 줄에
    있으므로), 그 절에서 수치를 못 뽑는다 — `rag_core/retrieval/mine_aggregate.py`
    가 광산별 생산량·매장량을 추출할 때 이 결함 때문에 특정 문서에서 값을
    놓치는 사례가 재현됐다(검증결과: `documents/산출물/2026-W38_0914-0920/
    광산자료_집계질의_검증결과_260917.md` §6)."""

    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _HEADING_MARKER_AND_TITLE_RE.match(line)
        if not match:
            continue
        hashes, title = match.group(1), match.group(2)
        if _is_numeric_only_title(title):
            lines[i] = title
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def restore_document_title_heading(text: str, title: str) -> str:
    """수치형 문서 제목이 유일한 헤딩일 때 그 제목을 루트 노드로 복원한다.

    OCR 문서 ``11.27.pdf``처럼 첫 줄의 ``# 11.27``가 유일한 구조 표식인 경우,
    일반 수치 헤딩 강등 규칙이 적용되면 PageIndex에는 노드가 하나도 남지 않는다.
    프론트매터 제목과 완전히 같은 첫 본문 줄만 다시 헤딩으로 바꿔 줄 수와 원문
    내용을 보존한다. 제목과 다른 수치·단위 줄은 계속 평문으로 둔다.
    """

    clean_title = str(title or "").strip()
    if not clean_title or _HEADING_RE.search(text):
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == clean_title:
            lines[index] = f"# {clean_title}"
            return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return text


def fix_blank_heading_titles(text: str, *, max_title_len: int = 60) -> str:
    """헤딩 마커(`#`~`######`)는 살아있는데 제목 텍스트가 통째로 공백인 줄에
    본문 첫 줄 기반 폴백 제목을 채운다.

    실측 확인(2026-08-26): PDF→MD 변환 결함으로 `조달청보고서` 868건 중 4건
    (Weekly_0217/0224/0303, 니켈_이재호_조달청_연구원)에서 이 패턴이 나왔다 —
    `services/shared/pageindex_client.build_tree_from_markdown()`(md_to_tree)는
    제목이 빈 헤딩을 노드로 만들지 않고 건너뛰어, 그 아래 본문이 상위 섹션에
    통째로 합쳐진다(개별 광종·주제 단위로는 pageindex 검색이 안 됨 — diff
    건수가 이 패턴 개수와 정확히 일치함을 실측으로 확인). USGS의 "헤딩 자체가
    사라진" 결함(`pageindex_agent.py` 참고)과는 증상이 달라 같은 방식으로
    우회하지 않고, 원본 마크다운을 트리 빌더에 넣기 전에 여기서 보정한다."""

    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _BLANK_TITLE_HEADING_RE.match(line):
            continue
        hashes = line.strip()
        fallback = None
        for candidate in lines[i + 1:]:
            stripped_candidate = candidate.strip()
            if not stripped_candidate:
                continue
            if _HEADING_RE.match(candidate):
                break
            fallback = stripped_candidate[:max_title_len]
            break
        lines[i] = f"{hashes} {fallback or '(제목 없음)'}"
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def build_tree_for_okf(
    okf_path: Path,
    *,
    with_summary: bool = True,
    model: str | None = None,
    okf_root: Path = OKF_DOCUMENTS_ROOT,
) -> dict:
    """OKF 파일 1건 → 트리 JSON(메타데이터 포함 dict)."""

    from rag_core.pageindex_client import build_tree_from_markdown

    text = okf_path.read_text(encoding="utf-8")
    front, body, offset = split_frontmatter(text)
    body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    # 줄 수를 절대 안 바꾼다(헤딩 줄 하나를 그대로 교체만 함) — body_line_offset과
    # 트리 line_num이 그대로 OKF 파일 실제 줄 번호를 가리키게 유지하기 위해서다.
    body = fix_blank_heading_titles(body)
    body = demote_numeric_only_headings(body)
    body = restore_document_title_heading(body, str(front.get("title", okf_path.stem)))

    # doc_name은 md 파일 basename에서 나오므로(page_index_md.md_to_tree) 임시
    # 파일도 원본과 같은 이름으로 만든다.
    with tempfile.TemporaryDirectory(prefix="okf_pageindex_") as tmpdir:
        tmp_md = Path(tmpdir) / okf_path.name
        tmp_md.write_text(body, encoding="utf-8")
        started = time.monotonic()
        tree = build_tree_from_markdown(str(tmp_md), model=model, with_summary=with_summary)
        elapsed = time.monotonic() - started

    return {
        "doc_id": front.get("doc_id", ""),
        "title": front.get("title", okf_path.stem),
        "source_group": front.get("source_group", ""),
        "resource": front.get("resource", ""),
        "fmt": front.get("fmt", ""),
        "document_date": front.get("document_date"),
        "minerals": front.get("minerals", []),
        "content_keywords": front.get("content_keywords", []),
        "okf_path": okf_path.relative_to(okf_root).as_posix(),
        _OKF_BODY_SHA256_KEY: body_sha256,
        "body_line_offset": offset,
        "with_summary": with_summary,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_sec": round(elapsed, 2),
        "doc_name": tree.get("doc_name", okf_path.stem),
        "line_count": tree.get("line_count", 0),
        "structure": tree.get("structure", []),
    }


def _tree_path(okf_path: Path, trees_root: Path, okf_root: Path = OKF_DOCUMENTS_ROOT) -> Path:
    rel = okf_path.relative_to(okf_root)
    return trees_root / rel.with_suffix(".tree.json")


def sync_tree_metadata_for_okf(okf_path: Path, tree_path: Path) -> bool:
    """한 OKF의 프론트매터 검색 메타를 기존 트리에 반영한다.

    트리 구조가 dict가 아니면 손상된 이전 산출물로 보고 건드리지 않는다. 호출부의
    freshness 판정이 그 파일을 stale로 골라 재생성한다.
    """

    keys = ("title", "source_group", "resource", "fmt", "document_date", "minerals", "content_keywords")
    front, _, offset = split_frontmatter(okf_path.read_text(encoding="utf-8"))
    try:
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(tree, dict):
        return False
    changed = False
    for key in keys:
        value = front.get(key, [] if key in {"minerals", "content_keywords"} else None)
        if tree.get(key) != value:
            tree[key] = value
            changed = True
    if tree.get("body_line_offset") != offset:
        tree["body_line_offset"] = offset
        changed = True
    if changed:
        tree_path.write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


def sync_tree_metadata(*, okf_root: Path = OKF_DOCUMENTS_ROOT,
                       trees_root: Path = PAGEINDEX_TREES_ROOT) -> int:
    """재요약 없이 OKF 프론트매터 검색 메타를 기존 PageIndex 트리에 반영한다."""

    updated = 0
    for okf_path in sorted(okf_root.rglob("*.md")):
        tree_path = _tree_path(okf_path, trees_root, okf_root)
        if not tree_path.is_file():
            continue
        if sync_tree_metadata_for_okf(okf_path, tree_path):
            updated += 1
    return updated


def count_nodes(structure: list) -> int:
    return sum(1 + count_nodes(node.get("nodes", [])) for node in structure)


def build_all(
    *,
    okf_root: Path = OKF_DOCUMENTS_ROOT,
    trees_root: Path = PAGEINDEX_TREES_ROOT,
    with_summary: bool = True,
    limit: int | None = None,
    pattern: str | None = None,
    force: bool = False,
    model: str | None = None,
) -> dict:
    """okf_documents 전체(또는 일부)에 대해 트리를 만들어 저장한다."""

    candidates = sorted(p for p in okf_root.rglob("*.md") if p.is_file())
    if pattern:
        candidates = [p for p in candidates if pattern in p.as_posix()]

    fresh_skipped = 0
    metadata_synced = 0
    stale_candidates = 0
    if force:
        paths = candidates
    else:
        paths = []
        for okf_path in candidates:
            tree_path = _tree_path(okf_path, trees_root, okf_root)
            if tree_path.is_file() and tree_is_fresh_for_okf(tree_path, okf_path):
                fresh_skipped += 1
                metadata_synced += int(sync_tree_metadata_for_okf(okf_path, tree_path))
                continue
            if tree_path.exists():
                stale_candidates += 1
            paths.append(okf_path)
    if limit:
        paths = paths[:limit]

    done, failed, skipped = 0, 0, 0
    elapsed_total = 0.0
    status_con = ingest_status.pg_connect_safe()
    try:
        for index, okf_path in enumerate(paths, start=1):
            rel = okf_path.relative_to(okf_root).as_posix()
            started = time.monotonic()
            try:
                tree = build_tree_for_okf(
                    okf_path, with_summary=with_summary, model=model, okf_root=okf_root
                )
            except Exception as e:  # noqa: BLE001 - 한 문서 실패가 배치 전체를 막지 않게
                failed += 1
                logger.error("[%d/%d] FAIL %s: %s", index, len(paths), rel, e, exc_info=True)
                try:
                    front, _, _ = split_frontmatter(okf_path.read_text(encoding="utf-8"))
                    fid = ingest_status.normalize_file_id(front.get("doc_id", ""))
                    if fid:
                        ingest_status.upsert_file_stage_status(
                            fid, "pageindex", "failed", error_message=str(e)[:2000], con=status_con,
                        )
                except Exception:  # noqa: BLE001 - 상태기록 실패는 무시(원본 실패만 카운트)
                    pass
                continue
            fid = ingest_status.normalize_file_id(tree["doc_id"])
            if not tree["structure"]:
                skipped += 1
                logger.warning("[%d/%d] 노드 0개(헤딩 없음) — 건너뜀: %s", index, len(paths), rel)
                if fid:
                    ingest_status.upsert_file_stage_status(fid, "pageindex", "skipped", con=status_con)
                continue
            out_path = _tree_path(okf_path, trees_root, okf_root)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            took = time.monotonic() - started
            elapsed_total += took
            done += 1
            if fid:
                ingest_status.upsert_file_stage_status(fid, "pageindex", "success", con=status_con)
            logger.info(
                "[%d/%d] %s — 노드 %d개, %.1f초",
                index, len(paths), rel, count_nodes(tree["structure"]), took,
            )
    finally:
        ingest_status.commit_close_safe(status_con)
    return {
        "candidate_count": len(candidates),
        "target_count": len(paths),
        "done": done,
        "failed": failed,
        "skipped_no_heading": skipped,
        "fresh_skipped": fresh_skipped,
        "metadata_synced": metadata_synced,
        "stale_candidates": stale_candidates,
        "elapsed_sec": round(elapsed_total, 1),
        "avg_sec": round(elapsed_total / done, 1) if done else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="문서-OKF → PageIndex 트리 생성")
    parser.add_argument("--okf-root", default=str(OKF_DOCUMENTS_ROOT))
    parser.add_argument("--trees-root", default=str(PAGEINDEX_TREES_ROOT))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pattern", default=None, help="경로 부분문자열 필터")
    parser.add_argument("--no-summary", action="store_true", help="LLM 노드요약 생략")
    parser.add_argument("--force", action="store_true", help="이미 만든 트리도 재생성")
    parser.add_argument("--sync-metadata", action="store_true",
                        help="기존 트리를 재요약하지 않고 OKF 검색 메타만 동기화")
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    okf_root = Path(args.okf_root).expanduser().resolve()
    trees_root = Path(args.trees_root).expanduser().resolve()

    if args.sync_metadata:
        print(
            f"트리 메타데이터 동기화: "
            f"{sync_tree_metadata(okf_root=okf_root, trees_root=trees_root)}건",
            flush=True,
        )
        return 0

    configure_logging()
    with ingest_status.pipeline_run("pageindex.build_pageindex_trees", args=vars(args)) as run:
        summary = build_all(
            okf_root=okf_root,
            trees_root=trees_root,
            with_summary=not args.no_summary,
            limit=args.limit,
            pattern=args.pattern,
            force=args.force,
            model=args.model,
        )
        run.metrics.update(summary)
        print(json.dumps(summary, ensure_ascii=False))
        if summary["failed"]:
            # 예외를 context 안에서 올려 pipeline_run을 failed로 갱신하고, 호출한
            # ingest.run_chain에도 non-zero returncode를 전달한다.
            raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
