# -*- coding: utf-8 -*-
"""PageIndex 조회 — §5-4의 3번째 검색 도구(rag_chat·report_gen 공용 정본).

`documents/meta/CONTAINER_ARCHITECTURE.md` §5-4 "③ PageIndex 조회": 문서-OKF의
원문 구조에서 만든 목차/섹션 트리를 타고 들어가 관련 섹션을 찾는다 — 벡터 유사도만
으로는 잘 안 걸리는 대량·구조화 보고서(USGS 등)를 보완하는 목적.

**이번 범위 = 결정적(deterministic) 기본 조회까지**. §5-4가 그리는 "LLM이 트리를
타고 들어가며 탐색"하는 완전한 에이전틱 traversal은 후속 과제로 남긴다 —
LLM 없이도 (1) 문서 찾기 (2) 노드(섹션) 찾기 (3) 노드 원문 읽기가 되는 층을 먼저
확정해두면, 후속 에이전틱 층은 이 세 함수를 도구로 부르기만 하면 된다.
(`search_nodes()`가 돌려주는 노드의 `okf_path`+`line_num`으로 `read_node_text()`를
부르는 게 그 "타고 들어가는" 한 스텝에 해당한다.)

데이터 소스: `ingest/pageindex/build_pageindex_trees.py`(구 services/ingestion/)가 만든
`data_lake/semi_structure/pageindex_trees/**/*.tree.json`
(원문은 `data_lake/semi_structure/okf_documents/**/*.md`).

점수 계산은 `rag/ragkit/tokenize_ko.py`의 토크나이저를 그대로 쓴다 — BM25 색인과
같은 토큰화를 써야 "같은 질의에 두 도구가 딴소리하는" 상황을 피할 수 있고,
한국어 조사 때문에 단순 부분문자열 매칭이 잘 안 걸리는 문제도 그쪽에서 이미
해결돼 있다(글자 바이그램).
"""
from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_INHOUSE_ROOT = Path(__file__).resolve().parents[3]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from rag.ragkit.tokenize_ko import to_fts_text  # noqa: E402

#: 트리·원문 위치. 컨테이너에서 마운트 지점이 달라질 수 있어 환경변수로 덮어쓸 수 있게 둔다.
TREES_ROOT = Path(
    os.environ.get("PAGEINDEX_TREES_DIR", _INHOUSE_ROOT / "data_lake/semi_structure/pageindex_trees")
)
OKF_DOCUMENTS_ROOT = Path(
    os.environ.get("OKF_DOCUMENTS_DIR", _INHOUSE_ROOT / "data_lake/semi_structure/okf_documents")
)


class PageIndexError(RuntimeError):
    """트리 저장소가 없거나 비어 있을 때."""


def _tokens(text: str) -> set[str]:
    return set(to_fts_text(text or "").split())


def _score(query_tokens: set[str], text: str) -> float:
    """질의 토큰이 대상 텍스트에 얼마나 덮이는가(0~1). 질의 길이로 정규화."""

    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokens(text)) / len(query_tokens)


@lru_cache(maxsize=1)
def _load_trees(trees_root_str: str) -> list[dict[str, Any]]:
    """트리 JSON 전량 로드(프로세스당 1회). 문서 수백 건 규모까지는 이걸로 충분하다."""

    trees_root = Path(trees_root_str)
    if not trees_root.is_dir():
        raise PageIndexError(
            f"PageIndex 트리 디렉토리가 없다: {trees_root} — "
            "ingest/pageindex/build_pageindex_trees.py를 먼저 실행할 것"
        )
    trees: list[dict[str, Any]] = []
    for path in sorted(trees_root.rglob("*.tree.json")):
        try:
            tree = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tree["_tree_path"] = str(path)
        trees.append(tree)
    if not trees:
        raise PageIndexError(f"PageIndex 트리가 한 건도 없다: {trees_root}")
    return trees


def load_trees(trees_root: Path | str = TREES_ROOT) -> list[dict[str, Any]]:
    """저장된 트리 전체(문서 단위 dict 리스트)."""

    return _load_trees(str(trees_root))


def reload_trees() -> None:
    """트리를 다시 만든 뒤 같은 프로세스에서 최신본을 보게 할 때(장기 실행 서비스용)."""

    _load_trees.cache_clear()


def _doc_meta(tree: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": tree.get("doc_id", ""),
        "title": tree.get("title", ""),
        "doc_name": tree.get("doc_name", ""),
        "source_group": tree.get("source_group", ""),
        "resource": tree.get("resource", ""),
        "okf_path": tree.get("okf_path", ""),
        "node_count": count_nodes(tree.get("structure", [])),
    }


def count_nodes(structure: list[dict[str, Any]]) -> int:
    return sum(1 + count_nodes(node.get("nodes", [])) for node in structure)


