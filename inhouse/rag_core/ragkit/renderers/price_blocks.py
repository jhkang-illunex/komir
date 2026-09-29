"""가격 기반 복합 질의를 조립하는 공통 renderer.

가격 Action은 공통으로 사용하고, 동반 블록을 무역 순위·세계 생산량 YoY·가격
전망으로 선택한다. 대상 Action 조합만 명시적으로 매칭한다.
"""
from __future__ import annotations

import math

from ..chatbot_events import extract_markdown_tables
from .price import price_display_unit, price_series_observations


def _keys(table):
    return [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]


def _number(value):
    try:
        number = float(str(value).replace(",", "").replace("%", "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _fmt(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _country_rows(item):
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
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


def _yoy_records(item):
    """세계 생산량 YoY 표에서 전년·당년 물량과 증감률을 함께 읽는다."""
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        find = lambda *names: next((i for i, key in enumerate(keys) if key in names), None)
        mineral_i = find("mineral", "광종")
        prior_year_i = find("prior_year", "previous_year", "전년")
        prior_tonnes_i = find("prior_tonnes", "prior_ton", "previous_tonnes", "전년생산량")
        year_i = find("year", "calendar_year", "연도")
        tonnes_i = find("tonnes", "ton", "production_tonnes", "생산량")
        change_tonnes_i = find("change_tonnes", "delta_tonnes", "증감량")
        pct_i = find("pct_change", "change_pct", "yoy_pct", "증감률")
        if (prior_year_i is None or prior_tonnes_i is None or year_i is None
                or tonnes_i is None or pct_i is None):
            continue
        records = []
        for row in table["rows"]:
            required_indices = [prior_year_i, prior_tonnes_i, year_i, tonnes_i, pct_i]
            if max(required_indices) >= len(row):
                continue
            try:
                prior_year = int(str(row[prior_year_i]).strip()[:4])
                year = int(str(row[year_i]).strip()[:4])
                prior_tonnes = _number(row[prior_tonnes_i])
                tonnes = _number(row[tonnes_i])
                pct = _number(row[pct_i])
            except (TypeError, ValueError):
                continue
            if prior_tonnes is None or tonnes is None or pct is None:
                continue
            change_tonnes = (
                _number(row[change_tonnes_i])
                if change_tonnes_i is not None and change_tonnes_i < len(row)
                else tonnes - prior_tonnes
            )
            records.append({
                "mineral": row[mineral_i].strip() if mineral_i is not None and mineral_i < len(row) else None,
                "prior_year": prior_year, "prior_tonnes": prior_tonnes,
                "year": year, "tonnes": tonnes,
                "change_tonnes": change_tonnes, "pct": pct,
            })
        if records:
            return records
    return []


def _yoy_rows(item):
    """하위 호환용 YoY 연도·증감률 추출기."""
    return [(record["year"], record["pct"]) for record in _yoy_records(item)]


def _signed(value):
    number = _number(value)
    if number is None or number == 0:
        return "0"
    return ("+" if number > 0 else "-") + _fmt(abs(number))


def _forecast_row(item):
    """정규화된 ``forecast.price`` 표의 첫 유효 행을 읽는다."""
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        required = {"forecast_date", "forecast_period", "current_price", "predicted_price", "unit"}
        if not required <= set(keys) or not table["rows"]:
            continue
        row = table["rows"][0]
        values = {}
        for key in required:
            index = keys.index(key)
            if index >= len(row) or not str(row[index]).strip():
                break
            values[key] = str(row[index]).strip()
        if len(values) != len(required):
            continue
        current = _number(values["current_price"])
        predicted = _number(values["predicted_price"])
        if current is not None and predicted is not None:
            return values["forecast_date"], values["forecast_period"], current, predicted, values["unit"]
    return None


def _matches(action, evidence):
    requirement_id = getattr(action, "requirement_id", None)
    return [(index, item) for index, item in enumerate(evidence, 1)
            if getattr(item, "requirement_id", None) == requirement_id]


def _successful(action, action_results):
    if not action_results:
        return True
    for result in action_results:
        if getattr(result, "requirement_id", None) == getattr(action, "requirement_id", None):
            return getattr(result, "status", None) == "success"
    return True


def _actions(action_plan):
    actions = list(getattr(action_plan, "actions", ()) or ())
    if len(actions) != 2 or sum(item.action_id == "price.series" for item in actions) != 1:
        return None
    price = next(item for item in actions if item.action_id == "price.series")
    companion = next(item for item in actions if item is not price)
    if companion.action_id not in {"trade.country_rank", "resource.yoy"}:
        return None
    return price, companion


def render_price_rank_yoy_blocks(evidence: list, action_plan, action_results=None):
    """MP03(price+rank)와 MP04(price+YoY)를 같은 조립 진입점에서 처리한다."""
    pair = _actions(action_plan)
    if pair is None:
        return None
    price_action, companion_action = pair
    if not _successful(price_action, action_results) or not _successful(companion_action, action_results):
        return None
    mineral = getattr(price_action.slots, "mineral", None)
    companion_mineral = getattr(companion_action.slots, "mineral", None)
    if not mineral or companion_mineral and companion_mineral != mineral:
        return None

    price = next(((index, item, price_series_observations(item.text))
                  for index, item in _matches(price_action, evidence)
                  if price_series_observations(item.text)), None)
    companion = next(((index, item) for index, item in _matches(companion_action, evidence)), None)
    if price is None or companion is None:
        return None
    pidx, price_item, points = price
    cidx, companion_item = companion

    if companion_action.action_id == "resource.yoy":
        yoy = _yoy_records(companion_item)
        if not yoy:
            return None
        yearly = {}
        for observed, value in points:
            yearly.setdefault(observed.year, []).append(value)
        price_unit = price_display_unit(getattr(price_item, "unit", None))
        price_sentences = []
        production_sentences = []
        for record in yoy:
            year = record["year"]
            if year not in yearly:
                continue
            average = sum(yearly[year]) / len(yearly[year])
            price_suffix = f" {price_unit}" if price_unit else ""
            price_sentences.append(f"{year}년 평균 가격은 {_fmt(average)}{price_suffix}입니다.")
            unit = str(getattr(companion_item, "unit", None) or "").strip()
            if not unit:
                return None
            delta = _signed(record["change_tonnes"])
            pct = float(record["pct"])
            direction = "증가" if pct > 0 else "감소" if pct < 0 else "변동이 없습니다"
            if direction == "변동이 없습니다":
                production_sentences.append(
                    f"{mineral}의 세계 생산량은 {record['prior_year']}년 {_fmt(record['prior_tonnes'])}{unit}에서 "
                    f"{record['year']}년 {_fmt(record['tonnes'])}{unit}으로 변동이 없었습니다({pct:+.2f}%)."
                )
            else:
                production_sentences.append(
                    f"{mineral}의 세계 생산량은 {record['prior_year']}년 {_fmt(record['prior_tonnes'])}{unit}에서 "
                    f"{record['year']}년 {_fmt(record['tonnes'])}{unit}으로 {delta}{unit} "
                    f"({pct:+.2f}%) {direction}했습니다."
                )
        if not price_sentences or not production_sentences:
            return None
        return (
            f"광물가격 : {mineral}의 " + " ".join(price_sentences)
            + "\n세계 생산량 : " + " ".join(production_sentences) + "\n"
            "※ 두 지표를 나란히 제시하며 상호 인과관계로 해석하지 않습니다.",
            {pidx, cidx},
        )

    countries = _country_rows(companion_item)
    if not countries:
        return None
    unit = price_display_unit(getattr(price_item, "unit", None))
    unit_text = f" {unit}" if unit else ""
    period = getattr(getattr(price_action.slots, "period", None), "kind", None)
    country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:3])
    if period == "latest":
        latest = points[-1]
        previous_month = [value for observed, value in points
                          if observed.year * 12 + observed.month == latest[0].year * 12 + latest[0].month - 1]
        if previous_month:
            average = sum(previous_month) / len(previous_month)
            pct = (latest[1] - average) / average * 100 if average else None
        else:
            pct = None
        if pct is not None:
            price_line = (f"광물가격 : {latest[0].isoformat()} 가격 "
                          f"{_fmt(latest[1])}{unit_text}, 전월 평균 대비 {pct:+.2f}%")
        else:
            price_line = (f"광물가격 : {latest[0].isoformat()} 기준 최근 가격 "
                          f"{_fmt(latest[1])}{unit_text}. 전월 평균 비교 자료는 확인되지 않았습니다")
        return f"수급지도 : 수입 상위국 {country_text}\n{price_line}", {pidx, cidx}
    if len(points) >= 2 and points[0][1]:
        change = (points[-1][1] - points[0][1]) / points[0][1] * 100
        high_date, high = max(points, key=lambda point: point[1])
        return (
            f"광물가격 : {points[0][0].isoformat()}~{points[-1][0].isoformat()} 가격 {change:+.2f}% 변동, "
            f"고점 {_fmt(high)}{unit_text}({high_date.strftime('%Y-%m')})\n"
            f"수급지도 : 수입국 {country_text}",
            {pidx, cidx},
        )
    observed, value = points[0]
    return (
        f"광물가격 : {observed.isoformat()} 기준 최근 확인 가격 {_fmt(value)}{unit_text}. "
        "조회된 가격 관측치가 1건이라 기간 변동률과 추세는 계산할 수 없습니다.\n"
        f"수급지도 : 수입 상위국 {country_text}",
        {pidx, cidx},
    )


