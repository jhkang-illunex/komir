"""지도 보고서의 표시 단위와 동일 조회범위 전년 비교."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP


def compact_quantity(value: float, unit: str) -> tuple[str, str]:
    scales = {"달러": (1, "달러"), "톤": (1, "톤"), "천톤": (1000, "톤"),
              "천 톤": (1000, "톤"), "백만톤": (1000000, "톤"), "백만 톤": (1000000, "톤")}
    if unit not in scales:
        return str(value), unit
    scale, label = scales[unit]
    amount = Decimal(str(value)) * scale
    divisor, suffix = (Decimal(100000000), "억") if abs(amount) >= 100000000 else (Decimal(10000), "만")
    if abs(amount) >= 10000:
        rounded = (amount / divisor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return f"약 {rounded:,}{suffix}", label
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
    comparison = f"{abs(change):.2f}% {direction}했습니다" if change else "변동이 없습니다"
    return (f"참고로 동일 조회범위의 수입액은 {previous_year}년 {previous:,.0f}달러에서 "
            f"{current_year}년 {current:,.0f}달러로 전년 동기 대비 {comparison}.")


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
