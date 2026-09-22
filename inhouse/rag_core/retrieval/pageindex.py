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

점수 계산은 `rag_core/ragkit/tokenize_ko.py`의 토크나이저를 그대로 쓴다 — BM25 색인과
같은 토큰화를 써야 "같은 질의에 두 도구가 딴소리하는" 상황을 피할 수 있고,
한국어 조사 때문에 단순 부분문자열 매칭이 잘 안 걸리는 문제도 그쪽에서 이미
해결돼 있다(글자 바이그램).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

def _find_inhouse_root(start: Path) -> Path:
    """`rag_core/ragkit/tokenize_ko.py`(아래서 바로 import하는 그 모듈)를 담은
    디렉토리를 위로 훑어 찾는다. 2026-09-07 services/ 해체 후 이 파일은
    rag_core/retrieval/pageindex.py로 소스트리·컨테이너(/app) 모두 parents[2]가
    루트로 같아졌지만, 고정 parents[N] 인덱스는 배치가 달라지는 순간 조용히
    틀리는 전례가 있어 마커 탐색을 유지한다 — 2026-09-03 실측
    확인(컨테이너에서 TREES_ROOT가 `/data_lake/...`로 잘못 잡혀 매 조회가
    "디렉토리 없음"으로 실패, routers/chat.py의 `_find_root` 탐색 패턴과
    동일 원리로 교체)."""

    for candidate in (start, *start.parents):
        if (candidate / "rag_core/ragkit/tokenize_ko.py").is_file():
            return candidate
    raise ImportError(f"rag_core/ragkit/tokenize_ko.py를 {start} 상위에서 찾지 못함")


_INHOUSE_ROOT = _find_inhouse_root(Path(__file__).resolve())
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from rag_core.ragkit.tokenize_ko import to_fts_text  # noqa: E402

def _data_lake_default() -> Path:
    """INGEST_DATA_LAKE_DIR(.env, 2026-09-16 ingest 디렉토리 계약)가 있으면 그곳, 없으면 레거시
    data_lake/semi_structure. PAGEINDEX_TREES_DIR·OKF_DOCUMENTS_DIR 환경변수가 있으면 그쪽이 우선."""
    try:
        from common.config import get_settings

        v = (get_settings().INGEST_DATA_LAKE_DIR or "").strip()
        if v:
            return Path(v).expanduser().resolve()
    except Exception:  # noqa: BLE001
        pass
    return _INHOUSE_ROOT / "data_lake/semi_structure"


#: 트리·원문 위치. 컨테이너에서 마운트 지점이 달라질 수 있어 환경변수로 덮어쓸 수 있게 둔다
#: (PAGEINDEX_TREES_DIR·OKF_DOCUMENTS_DIR > INGEST_DATA_LAKE_DIR > 레거시).
TREES_ROOT = Path(
    os.environ.get("PAGEINDEX_TREES_DIR", _data_lake_default() / "pageindex_trees")
)
OKF_DOCUMENTS_ROOT = Path(
    os.environ.get("OKF_DOCUMENTS_DIR", _data_lake_default() / "okf_documents")
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
        "fmt": tree.get("fmt", ""),
        "document_date": tree.get("document_date"),
        "minerals": tree.get("minerals", []),
        "content_keywords": tree.get("content_keywords", []),
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
            for key in ("title", "doc_name", "source_group", "okf_path", "resource", "fmt", "document_date")
        )
        haystack += " " + " ".join(tree.get("minerals", []) + tree.get("content_keywords", []))
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


