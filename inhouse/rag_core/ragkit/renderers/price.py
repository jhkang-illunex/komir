"""가격 비교 Evidence의 결정적 renderer."""
from __future__ import annotations

from ..chatbot_events import extract_markdown_tables


def render_price_comparison(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    """두 광종의 공통 기간 변동률을 요청 순서대로 렌더링한다."""
    actions = getattr(action_plan, "actions", [])
    if len(actions) != 1 or getattr(actions[0], "action_id", None) != "price.compare":
        return None
    action = actions[0]
    requested = list(getattr(action.slots, "minerals", None) or [])
    rows: dict[str, float] = {}
    cited: set[int] = set()
    for index, item in enumerate(evidence, 1):
        if getattr(item, "action_id", None) != "price.compare":
            continue
        cited.add(index)
        for table in extract_markdown_tables(item.text):
            keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
            try:
                mineral_index, pct_index = keys.index("mineral"), keys.index("pct_change")
            except ValueError:
                continue
            for row in table["rows"]:
                try:
                    rows[row[mineral_index]] = float(row[pct_index].replace(",", "").replace("%", ""))
                except (ValueError, AttributeError):
                    continue
    if len(requested) != 2 or any(name not in rows for name in requested):
        return None
    months = getattr(getattr(action.slots, "period", None), "trailing_months", None)
    period_label = f"최근 {months // 12}년" if months and months % 12 == 0 else f"최근 {months}개월" if months else "공통 관측기간"
    return (f"{period_label} {requested[0]}·{requested[1]} 가격 비교입니다. 비교 차트는 아래에 표시합니다. "
            f"같은 기간 {requested[0]} {rows[requested[0]]:+.2f}%, {requested[1]} {rows[requested[1]]:+.2f}%입니다."), cited
