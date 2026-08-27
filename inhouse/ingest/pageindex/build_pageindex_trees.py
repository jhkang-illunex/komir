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
import json
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest import status as ingest_status  # noqa: E402

OKF_DOCUMENTS_ROOT = _INHOUSE_ROOT / "data_lake/semi_structure/okf_documents"
PAGEINDEX_TREES_ROOT = _INHOUSE_ROOT / "data_lake/semi_structure/pageindex_trees"


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


_HEADING_RE = re.compile(r"^#{1,6}\s")
_BLANK_TITLE_HEADING_RE = re.compile(r"^#{1,6}\s*$")


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

    from services.shared.pageindex_client import build_tree_from_markdown

    text = okf_path.read_text(encoding="utf-8")
    front, body, offset = split_frontmatter(text)
    # 줄 수를 절대 안 바꾼다(헤딩 줄 하나를 그대로 교체만 함) — body_line_offset과
    # 트리 line_num이 그대로 OKF 파일 실제 줄 번호를 가리키게 유지하기 위해서다.
    body = fix_blank_heading_titles(body)

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
        "okf_path": okf_path.relative_to(okf_root).as_posix(),
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

    paths = sorted(p for p in okf_root.rglob("*.md") if p.is_file())
    if pattern:
        paths = [p for p in paths if pattern in p.as_posix()]
    if not force:
        paths = [p for p in paths if not _tree_path(p, trees_root, okf_root).exists()]
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
                print(f"  [{index}/{len(paths)}] FAIL {rel}", flush=True)
                traceback.print_exc()
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
                print(f"  [{index}/{len(paths)}] 노드 0개(헤딩 없음) — 건너뜀: {rel}", flush=True)
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
            print(
                f"  [{index}/{len(paths)}] {rel} — 노드 {count_nodes(tree['structure'])}개, "
                f"{took:.1f}초",
                flush=True,
            )
    finally:
        ingest_status.commit_close_safe(status_con)
    return {
        "target_count": len(paths),
        "done": done,
        "failed": failed,
        "skipped_no_heading": skipped,
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
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)

    with ingest_status.pipeline_run("pageindex.build_pageindex_trees", args=vars(args)) as run:
        summary = build_all(
            okf_root=Path(args.okf_root).expanduser().resolve(),
            trees_root=Path(args.trees_root).expanduser().resolve(),
            with_summary=not args.no_summary,
            limit=args.limit,
            pattern=args.pattern,
            force=args.force,
            model=args.model,
        )
        run.metrics.update(summary)
        print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
