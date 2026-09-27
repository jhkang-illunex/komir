"""광종 모집단의 수입·생산 비중과 같은 기간 가격 변동을 결합한다."""
from __future__ import annotations

from calendar import monthrange
from datetime import date
import math

from common.komis_raw import KomisRawDataRepository, RawDataAccessError
from rag_core.ragkit.data_source_policy import DataSourcePolicy, policy_for_data_source
from .evidence import Evidence, KOMIS_RAW_DUMMY_CAVEAT


def _months_ago(today: date, months: int) -> date:
    offset = today.year * 12 + today.month - 1 - months
    year, month_zero = divmod(offset, 12)
    month = month_zero + 1
    return date(year, month, min(today.day, monthrange(year, month)[1]))


def _price_bounds(period, today: date) -> tuple[str, str]:
    if period is None or period.kind == "trailing_months":
        months = period.trailing_months if period and period.trailing_months else 12
        return _months_ago(today, months).strftime("%Y%m%d"), today.strftime("%Y%m%d")
    if period.kind == "calendar_year" and period.calendar_year:
        return f"{period.calendar_year}0101", f"{period.calendar_year}1231"
    if period.kind == "range" and period.start and period.end:
        return period.start.replace("-", ""), period.end.replace("-", "")
    raise ValueError("교차 순위는 최근 N개월, 연도 또는 명시 기간만 지원합니다.")


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _make_evidence(action_id: str, rows: list[dict], *, source: str,
                   section: str, caveat: str | None) -> Evidence:
    if action_id == "trade.price_cross_rank":
        columns = ("rank", "country", "mineral", "share_pct", "trade_start", "trade_end",
                   "price_start", "price_end", "pct_change", "price_criterion",
                   "price_currency_code", "weight_unit_code", "trade_metric")
    else:
        columns = ("rank", "year", "mineral", "country", "share_pct", "price_start",
                   "price_end", "pct_change", "price_criterion", "price_currency_code",
                   "weight_unit_code")
    text = "| " + " | ".join(columns) + " |\n|" + "|".join("---" for _ in columns) + "|"
    text += "\n" + "\n".join("| " + " | ".join(_cell(row.get(key, "")) for key in columns) + " |" for row in rows)
    return Evidence(kind="structured", source=source, section=section, text=text,
                    caveat=caveat)


def fetch_cross_rank_evidence(action_call, *, today: date | None = None,
                              repo: KomisRawDataRepository | None = None) -> tuple[list[Evidence], list[str]]:
    """검증된 한 Action의 교차 순위를 반환한다. 가격 결측은 만들지 않는다."""
    repo = repo or KomisRawDataRepository()
    today = today or date.today()
    slots = action_call.slots
    try:
        start, end = _price_bounds(slots.period, today)
        top_n = slots.top_n or 5
        mineral_names = slots.minerals or ([slots.mineral] if slots.mineral else None)
        if action_call.action_id == "trade.price_cross_rank":
            candidates = repo.fetch_country_import_mineral_shares(
                country=slots.partner_country, metric=slots.metric or "import_amount",
                start_period=start, end_period=end, top_n=top_n,
                mineral_names=mineral_names,
            )
        elif action_call.action_id == "resource.price_cross_rank":
            candidates = repo.fetch_top_producer_mineral_shares(
                year=slots.reference_year, top_n=top_n, mineral_names=mineral_names,
            )
        else:
            raise ValueError("지원하지 않는 교차 순위 Action입니다.")
        if not candidates.rows:
            return [], ["no_data:cross_rank_candidates"]
        policies = [policy_for_data_source(row.get("data_source")) for row in candidates.rows]
        if DataSourcePolicy.SOURCE_UNAVAILABLE in policies:
            return [], ["source_unavailable:cross_rank_provenance_unverified"]
        # 가격 가용기간이 광종마다 달라 전체 후보를 한 번에 비교하면 공통
        # 관측일이 없어 모두 기권할 수 있다. 각 광종의 요청 기간 내 실제 시작·끝
        # 관측값을 조회하고 그 날짜를 행마다 보존한다. 기간이 다른 변동률을
        # 서로 순위화하거나 동일 기간 수치라고 설명하지 않는다.
        by_mineral = {}
        for candidate in candidates.rows:
            try:
                prices = repo.fetch_price_comparison(
                    mineral_names=[candidate["mineral"]],
                    start_period=start, end_period=end,
                )
            except RawDataAccessError:
                continue
            comparison = prices.metadata.get("comparison", [])
            if len(comparison) == 1 and comparison[0].get("start_date") != comparison[0].get("end_date"):
                by_mineral[candidate["mineral"]] = comparison[0]
        missing = [row["mineral"] for row in candidates.rows if row["mineral"] not in by_mineral]
        if missing:
            return [], ["source_unavailable:cross_rank_price_missing:" + ",".join(missing)]
        dummy = DataSourcePolicy.ALLOW_DUMMY in policies
        # 가격 원시행 더미 추적은 광종 마스터의 교역·생산 출처와 별개로 확인한다.
        serials = [repo.resolve_price_criterion_serials(row["mineral_code"])[0]
                   for row in candidates.rows]
        dummy = dummy or any(repo.price_criteria_have_dummy_rows(serials).values())
        joined = []
        for row in candidates.rows:
            price = by_mineral[row["mineral"]]
            pct = price.get("pct_change")
            if pct is None or not math.isfinite(float(pct)):
                return [], ["source_unavailable:cross_rank_price_change_invalid"]
            joined.append({
                **{key: value for key, value in row.items() if key != "data_source"},
                "trade_start": row.get("first_date", ""),
                "trade_end": row.get("last_date", ""),
                "price_start": price["start_date"], "price_end": price["end_date"],
                "pct_change": round(float(pct), 2),
                "price_criterion": price.get("price_criterion") or "",
                "price_currency_code": price.get("price_currency_code") or "",
                "weight_unit_code": price.get("weight_unit_code") or "",
                "trade_metric": slots.metric or "import_amount",
            })
        if action_call.action_id == "trade.price_cross_rank":
            source = "public.KO_CSTM_CMMRC · public.KO_MNRL_PRC"
            section = f"{slots.partner_country} 수입 비중 상위 광종과 동일 기간 가격 변동"
        else:
            source = "public.KO_RSRC_PRDCTN_QUTY · public.KO_MNRL_PRC"
            section = "공식 세계 생산량 대비 1위국 비중 상위 광종과 가격 변동"
        evidence = _make_evidence(action_call.action_id, joined, source=source,
                                  section=section,
                                  caveat=KOMIS_RAW_DUMMY_CAVEAT if dummy else None)
        return [evidence], []
    except (RawDataAccessError, ValueError, IndexError, KeyError) as exc:
        return [], [f"source_unavailable:cross_rank_query:{type(exc).__name__}"]