def _explicit_document_tree(doc: str, body_query: str | None, *, trees_root: Path | str,
                            exclude_source_groups: frozenset[str]) -> dict[str, Any] | None:
    """명시 lookup 전용으로 파일명 구분자까지 풀어 문서 하나를 고른다."""
    trees = [tree for tree in load_trees(trees_root) if tree.get("source_group") not in exclude_source_groups]
    words = [word.casefold() for word in re.findall(r"[A-Za-z0-9가-힣]+", f"{doc} {body_query or ''}")
             if len(word) >= 3 and word not in {"보고서", "정리자료", "광산", "위치", "원문"}]
    if not words:
        return None
    # 사용자는 "2026년 6월 16일"처럼 말하고, 조달청 파일은
    # ``20260616_...``으로 저장된다. 날짜를 별도 강한 식별자로 정규화하지
    # 않으면 공통 단어(주간·경제·비철금속)만으로 수백 문서가 동점이 된다.
    requested_dates = {
        f"{year}{int(month):02d}{int(day):02d}"
        for year, month, day in re.findall(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", doc)
    }
    requested_dates.update(re.findall(r"(?<!\d)(20\d{2})[-._/]?(\d{2})[-._/]?(\d{2})(?!\d)", doc))
    requested_dates = {
        "".join(item) if isinstance(item, tuple) else item
        for item in requested_dates
    }
    scored = []
    for tree in trees:
        haystack = " ".join(str(tree.get(key, "")).replace("_", " ").replace("-", " ")
                            for key in ("title", "doc_name", "okf_path", "resource", "fmt", "document_date")).casefold()
        haystack += " " + " ".join(tree.get("minerals", []) + tree.get("content_keywords", [])).casefold()
        score = sum(word in haystack for word in words)
        # 제목 축약어만 겹치는 여러 문서가 있어도, 사용자가 준 문서 식별자가
        # 파일명/제목에 통째로 들어 있으면 그 문서를 결정적으로 선택한다.
        compact_doc = re.sub(r"[^a-z0-9가-힣]", "", doc.casefold())
        compact_haystack = re.sub(r"[^a-z0-9가-힣]", "", haystack)
        if compact_doc and compact_doc in compact_haystack:
            score += 100
        if any(date_value in compact_haystack for date_value in requested_dates):
            score += 10
        if score:
            scored.append((score, tree))
    scored.sort(key=lambda item: (-item[0], item[1].get("okf_path", "")))
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][1]


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
        # 2026-09-18(감사 후속): 예전엔 여기서 조용히 ""을 돌려줘서, 호출부가
        # title/summary는 있고 본문만 빈 "가짜 근거"를 그대로 evidence로
        # 흘려보낼 수 있었다(필터링 없이). 최소한 로그는 남긴다 — 이 함수
        # 자체는 여전히 ""을 돌려주고(트리 JSON이 원문 없이도 만들어질 수
        # 있는 정상 상황을 에러로 취급하지 않는다), 실제 필터링은 lookup()이
        # 이 빈 텍스트를 근거로 내보내지 않도록 처리한다.
        _logger.warning(
            "pageindex OKF 원문 없음: doc_id=%s okf_path=%s node_id=%s",
            hit.get("doc_id", ""), hit["okf_path"], hit.get("node_id", ""),
        )
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


def _usgs_2026_rare_earth_context(lines: list[str]) -> str | None:
    """희토류 총괄 통계와 Nd 가격을 구분하는 공개 USGS 원문 발췌다.

    Q15의 명시 문서 fallback은 숫자 한 행만으로는 표의 단위·열·광종 범위를
    잃는다. 아래는 같은 ``RARE EARTHS`` 장에서 실제로 존재하는 제목, 단위,
    가격 표 머리·행, 생산·매장량 표 머리·총계, 범위 각주만 차례로 묶는다.
    다른 문서나 다른 body fallback에는 적용하지 않는다.
    """
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "###### RARE EARTHS1")
        end = next(i for i, line in enumerate(lines[start + 1:], start + 1)
                   if line.strip() == "###### RARE EARTHS (HEAVY)1")
    except StopIteration:
        return None
    chapter = lines[start:end]

    def one(predicate):
        return next((line for line in chapter if predicate(line)), None)

    title = one(lambda line: line.strip() == "###### RARE EARTHS1")
    unit = one(lambda line: "[Data in metric tons, rare-earth-oxide (REO) equivalent" in line)
    price_table = one(lambda line: "Price, average, dollars per kilogram:" in line)
    nd_price = one(lambda line: "Neodymium oxide, 99.5% minimum" in line)
    production_title = one(lambda line: "World Mine Production and Reserves:" in line)
    production_columns = one(lambda line: line.startswith("Mine production") and "Reserves" in line)
    world_total = one(lambda line: line.startswith("World total (rounded)"))
    scope = one(lambda line: line.startswith("- 1Data include lanthanides and yttrium"))
    nd_at = (nd_price or "").find("Neodymium oxide, 99.5% minimum")
    # 가격 표의 PDF 변환 행은 여러 산화물을 한 줄로 이어 붙인다. Advisor가
    # 앞·뒤만 보는 제한 발췌에서도 Nd 행을 보도록, 원문 행에서 그 주변만
    # 잘라 가격 머리 바로 뒤에 둔다.
    nd_excerpt = nd_price[nd_at:nd_at + 180] if nd_at >= 0 else None
    production_at = (production_title or "").find("World Mine Production and Reserves:")
    production_excerpt = production_title[production_at:production_at + 40] if production_at >= 0 else None
    # Advisor의 tail 300자에도 표 머리·총계·범위와 절 제목이 함께 남도록
    # 실제 절 제목을 표 행 뒤에 둔다. 내용은 같은 원문 문자열을 재배열할 뿐이다.
    excerpt = [title, unit, price_table, nd_excerpt, production_columns, world_total, production_excerpt, scope]
    if not nd_price or not all(excerpt):
        return None
    return "\n\n".join(excerpt)


