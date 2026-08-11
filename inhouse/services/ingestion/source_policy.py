# -*- coding: utf-8 -*-
"""유료 출처 차단 정책 — 경로/라벨 문자열만으로 판정(별도 allowlist DB 불필요).

출처: komis-report-generator-main(외부 repo, 2026-08-11 확인)의
document_ingestion/source_policy.py 그대로 이식(로직 변경 없음). 병합계획
(documents/산출물/2026-W33_0810-0816/병합계획_komis-report-generator_260811.md)
결정②.

komir 쪽에도 동일한 유료출처 배제 필요가 이미 있었음(구 mineral_supply_risk/
CLAUDE.md 기록: 보고서_2의 AsianMetal·Argus 일부는 로컬 --zips로만 별도 처리) —
지금까지는 문서화된 관례로만 지켜지고 코드 강제가 없었는데, 이 모듈이 그 강제
지점이 된다.
"""
from __future__ import annotations

import re
import unicodedata

_TOKEN_SEPARATOR = re.compile(r"[\W_]+", flags=re.UNICODE)

_WOOD_MACKENZIE_MINERALS = {
    "copper",
    "nickel",
    "lithium",
    "동",
    "니켈",
    "리튬",
}


def normalized_source_tokens(value: str) -> tuple[str, ...]:
    """출처 라벨/경로를 정책 매칭용으로 정규화."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("\\", "/")
    return tuple(token for token in _TOKEN_SEPARATOR.split(normalized) if token)


def is_excluded_paid_source(value: str) -> bool:
    """라벨/경로가 영구 배제 대상 유료 출처에 해당하는지 여부."""

    normalized_tokens = normalized_source_tokens(value)
    tokens = set(normalized_tokens)
    compact = "".join(normalized_tokens)

    wood_mackenzie = (
        {"wood", "mackenzie"} <= tokens or "woodmackenzie" in compact or "우드맥킨지" in compact
    )
    if wood_mackenzie and tokens & _WOOD_MACKENZIE_MINERALS:
        return True

    argus_market = bool(
        tokens & {"metal", "metals", "비철금속"}
        or {"non", "ferrous"} <= tokens
        or "nonferrous" in compact
    )
    if "argus" in tokens and argus_market:
        return True

    asian_metal = {"asian", "metal"} <= tokens or "asianmetal" in compact
    return asian_metal and bool(tokens & {"lithium", "리튬"})
