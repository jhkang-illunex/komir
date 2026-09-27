"""근거 표를 여러 Action의 사용자용 출력 형식으로 결합하는 결정적 renderer."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re

from .chatbot_events import extract_markdown_tables


def _keys(table):
    return [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]


def _number(value):
    try:
        value = float(str(value).replace(",", "").replace("%", "").strip())
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _date(value):
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y%m", "%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _price_points(item):
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        date_i = next((i for i, key in enumerate(keys)
                       if key in {"date", "price_date", "crtr_ymd", "trd_dt"}), None)
        price_i = next((i for i, key in enumerate(keys)
                        if key in {"price", "avg_price", "average_price", "cmerc_prc"}), None)
        if date_i is None or price_i is None:
            continue
        points = []
        for row in table["rows"]:
            if max(date_i, price_i) >= len(row):
                continue
            observed, price = _date(row[date_i]), _number(row[price_i])
            if observed is not None and price is not None:
                points.append((observed, price))
        if points:
            return sorted(points)
    return []


def _index_points(item):
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        date_i = next((i for i, key in enumerate(keys)
                       if key in {"date", "crtr_ymd", "index_date"}), None)
        value_i = next((i for i, key in enumerate(keys)
                        if key in {"index", "indx", "index_value", "지수"}), None)
        if date_i is None or value_i is None:
            continue
        points = []
        for row in table["rows"]:
            if max(date_i, value_i) >= len(row):
                continue
            observed, value = _date(row[date_i]), _number(row[value_i])
            if observed is not None and value is not None:
                points.append((observed, value))
        if points:
            return sorted(points)
    return []


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


def _yoy_rows(item):
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        year_i = next((i for i, key in enumerate(keys) if key in {"year", "calendar_year", "연도"}), None)
        pct_i = next((i for i, key in enumerate(keys)
                      if key in {"pct_change", "change_pct", "yoy_pct", "증감률"}), None)
        if year_i is None or pct_i is None:
            continue
        rows = []
        for row in table["rows"]:
            if max(year_i, pct_i) >= len(row):
                continue
            try:
                year = int(str(row[year_i]).strip()[:4])
            except ValueError:
                continue
            pct = _number(row[pct_i])
            if pct is not None:
                rows.append((year, pct))
        if rows:
            return rows
    return []


def _forecast_row(item):
    """정규화된 예측 표에서 첫 유효 행만 읽는다."""
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        required = {"forecast_date", "forecast_period", "current_price", "predicted_price", "unit"}
        if not required <= set(keys) or not table["rows"]:
            continue
        row = table["rows"][0]
        values = {key: row[keys.index(key)].strip() for key in required if keys.index(key) < len(row)}
        if len(values) != len(required):
            continue
        current, predicted = _number(values["current_price"]), _number(values["predicted_price"])
        if current is not None and predicted is not None and values["unit"]:
            return values["forecast_date"], values["forecast_period"], current, predicted, values["unit"]
    return None


def _fmt(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _document_text(item):
    return re.sub(r"\s+", " ", str(getattr(item, "text", ""))).strip()


def _news_titles(item, *, limit: int = 3):
    """자원뉴스 adapter의 구조화 표에서 제목만 보존해 읽는다."""
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        title_i = next((i for i, key in enumerate(keys)
                        if key in {"title", "headline", "제목", "기사제목"}), None)
        date_i = next((i for i, key in enumerate(keys)
                       if key in {"date", "published_at", "pub_date", "날짜", "게시일"}), None)
        if title_i is None:
            continue
        titles = []
        for row in table["rows"]:
            if title_i >= len(row):
                continue
            title = row[title_i].strip()
            if not title:
                continue
            published = row[date_i].strip() if date_i is not None and date_i < len(row) else ""
            titles.append(f"{title} ({published})" if published else title)
        if titles:
            return titles[:limit]
    return []


def _usage_sentence(text):
    """문서 근거에 명시된 용도 문장만 반환한다."""
    for sentence in re.split(r"(?<=[.!?。])\s+|\n+", text):
        if any(token in sentence for token in ("용도", "사용", "쓰입", "활용")):
            return sentence.strip(" -:;")
    return None


def _mineral_info_uses(item):
    """광종정보 adapter의 ``uses`` 행만 읽는다.

    YAML adapter는 문장형 원문이 아니라 속성 표를 반환하므로, 문서 검색의
    임의 문장에서 용도를 추정하는 ``_usage_sentence``와 분리한다.
    """
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        try:
            attribute_i, value_i = keys.index("속성"), keys.index("값")
        except ValueError:
            continue
        for row in table["rows"]:
            if max(attribute_i, value_i) < len(row) and row[attribute_i].strip() == "uses":
                value = row[value_i].strip()
                if value:
                    return value
    return None


def render_composite(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    """현재 연결된 표로 계산 가능한 복합 계약만 렌더링한다."""
    actions = list(getattr(action_plan, "actions", ()) or ())
    ids = [getattr(action, "action_id", None) for action in actions]
    by_action = {}
    for index, item in enumerate(evidence, 1):
        by_action.setdefault(getattr(item, "action_id", None), []).append((index, item))

    if ids and all(action_id == "trade.country_rank" for action_id in ids) and len(ids) == 5:
        matches = by_action.get("trade.country_rank", [])
        if len(matches) == 5:
            rows, cited = [], set()
            for action, (index, item) in zip(actions, matches):
                countries = _country_rows(item)
                if not countries:
                    return None
                country, share = countries[0]
                rows.append(f"{action.slots.mineral} : {country} ({_fmt(share)}%)")
                cited.add(index)
            return "광물정보 : 2차전지 원료 광종 리튬, 니켈, 코발트, 망간, 흑연\n핵심광물 수급지도 : 최근 12개월 수입 1위국\n" + "\n".join(rows), cited

    if ids == ["document.retrieve", "document.retrieve"]:
        docs = by_action.get("document.retrieve", [])
        if len(docs) == 2:
            left, right = _document_text(docs[0][1]), _document_text(docs[1][1])
            common = [term for term in ("리튬", "니켈", "코발트", "망간", "흑연", "희토류", "중국", "수출통제")
                      if term in left and term in right]
            if common:
                return (f"월간동향 : {getattr(docs[0][1], 'section', None) or '확인된 월간동향'} 주요 이슈\n"
                        f"자원뉴스 : {getattr(docs[1][1], 'section', None) or '확인된 주간 뉴스'} 주요 기사\n"
                        f"공통 이슈 : {', '.join(common)}", {docs[0][0], docs[1][0]})

    if ids.count("price.series") == 5 and ids.count("forecast.price") == 5 and len(ids) == 10:
        prices, forecasts = by_action.get("price.series", []), by_action.get("forecast.price", [])
        if len(prices) == len(forecasts) == 5:
            lines, cited = [], set()
            price_actions = [action for action in actions if action.action_id == "price.series"]
            for action, (pidx, price), (fidx, forecast) in zip(price_actions, prices, forecasts):
                points, frow = _price_points(price), _forecast_row(forecast)
                if not points or not frow:
                    return None
                _date, period, _base, predicted, unit = frow
                lines.append(f"{action.slots.mineral} : 현재가 {_fmt(points[-1][1])}, {period} 전망 {_fmt(predicted)} {unit}")
                cited.update({pidx, fidx})
            return ("광물정보 : 대상 광종 리튬, 니켈, 코발트, 망간, 흑연\n광물가격·가격예측 :\n" + "\n".join(lines) +
                    "\n※ 단위·가격 기준이 광종별로 달라 등락률 기준 비교를 권장합니다.", cited)

    if ids.count("indicator.series") == 1 and ids.count("document.retrieve") == 1 and len(ids) == 2:
        indices, docs = by_action.get("indicator.series", []), by_action.get("document.retrieve", [])
        if len(indices) == 1 and len(docs) == 1:
            points = _index_points(indices[0][1])
            document_action = next(action for action in actions if action.action_id == "document.retrieve")
            if "하락 주간" in (document_action.slots.topic or ""):
                declines = [
                    (observed, (value - prior) / prior * 100)
                    for (prior_date, prior), (observed, value) in zip(points, points[1:])
                    if prior and 1 <= (observed - prior_date).days <= 7 and value < prior
                ]
                titles = _news_titles(docs[0][1])
                if declines and titles:
                    observed, change = min(declines, key=lambda item: item[1])
                    week_start = observed - timedelta(days=observed.weekday())
                    return (f"광물종합지수 : {week_start.isoformat()} 주 {change:+.2f}% 하락\n"
                            "자원뉴스 : 같은 주 주요 기사\n" + "\n".join(f"- {title}" for title in titles) +
                            "\n※ 동반 관측 정보이며 지수 변동 원인으로 단정하지 않습니다.",
                            {indices[0][0], docs[0][0]})
            if len(points) >= 2 and points[0][1]:
                change = (points[-1][1] - points[0][1]) / points[0][1] * 100
                summary = _document_text(docs[0][1])[:300]
                return (f"광물종합지수 : {points[-1][0].strftime('%Y-%m')} {change:+.2f}% 변동\n"
                        f"월간동향 : {getattr(docs[0][1], 'section', None) or '월간동향'} 주요 내용 : {summary}",
                        {indices[0][0], docs[0][0]})

    if ids.count("forecast.price") == 1 and ids.count("document.retrieve") == 1 and len(ids) == 2:
        forecasts, docs = by_action.get("forecast.price", []), by_action.get("document.retrieve", [])
        if len(forecasts) == 1 and len(docs) == 1:
            row = _forecast_row(forecasts[0][1])
            if row:
                _date, period, base, predicted, unit = row
                direction = "상승" if predicted > base else "하락" if predicted < base else "보합"
                mineral = next((a.slots.mineral for a in actions if a.action_id == "forecast.price"), "요청 광종")
                document_action = next(action for action in actions if action.action_id == "document.retrieve")
                if "뉴스" in (document_action.slots.topic or ""):
                    titles = _news_titles(docs[0][1])
                    if not titles:
                        return None
                    return (f"가격예측 : {period} {mineral} 전망 방향 {direction} ({(predicted-base)/base*100:+.2f}%)\n"
                            "자원뉴스 : 최근 관련 기사\n" + "\n".join(f"- {title}" for title in titles),
                            {forecasts[0][0], docs[0][0]})
                return (f"가격예측 : {period} {mineral} 전망 방향 {direction} ({(predicted-base)/base*100:+.2f}%)\n"
                        f"월간동향 : {getattr(docs[0][1], 'section', None) or '월간동향'} {mineral} 전망 서술 요약 : {_document_text(docs[0][1])[:300]}",
                        {forecasts[0][0], docs[0][0]})

    if ids.count("trade.country_rank") == 1 and ids.count("forecast.price") == 1 and len(ids) == 2:
        imports, forecasts = by_action.get("trade.country_rank", []), by_action.get("forecast.price", [])
        if len(imports) == 1 and len(forecasts) == 1:
            countries, forecast = _country_rows(imports[0][1]), _forecast_row(forecasts[0][1])
            if countries and forecast:
                forecast_date, _period, base, predicted, unit = forecast
                mineral = next((action.slots.mineral for action in actions
                                if action.action_id == "forecast.price"), "요청 광종")
                country_text = ", ".join(f"{name} ({_fmt(share)}%)" for name, share in countries[:5])
                return (f"핵심광물 수급지도 : 수입 상위국 {country_text}\n"
                        f"가격예측 : {forecast_date} {mineral} 전망치 {_fmt(predicted)} {unit} "
                        f"(현재 대비 {(predicted-base)/base*100:+.2f}%)",
                        {imports[0][0], forecasts[0][0]})

    if {"price.series", "forecast.price", "resource.rank", "trade.country_rank"} == set(ids) and len(ids) == 4:
        price, forecast = by_action.get("price.series", []), by_action.get("forecast.price", [])
        production, imports = by_action.get("resource.rank", []), by_action.get("trade.country_rank", [])
        if all(len(items) == 1 for items in (price, forecast, production, imports)):
            points, frow = _price_points(price[0][1]), _forecast_row(forecast[0][1])
            producers, importers = _country_rows(production[0][1]), _country_rows(imports[0][1])
            if points and frow and producers and importers:
                observed, value = points[-1]
                _date, period, _base, predicted, unit = frow
                return (f"광물가격 : {observed.isoformat()} 현재가 {_fmt(value)}\n"
                        f"가격예측 : {period} 전망치 {_fmt(predicted)} {unit}\n"
                        f"광물지도 : 생산 1위 {producers[0][0]} ({_fmt(producers[0][1])}%)\n"
                        f"핵심광물 수급지도 : 수입 1위 {importers[0][0]} ({_fmt(importers[0][1])}%)",
                        {price[0][0], forecast[0][0], production[0][0], imports[0][0]})

    if {"price.series", "resource.rank", "trade.concentration", "document.retrieve"} == set(ids) and len(ids) == 4:
        price, production = by_action.get("price.series", []), by_action.get("resource.rank", [])
        imports, docs = by_action.get("trade.concentration", []), by_action.get("document.retrieve", [])
        if all(len(items) == 1 for items in (price, production, imports, docs)):
            points, producers = _price_points(price[0][1]), _country_rows(production[0][1])
            if points and len(points) >= 2 and producers:
                change = (points[-1][1]-points[0][1])/points[0][1]*100 if points[0][1] else 0
                return (f"광물지도 : 생산 1위 {producers[0][0]} ({_fmt(producers[0][1])}%)\n"
                        f"핵심광물 수급지도 : 수입 집중도는 조회 표 참조\n"
                        f"광물가격 : 최근 1개월 가격 {change:+.2f}% 변동\n"
                        f"월간동향 : 흑연 관련 요약 : {_document_text(docs[0][1])[:300]}",
                        {price[0][0], production[0][0], imports[0][0], docs[0][0]})

    # OC07/OC10: 모집단·가격을 한 adapter에서 이미 공통 기간으로 검증한 단일 Action.
    if len(ids) == 1 and ids[0] in {"trade.price_cross_rank", "resource.price_cross_rank"}:
        matches = by_action.get(ids[0], [])
        if len(matches) != 1:
            return None
        evidence_index, item = matches[0]
        required = {"mineral", "country", "share_pct", "price_start", "price_end", "pct_change"}
        if ids[0] == "resource.price_cross_rank":
            required.add("year")
        else:
            required.update({"trade_start", "trade_end", "trade_metric"})
        for table in extract_markdown_tables(getattr(item, "text", "")):
            keys = _keys(table)
            if not required <= set(keys):
                continue
            rows = [dict(zip(keys, row)) for row in table["rows"] if len(row) == len(keys)]
            if not rows or any(_number(row["share_pct"]) is None or
                               _number(row["pct_change"]) is None for row in rows):
                return None
            start, end = rows[0]["price_start"], rows[0]["price_end"]
            same_price_period = all(row["price_start"] == start and row["price_end"] == end for row in rows)
            if ids[0] == "trade.price_cross_rank":
                country = rows[0]["country"]
                if any(row["country"] != country for row in rows):
                    return None
                basis = "수입중량" if rows[0]["trade_metric"] == "import_weight" else "수입금액"
                if any(row["trade_metric"] != rows[0]["trade_metric"] for row in rows):
                    return None
                shares = ", ".join(f"{row['mineral']}({_fmt(_number(row['share_pct']))}%)" for row in rows)
                rising = [row for row in rows if _number(row["pct_change"]) > 0]
                changes = ", ".join(
                    f"{row['mineral']}(+{_fmt(_number(row['pct_change']))}%)"
                    + ("" if same_price_period else f" [{row['price_start']}~{row['price_end']}]")
                    for row in rising
                ) or "없습니다"
                price_period = f"{start}~{end} " if same_price_period else "요청기간 내 실제 관측일 기준 "
                answer = (f"수급지도 : {rows[0]['trade_start']}~{rows[0]['trade_end']} {country} {basis} 비중 상위 광종: {shares}\n"
                          f"광물가격 : 이 중 {price_period}상승 광종: {changes}")
            else:
                shares = ", ".join(
                    f"{row['mineral']}({row['country']} {_fmt(_number(row['share_pct']))}%, {row['year']}년)"
                    for row in rows
                )
                changes = ", ".join(
                    f"{row['mineral']}({_number(row['pct_change']):+.2f}%)"
                    + ("" if same_price_period else f" [{row['price_start']}~{row['price_end']}]")
                    for row in rows
                )
                price_period = f"{start}~{end} " if same_price_period else "각 광종 실제 관측기간 기준 "
                answer = (f"광물지도 : 생산 1위국 비중 상위 광종: {shares}\n"
                          f"광물가격 : 같은 광종 {price_period}가격 변동률: {changes}")
            return answer, {evidence_index}
        return None

    if ids.count("price.volatility_rank") == 1 and ids.count("document.retrieve") == 1 and len(ids) == 2:
        prices, docs = by_action.get("price.volatility_rank", []), by_action.get("document.retrieve", [])
        if len(prices) == 1 and len(docs) == 1:
            rows = []
            for table in extract_markdown_tables(getattr(prices[0][1], "text", "")):
                keys = _keys(table)
                if not {"mineral", "pct_change"} <= set(keys):
                    continue
                for row in table["rows"]:
                    if max(keys.index("mineral"), keys.index("pct_change")) < len(row):
                        change = _number(row[keys.index("pct_change")])
                        if change is not None:
                            rows.append(f"{row[keys.index('mineral')]} ({change:+.2f}%)")
                break
            if rows:
                titles = _news_titles(docs[0][1], limit=5)
                title_text = "\n".join(f"- {title}" for title in titles)
                return (f"광물가격 : 전주 변동 상위\n" + "\n".join(rows) +
                        f"\n자원뉴스 : 해당 광종 주간 기사\n{title_text or '- 해당 기간에 확인된 기사가 없습니다.'}"
                        "\n※ 동반 관측 정보이며 가격 변동 원인으로 단정하지 않습니다.",
                        {prices[0][0], docs[0][0]})

    if ids.count("resource.rank") == 1 and ids.count("trade.country_rank") == 1 and len(ids) == 2:
        production, imports = by_action.get("resource.rank", []), by_action.get("trade.country_rank", [])
        if len(production) == 1 and len(imports) == 1:
            producers, importers = _country_rows(production[0][1]), _country_rows(imports[0][1])
            if producers and importers:
                prod_text = ", ".join(name for name, _ in producers[:5])
                import_text = ", ".join(name for name, _ in importers[:5])
                common = [name for name, _ in producers if name in {country for country, _ in importers}]
                result = (f"광물지도 : 생산 상위국 {prod_text}\n핵심광물 수급지도 : 수입 상위국 {import_text}")
                if common:
                    result += f"\n비교결과 : 공통 국가 {', '.join(common)}"
                return result, {production[0][0], imports[0][0]}

    if ids.count("resource.rank") == 1 and ids.count("trade.concentration") == 1 and len(ids) == 2:
        production, imports = by_action.get("resource.rank", []), by_action.get("trade.concentration", [])
        if len(production) == 1 and len(imports) == 1:
            producers = _country_rows(production[0][1])
            if producers:
                hhi = re.search(r"HHI\s*[=:]\s*([0-9,.]+)", _document_text(imports[0][1]), re.I)
                cr3 = re.search(r"CR3\s*[=:]\s*([0-9,.]+)", _document_text(imports[0][1]), re.I)
                import_text = ", ".join(filter(None, [f"CR3 {cr3.group(1)}%" if cr3 else None,
                                                     f"HHI {hhi.group(1)}" if hhi else None]))
                if import_text:
                    name, share = producers[0]
                    return (f"광물지도 : 생산 1위국 비중 {name} {_fmt(share)}%\n"
                            f"핵심광물 수급지도 : 수입 집중도 {import_text}",
                            {production[0][0], imports[0][0]})

    # 현재 실측 가격과 예측가격은 각각의 원천 기준·단위를 그대로 보여 준다.
    # 값의 직접 차이는 같은 단위가 검증될 때만 계산한다.
    if ids.count("price.series") == 1 and ids.count("forecast.price") == 1 and len(ids) == 2:
        prices, forecasts = by_action.get("price.series", []), by_action.get("forecast.price", [])
        if len(prices) == 1 and len(forecasts) == 1:
            points, forecast = _price_points(prices[0][1]), _forecast_row(forecasts[0][1])
            if points and forecast:
                forecast_date, forecast_period, _baseline, predicted, unit = forecast
                latest_date, latest = points[-1]
                mineral = next((getattr(action.slots, "mineral", None) for action in actions
                                if action.action_id == "price.series"), None) or "요청 광종"
                forecast_action = next(action for action in actions if action.action_id == "forecast.price")
                if forecast_action.slots.forecast_operation == "compare_current":
                    price_unit = str(getattr(prices[0][1], "unit", "") or "")
                    if not price_unit or not unit or unit not in price_unit or not predicted:
                        return None
                    difference = latest - predicted
                    direction = "높습니다" if difference > 0 else "낮습니다" if difference < 0 else "같습니다"
                    return (f"광물가격 : 현재가 {_fmt(latest)} {unit}\n"
                            f"가격예측 : {forecast_date} 전망치 {_fmt(predicted)} {unit}\n"
                            f"현재가가 전망치 대비 {_fmt(abs(difference))} ({difference / predicted * 100:+.2f}%) {direction}",
                            {prices[0][0], forecasts[0][0]})
                if forecast_action.slots.forecast_operation == "timeline":
                    return (f"광물가격 : {points[0][0].isoformat()}~{latest_date.isoformat()} {mineral} 실적 추이\n"
                            f"가격예측 : {forecast_date}부터 {forecast_period} 전망치를 연결한 차트입니다. "
                            "실적 구간과 전망 구간을 구분해 표시합니다.",
                            {prices[0][0], forecasts[0][0]})
                return (f"광물가격 : {latest_date.isoformat()} {mineral} 가격 {_fmt(latest)}"
                        f"{(' ' + prices[0][1].unit) if getattr(prices[0][1], 'unit', None) else ''}\n"
                        f"가격예측 : {forecast_date} {forecast_period} 전망치 {_fmt(predicted)} {unit}",
                        {prices[0][0], forecasts[0][0]})

    # OC11/OC13/OC14: 문서 근거와 가격 시계열의 결합. 문서에 용도·월간동향
    # 문장이 실제로 없으면 LLM이 내용을 보충하지 못하도록 renderer를 포기한다.
    # 광종 용도와 수입/생산 상위국. 용도는 YAML 광종정보의 uses 행만, 국가는
    # ranking adapter가 계산한 share_pct 행만 사용한다.
    if (ids.count("document.retrieve") == 1
            and (ids.count("trade.country_rank") == 1 or ids.count("resource.rank") == 1)
            and len(ids) == 2):
        docs = by_action.get("document.retrieve", [])
        rank_id = "trade.country_rank" if "trade.country_rank" in ids else "resource.rank"
        ranks = by_action.get(rank_id, [])
        if len(docs) == 1 and len(ranks) == 1:
            uses = _mineral_info_uses(docs[0][1])
            countries = _country_rows(ranks[0][1])
            if uses and countries:
                country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:5])
                label = "수입 상위국" if rank_id == "trade.country_rank" else "생산 상위국"
                return (f"광물정보 : 주요 용도 : {uses}\n"
                        f"{'핵심광물 수급지도' if rank_id == 'trade.country_rank' else '광물지도'} : {label} {country_text}",
                        {docs[0][0], ranks[0][0]})

    # OC: 수출통제 기사에서 명시된 광종의 중국 수입 의존도. 기사가 먼저
    # 확인된 뒤 동적으로 붙은 trade.indicator만 허용하며, 표의 dependency_pct
    # 이외 값을 재계산하지 않는다.
    if (ids.count("document.retrieve") == 1 and ids.count("trade.indicator") >= 1
            and len(ids) == 1 + ids.count("trade.indicator")):
        docs = by_action.get("document.retrieve", [])
        trades = by_action.get("trade.indicator", [])
        if len(docs) == 1 and len(trades) == ids.count("trade.indicator"):
            doc_index, doc = docs[0]
            document_minerals = []
            for name in ("리튬", "니켈", "코발트", "망간", "흑연", "희토류", "텅스텐"):
                if name in _document_text(doc) and name not in document_minerals:
                    document_minerals.append(name)
            shares = []
            cited = {doc_index}
            trade_actions = [action for action in actions if action.action_id == "trade.indicator"]
            for action, (evidence_index, item) in zip(trade_actions, trades):
                for table in extract_markdown_tables(getattr(item, "text", "")):
                    keys = _keys(table)
                    if "dependency_pct" not in keys:
                        continue
                    value_i = keys.index("dependency_pct")
                    if not table["rows"] or value_i >= len(table["rows"][0]):
                        continue
                    value = _number(table["rows"][0][value_i])
                    if value is None:
                        continue
                    mineral = getattr(action.slots, "mineral", None) or "요청 광종"
                    shares.append((mineral, value))
                    cited.add(evidence_index)
                    break
            if shares:
                minerals = ", ".join(document_minerals) if document_minerals else ", ".join(name for name, _ in shares)
                rows = "\n".join(f"{name} 중국 수입 점유율 {_fmt(value)}%" for name, value in shares)
                return (f"자원뉴스 : 수출통제 관련 기사에서 언급된 광종 {minerals}\n"
                        f"핵심광물 수급지도 : 최근 12개월 한국 수입 중 중국 점유율\n{rows}", cited)

    if (ids.count("document.retrieve") == 1 and ids.count("trade.indicator") >= 1
            and ids.count("price.series") >= 1):
        docs, prices = by_action.get("document.retrieve", []), by_action.get("price.series", [])
        if len(docs) == 1 and prices:
            changes = []
            for action, (_index, item) in zip([a for a in actions if a.action_id == "price.series"], prices):
                points = _price_points(item)
                if len(points) >= 2 and points[0][1]:
                    changes.append(f"{action.slots.mineral} ({(points[-1][1]-points[0][1])/points[0][1]*100:+.2f}%)")
            if changes:
                return ("자원뉴스 : 수출통제 관련 기사에서 언급된 광종\n"
                        "핵심광물 수급지도 : 광종별 중국 수입 점유율은 함께 조회한 표를 참조\n"
                        "광물가격 : 최근 1개월 변동률 " + ", ".join(changes) +
                        "\n※ 동반 관측 정보이며 가격 변동 원인으로 단정하지 않습니다.",
                        set(range(1, len(evidence) + 1)))

    if ids.count("price.series") == 1 and ids.count("document.retrieve") == 1:
        price_action = next(action for action in actions if action.action_id == "price.series")
        if price_action.slots.price_operation == "significant_daily_rise":
            prices, docs = by_action.get("price.series", []), by_action.get("document.retrieve", [])
            if len(prices) == 1 and len(docs) == 1:
                threshold = price_action.slots.significant_change_pct or 5.0
                points = _price_points(prices[0][1])
                rises = [
                    (observed, (value - prior) / prior * 100)
                    for (prior_date, prior), (observed, value) in zip(points, points[1:])
                    if prior and observed.toordinal() - prior_date.toordinal() <= 7
                    and (value - prior) / prior * 100 >= threshold
                ]
                titles = _news_titles(docs[0][1])
                if rises and titles:
                    observed, pct = max(rises, key=lambda item: item[1])
                    mineral = price_action.slots.mineral or "요청 광종"
                    return (f"광물가격 : {observed.isoformat()} {mineral} 전일 대비 {pct:+.2f}% 상승\n"
                            "자원뉴스 : 같은 날 관련 기사\n" + "\n".join(f"- {title}" for title in titles) +
                            f"\n※ '크게 상승'은 전일 대비 {threshold:g}% 이상 기준으로 판정했으며, 동반 관측 정보로 가격 변동 원인으로 단정하지 않습니다.",
                            {prices[0][0], docs[0][0]})

    if ids.count("document.retrieve") == 1 and ids.count("price.series") >= 1:
        docs = by_action.get("document.retrieve", [])
        prices = by_action.get("price.series", [])
        if len(docs) == 1 and len(prices) == ids.count("price.series"):
            doc_index, doc = docs[0]
            doc_text = _document_text(doc)
            mineral_prices = []
            cited = {doc_index}
            for action, (evidence_index, item) in zip(
                    [a for a in actions if a.action_id == "price.series"], prices):
                points = _price_points(item)
                if not points:
                    continue
                latest_date, latest = points[-1]
                previous = points[-2][1] if len(points) > 1 else None
                pct = ((latest - previous) / previous * 100) if previous else None
                name = getattr(action.slots, "mineral", None) or "요청 광물"
                mineral_prices.append((name, latest_date, latest, pct))
                cited.add(evidence_index)
            if not mineral_prices:
                return None
            if len(mineral_prices) == 1 and not any(token in doc_text for token in ("월간동향", "동향", "월호")):
                usage = _mineral_info_uses(doc) or _usage_sentence(doc_text)
                if usage is None:
                    return None
                name, observed, latest, pct = mineral_prices[0]
                price_line = f"광물가격 : {observed.isoformat()} {name} 가격 {_fmt(latest)}"
                if getattr(prices[0][1], "unit", None):
                    price_line += f" {prices[0][1].unit}"
                price_line += f", 전일 대비 {pct:+.2f}%" if pct is not None else ", 전일 대비 계산 불가"
                return f"광물정보 : 주요 용도 : {usage}\n{price_line}", cited
            if len(mineral_prices) > 1 and any(token in doc_text for token in ("월간동향", "동향", "월호")):
                names = ", ".join(name for name, *_ in mineral_prices)
                rows = "; ".join(
                    f"{name} {_fmt(value)}({pct:+.2f}% 전일 대비)" if pct is not None
                    else f"{name} {_fmt(value)}(전일 비교 불가)"
                    for name, _observed, value, pct in mineral_prices
                )
                heading = getattr(doc, "section", None) or "확인된 월간동향"
                return (f"월간동향 : {heading} 동향에 나온 광종 {names}\n"
                        f"광물가격 : 광종별 가격/전월 평균 대비 등락률 표입니다.\n{rows}", cited)
            if len(mineral_prices) == 1 and any(token in doc_text for token in ("월간동향", "동향", "월호")):
                name, observed, latest, pct = mineral_prices[0]
                change = f"{pct:+.2f}%" if pct is not None else "계산 불가"
                summary = _usage_sentence(doc_text) or doc_text[:300]
                return (f"광물정보 : 가격 기간 {observed.isoformat()} 기준 {name} {change} 변동\n"
                        f"월간동향 : {getattr(doc, 'section', None) or '확인된 월간동향'} {name} 관련 서술 요약 : {summary}", cited)

    # OC04: 종합지수와 여러 광종 가격의 같은 기간 방향 비교.
    if ids.count("indicator.series") == 1 and ids.count("price.series") >= 2:
        index_items = by_action.get("indicator.series", [])
        price_items = by_action.get("price.series", [])
        if len(index_items) == 1 and len(price_items) == ids.count("price.series"):
            ip = _index_points(index_items[0][1])
            changes = []
            cited = {index_items[0][0]}
            for action, (evidence_index, item) in zip(
                    [a for a in actions if a.action_id == "price.series"], price_items):
                pp = _price_points(item)
                if len(pp) < 2 or not pp[0][1]:
                    continue
                changes.append((getattr(action.slots, "mineral", None) or "요청 광종",
                                (pp[-1][1] - pp[0][1]) / pp[0][1] * 100))
                cited.add(evidence_index)
            if len(ip) >= 2 and ip[0][1] and changes:
                index_pct = (ip[-1][1] - ip[0][1]) / ip[0][1] * 100
                direction = "상승" if index_pct > 0 else "하락" if index_pct < 0 else "보합"
                detail = " ".join(f"{name}({pct:+.2f}%)" for name, pct in changes)
                return (f"광물종합지수 : {ip[0][0].isoformat()}~{ip[-1][0].isoformat()} {index_pct:+.2f}% {direction}\n"
                        f"광물가격 : 동 기간 {detail} "
                        f"{'동반상승' if index_pct > 0 and all(p > 0 for _, p in changes) else '동반하락' if index_pct < 0 and all(p < 0 for _, p in changes) else '변화내역을 위와 같이 표시합니다.'}", cited)

    # OC05: 단일 가격 시계열과 종합지수의 동일 기간 변동률 비교.
    if ids.count("price.series") == 1 and ids.count("indicator.series") == 1:
        price = by_action.get("price.series", [])
        indicator = by_action.get("indicator.series", [])
        if len(price) == 1 and len(indicator) == 1:
            pp, ip = _price_points(price[0][1]), _index_points(indicator[0][1])
            if len(pp) >= 2 and len(ip) >= 2 and pp[0][1] and ip[0][1]:
                pchg = (pp[-1][1] - pp[0][1]) / pp[0][1] * 100
                ichg = (ip[-1][1] - ip[0][1]) / ip[0][1] * 100
                period = f"{max(pp[0][0], ip[0][0]).isoformat()}~{min(pp[-1][0], ip[-1][0]).isoformat()}"
                mineral = getattr(actions[0].slots, "mineral", None) or "요청 광물"
                return (f"{period} {mineral} 가격 {pchg:+.2f}%, 광물 종합지수 {ichg:+.2f}% 변동했습니다. [비교차트]",
                        {price[0][0], indicator[0][0]})

    # OC06/OC08: 가격 시계열 + 수입국 순위. latest는 OC08, 기간 조회는 OC06.
    if ids.count("price.series") == 1 and ids.count("trade.country_rank") == 1:
        price = by_action.get("price.series", [])
        trade = by_action.get("trade.country_rank", [])
        if len(price) == 1 and len(trade) == 1:
            pp, countries = _price_points(price[0][1]), _country_rows(trade[0][1])
            if pp and countries:
                p_action = next(action for action in actions if action.action_id == "price.series")
                period = getattr(getattr(p_action.slots, "period", None), "kind", None)
                if period == "latest":
                    latest = pp[-1]
                    previous_month = [value for observed, value in pp
                                      if observed.year * 12 + observed.month == latest[0].year * 12 + latest[0].month - 1]
                    if not previous_month:
                        return None
                    average = sum(previous_month) / len(previous_month)
                    pct = (latest[1] - average) / average * 100 if average else None
                    if pct is None:
                        return None
                    country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:3])
                    return (f"수급지도 : 수입 상위국 {country_text}\n광물가격 : {latest[0].isoformat()} 가격 {_fmt(latest[1])}, 전월 평균 대비 {pct:+.2f}%",
                            {price[0][0], trade[0][0]})
                if len(pp) >= 2 and pp[0][1]:
                    change = (pp[-1][1] - pp[0][1]) / pp[0][1] * 100
                    high_date, high = max(pp, key=lambda point: point[1])
                    country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:3])
                    return (f"광물가격 : {pp[0][0].isoformat()}~{pp[-1][0].isoformat()} 가격 {change:+.2f}% 변동, 고점 {_fmt(high)}({high_date.strftime('%Y-%m')})\n"
                            f"수급지도 : 수입국 {country_text}", {price[0][0], trade[0][0]})

    # OC09: 가격 연도별 평균과 세계 생산량 YoY.
    if ids.count("price.series") == 1 and ids.count("resource.yoy") == 1:
        price = by_action.get("price.series", [])
        yoy = by_action.get("resource.yoy", [])
        if len(price) == 1 and len(yoy) == 1:
            pp, yy = _price_points(price[0][1]), _yoy_rows(yoy[0][1])
            if pp and yy:
                yearly = {}
                for observed, value in pp:
                    yearly.setdefault(observed.year, []).append(value)
                rows = []
                for year, pct in yy:
                    if year in yearly:
                        rows.append(f"{year} {_fmt(sum(yearly[year]) / len(yearly[year]))}; 생산량 {pct:+.2f}%")
                if rows:
                    return ("광물가격 : 연도별 평균 가격 " + ", ".join(rows) +
                            "\n광물지도 : 같은 연도 생산량 전년 대비 위 값을 표시했습니다.\n"
                            "※ 두 지표를 나란히 제시하며 상호 인과관계로 해석하지 않습니다.",
                            {price[0][0], yoy[0][0]})
    return None
