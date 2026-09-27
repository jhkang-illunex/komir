"""광종정보 Evidence의 결정적 문장 renderer."""
from __future__ import annotations

from ..chatbot_events import extract_markdown_tables


def render_mineral_info(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    actions = list(getattr(action_plan, "actions", ()) or ())
    if len(actions) != 1 or actions[0].action_id != "document.retrieve":
        return None
    topic = (getattr(actions[0].slots, "topic", "") or "").replace(" ", "")
    is_usage = any(token in topic for token in ("용도", "어디에쓰", "어디쓰", "쓰여", "사용처", "활용처"))
    for index, item in enumerate(evidence, 1):
        if getattr(item, "action_id", None) != "document.retrieve":
            continue
        for table in extract_markdown_tables(getattr(item, "text", "")):
            keys = [column.strip() for column in table["columns"]]
            if not {"광종", "속성", "값"} <= set(keys):
                continue
            mineral_i, key_i, value_i = keys.index("광종"), keys.index("속성"), keys.index("값")
            values = {row[key_i]: row[value_i] for row in table["rows"] if len(row) > value_i}
            mineral = next((row[mineral_i] for row in table["rows"] if len(row) > mineral_i), None)
            if is_usage and values.get("uses"):
                return f"{mineral}의 주요 용도는 {values['uses']}입니다.", {index}
            if not is_usage and mineral and values.get("element_symbol") and values.get("atomic_number") and values.get("characteristics"):
                return (f"{mineral}은(는) 원소기호 {values['element_symbol']}, 원자번호 {values['atomic_number']}의 금속이며, "
                        f"주요 특성은 {values['characteristics']}입니다."), {index}
    return None
