"""단일 최신 재고량의 결정적 표기."""
from __future__ import annotations


def render_latest_inventory(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    actions = getattr(action_plan, "actions", [])
    if len(actions) != 1 or getattr(actions[0], "action_id", None) != "inventory.latest":
        return None
    selected = [(index, item) for index, item in enumerate(evidence, 1)
                if getattr(item, "action_id", None) == "inventory.latest"
                and (getattr(item, "unit", None) or "").startswith("재고기준=")]
    if len(selected) != 1:
        return None
    index, item = selected[0]
    return (
        f"최신 보유 재고량입니다. 기준일은 {item.as_of or '미확인'}입니다.\n\n{item.text}",
        {index},
    )
