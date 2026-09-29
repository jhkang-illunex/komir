"""기간별 보고서 검색 결과를 제목·발행일·본문 발췌와 함께 표시한다."""
from __future__ import annotations

from rag_core.ragkit.chatbot_events import extract_markdown_tables


def render_period_report_search(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    actions = list(getattr(action_plan, "actions", ()) or ())
    if (len(actions) != 1 or getattr(actions[0], "action_id", None) != "document.retrieve"
            or "보고서" not in (getattr(actions[0].slots, "topic", "") or "")):
        return None
    matches = [
        (index, item) for index, item in enumerate(evidence, 1)
        if getattr(item, "section", "") == "기간별 보고서 검색"
        and "게시일 | 보고서 | 제목" in getattr(item, "text", "")
    ]
    if len(matches) != 1:
        return None
    evidence_index, item = matches[0]
    tables = extract_markdown_tables(item.text)
    if not tables:
        return None
    table = tables[0]
    columns = [str(column).strip() for column in table["columns"]]
    try:
        date_i, source_i = columns.index("게시일"), columns.index("보고서")
        title_i, content_i = columns.index("제목"), columns.index("내용 발췌")
    except ValueError:
        return None
    lines = [f"기간 내 확인된 보고서 {len(table['rows'])}건입니다."]
    for row in table["rows"]:
        if len(row) <= max(date_i, source_i, title_i, content_i):
            continue
        published = row[date_i].strip()
        source = row[source_i].strip()
        title = row[title_i].strip()
        content = row[content_i].strip()
        if not title or not content:
            continue
        lines.append(f"\n- {published} · {source} · {title}\n  내용: {content[:700]}")
    if len(lines) == 1:
        return None
    return "\n".join(lines), {evidence_index}
