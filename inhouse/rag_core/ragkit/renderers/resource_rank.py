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


def render_resource_operation(evidence: list, action_plan, action_results=None, *, trace: dict | None = None) -> tuple[str, set[int]] | None:
    """Render typed resource filter/aggregate requests from the full ranking table.

    ``resource.rank`` remains the physical action.  This renderer applies only
    the semantic operation carried in typed slots; it never inspects the raw
    question and never invents a value when the requested row/field is absent.
    """
    def fail(reason: str):
        if trace is not None:
            trace.setdefault("attempts", []).append({"renderer": "resource_operation", "status": "not_selected", "reason": reason})
        return None

    actions = list(getattr(action_plan, "actions", ()) or ())
    if not actions or any(getattr(a, "action_id", None) != "resource.rank" for a in actions):
        return fail("action_contract_not_resource_rank")
    # Multiple resource operations share the same typed population.  Compute
    # their scalar outputs from each structured evidence table and keep the
    # derived values in the deterministic renderer; never send them back to
    # the generative answer model.
    if len(actions) > 1:
        values = {}
        for action in actions:
            op = getattr(action.slots, "resource_operation", None)
            if op not in {"average", "sum", "count", "min", "max"}:
                return fail(f"unsupported_or_missing_operation:{op}")
            req = getattr(action, "requirement_id", None)
            item = next((e for e in evidence if getattr(e, "requirement_id", None) == req), None)
            if item is None:
                item = next((e for e in evidence if getattr(e, "action_id", None) == "resource.rank"), None)
            if item is None:
                return fail(f"missing_structured_evidence:{req}")
            tables = extract_markdown_tables(getattr(item, "text", ""))
            if not tables:
                return fail("structured_evidence_has_no_table")
            table = tables[0]
            keys = [c.split("(", 1)[0].strip().casefold() for c in table["columns"]]
            if "total" not in keys:
                return fail("structured_table_missing_total")
            ti = keys.index("total")
            nums = [_number(row[ti]) for row in table["rows"] if ti < len(row)]
            nums = [n for n in nums if n is not None]
            if not nums:
                return fail("structured_table_has_no_numeric_total")
            values[op] = {"average": sum(nums) / len(nums), "sum": sum(nums),
                          "count": len(nums), "min": min(nums), "max": max(nums)}[op]
        if "average" in values and "sum" in values:
            values["difference"] = values["sum"] - values["average"]
        parts = []
        if "average" in values: parts.append(f"생산량 평균: {values['average']:,.2f}톤")
        if "sum" in values: parts.append(f"생산량 합계: {values['sum']:,.2f}톤")
        if "difference" in values: parts.append(f"합계와 평균의 차이: {values['difference']:,.2f}톤")
        if parts:
            cited = {
                i for i, item in enumerate(evidence, 1)
                if getattr(item, "action_id", None) == "resource.rank"
                and getattr(item, "kind", None) == "structured"
            }
            return "구조화된 자원 집계 결과입니다. " + " / ".join(parts), cited
        return fail("no_supported_aggregate_output")
    action = actions[0]
    operation = getattr(action.slots, "resource_operation", None)
    if operation in {None, "level", "first", "latest"}:
        return fail(f"unsupported_or_missing_operation:{operation}")
    outcomes = list(action_results or [])
    if outcomes and getattr(outcomes[0], "status", None) != "success":
        return fail("action_result_not_success")
    for index, item in enumerate(evidence, 1):
        tables = extract_markdown_tables(getattr(item, "text", ""))
        if not tables:
            continue
        table = tables[0]
        keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
        try:
            country_i, total_i = keys.index("country"), keys.index("total")
        except ValueError:
            continue
        rows = []
        for row in table["rows"]:
            if max(country_i, total_i) >= len(row):
                continue
            value = _number(row[total_i])
            if value is not None:
                rows.append((str(row[country_i]).strip(), value))
        if not rows:
            continue
        country = getattr(action.slots, "resource_country", None)
        if country:
            wanted = country.casefold()
            selected = next((value for name, value in rows if name.casefold() == wanted), None)
            if selected is None:
                return f"요청한 국가의 {action.slots.metric} 자료를 확인하지 못했습니다.", {index}
            return f"{country}의 {action.slots.metric} 값은 {selected:,.2f}톤입니다.", {index}
        if operation == "average": value = sum(v for _, v in rows) / len(rows)
        elif operation == "sum": value = sum(v for _, v in rows)
        elif operation == "count": return f"값이 있는 국가 수는 {len(rows)}개입니다.", {index}
        elif operation == "min": value = min(v for _, v in rows)
        elif operation == "max": value = max(v for _, v in rows)
        else: return None
        labels = {"average": "산술평균", "sum": "합계", "min": "최솟값", "max": "최댓값"}
        return f"{action.slots.metric} {labels[operation]}은 {value:,.2f}톤입니다.", {index}
    return fail("structured_table_not_renderable")