def find_documents(
    query: str,
    *,
    limit: int = 5,
    trees_root: Path | str = TREES_ROOT,
    exclude_source_groups: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """문서명/제목/소스그룹으로 문서 트리를 찾는다(점수 내림차순).

    `doc_id`나 파일경로를 그대로 넣으면 해당 문서가 정확매칭으로 1등이 된다.

    `exclude_source_groups`: 트리의 `source_group` 필드가 이 집합에 있으면
    후보에서 제외한다 — MCP public 프로필이 라이선스 제한 소스(예: Argus)를
    걸러내는 지점(`shared.retrieval.access.PRIVATE_ONLY_SOURCE_GROUPS`). 기본값
    (빈 집합)이면 기존 동작과 동일. 트리 로딩·캐시(`load_trees`)는 그대로 두고
    호출마다 후보만 거른다."""

    trees = load_trees(trees_root)
    if exclude_source_groups:
        trees = [t for t in trees if t.get("source_group") not in exclude_source_groups]
    needle = (query or "").strip()
    query_tokens = _tokens(needle)
    scored: list[tuple[float, dict[str, Any]]] = []
    for tree in trees:
        haystack = " ".join(
            str(tree.get(key, ""))
            for key in ("title", "doc_name", "source_group", "okf_path", "resource")
        )
        score = _score(query_tokens, haystack)
        if needle and (needle == tree.get("doc_id") or needle in tree.get("okf_path", "")):
            score = 1.0 + score  # 식별자 정확매칭은 항상 위로
        if score > 0:
            scored.append((score, tree))
    scored.sort(key=lambda item: (-item[0], item[1].get("okf_path", "")))
    return [dict(_doc_meta(tree), score=round(score, 3)) for score, tree in scored[:limit]]


def get_tree(
    doc: str,
    *,
    trees_root: Path | str = TREES_ROOT,
) -> dict[str, Any] | None:
    """doc_id·okf_path·제목으로 문서 트리 1건을 통째로 돌려준다(없으면 None)."""

    trees = load_trees(trees_root)
    needle = (doc or "").strip()
    for tree in trees:
        if needle and needle in (tree.get("doc_id"), tree.get("okf_path"), tree.get("doc_name")):
            return tree
    matches = find_documents(needle, limit=1, trees_root=trees_root)
    if not matches:
        return None
    target = matches[0]["okf_path"]
    for tree in trees:
        if tree.get("okf_path") == target:
            return tree
    return None


def iter_nodes(structure: list[dict[str, Any]], _path: tuple[str, ...] = ()):
    """트리를 깊이우선으로 펼치며 (노드, 상위제목 경로)를 낸다."""

    for node in structure:
        path = _path + (node.get("title", ""),)
        yield node, path
        yield from iter_nodes(node.get("nodes", []), path)


def toc(doc: str, *, trees_root: Path | str = TREES_ROOT) -> list[dict[str, Any]]:
    """문서 1건의 평면 목차(node_id·depth·제목·요약) — LLM에게 트리를 보여줄 때 쓴다."""

    tree = get_tree(doc, trees_root=trees_root)
    if tree is None:
        return []
    entries = []
    for node, path in iter_nodes(tree.get("structure", [])):
        entries.append(
            {
                "node_id": node.get("node_id", ""),
                "depth": len(path) - 1,
                "title": node.get("title", ""),
                "summary": node.get("summary", ""),
                "line_num": node.get("line_num", 0),
            }
        )
    return entries


def search_nodes(
    query: str,
    *,
    doc: str | None = None,
    doc_limit: int = 3,
    node_limit: int = 8,
    trees_root: Path | str = TREES_ROOT,
    exclude_source_groups: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """질의 → (관련 문서 선택 →) 트리 내 관련 노드 목록.

    `doc`을 주면 그 문서 안에서만, 없으면 `find_documents()` 상위 `doc_limit`건
    안에서 노드를 찾는다. 노드 점수는 제목·요약·상위제목 경로 기준.

    `exclude_source_groups`: `find_documents()`와 동일 규약(빈 집합이면 기존
    동작과 동일). `doc`을 명시해도 그 문서의 `source_group`이 이 집합에 있으면
    제외한다 — 문서 id를 직접 지정하는 우회로 라이선스 경계를 넘지 못하게
    막는다."""

    trees = load_trees(trees_root)
    if doc:
        target = get_tree(doc, trees_root=trees_root)
        if target is not None and target.get("source_group") in exclude_source_groups:
            target = None
        candidates = [target] if target else []
    else:
        wanted = {
            meta["okf_path"]
            for meta in find_documents(
                query, limit=doc_limit, trees_root=trees_root,
                exclude_source_groups=exclude_source_groups,
            )
        }
        candidates = [tree for tree in trees if tree.get("okf_path") in wanted]

    query_tokens = _tokens(query)
    hits: list[dict[str, Any]] = []
    for tree in candidates:
        for node, path in iter_nodes(tree.get("structure", [])):
            # 2026-08-11 버그수정(실측): 노드 본문이 짧으면 pageindex_lib가 그 노드의
            # summary를 비워두고 대신 prefix_summary(상위 문맥을 물려받은 요약)만
            # 채운다 — 이 필드를 haystack에서 빼먹으면 그런 노드는 절대 안 걸린다
            # (실측 사례: "4. 검증 훅" 노드의 QWK 언급이 summary가 아니라
            # prefix_summary에만 있어 검색 0건이었음).
            haystack = " ".join(
                [*path, node.get("summary", "") or "", node.get("prefix_summary", "") or ""]
            )
            score = _score(query_tokens, haystack)
            if score <= 0:
                continue
            hits.append(
                {
                    "score": round(score, 3),
                    "doc_id": tree.get("doc_id", ""),
                    "doc_title": tree.get("title", ""),
                    "okf_path": tree.get("okf_path", ""),
                    "resource": tree.get("resource", ""),
                    "node_id": node.get("node_id", ""),
                    "title": node.get("title", ""),
                    "summary": node.get("summary", ""),
                    "node_path": " > ".join(path),
                    "line_num": node.get("line_num", 0),
                    "body_line_offset": tree.get("body_line_offset", 0),
                }
            )
    hits.sort(key=lambda hit: (-hit["score"], hit["okf_path"], hit["node_id"]))
    return hits[:node_limit]


def read_node_text(
    hit: dict[str, Any],
    *,
    max_chars: int = 4000,
    okf_root: Path | str = OKF_DOCUMENTS_ROOT,
) -> str:
    """`search_nodes()` 결과 1건 → 문서-OKF 원문에서 그 섹션 본문을 읽어온다.

    트리 JSON은 노드 본문을 담지 않는다(PageIndex는 목차 트리만 저장하고 본문은
    원문에서 읽는 설계) — `line_num`(본문 기준) + `body_line_offset`(프론트매터
    줄 수)으로 OKF 파일의 실제 줄 위치를 복원해 다음 섹션 직전까지 잘라 준다.
    """

    okf_path = Path(okf_root) / hit["okf_path"]
    if not okf_path.is_file():
        return ""
    lines = okf_path.read_text(encoding="utf-8").splitlines()
    start = hit.get("line_num", 1) + hit.get("body_line_offset", 0) - 1
    start = max(start, 0)
    heading = lines[start].strip() if start < len(lines) else ""
    depth = len(heading) - len(heading.lstrip("#")) if heading.startswith("#") else 0

    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].lstrip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if depth and level > depth:
            continue  # 하위 섹션은 이 노드 본문에 포함
        end = index
        break
    return "\n".join(lines[start:end]).strip()[:max_chars]


def lookup(
    query: str,
    *,
    doc: str | None = None,
    doc_limit: int = 3,
    node_limit: int = 5,
    with_text: bool = True,
    trees_root: Path | str = TREES_ROOT,
    exclude_source_groups: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """도구 단일 진입점 — 질의 → {문서 후보, 관련 노드(+원문)}.

    rag_chat/report_gen이 부를 때는 이 함수 하나만 쓰면 된다. `exclude_source_groups`는
    `find_documents()`/`search_nodes()`와 동일 규약 — MCP public 프로필이 라이선스
    제한 소스를 걸러내는 지점(`shared.retrieval.access.PRIVATE_ONLY_SOURCE_GROUPS`)."""

    if doc:
        target = get_tree(doc, trees_root=trees_root)
        if target is not None and target.get("source_group") in exclude_source_groups:
            target = None
        documents = [dict(_doc_meta(target), score=1.0)] if target else []
    else:
        documents = find_documents(
            query, limit=doc_limit, trees_root=trees_root,
            exclude_source_groups=exclude_source_groups,
        )
    nodes = search_nodes(
        query, doc=doc, doc_limit=doc_limit, node_limit=node_limit, trees_root=trees_root,
        exclude_source_groups=exclude_source_groups,
    )
    if with_text:
        for hit in nodes:
            hit["text"] = read_node_text(hit)
    return {"query": query, "documents": documents, "nodes": nodes}


if __name__ == "__main__":  # 수동 점검용
    import argparse

    parser = argparse.ArgumentParser(description="PageIndex 조회 점검")
    parser.add_argument("query")
    parser.add_argument("--doc", default=None)
    parser.add_argument("--nodes", type=int, default=5)
    args = parser.parse_args()
    result = lookup(args.query, doc=args.doc, node_limit=args.nodes, with_text=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
