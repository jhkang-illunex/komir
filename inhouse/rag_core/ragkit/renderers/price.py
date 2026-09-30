"""가격 비교 Evidence의 결정적 renderer."""
from __future__ import annotations

import re
import math
from datetime import date, datetime

from ..chatbot_events import extract_markdown_tables


# KOMIS public.st_code_mst live code-table values (verified 2026-09-26).
_PRICE_CODE_VALUES = {"PR001": "USD", "WT002": "톤"}


def natural_price_basis(unit: str | None) -> str | None:
    """가격기준과 원천 코드를 사용자 문장에 쓸 수 있는 순서로 풀어 쓴다."""
    values = {}
    for part in (unit or "").split(";"):
        key, separator, value = part.partition("=")
        if separator and value.strip():
            values[key.strip()] = value.strip()
    clauses = []
    basis = re.sub(r"\[dev_dummy\]\s*", "", values.get("가격기준", ""), flags=re.IGNORECASE).strip()
    if basis:
        clauses.append(f"가격 기준은 {basis}")
    if currency := values.get("통화코드"):
        if display_currency := _PRICE_CODE_VALUES.get(currency.upper()):
            clauses.append(f"통화는 {display_currency}")
    if weight := values.get("중량단위코드"):
        if display_weight := _PRICE_CODE_VALUES.get(weight.upper()):
            clauses.append(f"중량 단위는 {display_weight}")
    return ("이며, ".join(clauses) + "입니다.") if clauses else None


def price_display_unit(unit: str | None) -> str | None:
    """검증된 KOMIS 가격 코드를 차트·문장용 단위로 바꾼다."""
    values = {}
    for part in (unit or "").split(";"):
        key, separator, value = part.partition("=")
        if separator and value.strip():
            values[key.strip()] = value.strip()
    currency = _PRICE_CODE_VALUES.get(values.get("통화코드", "").upper())
    weight = _PRICE_CODE_VALUES.get(values.get("중량단위코드", "").upper())
    return f"{currency}/{weight}" if currency and weight else currency


