"""인용 Evidence의 사용자 표시 메타데이터 renderer."""
from __future__ import annotations

import re

from ..menu_catalog import menu_source
from ..official_sources import official_source, public_source_label

_OPAQUE_PRICE_UNIT_CODE = re.compile(r"\b(?:PR|WT)\d+\b", re.IGNORECASE)
_ACTION_SECTIONS = {
    "price.series": "광물가격", "price.compare": "광물가격 비교",
    "forecast.price": "가격예측", "inventory.latest": "광물 재고량",
    "trade.country_rank": "수출입 국가 순위", "trade.monthly": "수출입 현황",
    "trade.concentration": "수출입 집중도", "resource.rank": "광물 생산·매장량",
    "indicator.series": "광물 지표",
}


def public_section(item) -> str:
    """내부 테이블·SQL 식별자를 숨긴 사용자용 근거 구간 이름."""
    catalog_source = menu_source(getattr(item, "menu_page_id", None))
    if catalog_source:
        return catalog_source.get("source_label") or catalog_source.get("label") or ""
    section = str(getattr(item, "section", "") or "")
    if re.search(r"\b(?:KO|AI)_[A-Z0-9_]+\b|\bpublic\.[a-zA-Z0-9_]+", section):
        return _ACTION_SECTIONS.get(getattr(item, "action_id", None), "구조화 데이터")
    return section


def user_visible_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    visible = []
    for part in unit.split(";"):
        if _OPAQUE_PRICE_UNIT_CODE.search(part):
            continue
        value = re.sub(r"\[dev_dummy\]\s*", "", part, flags=re.IGNORECASE).strip()
        if value and not value.rstrip().endswith("="):
            visible.append(value)
    return "; ".join(visible) or None


def data_status(evidence) -> str | None:
    # 개발 단계에서는 더미 원천도 일반 결과로 표시한다. 원천 상태는 Evidence에
    # 내부 추적용으로만 보존하고 사용자 인용 메타데이터에는 노출하지 않는다.
    return None


def _user_visible_warning(caveat: str | None) -> str | None:
    """개발용 더미 표시는 숨기되, 다른 원천 검증 경고는 보존한다."""
    if caveat and "개발용 더미" not in caveat:
        return caveat
    return None


def citation_sources(cited_indices: set[int], evidence: list) -> list[dict]:
    result = []
    for index, item in enumerate(evidence, 1):
        if index not in cited_indices:
            continue
        hide_price_period = getattr(item, "action_id", None) == "price.series"
        official = official_source(item.source)
        catalog_source = menu_source(getattr(item, "menu_page_id", None))
        public_menu_source = ({key: value for key, value in catalog_source.items()
                              if key != "source_tables"} if catalog_source else None)
        result.append({
            "index": index, "kind": item.kind, "source": public_source_label(item.source),
            "section": public_section(item),
            "as_of": None if hide_price_period else item.as_of, "unit": user_visible_unit(item.unit),
            "data_status": data_status(item),
            "warnings": ([warning] if (warning := _user_visible_warning(getattr(item, "caveat", None))) else []),
            "requirement_id": getattr(item, "requirement_id", None),
            "action_id": getattr(item, "action_id", None),
            "observed_period": None if hide_price_period else getattr(item, "observed_period", None),
            "menu_source": public_menu_source,
            **({"official_url": official.url} if official else {}),
        })
    return result


def data_warnings(cited_indices: set[int], evidence: list) -> list[str]:
    return sorted({warning for index, item in enumerate(evidence, 1)
                   if index in cited_indices
                   if (warning := _user_visible_warning(getattr(item, "caveat", None)))})


def dummy_data_notice(cited_indices: set[int], evidence: list) -> str:
    warnings = data_warnings(cited_indices, evidence)
    return "\n\n" + "\n".join(f"⚠ {warning}" for warning in warnings) if warnings else ""


def partial_forecast_notice(warnings: list[str]) -> str:
    if "source_unavailable:price_forecast_partial" not in warnings:
        return ""
    return "\n\n※ 가격예측 데이터 원천이 아직 연결되지 않아 전망치와 현재가 비교는 제공하지 못했습니다."
