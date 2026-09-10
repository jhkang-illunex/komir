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