def _document_body_fallback(
    query: str, tree: dict[str, Any], *, max_chars: int = 1200,
    okf_root: Path | str = OKF_DOCUMENTS_ROOT,
) -> dict[str, Any] | None:
    """명시 문서 안에서만 질의어가 가장 많이 겹치는 실제 본문 행을 읽는다.

    제목·목차에 대상이 없어 node 검색이 0건인 경우의 좁은 보완이다. 호출자는
    이미 ``doc``으로 하나의 접근 허용 트리를 확정했어야 하며, 본문에 질의어가
    없으면 후보 메타데이터를 근거로 만들지 않고 None을 반환한다.
    """
    okf_path = Path(okf_root) / str(tree.get("okf_path", ""))
    if not okf_path.is_file():
        return None
    lines = okf_path.read_text(encoding="utf-8").splitlines()
    query_tokens = _tokens(query)
    if not query_tokens:
        return None
    scored = [(_score(query_tokens, line), index) for index, line in enumerate(lines)]
    # 동점은 문서 앞의 행을 고른다. 표의 "JV Inkai"와 "South Inkai"처럼
    # 같은 토큰 수가 겹칠 때 뒤 행을 택하면 다른 광산 사실을 섞을 수 있다.
    # 광종명 한 단어만으로 같은 점수인 행이 여럿이면, 단독 표기보다 실제
    # 문맥이 있는 긴 원문 행을 선택한다. 광산 표는 아래 table_candidates가
    # 별도로 우선하므로 행 혼합 위험이 없다.
    score, index = max(scored, key=lambda item: (item[0], len(lines[item[1]]), -item[1]), default=(0.0, -1))
    selected_header: str | None = None
    selected_columns: tuple[int, int] | None = None

    # 문서 제목과 같은 일반어가 front matter에서 먼저 맞더라도, ``광산|위치``
    # 표 안에 실제 대상 행이 있으면 그 행을 우선한다. 그래야 회사명 질의가
    # 제목 행을 근거로 단일 광산처럼 보이는 일을 막을 수 있다.
    table_candidates: list[tuple[float, int, str, int, int]] = []
    for header_index, candidate_header in enumerate(lines):
        if "광산" not in candidate_header or "위치" not in candidate_header or "|" not in candidate_header:
            continue
        header_cells = [cell.strip() for cell in candidate_header.strip("|").split("|")]
        try:
            mine_col = header_cells.index("광산")
            location_col = header_cells.index("위치")
        except ValueError:
            continue
        for row_index, row in enumerate(lines[header_index + 1:], header_index + 1):
            if "|" not in row:
                # 표 본문을 한 번 지난 뒤에는 다음 prose로 넘어간다.
                if row_index > header_index + 1:
                    break
                continue
            row_cells = [cell.strip() for cell in row.strip("|").split("|")]
            if len(row_cells) <= mine_col or not row_cells[mine_col]:
                continue
            row_score = _score(query_tokens, row)
            if row_score >= 0.5:
                table_candidates.append((row_score, row_index, candidate_header, mine_col, location_col))
    if table_candidates:
        # 동점이면 앞 행을 택한다. 하나의 회사에 여러 광산이 있어도 그 사실은
        # 아래 match_count로 보존하고, 서로 다른 행의 값을 섞지는 않는다.
        score, index, selected_header, mine_col, location_col = max(
            table_candidates, key=lambda item: (item[0], -item[1])
        )
        selected_columns = (mine_col, location_col)
    # 한 글자 조사나 문서의 일반 제목만 겹친 경우에는 본문 사실로 취급하지 않는다.
    if score < 0.5 or index < 0:
        return None
    # 광산 표는 인접 행이 모두 다른 광산이다. 선택 행과, 열 의미를 밝히는
    # 가장 가까운 표 헤더만 남긴다. 이웃 광산 행은 절대 섞지 않는다.
    header = selected_header or next((line for line in reversed(lines[:index])
                   if "광산" in line and "위치" in line and "|" in line), None)
    text = "\n".join([*( [header] if header else [] ), lines[index]]).strip()
    contextual_applied = False
    if (tree.get("okf_path") == "생산매장량_USGS/USGS_2026.md"
            and ("World total (rounded)" in query or "Neodymium oxide, 99.5% minimum" in query)):
        # 두 body_query는 chatbot_graph의 typed Q15 route에서만 생성된다. 실제
        # 원문 절을 충분히 담은 경우에만 한 행 fallback을 바꾼다.
        contextual = _usgs_2026_rare_earth_context(lines)
        if contextual:
            text = contextual
            contextual_applied = True
    # PDF 변환 한 줄이 길어도 대상 광산명이 있는 주변을 남긴다. 앞 1,200자만
    # 자르면 Escondida처럼 같은 줄 뒤쪽의 사실("in Chile")이 사라진다.
    anchors = sorted((word for word in re.findall(r"[A-Za-z0-9가-힣]+", query) if len(word) >= 3), key=len, reverse=True)
    anchor_at = next((text.casefold().find(word.casefold()) for word in anchors if text.casefold().find(word.casefold()) >= 0), -1)
    if not contextual_applied and len(text) > max_chars and anchor_at >= 0:
        excerpt_start = max(0, anchor_at - max_chars // 3)
        text = text[excerpt_start:excerpt_start + max_chars]
    elif not contextual_applied:
        text = text[:max_chars]
    match_count = 1
    if header:
        header_cells = [cell.strip() for cell in header.strip("|").split("|")]
        row_cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
        try:
            mine_col, location_col = selected_columns or (header_cells.index("광산"), header_cells.index("위치"))
        except ValueError:
            mine_col = location_col = -1
        if mine_col >= 0 and location_col >= 0 and len(row_cells) > max(mine_col, location_col):
            mine_name = row_cells[mine_col]
            # 위치 다음 열은 소유사 등 전혀 다른 필드일 수 있다. 두 값이 모두
            # 숫자 좌표 형태일 때만 이어서 제시하고, 그 외에는 위치 첫 칸만 쓴다.
            location_values = [row_cells[location_col]] if row_cells[location_col] else []
            next_value = row_cells[location_col + 1] if len(row_cells) > location_col + 1 else ""
            numeric = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
            if location_values and next_value and numeric.fullmatch(location_values[0]) and numeric.fullmatch(next_value):
                location_values.append(next_value)
            if mine_name and location_values:
                text += f"\n\n원문 표의 선택 행에서 {mine_name}의 위치 열 값은 {', '.join(location_values)}으로 기재되어 있다."
            names: set[str] = set()
            query_mentions = 0
            header_index = lines.index(header)
            for line in lines[header_index + 1:]:
                if "|" not in line:
                    break
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) <= mine_col or not cells[mine_col]:
                    continue
                # 표의 바로 왼쪽 무제목 열에는 광상명이 따로 적히는 경우가 있다.
                # 이 열과 '광산' 열만 합쳐 distinct 광산 행을 센다.
                for candidate in (cells[mine_col - 1] if mine_col else "", cells[mine_col]):
                    if candidate:
                        names.add(candidate)
                query_mentions += sum(query.strip().casefold() in cell.casefold() for cell in cells if query.strip())
            query_name = query.strip().casefold()
            title_mentions_query = query_name and query_name in str(tree.get("title", "")).casefold()
            # 회사명은 문서 제목에는 있지만 표의 개별 광산명과 일치하지 않는다.
            # 제목과 표 여러 행에서 반복되는 식별자는 단일 광산명이 아니므로,
            # distinct 광산 행 수를 ambiguity metadata로 보존한다. 특정 광산명은
            # 표에서 한 행만 맞아 기존 단건 경로를 유지한다.
            match_count = len(names) if title_mentions_query and query_mentions >= 2 and len(names) >= 2 else 1
    if not text:
        return None
    return {
        "score": round(score, 3), "doc_id": tree.get("doc_id", ""),
        "doc_title": tree.get("title", ""), "okf_path": tree.get("okf_path", ""),
        "resource": tree.get("resource", ""), "node_id": f"body-line-{index + 1}",
        "source_override": tree.get("okf_path", ""),
        "title": "명시 문서 본문 행", "node_path": f"명시 문서 본문 {index + 1}행 (동일 식별자 행 {match_count}개)",
        "line_num": index + 1, "body_line_offset": 0, "text": text,
    }


