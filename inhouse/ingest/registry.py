# -*- coding: utf-8 -*-
"""소스 그룹 레지스트리 — "landing의 어느 폴더가, 어떤 이름·정책으로 data_lake에 들어가나"를 데이터로.

2026-09-16 이전엔 USGS·조달청·Argus·광산자료가 각각 `build_okf_documents.py`의 파이썬 함수
(원본 루트·출력명·태그·유료 여부가 코드에 박힘)였다. 그룹을 하나 더 넣을 때마다 코드를 고쳐야
했고, 컨테이너 주간 체인(`--what all`)에 그룹이 들어가는지도 코드로 정해졌다. 이제 이 표 한 곳에서:

- `key`: CLI `--what <key>`, processing/<key>/(추출 산출물), landing/<landing_subdir>/ 기본값.
- `landing_subdir`: `INGEST_LANDING_DIR`가 설정된 새 레이아웃에서의 폴더명(단순·ASCII).
- `legacy_root`: `INGEST_LANDING_DIR` 미설정(레거시)일 때의 원본 위치 — 기존 호스트 동작 보존.
- `out_dirname`: 문서-OKF 출력 폴더 = `doc_chunk.src` = PageIndex `source_group`. **불변**(바꾸면
  기존 색인과 어긋난다).
- `allow_paid`: source_policy.py 유료출처 차단을 이 그룹만 우회(Argus, 2026-08-12 사용자 확인).
- `private_only`: public 프로필 노출 금지 — 정본은 `rag_core/retrieval/access.py`의
  `PRIVATE_ONLY_SOURCE_GROUPS`이고 여기 값과 일치해야 한다(tests/test_paths_registry.py가 검사).
- `in_all`: `--what all`(주간 체인)에 포함. 원본 루트가 없으면 예외가 아니라 건너뛴다(경고).
- `subdir_from_path`: 원본의 첫 하위 폴더명(광종)을 출력 하위 폴더·태그·commodity_hint로 쓴다.

`kind="artifacts"` 그룹(md/docx, rag_core/ragkit/ingest.py::load_documents)은 PDF 추출 파이프라인을
타지 않아 `landing_subdir`·`legacy_root`만 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import get_paths, repo_root, inhouse_root


@dataclass(frozen=True)
class SourceGroup:
    key: str
    landing_subdir: str
    legacy_root: Path | None
    out_dirname: str
    description: str
    tags: tuple[str, ...]
    kind: str = "pdf_group"          # pdf_group | artifacts
    allow_paid: bool = False
    private_only: bool = False
    in_all: bool = True
    subdir_from_path: bool = False

    def landing_root(self) -> Path | None:
        return get_paths().landing_root(self.landing_subdir, self.legacy_root)

    def extract_dir(self) -> Path:
        return get_paths().extract_dir(self.key)

    def okf_dir(self) -> Path:
        return get_paths().okf_documents / self.out_dirname


_REPO = repo_root()

GROUPS: tuple[SourceGroup, ...] = (
    SourceGroup(
        key="artifacts", landing_subdir="incoming", legacy_root=inhouse_root() / "incoming",
        out_dirname="산출물", description="발주처 제출용 최종 산출물(md·docx) + 외부공개 PDF 정제본",
        tags=("document-source",), kind="artifacts",
    ),
    SourceGroup(
        key="usgs", landing_subdir="usgs", legacy_root=_REPO / "documents" / "3. 생산매장량(USGS)",
        out_dirname="생산매장량_USGS", description="USGS Mineral Commodity Summaries",
        tags=("document-source", "USGS", "생산매장량"),
    ),
    SourceGroup(
        key="jodalcheong", landing_subdir="jodalcheong", legacy_root=_REPO / "documents" / "조달청보고서",
        out_dirname="조달청보고서", description="조달청 비철금속 시장동향·전망 보고서",
        tags=("document-source", "조달청보고서"),
    ),
    SourceGroup(
        key="argus", landing_subdir="argus",
        legacy_root=_REPO / "documents" / "보고서_2" / "Argus Metal_비철금속_2023~2026_일일 (1)",
        out_dirname="Argus_비철금속_일일",
        description="Argus Non-Ferrous Markets(비철금속 일일 시황, 유료구독 원문 — 내부 전용)",
        tags=("document-source", "Argus", "유료구독-내부전용"),
        allow_paid=True, private_only=True,
    ),
    SourceGroup(
        key="mines", landing_subdir="mines", legacy_root=_REPO / "nas_document" / "학습데이터",
        out_dirname="광산자료",
        description="광산별 생산·매장량 기업 공시 자료(연간보고서·기술보고서·산출 워크북)",
        tags=("document-source", "광산자료", "생산매장량"),
        subdir_from_path=True,
    ),
)

BY_KEY: dict[str, SourceGroup] = {g.key: g for g in GROUPS}
PDF_GROUPS: tuple[SourceGroup, ...] = tuple(g for g in GROUPS if g.kind == "pdf_group")
#: build_pgvector_okf.py가 다루는 doc_chunk.src 목록(문서-OKF 대용량 갈래).
OKF_SOURCE_GROUPS: tuple[str, ...] = tuple(g.out_dirname for g in PDF_GROUPS)
PRIVATE_ONLY_OUT_DIRNAMES: frozenset[str] = frozenset(g.out_dirname for g in GROUPS if g.private_only)


def get_group(key: str) -> SourceGroup:
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(f"unknown source group {key!r}; known: {', '.join(BY_KEY)}") from None


def describe() -> list[dict]:
    """`run_chain --list`·감사용: 그룹별 원본 루트 존재 여부까지."""
    out = []
    for g in GROUPS:
        root = g.landing_root()
        out.append({
            "key": g.key, "kind": g.kind, "out_dirname": g.out_dirname,
            "landing_root": str(root) if root else None,
            "exists": bool(root and root.is_dir()),
            "extract_dir": str(g.extract_dir()) if g.kind == "pdf_group" else None,
            "in_all": g.in_all, "allow_paid": g.allow_paid, "private_only": g.private_only,
        })
    return out
