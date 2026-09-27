"""인용 Evidence의 사용자 표시 메타데이터 renderer."""
from __future__ import annotations

import re

from ..menu_catalog import menu_source
from ..official_sources import official_source, public_source_label

_OPAQUE_PRICE_UNIT_CODE = re.compile(r"\b(?:PR|WT)\d+\b", re.IGNORECASE)


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
    return "DEV_DUMMY" if "개발용 더미" in (getattr(evidence, "caveat", None) or "") else None


def citation_sources(cited_indices: set[int], evidence: list) -> list[dict]:
    result = []
    for index, item in enumerate(evidence, 1):
        if index not in cited_indices:
            continue
        official = official_source(item.source)
        result.append({
            "index": index, "kind": item.kind, "source": public_source_label(item.source),
            "section": item.section, "as_of": item.as_of, "unit": user_visible_unit(item.unit),
            "data_status": data_status(item),
            "warnings": [item.caveat] if getattr(item, "caveat", None) else [],
            "requirement_id": getattr(item, "requirement_id", None),
            "action_id": getattr(item, "action_id", None),
            "observed_period": getattr(item, "observed_period", None),
            "menu_source": menu_source(getattr(item, "menu_page_id", None)),
            **({"official_url": official.url} if official else {}),
        })
    return result


def data_warnings(cited_indices: set[int], evidence: list) -> list[str]:
    return sorted({getattr(item, "caveat", None) for index, item in enumerate(evidence, 1)
                   if index in cited_indices and getattr(item, "caveat", None)})


def dummy_data_notice(cited_indices: set[int], evidence: list) -> str:
    warnings = data_warnings(cited_indices, evidence)
    return "\n\n" + "\n".join(f"⚠ {warning}" for warning in warnings) if warnings else ""


def partial_forecast_notice(warnings: list[str]) -> str:
    if "source_unavailable:price_forecast_partial" not in warnings:
        return ""
    return "\n\n※ 가격예측 데이터 원천이 아직 연결되지 않아 전망치와 현재가 비교는 제공하지 못했습니다."
