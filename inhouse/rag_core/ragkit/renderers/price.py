"""가격 비교 Evidence의 결정적 renderer."""
from __future__ import annotations

import re

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


def render_price_series(evidence: list, action_plan, *, operation_answer, latest_answer,
                        summary, observations, natural_basis) -> tuple[str, set[int]] | None:
    """단일 가격 Evidence의 기간별 표시·인용 결정을 담당한다.

    계산 보조 함수는 기존 가격 도메인 구현을 주입받아, 이 단계에서는 renderer
    경계만 분리한다. 다음 단계에서 해당 보조 함수도 이 모듈로 이동한다.
    """
    actions = getattr(action_plan, "actions", [])
    if len(actions) != 1 or getattr(actions[0], "action_id", None) != "price.series":
        return None
    selected = [(index, item) for index, item in enumerate(evidence, 1)
                if getattr(item, "action_id", None) == "price.series"
                and (getattr(item, "unit", None) or "").startswith("가격기준=")
                and getattr(item, "observed_period", None)]
    if len(evidence) != 1 or len(selected) != 1:
        return None
    index, item = selected[0]
    slots = actions[0].slots
    period = getattr(slots, "period", None)
    if getattr(slots, "price_operation", None):
        return operation_answer(item, getattr(slots, "mineral", None), slots.price_operation, period), {index}
    if period and period.kind == "latest":
        return latest_answer(item, getattr(slots, "mineral", None)), {index}
    if period and period.kind == "trailing_months" and period.trailing_months:
        duration = "1년" if period.trailing_months == 12 else f"{period.trailing_months}개월"
        heading = f"최근 {duration} 가격 요약입니다."
    elif period and period.kind == "calendar_year" and period.calendar_year:
        heading = f"{period.calendar_year}년 가격 요약입니다."
    else:
        points = observations(item.text)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", item.observed_period)
        latest = points[-1][0].isoformat() if points else (dates[-1] if dates else item.observed_period)
        heading = f"최신 보유 관측일({latest}) 가격 요약입니다."
    answer = f"{heading} 조회된 값 기준입니다."
    basis = natural_basis(item.unit)
    if basis:
        answer += f" {basis}"
    answer += f"\n\n{summary(item)}"
    suffix = ("표에는 최신 관측값 1건을 표시했습니다."
              if len(observations(item.text)) == 1
              else "표와 차트는 조회된 가격값으로 작성했습니다.")
    answer += f"\n\n{suffix}"
    return answer, {index}