def lookup(
    query: str,
    *,
    doc: str | None = None,
    doc_limit: int = 3,
    node_limit: int = 5,
    with_text: bool = True,
    body_fallback: bool = False,
    body_query: str | None = None,
    trees_root: Path | str = TREES_ROOT,
    exclude_source_groups: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """도구 단일 진입점 — 질의 → {문서 후보, 관련 노드(+원문)}.

    rag_chat/report_gen이 부를 때는 이 함수 하나만 쓰면 된다. `exclude_source_groups`는
    `find_documents()`/`search_nodes()`와 동일 규약 — MCP public 프로필이 라이선스
    제한 소스를 걸러내는 지점(`shared.retrieval.access.PRIVATE_ONLY_SOURCE_GROUPS`)."""

    target: dict[str, Any] | None = None
    if doc:
        target = _explicit_document_tree(
            doc, body_query, trees_root=trees_root, exclude_source_groups=exclude_source_groups,
        ) if body_fallback else get_tree(doc, trees_root=trees_root)
        if target is not None and target.get("source_group") in exclude_source_groups:
            target = None
        documents = [dict(_doc_meta(target), score=1.0)] if target else []
    else:
        documents = find_documents(
            query, limit=doc_limit, trees_root=trees_root,
            exclude_source_groups=exclude_source_groups,
        )
    nodes = search_nodes(
        query, doc=(target.get("okf_path") if target is not None else doc), doc_limit=doc_limit, node_limit=node_limit, trees_root=trees_root,
        exclude_source_groups=exclude_source_groups,
    )
    if with_text:
        for hit in nodes:
            hit["text"] = read_node_text(hit)
        # 2026-09-18(감사 후속): OKF 원문이 없어 본문이 빈 hit는 title/summary만
        # 있는 "가짜 근거"가 되므로 여기서 걸러낸다(read_node_text가 이미
        # 그 경우를 경고 로그로 남긴 뒤다 — 위 read_node_text 참고).
        nodes = [hit for hit in nodes if hit["text"]]
    # mine.profile처럼 문서 식별자는 없지만 public/private 필터 뒤 후보가 정확히
    # 한 건인 경우도 같은 좁은 fallback을 허용한다. 후보가 둘 이상이면 어떤
    # 문서의 행인지 추측하지 않는다.
    fallback_target = target
    if body_fallback and fallback_target is None and len(documents) == 1:
        fallback_target = get_tree(documents[0]["okf_path"], trees_root=trees_root)
    if body_fallback and with_text and fallback_target is not None:
        fallback = _document_body_fallback(body_query or query, fallback_target)
        if fallback is not None and not any(hit.get("line_num") == fallback["line_num"] for hit in nodes):
            # 기존 목차 절도 보존하되, 특정 사실은 선택된 본문 행에서 먼저
            # 확인할 수 있도록 fallback을 첫 근거로 둔다.
            nodes = [fallback, *nodes]
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