def render_price_forecast_blocks(evidence: list, action_plan, action_results=None):
    """FBQ81의 5개 광종 가격·전망을 광종별 근거로 결합한다.

    실행 순서가 아니라 광종 슬롯과 requirement_id로 가격·전망을 짝짓는다.
    전망 원천이 일부 비어도 가격 근거를 버리지 않고 해당 광종에만 미제공을
    표시하며, 수치를 추정하거나 다른 광종의 전망을 재사용하지 않는다.
    """
    actions = list(getattr(action_plan, "actions", ()) or ())
    price_actions = [item for item in actions if item.action_id == "price.series"]
    forecast_actions = [item for item in actions if item.action_id == "forecast.price"]
    if len(actions) != 10 or len(price_actions) != 5 or len(forecast_actions) != 5:
        return None
    minerals = [getattr(item.slots, "mineral", None) for item in price_actions]
    if not all(minerals) or len(set(minerals)) != 5:
        return None
    forecast_by_mineral = {}
    for action in forecast_actions:
        mineral = getattr(action.slots, "mineral", None)
        if not mineral or mineral in forecast_by_mineral:
            return None
        forecast_by_mineral[mineral] = action

    records = []
    cited = set()
    for price_action in price_actions:
        mineral = price_action.slots.mineral
        forecast_action = forecast_by_mineral.get(mineral)
        if forecast_action is None:
            return None
        price_match = next(
            ((index, item, price_series_observations(item.text))
             for index, item in _matches(price_action, evidence)
             if price_series_observations(item.text)),
            None,
        )
        forecast_match = next(
            ((index, item, _forecast_row(item))
             for index, item in _matches(forecast_action, evidence)
             if _forecast_row(item)),
            None,
        )
        price_ok = _successful(price_action, action_results) and price_match is not None
        forecast_ok = _successful(forecast_action, action_results) and forecast_match is not None
        if not price_ok and not forecast_ok:
            continue
        price_text = "현재 가격 자료 없음"
        forecast_text = "전망 자료 없음"
        if price_ok:
            pidx, price_item, points = price_match
            observed, value = points[-1]
            raw_unit = str(getattr(price_item, "unit", "") or "").strip()
            unit = price_display_unit(raw_unit) or raw_unit or None
            price_text = f"현재가 {_fmt(value)}"
            if unit:
                price_text += f" {unit}"
            price_text += f" ({observed.isoformat()})"
            cited.add(pidx)
        if forecast_ok:
            fidx, _forecast_item, row = forecast_match
            forecast_date, period, _current, predicted, unit = row
            forecast_text = f"{period} 전망 {_fmt(predicted)} {unit} ({forecast_date})"
            cited.add(fidx)
        records.append(f"{mineral} : {price_text}, {forecast_text}")

    if not records:
        return None
    return (
        "광물정보 : 대상 광종 " + ", ".join(minerals) + "\n"
        "광물가격·가격예측 :\n" + "\n".join(records)
        + "\n※ 현재 가격과 전망은 광종별 원천·기준일을 따로 표시하며, 광종 간 수치를 직접 비교하지 않습니다.",
        cited,
    )
