"""KOMIS 광물 재고량의 읽기 전용 어댑터."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from common.db import pg_connect
from .evidence import Evidence


def _subtract_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    # The source accepts YYYYMMDD.  Clamp month-end dates deterministically.
    import calendar
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _period_bounds(period: Any) -> tuple[str | None, str | None, bool]:
    """Return source bounds and whether the request is a time series."""
    if period is None:
        return None, None, False
    if hasattr(period, "model_dump"):
        period = period.model_dump(mode="json", exclude_none=True)
    if not isinstance(period, Mapping):
        return None, None, False
    kind = str(period.get("kind") or "").casefold()
    if kind in {"latest", ""}:
        return None, None, False
    if kind == "trailing_months" and period.get("trailing_months"):
        end = date.today()
        start = _subtract_months(end, int(period["trailing_months"]))
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), True
    if kind == "calendar_year" and period.get("calendar_year"):
        year = int(period["calendar_year"])
        return f"{year:04d}0101", f"{year:04d}1231", True
    if kind == "range" and (period.get("start") or period.get("end")):
        start = str(period.get("start") or "00010101").replace("-", "")
        end = str(period.get("end") or date.today().isoformat()).replace("-", "")
        return start[:8], end[:8], True
    return None, None, False


def _monthly_last_rows(rows: list[tuple]) -> list[tuple]:
    """Keep the last inventory level in each month, never sum stock levels."""
    grouped: dict[tuple[str, object], tuple] = {}
    for row in rows:
        try:
            observed = date.fromisoformat(str(row[0])[:4] + "-" + str(row[0])[4:6] + "-" + str(row[0])[6:8])
        except (ValueError, IndexError):
            continue
        criterion = row[2]
        key = (observed.strftime("%Y-%m"), criterion)
        # Keep the source value but expose the monthly bucket so the existing
        # table contract does not sum inventory levels as if they were flows.
        grouped[key] = (observed.strftime("%Y-%m"), *row[1:])
    return [grouped[key] for key in sorted(grouped)]


def fetch_inventory_evidence(mineral: str | None, *, basis: str | None = None,
                             price_criterion_serial: int | None = None,
                             period: Any = None,
                             action_id: str = "inventory.latest") -> tuple[list[Evidence], list[str]]:
    """`ko_mnrl_prc.invt`만 재고로 반환하고 가격 값과 섞지 않는다.

    ``inventory.latest``는 한 관측값, ``inventory.series``는 기간 내 월별
    마지막 관측값을 반환한다. 두 capability는 동일한 source query와
    canonical evidence 계약을 공유하며, action identity만 분리한다.
    광종은 매핑 테이블에서 가격기준 일련번호로 해소하고, 그 일련번호를
    `ko_mnrl_prc_crtr`에 연결해 재고 기준명(`prc_crtr`)을 함께 보존한다.
    """
    if action_id not in {"inventory.latest", "inventory.series"}:
        return [], ["inventory_unsupported_action"]
    if action_id == "inventory.series" and period is None:
        return [], ["inventory_series_period_required"]

    con = None
    try:
        con = pg_connect()
        with con.cursor() as cur:
            criterion_filter = ""
            params: list[object] = [mineral] if mineral else []
            mineral_filter = "m.mnrl_nm_ko = %s" if mineral else "pm.mnrl_prc_crtr_sn = %s"
            if not mineral:
                params = [price_criterion_serial]
            requested_start, requested_end, requested_series = _period_bounds(period)
            if action_id == "inventory.series" and not requested_series:
                return [], ["inventory_series_bounded_period_required"]
            # `latest` is deliberately scalar even if a stale/legacy caller
            # still carries a period slot. Only the explicit series capability
            # is allowed to widen the source query.
            start_period = requested_start if action_id == "inventory.series" else None
            end_period = requested_end if action_id == "inventory.series" else None
            is_series = action_id == "inventory.series"
            if basis:
                criterion_filter = " AND c.prc_crtr ILIKE %s"
            params.append(end_period or date.today().strftime("%Y%m%d"))
            period_filter = ""
            if start_period:
                period_filter = " AND p.crtr_ymd >= %s"
                params.append(start_period)
            if basis:
                # SQL의 기준명 조건은 기준일 조건 뒤에 위치한다.
                params.append(f"%{basis}%")
            if not is_series:
                params.append(1)
            limit_sql = "" if is_series else " LIMIT %s"
            order_sql = "ASC" if is_series else "DESC"
            cur.execute(
                "SELECT p.crtr_ymd, p.invt, c.prc_crtr, c.weig_unit_cd, m.mnrl_nm_ko "
                "FROM public.ai_prc_mnrl_map pm "
                "JOIN public.ai_mnrl_mst m ON m.mnrknd_unq_cd = pm.mnrknd_unq_cd "
                "JOIN public.ko_mnrl_prc_crtr c ON c.mnrl_prc_crtr_sn = pm.mnrl_prc_crtr_sn "
                "JOIN public.ko_mnrl_prc p ON p.mnrl_prc_crtr_sn = c.mnrl_prc_crtr_sn "
                "WHERE " + mineral_filter + " AND pm.use_yn = 'Y' "
                "AND p.status = 'Y' AND p.last_del_dt IS NULL "
                "AND p.invt IS NOT NULL AND p.invt <> 0 AND p.crtr_ymd <= %s" + period_filter + criterion_filter +
                f" ORDER BY p.crtr_ymd {order_sql}, p.mnrl_prc_crtr_sn ASC" + limit_sql,
                tuple(params),
            )
            if is_series:
                rows = cur.fetchall()
            else:
                row = cur.fetchone()
                rows = [row] if row else []
    except Exception as exc:  # noqa: BLE001
        return [], [f"inventory_query_failed:{type(exc).__name__}"]
    finally:
        if con is not None:
            con.close()
    if not rows:
        return [], ["inventory_not_found"]
    # A series keeps every observation row; latest retains the historical
    # single-row behavior.  Do not collapse multiple criteria into one value.
    rows = [row for row in rows if row]
    if not rows:
        return [], ["inventory_not_found"]
    if is_series:
        rows = _monthly_last_rows(rows)
        if not rows:
            return [], ["inventory_not_found"]
    latest_day = rows[-1][0]
    # weig_unit_cd는 기준정보의 원시 단위 코드다. 별도 단위 사전 확인 전에는
    # 임의로 ton/kg을 붙이지 않고 코드 그대로 보존한다.
    text_rows = []
    for day, value, criterion, weight_unit, mineral_name in rows:
        text_rows.append(f"| {day} | {mineral_name} | {criterion or '기준 미확인'} | {value} | {weight_unit or '미확인'} |")
    text = "\n".join((
        "| 기준일 | 광종 | 재고 종류 | 재고량 | 원시 단위 코드 |",
        "|---|---|---|---:|---|",
        *text_rows,
    ))
    return [Evidence(kind="structured", source="public.ko_mnrl_prc + public.ko_mnrl_prc_crtr",
                     section=f"KOMIS 재고량 · {rows[-1][4]}", text=text, as_of=str(latest_day),
                     observed_period=(f"{rows[0][0]}~{latest_day}" if is_series else str(latest_day)),
                     unit=f"재고기준={rows[-1][2] or '미확인'}", action_id=action_id)], []
