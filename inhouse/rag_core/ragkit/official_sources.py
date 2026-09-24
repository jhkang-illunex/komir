"""허용 공식 문서 출처의 사용자 공개 메타데이터."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OfficialSource:
    name: str
    url: str


_SOURCES: tuple[tuple[frozenset[str], OfficialSource], ...] = (
    (frozenset({"usgs"}), OfficialSource("USGS Mineral Commodity Summaries", "https://www.usgs.gov/centers/national-minerals-information-center/mineral-commodity-summaries")),
    (frozenset({"조달청보고서"}), OfficialSource("조달청 주간시장동향", "https://www.pps.go.kr/bichuk/bbs/list.do?key=00826")),
    (frozenset({"jodalcheong"}), OfficialSource("조달청 주간시장동향", "https://www.pps.go.kr/bichuk/bbs/list.do?key=00826")),
    (frozenset({"kotra"}), OfficialSource("KOTRA 국가정보", "https://www.kotra.or.kr/")),
    (frozenset({"iea"}), OfficialSource("IEA Global Critical Minerals Outlook 2025", "https://www.iea.org/reports/global-critical-minerals-outlook-2025")),
    (frozenset({"scrreen"}), OfficialSource("EU SCRREEN Factsheets", "https://scrreen.eu/crms-2023/")),
)


def _source_tokens(source: str) -> set[str]:
    return {token for token in re.split(r"[^0-9a-z가-힣]+", source.casefold()) if token}


def official_source(source: str | None) -> OfficialSource | None:
    """Return metadata only when the source itself has an exact allowlisted token."""

    tokens = _source_tokens(source or "")
    for required, metadata in _SOURCES:
        if required <= tokens:
            return metadata
    return None


def official_source_url(source: str | None) -> str | None:
    metadata = official_source(source)
    return metadata.url if metadata else None


def public_source_label(source: str | None) -> str:
    """Hide storage paths and DB identifiers from user-facing citations."""

    metadata = official_source(source)
    if metadata:
        return metadata.name
    value = source or ""
    if value.casefold().startswith("public.") or "KO_" in value:
        return "KOMIS 공식 데이터"
    if "/" in value or "\\" in value or value.casefold().endswith((".md", ".pdf", ".hwp", ".xlsx")):
        return "공식 문서 원문"
    return value or "확인된 출처"
