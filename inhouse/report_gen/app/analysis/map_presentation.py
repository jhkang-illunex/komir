"""지도 보고서의 표시 단위와 동일 조회범위 전년 비교."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from .additional_summary import _number


def compact_quantity(value: float, unit: str) -> tuple[str, str]:
    scales = {"달러": (1, "달러"), "톤": (1, "톤"), "천톤": (1000, "톤"),
              "천 톤": (1000, "톤"), "백만톤": (1000000, "톤"), "백만 톤": (1000000, "톤")}
    if unit not in scales:
        return str(value), unit
    scale, label = scales[unit]
    amount = Decimal(str(value)) * scale
    divisor, suffix = (Decimal(100000000), "억") if abs(amount) >= 100000000 else (Decimal(10000), "만")
    if abs(amount) >= 10000:
        # 2026-09-11 사용자 지적 — 정수(소수점 0자리)로 반올림하면 예를
        # 들어 1.5억~2.49억이 전부 "약 2억"으로 뭉개져(최대 약 33% 상대
        # 오차) "1.7~1.8억인데 2억으로 나온다"는 혼동을 준다. 1차로 소수점
        # 1자리까지 남겼다가, 같은 날 사용자 후속 지시("소수점 이하
        # 3자리에서 반올림해서 2자리까지 표기")로 소수점 2자리까지
        # 확장했다(오차 ±0.5% 수준) — 돈·무게라 더 러프하면 안 된다는
        # 판단. 정수로 딱 떨어지면(예: 2.00억) 불필요한 ".00"은 보이지
        # 않는다.
        rounded = (amount / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        display = f"{int(rounded):,}" if rounded == rounded.to_integral_value() else f"{rounded:,}"
        return f"약 {display}{suffix}", label
    return f"{amount.normalize():,f}", label


def compact_fact(text: str) -> str:
    def replace(match):
        value, unit = match.groups()
        rendered, label = compact_quantity(float(value.replace(',', '')), unit)
        return rendered + (" " if label == "달러" else "") + label
    return re.sub(r"(?<![\d.])(-?\d[\d,]*(?:\.\d+)?)\s*(백만\s*톤|천\s*톤|톤|달러)", replace, text)


def import_history_fact(request, series) -> str | None:
    """과거 원본 응답은 동일 광종·필터·기간 길이인 경우에만 비교한다."""
    from .errors import DataSourceError
    from .input_data import _parse_komis_map_korea_response, _parse_komis_map_global_response

    raw = request.komis_response
    snapshots = request.komis_history_responses or []
    yearly = {}
    if snapshots:
        if raw is None:
            raise DataSourceError("komis_history_responses requires komis_response")
        parser = _parse_komis_map_korea_response if request.page_id == "map_korea" else _parse_komis_map_global_response
        filters = ("srchMnrkndUnqCd", "srchCrtrYmd", "srchNtnCd", "srchMttrFlowCd", "srchMttrFlowDtlCd",
                   "srchHsCd", "srchTypeAW", "srchIncmNtnCd", "srchExpNtnCd", "srchTypeIE", "srchImxprtSeCd")
        try:
            start, end = (datetime.strptime(str(raw[key]), "%Y%m%d").date() for key in ("srchDateS", "srchDateE"))
            if start.year != end.year:
                raise ValueError("comparison requires a single year or year-to-date window")
            for snapshot in [raw, *snapshots]:
                if any((snapshot.get(key) or "") != (raw.get(key) or "") for key in filters):
                    raise ValueError("history filters differ")
                prev_start, prev_end = (datetime.strptime(str(snapshot[key]), "%Y%m%d").date() for key in ("srchDateS", "srchDateE"))
                if (prev_start.month, prev_start.day, prev_end.month, prev_end.day) != (start.month, start.day, end.month, end.day) or prev_start.year != prev_end.year:
                    raise ValueError("history period differs")
                _, totals, _ = parser(snapshot)
                # 상위국 목록은 잘릴 수 있으므로 세계/한국 총액을 목록 합으로 추정하지 않는다.
                if totals is None or totals.get("import_amount") is None:
                    raise ValueError("history total missing")
                if prev_end.year in yearly:
                    raise ValueError("duplicate history year")
                if prev_end.year > end.year:
                    raise ValueError("future history year")
                yearly[prev_end.year] = float(totals["import_amount"])
        except (ValueError, KeyError, TypeError) as exc:
            raise DataSourceError(f"invalid trade history: {exc}") from exc
        current_year = end.year
    elif raw is None:
        dates = sorted({row.date for row in series.observations})
        latest = date.fromisoformat(dates[-1])
        for day in dates:
            parsed = date.fromisoformat(day)
            if (parsed.month, parsed.day) == (latest.month, latest.day):
                yearly[parsed.year] = sum(row.import_amount or 0 for row in series.observations if row.date == day)
        current_year = latest.year
    else:
        return None
    previous_year = current_year - 1
    if previous_year not in yearly:
        return None
    previous, current = yearly[previous_year], yearly[current_year]
    if previous <= 0:
        return None
    change = (current - previous) / previous * 100
    direction = "증가" if change > 0 else "감소"
    comparison = f"{_number(abs(change))}% {direction}했습니다" if change else "변동이 없습니다"
    # 2026-09-13 검수 정정 — ①map_global은 세계 교역 총액인데 "수입액"으로
    # 하드코딩돼 있었다 ②과거 응답은 전년 연간(1/1~12/31) 전체이고 당해는
    # 조회 종료일까지의 집계라 "전년 동기"는 사실과 다르다(리튬 -89%가
    # 대부분 이 차이) — "전년 대비"로 중립화 ③"참고로" 접두어 제거(같은
    # 날 "참고:" 절 제목 제거와 같은 지시).
    label = "세계 교역 총액" if request.page_id == "map_global" else "수입액"
    return (f"동일 조회범위의 {label}은 {previous_year}년 {previous:,.0f}달러에서 "
            f"{current_year}년 {current:,.0f}달러로 전년 대비 {comparison}.")


def route_yearly_trend_fact(request, series) -> str | None:
    """map_global 전용 — 화면의 "주요 교역 루트"(원산국→도착국) 서사에 맞춰
    현재 상위 1~3위 루트의 전년대비 변화를 서술한다(2026-09-13, 발주처
    피드백 §10/§7-3 대응).

    기존 `country_yearly_trend`(`getBarChartDataNation` 기반 국가 단일축
    상위 3개국)는 화면이 보여주는 "1위는 중국→일본 루트" 같은 양자무역
    루트 서사와 축 자체가 달라 지적받았다("호주 교역액"처럼 화면 서사와
    무관한 국가가 나옴). 이 함수는 `import_history_fact`와 같은 재료
    (`komis_history_responses` — 과거 연도 `getListDataNation` 원본, 이미
    `GlobalTradeSummaryRequest`에 배선돼 있었지만 총액 비교에만 쓰였다)를
    (원산국코드, 도착국코드) 키로 매칭해 루트 단위 비교로 확장한다.

    호출부(`summary.py::_respond_trade_map`)가 이 함수보다 먼저
    `import_history_fact()`를 호출해 `komis_history_responses`의 필터
    (광종·기간 등)가 `komis_response`와 전부 일치하는지 이미 검증했다
    (불일치 시 `DataSourceError`로 그 시점에 실패한다) — 이 함수는 그
    검증을 통과한 뒤에만 호출되므로 필터를 다시 확인하지 않는다."""

    from .input_data import _parse_komis_map_global_response

    if request.page_id != "map_global":
        return None
    raw = request.komis_response
    snapshots = request.komis_history_responses or []
    if raw is None or not snapshots:
        return None

    def _routes_by_year(payload):
        observations, _, _ = _parse_komis_map_global_response(payload)
        if not observations:
            return None
        year = int(observations[0]["date"][0:4])
        routes = {(o["origin_country_code"], o["country_code"]): o["import_amount"] for o in observations}
        names = {(o["origin_country_code"], o["country_code"]): (o["origin_country_name"], o["country_name"]) for o in observations}
        return year, routes, names

    current = _routes_by_year(raw)
    if current is None:
        return None
    current_year, current_routes, names = current
    previous_year = current_year - 1
    previous_routes = None
    for snapshot in snapshots:
        parsed = _routes_by_year(snapshot)
        if parsed and parsed[0] == previous_year:
            previous_routes = parsed[1]
            break
    if not previous_routes:
        return None

    ranking = sorted(current_routes.items(), key=lambda item: item[1] or 0.0, reverse=True)
    parts = []
    for rank, (route_key, latest_amount) in enumerate(ranking[: min(3, len(ranking))], start=1):
        previous_amount = previous_routes.get(route_key)
        if not previous_amount:
            continue
        origin_name, dest_name = names.get(route_key, route_key)
        change = (latest_amount - previous_amount) / previous_amount * 100
        direction = "증가" if change > 0 else "감소" if change < 0 else "보합"
        parts.append(
            f"{rank}위 {origin_name}→{dest_name} 루트는 {previous_amount:,.0f}달러에서 "
            f"{latest_amount:,.0f}달러로 {_number(abs(change))}% {direction}"
        )
    if not parts:
        return None
    return f"{current_year}년 기준 {previous_year}년 대비, " + ", ".join(parts) + "했습니다."


def trade_scale_trend_fact(request, series) -> str | None:
    """map_korea 전용 — 수입·수출 규모의 연도별 시계열 문장(2026-09-10
    사용자 지시 — "규입규모 추이 차트용 데이터가 있는데 이걸로 시계열
    변동량 섹션도 추가, 수출/수입 잘 판별해서").

    `komis_history_responses`(과거 연도 `getListKoreaData` 원본, 이미
    `import_history_fact`가 쓰는 것과 같은 필드)를 현재 `komis_response`
    와 합쳐 연도별 (수입액, 수출액) 쌍을 뽑는다. `import_history_fact`
    (수입액만, 최근 2개년 비교 문장 1개)와 달리 이 함수는 **수입·수출
    둘 다**, **최근 최대 5개년**을 각각 독립된 방향 문장으로 명시해
    섞이지 않게 한다(사용자 지시 "잘 판별해서").

    map_global은 대상이 아니다 — `getListDataNation`(map_global의
    komis_response)은 행마다 세계 교역 "루트" 1건(원산국→도착국 쌍)일
    뿐 한국의 수입/수출 방향 쌍이 아니라 "한국의 수출액" 개념 자체가
    없다(map_korea의 `getListKoreaData`만 국가별 행에 `incmAmt`/`expAmt`
    양쪽이 함께 온다 — `calculate_domestic_trade_summary` docstring
    참고).

    반환 문자열은 압축 전 원 단위 숫자를 그대로 담는다 — 다른 map_korea
    근거와 같은 경로(`summary.py::_build_response`)로 나중에 일괄
    `compact_fact()`가 "약 N억/만"으로 축약하므로 여기서 직접 축약하지
    않는다."""

    if request.page_id != "map_korea":
        return None
    raw = request.komis_response
    snapshots = request.komis_history_responses or []
    if raw is None or not snapshots:
        return None
    from .errors import DataSourceError
    from .input_data import _parse_komis_map_korea_response

    filters = (
        "srchMnrkndUnqCd", "srchCrtrYmd", "srchNtnCd", "srchMttrFlowCd",
        "srchMttrFlowDtlCd", "srchHsCd", "srchTypeAW", "srchIncmExp",
    )
    yearly: dict[int, tuple[float, float]] = {}
    try:
        for snapshot in [raw, *snapshots]:
            if any((snapshot.get(key) or "") != (raw.get(key) or "") for key in filters):
                raise ValueError("trend filters differ")
            end = datetime.strptime(str(snapshot["srchDateE"]), "%Y%m%d").date()
            _, totals, _ = _parse_komis_map_korea_response(snapshot)
            if totals is None or totals.get("import_amount") is None:
                raise ValueError("trend total missing")
            if end.year in yearly:
                raise ValueError("duplicate trend year")
            yearly[end.year] = (float(totals["import_amount"]), float(totals.get("export_amount") or 0.0))
    except (ValueError, KeyError, TypeError) as exc:
        raise DataSourceError(f"invalid trade scale trend: {exc}") from exc
    if len(yearly) < 2:
        return None
    years = sorted(yearly)[-5:]
    import_parts = [f"{year}년 {yearly[year][0]:,.0f}달러" for year in years]
    export_parts = [f"{year}년 {yearly[year][1]:,.0f}달러" for year in years]
    span = f"최근 {len(years)}개년({years[0]}~{years[-1]})"
    return (
        f"{span} 수입액 추이는 " + " → ".join(import_parts) + "입니다. "
        "같은 기간 수출액 추이는 " + " → ".join(export_parts) + "입니다."
    )
