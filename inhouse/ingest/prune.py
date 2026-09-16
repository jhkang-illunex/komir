# -*- coding: utf-8 -*-
"""prune — landing에서 사라진 원본의 산출물(okf md·pageindex 트리·doc_chunk 행) 정리(2026-09-16).

왜 필요한가: okf/pageindex 빌더는 "있으면 쓴다"만 하고 사라진 문서의 산출물은 지우지 않는다
(2026-08-28 RAG 코퍼스 정리 때 확인된 gap — 그때는 수동 mv로 처리). data_lake를 "정리가 끝난
형태"라고 부르려면 landing과 어긋난 잔여물을 걷어내는 단계가 있어야 한다.

판정(문서 단위, PDF 그룹만):
- okf md 프론트매터의 `group_key` + `source_relative_path`(2026-09-16 이후 생성분)로
  `landing_root(group)/source_relative_path` 존재 여부를 본다.
- 그 키가 없는 예전 문서는 `resource`(저장소 기준 상대경로)를 저장소 루트에서 찾는다.
- 어느 쪽으로도 판정할 수 없으면 **건드리지 않는다**(불확실하면 보존).

안전장치:
- 기본은 dry-run(무엇을 지울지 보고만). `--apply`일 때만 삭제.
- 그룹의 landing 루트가 없거나 비어 있으면 그 그룹은 통째로 건너뛴다(마운트 누락으로 전부 삭제되는 일 방지).
- 한 그룹에서 지울 문서가 50%를 넘으면 `--force` 없이는 거부한다.
- DB 행 삭제는 `src=<out_dirname> AND doc_id=<okf doc_id 앞 16자>`로만(vectorize와 같은 키).
  `--no-db`면 파일만(테스트·DB 없는 환경).

    cd inhouse && python -m ingest.prune            # 보고만
    cd inhouse && python -m ingest.prune --apply    # 삭제
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _INHOUSE_ROOT.parent
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest.paths import IngestPaths, get_paths  # noqa: E402
from ingest.registry import PDF_GROUPS, SourceGroup  # noqa: E402

MAX_REMOVE_RATIO = 0.5


@dataclass
class Orphan:
    group: str
    okf_path: Path
    tree_path: Path | None
    doc_id: str
    reason: str


@dataclass
class PruneReport:
    orphans: list[Orphan] = field(default_factory=list)
    skipped_groups: dict[str, str] = field(default_factory=dict)
    refused_groups: dict[str, str] = field(default_factory=dict)
    scanned: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "orphans": [{"group": o.group, "okf": str(o.okf_path), "doc_id": o.doc_id, "reason": o.reason} for o in self.orphans],
            "skipped_groups": self.skipped_groups,
            "refused_groups": self.refused_groups,
        }


def _front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    try:
        _, raw, _ = text.split("---\n", 2)
        return yaml.safe_load(raw) or {}
    except (ValueError, yaml.YAMLError):
        return {}


def _tree_path(okf_path: Path, paths: IngestPaths) -> Path | None:
    try:
        rel = okf_path.relative_to(paths.okf_documents)
    except ValueError:
        return None
    return paths.pageindex_trees / rel.with_suffix(".tree.json")


def _source_exists(front: dict, group: SourceGroup, root: Path) -> bool | None:
    """True/False = 판정, None = 판정 불가(보존)."""
    rel = front.get("source_relative_path")
    if rel and front.get("group_key") == group.key:
        return (root / rel).exists()
    resource = front.get("resource")
    if resource and not Path(resource).is_absolute():
        candidate = _REPO_ROOT / resource
        if candidate.exists():
            return True
        # 저장소 기준 경로가 없더라도, landing 루트 아래 같은 파일명이 있으면 살아있는 것으로 본다
        name = Path(resource).name
        try:
            return any(p.name == name for p in root.rglob("*") if p.is_file())
        except OSError:
            return None
    return None


def scan(paths: IngestPaths | None = None, groups: tuple[SourceGroup, ...] = PDF_GROUPS, *,
         force: bool = False) -> PruneReport:
    paths = paths or get_paths()
    rep = PruneReport()
    for g in groups:
        okf_dir = paths.okf_documents / g.out_dirname
        if not okf_dir.is_dir():
            continue
        root = g.landing_root()
        if root is None or not Path(root).is_dir() or not any(p.is_file() for p in Path(root).rglob("*")):
            rep.skipped_groups[g.key] = f"landing 루트 없음/비어 있음: {root}"
            continue
        root = Path(root)
        docs = sorted(p for p in okf_dir.rglob("*.md") if p.is_file())
        rep.scanned[g.key] = len(docs)
        found: list[Orphan] = []
        for okf in docs:
            front = _front(okf)
            exists = _source_exists(front, g, root)
            if exists is None or exists:
                continue
            doc_id = str(front.get("doc_id", "")).removeprefix("doc_")[:16] or okf.stem[:16]
            found.append(Orphan(g.key, okf, _tree_path(okf, paths), doc_id, "source missing in landing"))
        if docs and len(found) / len(docs) > MAX_REMOVE_RATIO and not force:
            rep.refused_groups[g.key] = f"삭제 대상 {len(found)}/{len(docs)} > {int(MAX_REMOVE_RATIO * 100)}% — --force 없이는 거부"
            continue
        rep.orphans.extend(found)
    return rep


def apply(rep: PruneReport, *, db: bool = True) -> dict:
    removed_files = removed_rows = 0
    con = None
    if db and rep.orphans:
        from common.config import get_settings
        from common.db import pg_connect

        schema = get_settings().PG_SCHEMA
        con = pg_connect()
    try:
        for o in rep.orphans:
            if o.okf_path.exists():
                o.okf_path.unlink()
                removed_files += 1
            if o.tree_path and o.tree_path.exists():
                o.tree_path.unlink()
                removed_files += 1
            if con is not None:
                src = next(g.out_dirname for g in PDF_GROUPS if g.key == o.group)
                with con.cursor() as cur:
                    cur.execute(f"DELETE FROM {schema}.doc_chunk WHERE src = %s AND doc_id = %s", (src, o.doc_id))
                    removed_rows += cur.rowcount
        if con is not None:
            con.commit()
    finally:
        if con is not None:
            con.close()
    return {"removed_files": removed_files, "removed_rows": removed_rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="landing에서 사라진 원본의 okf/pageindex/doc_chunk 정리")
    ap.add_argument("--apply", action="store_true", help="실제 삭제(기본 dry-run)")
    ap.add_argument("--force", action="store_true", help="그룹 50% 초과 삭제도 허용")
    ap.add_argument("--no-db", action="store_true", help="doc_chunk 행은 건드리지 않음(파일만)")
    a = ap.parse_args(argv)

    from ingest import status as ingest_status

    with ingest_status.pipeline_run("prune.prune", args=vars(a)) as run:
        rep = scan(force=a.force)
        print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=1))
        run.metrics.update({"orphans": len(rep.orphans), "skipped": len(rep.skipped_groups),
                            "refused": len(rep.refused_groups), "apply": a.apply})
        if a.apply:
            res = apply(rep, db=not a.no_db)
            print("삭제:", res)
            run.metrics.update(res)
        else:
            print(f"dry-run: 삭제 대상 {len(rep.orphans)}건(--apply로 실행)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
