"""단일 최신 재고량의 결정적 표기."""
from __future__ import annotations

from ..chatbot_events import extract_markdown_tables


_VERIFIED_UNITS = {"WT002": "톤"}

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
    rows = []
    for table in extract_markdown_tables(item.text):
        keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
        date_i = next((i for i, key in enumerate(keys) if key in {"기준일", "date", "crtr_ymd"}), None)
        mineral_i = next((i for i, key in enumerate(keys) if key in {"광종", "mineral"}), None)
        type_i = next((i for i, key in enumerate(keys) if key in {"재고 종류", "재고기준", "inventory_type"}), None)
        amount_i = next((i for i, key in enumerate(keys) if key in {"재고량", "inventory", "invt", "quantity"}), None)
        unit_i = next((i for i, key in enumerate(keys) if key in {"원시 단위 코드", "weight_unit_code"}), None)
        if None in {date_i, mineral_i, amount_i}:
            continue
        for row in table["rows"]:
            if max(date_i, mineral_i, amount_i) >= len(row):
                continue
            observed = row[date_i].strip()
            if len(observed) == 8 and observed.isdigit():
                observed = f"{observed[:4]}-{observed[4:6]}-{observed[6:]}"
            mineral = row[mineral_i].strip()
            inventory_type = row[type_i].strip() if type_i is not None and type_i < len(row) else "재고"
            amount = row[amount_i].strip()
            code = row[unit_i].strip().upper() if unit_i is not None and unit_i < len(row) else ""
            unit = _VERIFIED_UNITS.get(code)
            if code and not unit:
                unit = "단위 미확인"
            quantity = f"{amount} {unit}" if unit else amount
            rows.append(f"{observed} 기준 {mineral} {inventory_type} 재고량은 {quantity}입니다.")
        if rows:
            break
    if rows:
        return ("\n".join(rows), {index})
    return (
        f"최신 보유 재고량입니다. 기준일은 {item.as_of or '미확인'}입니다.",
        {index},
    )
