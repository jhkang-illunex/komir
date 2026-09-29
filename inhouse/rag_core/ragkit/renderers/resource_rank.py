"""생산량·매장량 국가 순위의 결정형 복합 답변 renderer."""
from __future__ import annotations

import math
import re

from ..chatbot_events import extract_markdown_tables


def _number(value):
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _format_share(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _country_share_rows(item) -> list[tuple[str, float]]:
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
        country_i = next((i for i, key in enumerate(keys) if key in {"country", "국가"}), None)
        share_i = next((i for i, key in enumerate(keys)
                        if key == "share_pct" or key.startswith("비중")), None)
        if country_i is None or share_i is None:
            continue
        rows = []
        for row in table["rows"]:
            if max(country_i, share_i) >= len(row):
                continue
            country, share = str(row[country_i]).strip(), _number(row[share_i])
            if country and share is not None:
                rows.append((country, share))
        if rows:
            return rows
    return []


def _period_label(item, metric: str) -> str:
    observed = str(getattr(item, "observed_period", None)
                   or getattr(item, "as_of", None) or "")
    years = re.findall(r"(?<!\d)(\d{4})(?!\d)", observed)
    if not years:
        return "최신 확인 자료 기준"
    start, end = years[0], years[-1]
    if start == end:
        return f"{end}년 기준"
    if metric == "production":
        return f"{start}~{end}년 합산 기준"
    return f"{end}년 기준"


def _summary_line(mineral: str, metric: str, item, rows: list[tuple[str, float]]) -> str:
    label = "생산량" if metric == "production" else "매장량"
    period = _period_label(item, metric)
    text = str(getattr(item, "text", "") or "")
    denominator = (
        f"분모는 공식 세계 {label} 총량입니다."
        if "공식 세계 합계" in text
        else f"분모는 조회된 국가별 {label} 합계입니다."
    )
    if metric == "production":
        if len(rows) >= 2:
            first, second = rows[:2]
            return (
                f"{mineral} 생산량은 {period} 1위 {first[0]}({_format_share(first[1])}%), "
                f"2위 {second[0]}({_format_share(second[1])}%)입니다. {denominator}"
            )
        country, share = rows[0]
        return f"{mineral} 생산량은 {period} 1위가 {country}({_format_share(share)}%)입니다. {denominator}"

    if len(rows) >= 2:
        first, second = rows[:2]
        combined = first[1] + second[1]
        return (
            f"{mineral} 매장량은 {period} 상위 2개국이 {first[0]}({_format_share(first[1])}%) 및 "
            f"{second[0]}({_format_share(second[1])}%)이며, 합산 비중은 {_format_share(combined)}%입니다. {denominator}"
        )
    country, share = rows[0]
    return f"{mineral} 매장량은 {period} 1위가 {country}({_format_share(share)}%)입니다. {denominator}"


def render_production_reserves_pair(
    evidence: list, action_plan, action_results=None,
) -> tuple[str, set[int]] | None:
    """같은 광종의 생산량·매장량 Action 쌍을 표 근거에서 요약한다."""
    actions = list(getattr(action_plan, "actions", ()) or ())
    if len(actions) != 2 or any(
        getattr(action, "action_id", None) != "resource.rank" for action in actions
    ):
        return None
    metrics = [getattr(getattr(action, "slots", None), "metric", None) for action in actions]
    minerals = [getattr(getattr(action, "slots", None), "mineral", None) for action in actions]
    if set(metrics) != {"production", "reserves"} or not minerals[0] or minerals[0] != minerals[1]:
        return None

    outcomes = {getattr(item, "requirement_id", None): item for item in (action_results or [])}
    evidence_by_requirement: dict[str, list[tuple[int, object]]] = {}
    for index, item in enumerate(evidence, 1):
        requirement_id = getattr(item, "requirement_id", None)
        if requirement_id:
            evidence_by_requirement.setdefault(requirement_id, []).append((index, item))

    rendered: dict[str, str] = {}
    cited: set[int] = set()
    for action, metric in zip(actions, metrics):
        requirement_id = getattr(action, "requirement_id", None)
        outcome = outcomes.get(requirement_id)
        if outcome is not None and getattr(outcome, "status", None) != "success":
            continue
        selected = None
        for index, item in evidence_by_requirement.get(requirement_id, []):
            rows = _country_share_rows(item)
            if rows:
                selected = (index, item, rows)
                break
        if selected is None:
            continue
        index, item, rows = selected
        rendered[metric] = _summary_line(minerals[0], metric, item, rows)
        cited.add(index)

    if not rendered:
        return f"{minerals[0]} 생산량·매장량 상위 국가 자료를 확인하지 못했습니다.", set()

    lines = [rendered[metric] for metric in ("production", "reserves") if metric in rendered]
    missing = [metric for metric in ("production", "reserves") if metric not in rendered]
    if missing:
        missing_labels = "·".join("생산량" if metric == "production" else "매장량" for metric in missing)
        lines.append(f"{missing_labels} 자료는 확인되지 않았습니다.")
    return "\n\n".join(lines), cited