def format_price(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def price_series_observations(text: str) -> list[tuple[date, float]]:
    """가격 표에서 일자와 통상 가격을 추출해 날짜순 표본을 만든다."""
    date_formats = ("%Y%m%d", "%Y-%m-%d", "%Y%m", "%Y-%m", "%Y")
    for table in extract_markdown_tables(text):
        keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
        date_idx = next((idx for idx, key in enumerate(keys)
                         if key in {"crtr_ymd", "price_date", "date", "trd_dt"}), None)
        price_idx = next((idx for idx, key in enumerate(keys)
                          if key in {"cmerc_prc", "price", "avg_price", "average_price"}), None)
        if date_idx is None:
            date_idx = next((idx for idx, column in enumerate(table["columns"])
                             if "일자" in column or column.strip().casefold() == "date"), None)
        if price_idx is None:
            price_idx = next((idx for idx, column in enumerate(table["columns"])
                              if "가격" in column and not any(
                                  term in column for term in ("최저", "최고", "하한", "상한"))), None)
        if date_idx is None or price_idx is None:
            continue
        result = []
        for row in table["rows"]:
            raw_date = row[date_idx].strip()
            observed_date = None
            for fmt in date_formats:
                try:
                    observed_date = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    continue
            try:
                price = float(row[price_idx].replace(",", "").replace("%", "").strip())
            except (ValueError, AttributeError):
                continue
            if observed_date is not None and math.isfinite(price):
                result.append((observed_date, price))
        if result:
            return sorted(result)
    return []


def _price_series_summary(item) -> str:
    points = price_series_observations(item.text)
    if not points:
        return "조회된 가격 표의 날짜·가격 열을 판독하지 못해 최고·최저와 추세를 계산하지 못했습니다."
    if len(points) == 1:
        observed_date, price = points[0]
        return f"최신 가격은 {format_price(price)} ({observed_date.isoformat()})입니다."
    prices = [price for _, price in points]
    high_date, high = max(points, key=lambda point: point[1])
    low_date, low = min(points, key=lambda point: point[1])
    first, latest = prices[0], prices[-1]
    latest_date = points[-1][0]
    high_low_pct = ((high - low) / low * 100) if low else None
    period_change = latest - first
    period_change_pct = (period_change / first * 100) if first else None
    clauses = [f"최신 가격은 {format_price(latest)} ({latest_date.isoformat()})",
               f"최고가는 {format_price(high)} ({high_date.isoformat()})",
               f"최저가는 {format_price(low)} ({low_date.isoformat()})"]
    range_text = f"고저 차는 {format_price(high - low)}"
    if high_low_pct is not None:
        range_text += f"(최저가 대비 {high_low_pct:+.2f}%)"
    clauses.append(range_text)
    change_text = f"시작 값 대비 최신 값 변화는 {format_price(abs(period_change))}"
    if period_change < 0:
        change_text = change_text.replace("변화는", "변화는 -")
    elif period_change > 0:
        change_text = change_text.replace("변화는", "변화는 +")
    if period_change_pct is not None:
        change_text += f" ({period_change_pct:+.2f}%)"
    clauses.append(change_text)
    sample_size = min(30, len(prices) // 2)
    if sample_size >= 2:
        previous = prices[-2 * sample_size:-sample_size]
        recent = prices[-sample_size:]
        prior_mean = sum(previous) / len(previous)
        recent_mean = sum(recent) / len(recent)
        trend_pct = ((recent_mean - prior_mean) / prior_mean * 100) if prior_mean else 0.0
        trend = "상승" if trend_pct > 0.5 else "하락" if trend_pct < -0.5 else "보합"
        clauses.append(f"최근 가격 흐름은 {trend} 추세({trend_pct:+.2f}%)입니다")
    else:
        clauses.append("최근 가격 흐름은 표본이 부족해 판정하기 어렵습니다")
    return ". ".join(clauses) + "."


def _latest_price_answer(item, mineral: str | None) -> str:
    points = price_series_observations(item.text)
    if not points:
        return "조회된 가격 표의 날짜·가격 열을 판독하지 못했습니다."
    latest_date, latest_price = points[-1]
    label = mineral or "요청 광종"
    unit = price_display_unit(item.unit)
    price_with_unit = f"{format_price(latest_price)} {unit or '(원천 단위 미확인)'}"
    if len(points) < 2:
        return f"{latest_date.isoformat()} 기준 {label} 가격은 {price_with_unit}입니다. 직전 보유 관측값이 없어 등락은 계산하지 않았습니다."
    previous_date, previous_price = points[-2]
    change = latest_price - previous_price
    change_pct = (change / previous_price * 100) if previous_price else None
    comparison = "전일" if (latest_date - previous_date).days == 1 else f"직전 관측일({previous_date.isoformat()})"
    sign = "+" if change > 0 else "-" if change < 0 else ""
    change_text = format_price(abs(change))
    if change_pct is None:
        return f"{latest_date.isoformat()} 기준 {label} 가격은 {price_with_unit}입니다. {comparison} 대비 {sign}{change_text} 변동했습니다."
    return (f"{latest_date.isoformat()} 기준 {label} 가격은 {price_with_unit}입니다. "
            f"{comparison} 대비 {sign}{change_text}({change_pct:+.2f}%) 변동했습니다.")


def _monthly_price_observations(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    buckets: dict[tuple[int, int], list[float]] = {}
    for observed_date, price in points:
        buckets.setdefault((observed_date.year, observed_date.month), []).append(price)
    return [(date(year, month, 1), sum(values) / len(values))
            for (year, month), values in sorted(buckets.items())]


def _yearly_observation_months(text: str) -> dict[int, int]:
    for table in extract_markdown_tables(text):
        keys = [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]
        try:
            date_index = keys.index("price_date")
            count_index = keys.index("observation_months")
        except ValueError:
            continue
        result = {}
        for row in table["rows"]:
            try:
                result[int(row[date_index][:4])] = int(float(row[count_index]))
            except (ValueError, TypeError):
                continue
        return result
    return {}


def _months_before(value: date, months: int) -> date:
    ordinal = value.year * 12 + value.month - 1 - months
    return date(ordinal // 12, ordinal % 12 + 1, 1)


def _price_year_over_year_answer(
    points: list[tuple[date, float]], mineral: str, unit: str, basis: str,
) -> str:
    """최신 보유월과 전년 동월의 가격 변화율을 계산한다.

    기본은 일별 관측값의 월평균이며, ``monthly_latest``는 각 월의 마지막
    관측값을 사용한다. 월을 건너뛰는 데이터는 조용히 다른 월과 비교하지 않고
    계산 불가로 닫는다.
    """
    if not points:
        return "계산 불가: 전년 동월 비교에 필요한 가격 관측값이 없습니다."
    buckets: dict[tuple[int, int], list[tuple[date, float]]] = {}
    for observed_date, value in points:
        buckets.setdefault((observed_date.year, observed_date.month), []).append((observed_date, value))
    latest_key = max(buckets)
    previous_key = (latest_key[0] - 1, latest_key[1])
    if previous_key not in buckets:
        return (f"계산 불가: 최신 보유월 {latest_key[0]:04d}-{latest_key[1]:02d}와 "
                "비교할 전년 동월 가격 관측값이 없습니다.")

    def monthly_value(values: list[tuple[date, float]]) -> float:
        if basis == "monthly_latest":
            return max(values, key=lambda row: row[0])[1]
        return sum(value for _, value in values) / len(values)

    current = monthly_value(buckets[latest_key])
    previous = monthly_value(buckets[previous_key])
    if previous == 0:
        return "계산 불가: 전년 동월 가격이 0이어서 변화율을 계산할 수 없습니다."
    change = current - previous
    pct = change / previous * 100
    basis_label = "월 최신 관측값" if basis == "monthly_latest" else "일별 가격의 월평균"
    return (f"{latest_key[0]:04d}-{latest_key[1]:02d} 기준 {mineral} 가격은 "
            f"{format_price(current)} {unit}이며, 전년 동월({previous_key[0]:04d}-{previous_key[1]:02d}) "
            f"{format_price(previous)} {unit} 대비 {pct:+.2f}% 변동했습니다. "
            f"비교 기준: {basis_label}.")


def _price_operation_answer(
    item, mineral: str | None, operation: str, period,
    threshold: float | None = None, yoy_basis: str | None = None,
    extrema_direction: str | None = None,
) -> str:
    points = price_series_observations(item.text)
    label = mineral or "요청 광종"
    unit = price_display_unit(item.unit) or "(원천 단위 미확인)"
    if operation == "year_over_year":
        return _price_year_over_year_answer(
            points, label, unit,
            yoy_basis or getattr(item, "price_yoy_basis", None) or "monthly_average",
        )
    if operation == "period_extrema":
        if not points:
            return "계산 불가: 지정 기간의 가격 관측값이 없습니다."
        direction = extrema_direction or "max"
        observed, value = (min(points, key=lambda row: row[1])
                           if direction == "min" else max(points, key=lambda row: row[1]))
        word = "최저가" if direction == "min" else "최고가"
        return (f"지정 기간 내 {label} {word}는 {format_price(value)} {unit}이며, "
                f"{word} 날짜(관측일)는 {observed.isoformat()}입니다.")
    if operation == "period_average_delta":
        if not points:
            return "계산 불가: 조회된 가격 표의 날짜·가격 열을 판독하지 못했습니다."
        latest_date, latest_price = points[-1]
        average = sum(value for _, value in points) / len(points)
        if not average:
            return "계산 불가: 비교기간 평균 가격이 0이어서 변동률을 계산할 수 없습니다."
        months = getattr(period, "trailing_months", None)
        expected_start = _months_before(latest_date, months - 1) if months else None
        if (expected_start and points[0][0].year * 12 + points[0][0].month
                > expected_start.year * 12 + expected_start.month):
            return f"계산 불가: 최근 {months}개월 평균을 계산할 전체 관측기간이 확보되지 않았습니다."
        period_label = (f"최근 {months // 12}년" if months and months % 12 == 0
                        else f"최근 {months}개월" if months else "조회 기간")
        pct = (latest_price - average) / average * 100
        return (f"{latest_date.isoformat()} 기준 {label} 가격은 {format_price(latest_price)} {unit}입니다. "
                f"{period_label} 평균 대비 {pct:+.2f}%입니다.")

    if operation == "significant_daily_rise":
        threshold = threshold or 5.0
        if len(points) < 2:
            return (f"최근 조회기간에 가격 관측값이 {len(points)}건뿐이라 전일 대비 {threshold:g}% 이상 "
                    "상승 여부를 판정할 수 없어 같은 날 관련 뉴스는 조회하지 않았습니다.")
        rises = []
        for (prior_date, prior), (observed, value) in zip(points, points[1:]):
            if prior and observed.toordinal() - prior_date.toordinal() <= 7:
                pct = (value - prior) / prior * 100
                if pct >= threshold:
                    rises.append((observed, value, pct))
        if not rises:
            return (f"연속 가격 관측 구간에서 전일 대비 {threshold:g}% 이상 상승한 날을 찾지 못해 "
                    "같은 날 관련 뉴스는 조회하지 않았습니다.")
        observed, value, pct = max(rises, key=lambda row: row[2])
        return (f"광물가격 : {observed.isoformat()} {label} 가격은 전일 대비 {pct:+.2f}% 상승했습니다 "
                f"({format_price(value)} {unit}). '크게 상승'은 전일 대비 {threshold:g}% 이상 기준으로 판정했습니다.")

    monthly = _monthly_price_observations(points)
    if operation == "monthly_streak":
        if len(monthly) < 2:
            return "계산 불가: 월별 연속 추세를 계산하려면 최소 2개월의 가격 관측값이 필요합니다."
        latest_month, latest_average = monthly[-1]
        previous_month, previous_average = monthly[-2]
        if latest_month.year * 12 + latest_month.month != previous_month.year * 12 + previous_month.month + 1:
            return "계산 불가: 최신 두 관측월이 연속하지 않아 월별 연속 추세를 계산할 수 없습니다."
        delta = latest_average - previous_average
        direction = "상승" if delta > 0 else "하락" if delta < 0 else "보합"
        index = len(monthly) - 1
        while index > 0:
            current_month, current_value = monthly[index]
            prior_month, prior_value = monthly[index - 1]
            if (current_month.year * 12 + current_month.month
                    != prior_month.year * 12 + prior_month.month + 1):
                break
            current_direction = "상승" if current_value > prior_value else "하락" if current_value < prior_value else "보합"
            if current_direction != direction:
                break
            index -= 1
        start_month, start_average = monthly[index]
        months = len(monthly) - 1 - index
        pct = ((latest_average - start_average) / start_average * 100) if start_average else None
        pct_text = f"{pct:+.2f}%" if pct is not None else "계산 불가"
        return (f"{latest_month.strftime('%Y-%m')} 기준 {label} 월평균 가격은 {format_price(latest_average)} {unit}입니다. "
                f"{months}개월째 {direction}세이며, {direction} 구간 시작은 "
                f"{start_month.strftime('%Y-%m')}입니다. 현재 월평균 가격은 "
                f"{format_price(latest_average)} {unit}({pct_text})입니다.")

    if operation == "yearly_average":
        if not monthly:
            return "계산 불가: 연도별 평균을 계산할 가격 관측값이 없습니다."
        years: dict[int, list[float]] = {}
        for observed_date, value in points:
            years.setdefault(observed_date.year, []).append(value)
        current_year = date.today().year
        observed_months = _yearly_observation_months(item.text)
        values = [
            f"{year}{' YTD' if year == current_year or observed_months.get(year, 12) < 12 else ''} "
            f"{format_price(sum(values) / len(values))}"
            for year, values in sorted(years.items(), reverse=True)
        ]
        return f"{label} 연도별 평균 가격은 [{', '.join(values)}]입니다. 단위: {unit}"
    return "지원하지 않는 가격 집계 요청입니다."


def render_price_comparison(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    """두 광종의 동일 기간 변동률과 각 가격기준을 렌더링한다.

    ``slots.windows``가 있으면 MCP가 창별로 반환한 비교 Evidence를 하나의
    표로 조립한다. 창별 행을 마지막 값으로 덮어쓰지 않아 3·6·12개월 요청이
    모두 보존된다.
    """
    actions = getattr(action_plan, "actions", [])
    if len(actions) != 1 or getattr(actions[0], "action_id", None) != "price.compare":
        return None
    action = actions[0]
    requested = list(getattr(action.slots, "minerals", None) or [])
    rows: dict[str, tuple[float, str]] = {}
    window_rows: dict[tuple[int, str], tuple[str, str, str, float, str]] = {}
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
            basis_indexes = [
                index for index, key in enumerate(keys)
                if key in {"price_criterion", "price_currency_code", "weight_unit_code"}
            ]
            basis_labels = {
                "price_criterion": "가격기준",
                "price_currency_code": "통화",
                "weight_unit_code": "단위",
            }
            for row in table["rows"]:
                try:
                    basis_parts = []
                    for basis_index in basis_indexes:
                        raw_value = row[basis_index].strip()
                        if not raw_value:
                            continue
                        key = keys[basis_index]
                        display_value = (_PRICE_CODE_VALUES.get(raw_value.upper())
                                         if key in {"price_currency_code", "weight_unit_code"}
                                         else raw_value)
                        if display_value:
                            basis_parts.append(f"{basis_labels[key]}={display_value}")
                    basis = ", ".join(basis_parts)
                    mineral = row[mineral_index]
                    pct = float(row[pct_index].replace(",", "").replace("%", ""))
                    rows[mineral] = (pct, basis)
                    windows = list(getattr(action.slots, "windows", None) or [])
                    if windows:
                        section = str(getattr(item, "section", ""))
                        match = re.search(r"최근\s*(\d+)\s*개월", section)
                        if match:
                            window = int(match.group(1))
                            start_key = keys.index("start_date") if "start_date" in keys else None
                            end_key = keys.index("end_date") if "end_date" in keys else None
                            start = row[start_key] if start_key is not None and start_key < len(row) else ""
                            end = row[end_key] if end_key is not None and end_key < len(row) else ""
                            window_rows[(window, mineral)] = (start, end, basis, pct, section)
                except (ValueError, AttributeError):
                    continue
    windows = sorted(set(getattr(action.slots, "windows", None) or []))
    if windows:
        if not window_rows or not requested:
            return None
        lines = ["| 비교기간 | 광종 | 시작일 | 종료일 | 변동률(%) | 가격기준 |"]
        lines.append("|---|---|---|---|---:|---|")
        for window in windows:
            for mineral in requested:
                record = window_rows.get((window, mineral))
                if record is None:
                    lines.append(f"| 최근 {window}개월 | {mineral} | - | - | 자료 없음 | - |")
                    continue
                start, end, basis, pct, _section = record
                lines.append(f"| 최근 {window}개월 | {mineral} | {start or '-'} | {end or '-'} | {pct:+.2f} | {basis or '가격기준 정보 없음'} |")
        return ("가격 변화율 비교\n" + "\n".join(lines) +
                "\n※ 광종별 가격기준·통화·중량단위가 다를 수 있어 변동률만 비교하며 절대가격의 우열로 해석하지 않습니다."), cited
    if len(requested) != 2 or any(name not in rows for name in requested):
        return None
    months = getattr(getattr(action.slots, "period", None), "trailing_months", None)
    period_label = f"최근 {months // 12}년" if months and months % 12 == 0 else f"최근 {months}개월" if months else "공통 관측기간"
    left_change, left_basis = rows[requested[0]]
    right_change, right_basis = rows[requested[1]]
    return (
        f"{period_label} {requested[0]}·{requested[1]} 가격의 같은 기간 변동률입니다. "
        f"{requested[0]} {left_change:+.2f}% ({left_basis or '가격기준 정보 없음'}), "
        f"{requested[1]} {right_change:+.2f}% ({right_basis or '가격기준 정보 없음'})입니다. "
        "이는 각 시계열의 단순 비교입니다. 가격기준·통화·중량단위와 시장 조건이 다를 수 있으므로 "
        "등락률을 같은 의미의 우열이나 원인으로 해석할 때 주의해야 합니다."
    ), cited


def render_price_series(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    """단일 가격 Evidence의 계산·기간별 표시·인용 결정을 담당한다."""
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
        return _price_operation_answer(item, getattr(slots, "mineral", None), slots.price_operation, period,
                                       getattr(slots, "significant_change_pct", None),
                                       getattr(slots, "price_yoy_basis", None),
                                       getattr(slots, "selection_direction", None)), {index}
    if getattr(slots, "selection_mode", None) == "ordinal":
        points = price_series_observations(item.text)
        position = getattr(slots, "selection_position", None)
        if not position or len(points) < position:
            return "계산 불가: 지정 기간에 요청한 순번의 가격 관측값이 없습니다.", {index}
        observed, value = sorted(points, key=lambda row: row[0])[position - 1]
        unit = price_display_unit(item.unit) or "(원천 단위 미확인)"
        label = getattr(slots, "mineral", None) or "요청 광종"
        return (f"지정 기간의 {position}번째 {label} 가격 관측값은 "
                f"{format_price(value)} {unit}이며, 관측일은 {observed.isoformat()}입니다."), {index}
    if period and period.kind == "latest":
        return _latest_price_answer(item, getattr(slots, "mineral", None)), {index}
    if period and period.kind == "trailing_months" and period.trailing_months:
        duration = "1년" if period.trailing_months == 12 else f"{period.trailing_months}개월"
        heading = f"최근 {duration} 가격 요약입니다."
    elif period and period.kind == "calendar_year" and period.calendar_year:
        heading = f"{period.calendar_year}년 가격 요약입니다."
    else:
        points = price_series_observations(item.text)
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", item.observed_period)
        latest = points[-1][0].isoformat() if points else (dates[-1] if dates else item.observed_period)
        heading = f"최신 보유 관측일({latest}) 가격 요약입니다."
    answer = f"{heading} 조회된 값 기준입니다."
    basis = natural_price_basis(item.unit)
    if basis:
        answer += f" {basis}"
    answer += f"\n\n{_price_series_summary(item)}"
    return answer, {index}


def price_series_display_table(table: dict) -> dict:
    """단일 가격 표에서 사용자에게 의미가 없는 내부 코드 열을 제거한다."""
    hidden_keys = {
        "price_currency_code", "weight_unit_code", "price_criterion_serial", "mnrl_prc_crtr_sn",
    }
    keep = [index for index, header in enumerate(table["columns"])
            if header.split("(", 1)[0].strip().casefold() not in hidden_keys]
    if len(keep) == len(table["columns"]):
        return table
    columns = [table["columns"][index] for index in keep]
    rows = [[row[index] for index in keep] for row in table["rows"]]
    markdown = "\n".join([
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ])
    return {**table, "columns": columns, "rows": rows, "markdown": markdown}


def latest_price_display_table(table: dict) -> dict:
    """직전값은 등락 계산에만 쓰고 최신 가격 표에는 최신 행 하나만 남긴다."""
    if not price_series_observations(table["markdown"]):
        return table
    date_index = next((index for index, column in enumerate(table["columns"])
                       if column.split("(", 1)[0].strip().casefold()
                       in {"crtr_ymd", "price_date", "date", "trd_dt"} or "일자" in column), None)
    if date_index is None:
        return table
    parsed_rows: list[tuple[date, list[str]]] = []
    for row in table["rows"]:
        raw_date = str(row[date_index]).strip()
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y%m", "%Y-%m", "%Y"):
            try:
                parsed_rows.append((datetime.strptime(raw_date, fmt).date(), row))
                break
            except ValueError:
                continue
    if not parsed_rows:
        return table
    rows = [max(parsed_rows, key=lambda item: item[0])[1]]
    markdown = "\n".join([
        "| " + " | ".join(table["columns"]) + " |",
        "| " + " | ".join("---" for _ in table["columns"]) + " |",
        "| " + " | ".join(rows[0]) + " |",
    ])
    return {**table, "rows": rows, "markdown": markdown}
