"""무역 집계 결과를 고정 규칙으로 설명하는 renderer."""
from __future__ import annotations

import re

from ..action_contract import import_dependency_high_threshold
from ..chatbot_events import extract_markdown_tables


def render_import_dependency_high(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    """수입상대국 1위 비중이 과반을 초과한 광종만 결정적으로 표시한다."""
    actions = getattr(action_plan, "actions", [])
    if not actions or any(
        getattr(action, "action_id", None) != "trade.country_rank"
        or not str(getattr(action, "requirement_id", "")).startswith("import_dependency_")
        for action in actions
    ):
        return None
    threshold = import_dependency_high_threshold()
    selected: list[str] = []
    cited: set[int] = set()
    observed_periods: list[str] = []
    by_requirement = {
        getattr(action, "requirement_id", ""): getattr(action.slots, "mineral", None)
        for action in actions
    }
    for index, item in enumerate(evidence, 1):
        requirement_id = getattr(item, "requirement_id", "")
        mineral = by_requirement.get(requirement_id)
        if not mineral:
            continue
        observed = str(getattr(item, "observed_period", None) or getattr(item, "as_of", None) or "")
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", observed)
        if len(dates) >= 2:
            observed_periods.append(f"{dates[0]}~{dates[-1]}")
        for table in extract_markdown_tables(item.text):
            keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
            try:
                country_index = keys.index("country")
                share_index = keys.index("share_pct")
            except ValueError:
                continue
            if not table["rows"]:
                continue
            row = table["rows"][0]
            try:
                share = float(row[share_index].replace(",", "").replace("%", ""))
            except (AttributeError, ValueError):
                continue
            cited.add(index)
            if share > threshold:
                selected.append(f"{mineral}({row[country_index]} {share:.2f}%)")
            break
    criterion = f"특정 수입상대국 비중이 {threshold:g}%를 초과"
    period_label = "확인된 수입 자료 기준"
    if observed_periods and len(set(observed_periods)) == 1:
        period_label = f"실제 확인된 자료 기간 {observed_periods[0]} 기준"
    if selected:
        heading = f"{period_label}으로 {criterion}한 광종은 {', '.join(selected)}입니다."
    else:
        heading = f"조회된 광종 중 {period_label}으로 {criterion}한 광종은 없습니다."
    return (
        heading + " 이는 수입상대국 집중도를 나타내는 운영 기준입니다. "
        "가격 전망 원천은 현재 연결되어 있지 않아 전망 수치나 방향은 제시하지 않습니다."
    ), cited
