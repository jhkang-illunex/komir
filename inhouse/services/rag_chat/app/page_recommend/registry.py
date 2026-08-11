"""KOMIS 페이지 정의 레지스트리 — YAML 43건을 읽어 검증·조회한다.

이식 출처: komis-report-generator-main `search/registry.py`(2026-08-11 스냅샷).
원본에는 YAML을 `resources/registry/generated/{services,routing-index}.json` +
`page.schema.json`으로 미리 굽고(build_registry) CI에서 최신인지 확인하는
(check_registry) 빌드 단계가 있었는데, 이식하면서 뺐다 — 같은 레지스트리가 저장소에
두 벌(YAML 정본 + 생성 JSON)로 남고 그 둘을 동기화하는 CLI까지 komir에 들여올
이유가 없다(빌드 스텝 자체가 없음). 대신 서비스 기동 시 `load_source_registry()`로
YAML을 직접 읽는다(실측 로드 시간은 아래 스모크 테스트 기록 참고)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .models import PageDefinition

PAGE_ROOT = Path(__file__).resolve().parent / "resources" / "registry" / "pages"


class RegistryError(RuntimeError):
    """Raised when the page registry cannot be loaded or is internally inconsistent."""


class ServiceRegistry:
    """Validated lookup and lexical-selection index for page definitions."""

    def __init__(self, pages: Iterable[PageDefinition]) -> None:
        page_list = sorted(pages, key=lambda item: item.page_id)
        self._pages = {page.page_id: page for page in page_list}
        if len(self._pages) != len(page_list):
            raise RegistryError("duplicate page_id found")

        self._aliases: dict[str, str] = {}
        for page in page_list:
            for alias in page.aliases:
                if alias in self._pages or alias in self._aliases:
                    raise RegistryError(f"duplicate or conflicting page alias: {alias}")
                self._aliases[alias] = page.page_id

        page_ids = set(self._pages)
        for page in page_list:
            for distinction in page.routing.distinguish_from:
                if distinction.page_id not in page_ids:
                    raise RegistryError(
                        f"{page.page_id} distinguishes unknown page {distinction.page_id}"
                    )

    @property
    def pages(self) -> list[PageDefinition]:
        """Return registered pages in stable page-ID order."""

        return list(self._pages.values())

    @property
    def page_ids(self) -> set[str]:
        """Return the set of canonical page identifiers."""

        return set(self._pages)

    def get(self, page_id_or_alias: str) -> PageDefinition:
        """Resolve a canonical page ID or alias to its definition."""

        canonical_id = self._aliases.get(page_id_or_alias, page_id_or_alias)
        try:
            return self._pages[canonical_id]
        except KeyError as exc:
            raise RegistryError(f"unknown page_id: {page_id_or_alias}") from exc

    def routing_index(self) -> list[dict[str, Any]]:
        """Serialize the compact routing index for all registered pages."""

        return [page.routing_index_entry() for page in self.pages]

    def lexical_candidates(self, question: str, limit: int = 3) -> list[str]:
        """Rank page IDs by deterministic lexical overlap with a question."""

        normalized = question.strip().casefold()
        scored: list[tuple[int, str]] = []
        for page in self.pages:
            score = 0
            if page.identity.name.casefold() in normalized:
                score += 10
            for keyword in page.routing.keywords:
                if keyword.casefold() in normalized:
                    score += 3
            for phrase in page.routing.use_when:
                for token in phrase.casefold().split():
                    cleaned = token.strip("·,()[]{}")
                    if len(cleaned) >= 2 and cleaned in normalized:
                        score += 1
            if score:
                scored.append((score, page.page_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [page_id for _, page_id in scored[:limit]]

    def selection_context(self, page_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Build LLM selection context for a bounded set of page IDs."""

        result = []
        for page_id in page_ids:
            page = self.get(page_id)
            result.append(
                {
                    "page_id": page.page_id,
                    "section": page.identity.section,
                    "name": page.identity.name,
                    "summary": page.routing.summary,
                    "use_when": page.routing.use_when,
                    "do_not_use_when": page.routing.do_not_use_when,
                    "distinguish_from": [
                        item.model_dump(mode="json") for item in page.routing.distinguish_from
                    ],
                    "example_queries": page.routing.example_queries,
                }
            )
        return result


def load_source_registry(page_root: Path = PAGE_ROOT) -> ServiceRegistry:
    """Read and validate source YAML page definitions."""

    if not page_root.exists():
        raise RegistryError(f"page registry directory does not exist: {page_root}")
    pages: list[PageDefinition] = []
    for path in sorted(page_root.rglob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            pages.append(PageDefinition.model_validate(raw))
        except Exception as exc:
            raise RegistryError(f"invalid page registry file {path}: {exc}") from exc
    if not pages:
        raise RegistryError(f"no page YAML files found under {page_root}")
    return ServiceRegistry(pages)
