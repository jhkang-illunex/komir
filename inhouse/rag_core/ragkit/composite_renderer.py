"""근거 표를 여러 Action의 사용자용 출력 형식으로 결합하는 결정적 renderer."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re

from .chatbot_events import extract_markdown_tables
from .action_contract import COMPOSITE_INDEX_VARIANTS
from .renderers.price import price_display_unit
from .renderers.price_blocks import render_price_forecast_blocks, render_price_rank_yoy_blocks
from .renderers.resource_rank import render_production_reserves_pair


def _keys(table):
    return [column.split("(", 1)[0].strip().casefold() for column in table["columns"]]


def _number(value):
    try:
        value = float(str(value).replace(",", "").replace("%", "").strip())
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _hhi_risk_label(value):
    hhi = _number(value)
    if hhi is None or not 0 <= hhi <= 10_000:
        return None
    if hhi >= 8_000:
        return "매우 높은 위험"
    if hhi >= 6_000:
        return "높은 위험"
    return "주의 필요"


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


def _document_summary_text(item, *, limit: int = 300):
    """월간동향 표에서 요약 셀만 골라 사용자용 문장으로 반환한다."""
    raw = str(getattr(item, "text", ""))
    for table in extract_markdown_tables(raw):
        keys = _keys(table)
        summary_i = next((i for i, key in enumerate(keys)
                          if key in {"요약", "summary", "주요내용", "내용요약", "본문요약"}), None)
        if summary_i is None:
            continue
        summaries = [row[summary_i].strip() for row in table["rows"]
                     if summary_i < len(row) and row[summary_i].strip()]
        if summaries:
            return re.sub(r"\s+", " ", " ".join(summaries))[:limit]

    # 일반 문서형 근거는 표 외의 prose만 보존한다. 표만 있는 경우 전체 행을
    # fallback으로 내보내지 않아 원문 경로·메타데이터 덤프를 방지한다.
    prose = "\n".join(line for line in raw.splitlines()
                      if not line.strip().startswith("|")
                      and not re.search(r"(?:원문\s*:|(?:^|\s)(?:[A-Za-z]:)?[/\\][^\s]+|\.(?:md|pdf|hwp|hwpx|xlsx?)(?:\s|$))", line, re.I))
    return re.sub(r"\s+", " ", prose).strip()[:limit]


def _news_titles(item, *, limit: int = 3, expected_date: str | None = None):
    """자원뉴스 adapter의 구조화 표에서 제목만 보존해 읽는다."""
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        title_i = next((i for i, key in enumerate(keys)
                        if key in {"title", "headline", "제목", "기사제목"}), None)
        date_i = next((i for i, key in enumerate(keys)
                       if key in {"date", "published_at", "pub_date", "날짜", "게시일"}), None)
        if title_i is None:
            continue
        if expected_date and date_i is None:
            continue
        titles = []
        for row in table["rows"]:
            if title_i >= len(row):
                continue
            title = row[title_i].strip()
            if not title:
                continue
            published = row[date_i].strip() if date_i is not None and date_i < len(row) else ""
            if expected_date and re.sub(r"\D", "", published)[:8] != expected_date.replace("-", ""):
                continue
            titles.append(f"{title} ({published})" if published else title)
        if titles:
            return titles[:limit]
    return []


def _news_summary_rows(item, *, limit: int = 5):
    """자원뉴스 표의 날짜·제목·요약 셀을 사용자용 행으로 반환한다.

    제목만 요구한 질의와 요약을 요구한 질의를 같은 결정형 renderer에서
    구분하기 위해 사용한다. 요약 셀은 adapter가 원천 본문에서 만든 값만
    사용하며, 표에 요약이 없으면 빈 결과를 돌려 생성 모델의 추정을 막는다.
    """
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        title_i = next((i for i, key in enumerate(keys)
                        if key in {"title", "headline", "제목", "기사제목"}), None)
        summary_i = next((i for i, key in enumerate(keys)
                          if key in {"요약", "summary", "주요내용", "내용요약", "본문요약"}), None)
        date_i = next((i for i, key in enumerate(keys)
                       if key in {"date", "published_at", "pub_date", "날짜", "게시일"}), None)
        if title_i is None or summary_i is None:
            continue
        rows = []
        for row in table["rows"]:
            if max(title_i, summary_i) >= len(row):
                continue
            title = re.sub(r"\s+", " ", row[title_i]).strip()
            summary = re.sub(r"\s+", " ", row[summary_i]).strip()
            if len(summary) > 300:
                summary = summary[:300].rsplit(" ", 1)[0].rstrip() + "…"
            if not title or not summary:
                continue
            published = row[date_i].strip() if date_i is not None and date_i < len(row) else ""
            rows.append((published, title, summary))
        if rows:
            return rows[:limit]
    return []


def _weekly_report_rows(item, *, limit: int = 5):
    """주간동향 adapter의 게시일·제목 행을 보존해 읽는다.

    이 표는 뉴스 기사 표와 열 이름이 다르므로 `_news_titles`에 섞지 않는다.
    발행일은 adapter가 파일명에서 확인한 값이며, renderer가 날짜를 추정하지 않는다.
    """
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        title_i = next((i for i, key in enumerate(keys) if key in {"보고서 제목", "title", "제목"}), None)
        date_i = next((i for i, key in enumerate(keys) if key in {"게시일", "date", "published_at"}), None)
        source_i = next((i for i, key in enumerate(keys) if key in {"출처", "source"}), None)
        if title_i is None:
            continue
        rows = []
        for row in table["rows"]:
            if title_i >= len(row) or not row[title_i].strip():
                continue
            published = row[date_i].strip() if date_i is not None and date_i < len(row) else ""
            source = row[source_i].strip() if source_i is not None and source_i < len(row) else ""
            label = row[title_i].strip()
            if published:
                label += f" ({published})"
            if source:
                label += f" — {source}"
            rows.append(label)
        if rows:
            return rows[:limit]
    return []


def _mineral_info_rows(item):
    """RSC/KOMIS 광물정보 표에서 검증된 속성만 읽는다."""
    for table in extract_markdown_tables(getattr(item, "text", "")):
        keys = _keys(table)
        mineral_i = next((i for i, key in enumerate(keys) if key in {"광종", "mineral"}), None)
        attribute_i = next((i for i, key in enumerate(keys) if key in {"속성", "attribute"}), None)
        value_i = next((i for i, key in enumerate(keys) if key in {"값", "value"}), None)
        if None in {mineral_i, attribute_i, value_i}:
            continue
        rows = []
        for row in table["rows"]:
            if max(mineral_i, attribute_i, value_i) >= len(row):
                continue
            mineral, attribute, value = (row[mineral_i].strip(), row[attribute_i].strip(), row[value_i].strip())
            if mineral and attribute in {"uses", "characteristics", "element_symbol", "atomic_number"} and value:
                rows.append((mineral, attribute, value))
        if rows:
            return rows
    return []


def _usage_sentence(text):
    """문서 근거에 명시된 용도 문장만 반환한다."""
    # mineral_info YAML adapter의 구조화 표는 자유문장이 아니라 uses 속성에
    # 검증값을 담는다. 같은 evidence 계약에서 용도만 읽어 OC11에 사용한다.
    for table in extract_markdown_tables(text):
        keys = _keys(table)
        if not {"속성", "값"} <= set(keys):
            continue
        key_i, value_i = keys.index("속성"), keys.index("값")
        for row in table["rows"]:
            if len(row) > max(key_i, value_i) and row[key_i].strip() == "uses":
                return row[value_i].strip()
    for sentence in re.split(r"(?<=[.!?。])\s+|\n+", text):
        if any(token in sentence for token in ("용도", "사용", "쓰입", "활용")):
            return sentence.strip(" -:;")
    return None


def render_composite(evidence: list, action_plan, action_results=None) -> tuple[str, set[int]] | None:
    """현재 연결된 표로 계산 가능한 복합 계약만 렌더링한다.

    ``action_results``가 주어지면 일부 Action의 조회 실패를 반영해 성공한
    근거만 결정적으로 조립한다. 실패한 Action의 값을 LLM이 추정하거나 다른
    Action의 수치로 대체하지 않도록, 현재 지원하는 부분 응답 계약을 먼저
    처리한다.
    """
    actions = list(getattr(action_plan, "actions", ()) or ())
    ids = [getattr(action, "action_id", None) for action in actions]
    by_action = {}
    for index, item in enumerate(evidence, 1):
        by_action.setdefault(getattr(item, "action_id", None), []).append((index, item))

    # 이 조합은 별도 renderer가 응답을 담당한다. 기존 조합별 응답 계약은 아래에 유지한다.
    resource_rank_pair = render_production_reserves_pair(evidence, action_plan, action_results)
    if resource_rank_pair is not None:
        return resource_rank_pair

    # MP03(price+rank)·MP04(price+YoY)는 공통 블록 조립기가 처리한다.
    # 다른 Action 조합은 이 진입점에서 매칭되지 않아 기존 분기를 유지한다.
    price_metric_pair = render_price_rank_yoy_blocks(evidence, action_plan, action_results)
    if price_metric_pair is not None:
        return price_metric_pair

    # FBQ81(2차전지 5종 가격+전망)은 가격 공통 코어를 재사용하되, 광종별
    # price.series·forecast.price 근거를 requirement_id로 매칭한다.
    price_forecast_group = render_price_forecast_blocks(evidence, action_plan, action_results)
    if price_forecast_group is not None:
        return price_forecast_group

    # 종합지수의 명시 연도 범위는 실제 반환된 HI001 관측점으로만 계산한다.
    # 요청 구간 일부만 적재된 경우에도 전체를 조회 불가로 버리지 않고 실제
    # 관측 범위를 함께 밝혀, 누락된 연도를 데이터가 있는 것처럼 표현하지 않는다.
    if ids == ["indicator.series"]:
        action = actions[0]
        variant = getattr(action.slots, "indicator_variant", None) or "composite"
        if (getattr(action.slots, "indicator", None) == "composite_index"
                and variant in COMPOSITE_INDEX_VARIANTS
                and getattr(action.slots, "indicator_operation", None) == "period_change"):
            rows = by_action.get("indicator.series", [])
            for evidence_index, item in rows:
                points = _index_points(item)
                if len(points) < 2 or not points[0][1]:
                    continue
                start_date, start_value = points[0]
                end_date, end_value = points[-1]
                change = (end_value - start_value) / start_value * 100
                direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
                _index_code, display_name = COMPOSITE_INDEX_VARIANTS[variant]
                period = getattr(action.slots, "period", None)
                requested = ""
                if period is not None and getattr(period, "kind", None) == "range":
                    requested_start = str(period.start or "")[:4]
                    requested_end = str(period.end or "")[:4]
                    requested = f"요청하신 {requested_start}~{requested_end}년 중 확인된 자료 "
                return (
                    f"{display_name} : {requested}{start_date.isoformat()}~{end_date.isoformat()} "
                    f"{_fmt(start_value)}에서 {_fmt(end_value)}까지 {_fmt(change)}% {direction}했습니다.",
                    {evidence_index},
                )

    # 수입 편중도 질의는 전체 국가 표에서 상위 비중과 HHI를 함께 요약한다.
    # HHI가 최소 수입액 기준 미달로 adapter에서 제거된 경우에도 원 수치를
    # 추론하거나 출력하지 않고, 기준 미달 상태만 안내한다.
    if ids == ["trade.concentration"]:
        rows = by_action.get("trade.concentration", [])
        if len(rows) == 1:
            evidence_index, item = rows[0]
            countries = _country_rows(item)
            if countries:
                action = actions[0]
                mineral = getattr(action.slots, "mineral", None) or "요청 광종"
                leaders = countries[:2]
                leader_text = "와 ".join(
                    f"{country}({_fmt(share)}%)" for country, share in leaders
                )
                combined = sum(share for _country, share in leaders)
                prefix = f"{mineral} 수입은 {leader_text}이 전체의 {_fmt(combined)}%를 차지합니다."
                hhi_match = re.search(r"HHI=([0-9,.]+)", str(getattr(item, "section", "")))
                if hhi_match:
                    hhi = _number(hhi_match.group(1))
                    level = _hhi_risk_label(hhi)
                    if level is None:
                        return None
                    return (
                        f"{prefix} HHI {_fmt(hhi)}은 국가별 수입 비중을 제곱해 합산한 집중도 지수이며, "
                        f"'{level}' 구간입니다. 값이 클수록 수입이 일부 국가에 더 집중돼 있음을 뜻합니다. "
                        "이는 지정학적 위험 자체를 직접 측정하는 값은 아닙니다.",
                        {evidence_index},
                    )
                if "HHI 미표시: 수입액 100만 USD 기준 미달" in str(getattr(item, "section", "")):
                    return (
                        f"{prefix} 수입액이 100만 USD 기준에 미달해 HHI 수치와 집중도 등급은 표시하지 않습니다.",
                        {evidence_index},
                    )

    # 가격 실적은 조회됐지만 전망만 아직 없는 단순 결합 질문은 실적 값을
    # 남기고 전망 부재를 명시한다. 실패한 forecast 결과를 가격 응답까지
    # 덮어쓰거나 LLM이 전망을 추정하지 않게 한다.
    if action_results and len(actions) == 2 and set(ids) == {"price.series", "forecast.price"}:
        outcomes = {getattr(item, "requirement_id", None): item for item in action_results}
        price_action = next(action for action in actions if action.action_id == "price.series")
        forecast_action = next(action for action in actions if action.action_id == "forecast.price")
        price_outcome = outcomes.get(getattr(price_action, "requirement_id", None))
        forecast_outcome = outcomes.get(getattr(forecast_action, "requirement_id", None))
        if (price_outcome is not None and price_outcome.status == "success"
                and forecast_outcome is not None and forecast_outcome.status != "success"):
            matches = [(index, item) for index, item in by_action.get("price.series", [])
                       if getattr(item, "requirement_id", None) == price_action.requirement_id]
            for price_index, price in matches:
                points = _price_points(price)
                if not points:
                    continue
                observed, value = points[-1]
                mineral = getattr(price_action.slots, "mineral", None) or "요청 광종"
                unit = price_display_unit(getattr(price, "unit", None))
                suffix = f" {unit}" if unit else ""
                if getattr(forecast_action.slots, "forecast_operation", None) == "timeline" and len(points) >= 2:
                    return (
                        f"광물가격 : 실제 관측 구간 {points[0][0].isoformat()}~{observed.isoformat()} "
                        f"{mineral} 실적 가격 추이입니다.\n"
                        "가격예측 : 전망 데이터가 없어 전망 구간은 표시하지 않습니다.",
                        {price_index},
                    )
                return (
                    f"광물가격 : {observed.isoformat()} {mineral} 가격 {value:,.2f}{suffix}\n"
                    f"가격예측 : 전망 자료가 없어 예측값은 제공하지 못했습니다.",
                    {price_index},
                )

    # 현황 브리핑처럼 가격·전망·생산·수입을 함께 계획했을 때 전망 원천만
    # 비어 있을 수 있다. 성공한 세 Action을 그대로 표시하고 전망만 명시적으로
    # 미제공 처리한다. 성공한 Action의 의미를 섞는 일반 LLM 조립은 금지한다.
    if action_results and set(ids) == {
        "price.series", "forecast.price", "resource.rank", "trade.country_rank",
    } and len(ids) == 4:
        outcomes = {getattr(item, "requirement_id", None): item for item in action_results}
        failed_ids = {
            getattr(call, "action_id", None)
            for call in actions
            if (outcomes.get(getattr(call, "requirement_id", None)) is not None
                and getattr(outcomes[getattr(call, "requirement_id", None)], "status", None) != "success")
        }
        if "forecast.price" in failed_ids:
            price = by_action.get("price.series", [])
            production = by_action.get("resource.rank", [])
            imports = by_action.get("trade.country_rank", [])
            def first_rows(items, parser):
                for index, item in items:
                    rows = parser(item)
                    if rows:
                        return index, rows
                return None, None

            price_index, points = first_rows(price, _price_points)
            production_index, producers = first_rows(production, _country_rows)
            imports_index, importers = first_rows(imports, _country_rows)
            if points and producers and importers:
                observed, value = points[-1]
                mineral = next(
                    (getattr(call.slots, "mineral", None) for call in actions
                     if getattr(call, "action_id", None) == "price.series"),
                    "요청 광종",
                )
                return (
                    f"광물가격 : {observed.isoformat()} {mineral} 현재가 {_fmt(value)}\n"
                    f"가격예측 : 현재 {mineral}의 가격 전망 데이터가 없어 표시할 수 없습니다.\n"
                    f"광물지도 : 생산 1위 {producers[0][0]} ({_fmt(producers[0][1])}%)\n"
                    f"핵심광물 수급지도 : 수입 1위 {importers[0][0]} ({_fmt(importers[0][1])}%)",
                    {price_index, production_index, imports_index},
                )

    # 자원뉴스의 최신 목록은 ``ai_news`` adapter가 날짜·제목·요약을 이미
    # 구조화해 확인한 결과다. 이를 일반 생성 모델에 다시 맡기면, 정상 근거가
    # 있어도 모델이 빈 기권문을 반환해 ``off_topic``으로 오분류될 수 있다.
    # 단일 뉴스 조회는 표에 실제 제목이 있을 때만 결정적으로 출력하고, 제목이
    # 없으면 기존 일반 문서 응답 경로를 유지한다.
    if ids == ["document.retrieve"]:
        docs = by_action.get("document.retrieve", [])
        if len(docs) == 1:
            evidence_index, document = docs[0]
            action = actions[0]
            topic = str(getattr(action.slots, "topic", "") or "")
            is_news_request = (
                "뉴스" in topic or "기사" in topic
                or str(getattr(document, "section", "") or "") == "자원뉴스"
            )
            wants_summary = "요약" in topic or "정리" in topic
            summary_rows = _news_summary_rows(document) if is_news_request and wants_summary else []
            if summary_rows:
                return (
                    "최근 자원뉴스 요약 : 확인된 핵심 내용\n"
                    + "\n".join(
                        f"- {published + ' ' if published else ''}{title}: {summary}"
                        for published, title, summary in summary_rows
                    ),
                    {evidence_index},
                )
            titles = _news_titles(document, limit=5)
            if is_news_request and titles:
                return (
                    "최근 자원뉴스 : 확인된 기사\n" + "\n".join(f"- {title}" for title in titles),
                    {evidence_index},
                )
            weekly_rows = _weekly_report_rows(document)
            if "주간동향" in topic and weekly_rows:
                return (
                    "주간 자원뉴스 : 확인된 주간동향 보고서\n" + "\n".join(f"- {row}" for row in weekly_rows),
                    {evidence_index},
                )

    if ids and all(action_id == "trade.country_rank" for action_id in ids) and len(ids) == 5:
        rows, cited, periods = [], set(), []
        for action in actions:
            matches = [(index, item) for index, item in by_action.get("trade.country_rank", [])
                       if getattr(item, "requirement_id", None) == action.requirement_id]
            selected = next(((index, item, _country_rows(item)) for index, item in matches
                             if _country_rows(item)), None)
            if selected is None:
                rows = []
                break
            index, item, countries = selected
            country, share = countries[0]
            rows.append(f"{action.slots.mineral} : {country} ({_fmt(share)}%)")
            cited.add(index)
            observed = str(getattr(item, "observed_period", None) or getattr(item, "as_of", None) or "")
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", observed)
            if len(dates) >= 2:
                periods.append(f"{dates[0]}~{dates[-1]}")
        if len(rows) == len(actions):
            period_label = "확인된 수입 자료 기준"
            if periods and len(set(periods)) == 1:
                period_label = f"실제 확인된 자료 기간 {periods[0]} 기준"
            return ("광물정보 : 2차전지 원료 광종 리튬, 니켈, 코발트, 망간, 흑연\n"
                    f"핵심광물 수급지도 : {period_label} 광종별 수입 1위국\n" + "\n".join(rows), cited)

    if (ids == ["document.retrieve", "document.retrieve"]
            and all(not getattr(actions[evidence_index - 1].slots, "mineral", None)
                    for evidence_index, _item in by_action.get("document.retrieve", []))):
        docs = by_action.get("document.retrieve", [])
        if len(docs) == 2:
            left, right = _document_text(docs[0][1]), _document_text(docs[1][1])
            # 월간동향은 ``동``, 주간 비철금속 보고서는 ``구리``처럼 같은
            # 광종의 표기를 달리 쓴다. 이 작은 동의어 표만 정규화하며, 이외
            # 키워드는 두 원문에 동일 문자열이 실제 있을 때만 공통으로 표시한다.
            common = [label for label, aliases in (
                ("리튬", ("리튬",)), ("니켈", ("니켈",)), ("코발트", ("코발트",)),
                ("망간", ("망간",)), ("흑연", ("흑연",)), ("희토류", ("희토류",)),
                ("구리", ("구리", "동")), ("아연", ("아연",)), ("철광석", ("철광석",)),
                ("중국", ("중국",)), ("수출통제", ("수출통제",)),
            ) if any(alias in left for alias in aliases) and any(alias in right for alias in aliases)]
            if common:
                return (f"월간동향 : {getattr(docs[0][1], 'section', None) or '확인된 월간동향'} 주요 이슈\n"
                        f"자원뉴스 : {getattr(docs[1][1], 'section', None) or '확인된 주간 뉴스'} 주요 기사\n"
                        f"공통 이슈 : {', '.join(common)}", {docs[0][0], docs[1][0]})

    # 월간동향에 등장한 광종의 기본 정보는 월간 문서가 광종 범위를, RSC/KOMIS
    # adapter가 속성 값을 각각 책임진다. 둘 중 하나라도 빠지면 일반 경로로
    # 내려가며, 여기서 빈 특성을 채우지 않는다.
    monthly_docs = [pair for pair in by_action.get("document.retrieve", [])
                    if "월간동향" in str(getattr(actions[pair[0] - 1].slots, "topic", "") or "")]
    info_docs = [pair for pair in by_action.get("document.retrieve", [])
                 if pair not in monthly_docs]
    rank_docs = by_action.get("trade.country_rank", [])
    concentration_docs = by_action.get("trade.concentration", [])
    if len(monthly_docs) == 1 and info_docs and not rank_docs:
        monthly_index, monthly = monthly_docs[0]
        lines, cited = [], {monthly_index}
        for evidence_index, item in info_docs:
            info = _mineral_info_rows(item)
            if not info:
                continue
            mineral = info[0][0]
            selected = [f"{attribute}: {value}" for _name, attribute, value in info[:2]]
            lines.append(f"- {mineral}: " + "; ".join(selected))
            cited.add(evidence_index)
        if lines:
            return (f"월간동향 : {getattr(monthly, 'section', None) or '확인된 월간동향'}에 나온 광종\n"
                    "광물정보 : 검증된 기본 특성\n" + "\n".join(lines), cited)

    # 월간동향으로 대상 광종을 확정한 뒤에만 각 광종의 한국 수입 순위/집중도를
    # 결합한다. 순위 표의 비중과 concentration adapter의 HHI만 그대로 표시한다.
    if len(monthly_docs) == 1 and rank_docs:
        monthly_index, monthly = monthly_docs[0]
        lines, cited = [], {monthly_index}
        rank_actions = [action for action in actions if action.action_id == "trade.country_rank"]
        for action, (evidence_index, item) in zip(rank_actions, rank_docs):
            countries = _country_rows(item)
            if not countries:
                continue
            country, share = countries[0]
            lines.append(f"- {action.slots.mineral}: {country} ({_fmt(share)}%)")
            cited.add(evidence_index)
        hhis = []
        for evidence_index, item in concentration_docs:
            match = re.search(r"HHI=([0-9.]+)", str(getattr(item, "section", "")))
            if match:
                hhis.append(_fmt(_number(match.group(1))))
                cited.add(evidence_index)
        if lines:
            concentration = f"\n수입 집중도 : HHI {', '.join(hhis)}" if hhis else ""
            return (f"월간동향 : {getattr(monthly, 'section', None) or '확인된 월간동향'}에 나온 광종\n"
                    "핵심광물 수급지도 : 최근 12개월 한국 수입 1위국\n" + "\n".join(lines) + concentration,
                    cited)

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
        if action_results:
            outcomes = {getattr(item, "requirement_id", None): item for item in action_results}
            index_action = next(action for action in actions if action.action_id == "indicator.series")
            document_action = next(action for action in actions if action.action_id == "document.retrieve")
            index_outcome = outcomes.get(index_action.requirement_id)
            document_outcome = outcomes.get(document_action.requirement_id)
            index_match = next(((index, item) for index, item in indices
                                if getattr(item, "requirement_id", None) == index_action.requirement_id), None)
            document_match = next(((index, item) for index, item in docs
                                   if getattr(item, "requirement_id", None) == document_action.requirement_id), None)
            index_points = _index_points(index_match[1]) if index_match else []
            document_text = _document_summary_text(document_match[1]) if document_match else ""
            index_available = bool(
                index_outcome is not None and index_outcome.status == "success"
                and len(index_points) >= 2 and index_points[0][1]
            )
            document_available = bool(
                document_outcome is not None and document_outcome.status == "success"
                and document_text
            )
            # 한쪽 Action이 실패해도 성공한 내용은 살리되 내부 requirement_id는
            # 사용자 답변에 섞이지 않도록 이 조합의 부분 응답을 결정적으로 만든다.
            if not (index_available and document_available):
                lines, cited = [], set()
                if index_available:
                    start_date, start_value = index_points[0]
                    end_date, end_value = index_points[-1]
                    change = (end_value - start_value) / start_value * 100
                    direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
                    lines.append(
                        f"광물종합지수 : {start_date.isoformat()}~{end_date.isoformat()} "
                        f"{_fmt(change)}% {direction}했습니다."
                    )
                    cited.add(index_match[0])
                else:
                    lines.append("광물종합지수 : 요청 기간의 변동 자료를 확인하지 못했습니다.")
                if document_available:
                    title = getattr(document_match[1], "section", None) or "확인된 월간동향"
                    lines.append(f"월간동향 : {title} 주요 내용 : {document_text[:300]}")
                    cited.add(document_match[0])
                else:
                    lines.append("월간동향 : 확인 가능한 요약 자료를 찾지 못했습니다.")
                return "\n".join(lines), cited
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
                summary = _document_summary_text(docs[0][1])
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
                        f"월간동향 : {getattr(docs[0][1], 'section', None) or '월간동향'} {mineral} 전망 서술 요약 : {_document_summary_text(docs[0][1])}",
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
                        f"월간동향 : 흑연 관련 요약 : {_document_summary_text(docs[0][1])}",
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
            # YAML 광종정보와 일반 문서 모두에서 용도 행을 읽는 공용 추출기다.
            # `_mineral_info_uses`라는 과거 이름은 구현돼 있지 않아, 복합 질의가
            # 근거를 확보한 뒤에도 렌더링 단계에서 중단될 수 있었다.
            # Markdown 표의 행 경계를 보존해야 `uses` 속성만 추출할 수 있다.
            uses = _usage_sentence(getattr(docs[0][1], "text", ""))
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
            if len(prices) == 1:
                threshold = price_action.slots.significant_change_pct or 5.0
                points = _price_points(prices[0][1])
                rises = [
                    (observed, (value - prior) / prior * 100)
                    for (prior_date, prior), (observed, value) in zip(points, points[1:])
                    if prior and observed.toordinal() - prior_date.toordinal() <= 7
                    and (value - prior) / prior * 100 >= threshold
                ]
                if rises:
                    observed, pct = max(rises, key=lambda item: item[1])
                    mineral = price_action.slots.mineral or "요청 광종"
                    titles = (_news_titles(docs[0][1], expected_date=observed.isoformat())
                              if len(docs) == 1 else [])
                    price_line = f"광물가격 : {observed.isoformat()} {mineral} 전일 대비 {pct:+.2f}% 상승"
                    if titles:
                        return (price_line + "\n자원뉴스 : 같은 날 관련 기사\n"
                                + "\n".join(f"- {title}" for title in titles)
                                + f"\n※ '크게 상승'은 전일 대비 {threshold:g}% 이상 기준으로 판정했으며, "
                                  "동반 관측 정보로 가격 변동 원인으로 단정하지 않습니다.",
                                {prices[0][0], docs[0][0]})
                    if action_results:
                        outcomes = {getattr(item, "requirement_id", None): item for item in action_results}
                        news_action = next(action for action in actions if action.action_id == "document.retrieve")
                        news_outcome = outcomes.get(news_action.requirement_id)
                        status = getattr(news_outcome, "status", None)
                        failure_note = {
                            "no_data": "해당 날짜의 관련 뉴스를 찾지 못했습니다.",
                            "source_unavailable": "해당 날짜의 뉴스 자료원을 사용할 수 없습니다.",
                            "validation_failed": "해당 날짜의 뉴스 자료를 검증하지 못했습니다.",
                            "failed": "해당 날짜의 뉴스 조회에 실패했습니다.",
                            "blocked": "선행 조회가 완료되지 않아 해당 날짜의 뉴스를 조회하지 못했습니다.",
                        }.get(status, "조회된 뉴스에서 같은 날짜의 관련 기사 제목을 확인하지 못했습니다.")
                        return (price_line + f"\n자원뉴스 : {failure_note} "
                                f"※ '크게 상승'은 전일 대비 {threshold:g}% 이상 기준이며, "
                                "동반 관측 정보로 가격 변동 원인으로 단정하지 않습니다.",
                                {prices[0][0]})

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
                usage = _usage_sentence(getattr(doc, "text", ""))
                if usage is None:
                    return None
                name, observed, latest, pct = mineral_prices[0]
                price_line = f"광물가격 : {observed.isoformat()} {name} 가격 {_fmt(latest)}"
                # Evidence.unit에는 가격 기준과 코드가 보존된다. 사용자 문장에는
                # 그 전체 메타데이터를 그대로 붙이지 않고, 검증된 통화/중량 코드가
                # 모두 있는 경우에만 사람이 읽는 가격 단위로 표시한다.
                if unit := price_display_unit(getattr(prices[0][1], "unit", None)):
                    price_line += f" {unit}"
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
                summary = _usage_sentence(getattr(doc, "text", "")) or doc_text[:300]
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
                if len(pp) < 2:
                    continue
                # 지수와 가격의 시작·끝 보유일이 다를 수 있으므로, 두 시계열의
                # 실제 겹침 구간 안에서만 각각 첫/마지막 관측값을 택한다.
                overlap_start, overlap_end = max(ip[0][0], pp[0][0]), min(ip[-1][0], pp[-1][0])
                aligned = [point for point in pp if overlap_start <= point[0] <= overlap_end]
                index_aligned = [point for point in ip if overlap_start <= point[0] <= overlap_end]
                if len(aligned) < 2 or len(index_aligned) < 2 or not aligned[0][1]:
                    continue
                changes.append((getattr(action.slots, "mineral", None) or "요청 광종",
                                (aligned[-1][1] - aligned[0][1]) / aligned[0][1] * 100))
                cited.add(evidence_index)
            if len(ip) >= 2 and ip[0][1] and changes:
                # 모든 가격 series가 같은 시작일을 갖지 않을 수 있으므로, 지수
                # 변화는 각 가격에 공통인 전체 겹침 범위를 보장하지 않는 일반
                # 표시로 두고, 동반상승 판정은 방향만 사용한다.
                index_pct = (ip[-1][1] - ip[0][1]) / ip[0][1] * 100
                direction = "상승" if index_pct > 0 else "하락" if index_pct < 0 else "보합"
                same_direction = [(name, pct) for name, pct in changes
                                  if (index_pct > 0 and pct > 0) or (index_pct < 0 and pct < 0)]
                detail = " ".join(f"{name}({pct:+.2f}%)" for name, pct in same_direction)
                if not detail:
                    detail = "없음"
                return (f"광물종합지수 : {ip[0][0].isoformat()}~{ip[-1][0].isoformat()} {index_pct:+.2f}% {direction}\n"
                        f"광물가격 : 지수와 같은 방향으로 움직인 시스템 대상 광종 {detail}\n"
                        "※ 각 광종은 지수와 실제로 겹치는 보유기간의 가격 변동률로 비교했으며, 지수 구성광종 또는 인과관계를 뜻하지 않습니다.", cited)

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
        price_action = next(action for action in actions if action.action_id == "price.series")
        trade_action = next(action for action in actions if action.action_id == "trade.country_rank")
        price_matches = [(index, item) for index, item in by_action.get("price.series", [])
                         if getattr(item, "requirement_id", None) == price_action.requirement_id]
        trade_matches = [(index, item) for index, item in by_action.get("trade.country_rank", [])
                         if getattr(item, "requirement_id", None) == trade_action.requirement_id]
        price = next(((index, item, _price_points(item)) for index, item in price_matches
                      if _price_points(item)), None)
        trade = next(((index, item, _country_rows(item)) for index, item in trade_matches
                      if _country_rows(item)), None)
        if price and trade:
            pidx, _pitem, pp = price
            tidx, _titem, countries = trade
            if pp and countries:
                unit = price_display_unit(getattr(_pitem, "unit", None))
                unit_text = f" {unit}" if unit else ""
                period = getattr(getattr(price_action.slots, "period", None), "kind", None)
                if period == "latest":
                    latest = pp[-1]
                    previous_month = [value for observed, value in pp
                                      if observed.year * 12 + observed.month == latest[0].year * 12 + latest[0].month - 1]
                    country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:3])
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
                    return (f"수급지도 : 수입 상위국 {country_text}\n{price_line}", {pidx, tidx})
                if len(pp) >= 2 and pp[0][1]:
                    change = (pp[-1][1] - pp[0][1]) / pp[0][1] * 100
                    high_date, high = max(pp, key=lambda point: point[1])
                    country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:3])
                    return (f"광물가격 : {pp[0][0].isoformat()}~{pp[-1][0].isoformat()} 가격 {change:+.2f}% 변동, 고점 {_fmt(high)}{unit_text}({high_date.strftime('%Y-%m')})\n"
                            f"수급지도 : 수입국 {country_text}", {pidx, tidx})
                if len(pp) == 1:
                    observed, value = pp[0]
                    country_text = ", ".join(f"{name}({_fmt(share)}%)" for name, share in countries[:3])
                    return (
                        f"광물가격 : {observed.isoformat()} 기준 최근 확인 가격 {_fmt(value)}{unit_text}. "
                        "조회된 가격 관측치가 1건이라 기간 변동률과 추세는 계산할 수 없습니다.\n"
                        f"수급지도 : 수입 상위국 {country_text}",
                        {pidx, tidx},
                    )

    # 세계 생산국과 한국 수입국의 목록/교집합. 같은 국가명이 두 원천에 실제로
    # 있을 때만 공통국으로 표시해 모델이 국가를 추정하지 못하게 한다.
    if ids.count("resource.rank") == 1 and ids.count("trade.country_rank") == 1:
        production = by_action.get("resource.rank", [])
        trade = by_action.get("trade.country_rank", [])
        if len(production) == 1 and len(trade) == 1:
            producers, importers = _country_rows(production[0][1]), _country_rows(trade[0][1])
            if producers and importers:
                production_text = ", ".join(f"{country}({_fmt(share)}%)" for country, share in producers)
                import_text = ", ".join(f"{country}({_fmt(share)}%)" for country, share in importers)
                shared = [country for country, _share in producers if country in {name for name, _ in importers}]
                return (f"광물지도 : 세계 생산 상위국 {production_text}\n"
                        f"핵심광물 수급지도 : 우리나라 수입 상위국 {import_text}\n"
                        f"비교결과 : 공통 국가 {', '.join(shared) if shared else '없음'}",
                        {production[0][0], trade[0][0]})

    if ids.count("price.series") == 1 and ids.count("resource.rank") == 1 and ids.count("trade.country_rank") == 1:
        price, production, trade = by_action.get("price.series", []), by_action.get("resource.rank", []), by_action.get("trade.country_rank", [])
        if len(price) == len(production) == len(trade) == 1:
            points, producers, importers = _price_points(price[0][1]), _country_rows(production[0][1]), _country_rows(trade[0][1])
            if points and producers and importers:
                observed, value = points[-1]
                return (f"광물가격 : 현재가 {_fmt(value)} ({observed.isoformat()})\n광물지도 : 생산 1위 {producers[0][0]}({_fmt(producers[0][1])}%)\n핵심광물 수급지도 : 수입 1위 {importers[0][0]}({_fmt(importers[0][1])}%)", {price[0][0], production[0][0], trade[0][0]})

    # 생산 1위국 비중과 수입 HHI/1위국 비중은 각각의 집계 adapter가 계산한
    # 값만 표시한다. 상위 N개 표만으로 HHI를 재계산하지 않는다.
    if ids.count("resource.rank") == 1 and ids.count("trade.concentration") == 1:
        production = by_action.get("resource.rank", [])
        trade = by_action.get("trade.concentration", [])
        if len(production) == 1 and len(trade) == 1:
            producer_rows = []
            for table in extract_markdown_tables(production[0][1].text):
                if {"생산 1위국", "생산 1위국 비중"} <= set(table["columns"]) and table["rows"]:
                    country_i, share_i = table["columns"].index("생산 1위국"), table["columns"].index("생산 1위국 비중")
                    row = table["rows"][0]
                    share = _number(row[share_i])
                    if share is not None:
                        producer_rows.append((row[country_i], share))
            import_rows = _country_rows(trade[0][1])
            hhi_match = re.search(r"HHI=([0-9.]+)", getattr(trade[0][1], "section", ""))
            if producer_rows and import_rows and hhi_match:
                country, share = producer_rows[0]
                import_country, import_share = import_rows[0]
                return (f"광물지도 : 생산 1위국 {country}({_fmt(share)}%)\n"
                        f"핵심광물 수급지도 : 수입 CR3는 원천이 제공하지 않아 표시하지 않습니다. "
                        f"HHI {_fmt(_number(hhi_match.group(1)))}, 1위국 {import_country}({_fmt(import_share)}%)",
                        {production[0][0], trade[0][0]})

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
