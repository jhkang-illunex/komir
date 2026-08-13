# -*- coding: utf-8 -*-
"""`public.KO_*` 원천 행을 분석용 계열로 정규화 — 외부 저장소
`komis_report_generator/analysis/data_sources/database.py` 이식본(2026-08-11).

**원본에서 바뀐 것은 import 뿐**이다: 원본이 `analysis.scaffold`의
`PostgresRawDataRepository`(psycopg 직결)에서 받던 `RawDataset`을, 여기서는
`services/shared/komis_raw.KomisRawDataRepository`(→ `services/shared/db.read_sql_pg`)가
돌려주는 같은 모양의 `RawDataset`으로 받는다. 정규화 로직(중복월 검출·결측 경고
문구·data_version 해시 등)은 원본 그대로다.

⚠ 2026-08-11 실측: `public.KO_*`에 실제로 적재된 광종은 **텅스텐(MNRL0018) 하나**뿐이라
komir 5광종(CU/NI/CO/LI/REE)으로 이 정규화기를 호출하면 `DataSourceError`가 난다.
`services/shared/komis_raw.py` 상단의 실측 노트 참고.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.komis_raw import (  # noqa: E402
    AnalysisPreviewRequest,
    KomisRawDataRepository,
)

from ..indicators import month_ordinal  # noqa: E402
from ..models import (  # noqa: E402
    CompositeIndexSeries,
    ForecastHorizon,
    ForecastPeriod,
    IndicatorObservation,
    IndicatorSeries,
    MineralMapMeasure,
    MineralMapObservation,
    MineralMapSeries,
    Month,
    PageId,
    PriceForecastObservation,
    PriceForecastSeries,
)
from ._shared import (  # noqa: E402
    COMPOSITE_INDEX_CODES,
    COMPOSITE_SHEETS,
    SNAPSHOT_PATH,
    SUPPLY_UNAVAILABLE_PAGE_DATA,
    DataSourceError,
    MineralCatalog,
    _build_composite_series,
    _country_name,
    _database_month_text,
    _date_text,
    _finite_float,
    _finite_float_with_grouping,
    _load_country_names,
    _version,
)


class DatabaseIndicatorDataSource:
    """PostgreSQL 시장전망/수급안정 지표 행을 분석 엔진용으로 정규화한다."""

    _TABLES = {
        "indicator_market": "KO_MRKT_PRSPECT_IDCT",
        "indicator_supply": "KO_SPDM_STBT_INDX",
    }
    _SCORE_COLUMNS = {
        "indicator_market": "mrkt_prspect_idct",
        "indicator_supply": "spdm_stbt_indx",
    }

    def __init__(
        self,
        repository: KomisRawDataRepository,
        *,
        metadata_snapshot_path: str | Path = SNAPSHOT_PATH,
    ) -> None:
        self._repository = repository
        self._catalog = MineralCatalog(Path(metadata_snapshot_path))

    def get_series(
        self,
        *,
        page_id: PageId,
        mineral: str,
        start_month: Month | None,
        end_month: Month | None,
    ) -> IndicatorSeries:
        """요청 필터에 맞는 지표 계열 1개를 정규화해 돌려준다."""

        mineral_ref = self._catalog.resolve(page_id, mineral)
        dataset = self._repository.fetch_indicator_dataset(
            page_id=page_id,
            mineral_code=mineral_ref.code,
            start_month=start_month,
            end_month=end_month,
        )
        expected_table = self._TABLES[page_id]
        if dataset.source_table != expected_table:
            raise DataSourceError(
                f"expected database table {expected_table}, got {dataset.source_table}"
            )

        score_column = self._SCORE_COLUMNS[page_id]
        observations_by_month: dict[str, IndicatorObservation] = {}
        seen_months: set[str] = set()
        missing_scores = 0
        invalid_prices = 0
        for row in dataset.rows:
            row_code = str(row.get("mnrknd_unq_cd", "")).strip()
            if row_code != mineral_ref.code:
                raise DataSourceError(f"unexpected mineral code {row_code!r} in {expected_table}")
            month = _database_month_text(row.get("crtr_ymd"))
            if month in seen_months:
                raise DataSourceError(
                    f"duplicate month {month} for {mineral_ref.code} in {expected_table}"
                )
            seen_months.add(month)
            score = _finite_float(row.get(score_column))
            if score is None:
                missing_scores += 1
                continue
            raw_price = row.get("real_prc")
            price = _finite_float(raw_price)
            if raw_price is not None and price is None:
                invalid_prices += 1
            observations_by_month[month] = IndicatorObservation(
                month=month,
                score=score,
                price=price,
                crisis_flag=None,
            )

        source_months = sorted(observations_by_month)
        if not source_months:
            raise DataSourceError(f"no score values found for {mineral_ref.name} in {expected_table}")
        observations = [observations_by_month[month] for month in source_months]
        warnings = [
            "DB 조회 결과에 가격 기준과 가격 단위가 없어 가격의 절대 수준은 해석하지 않는다."
        ]
        if start_month is not None and source_months[0] != start_month:
            warnings.append(
                f"요청 시작월 {start_month}의 데이터가 없어 유효 시작월은 {source_months[0]}이다."
            )
        if end_month is not None and source_months[-1] != end_month:
            warnings.append(
                f"요청 종료월 {end_month}의 데이터가 없어 유효 종료월은 {source_months[-1]}이다."
            )
        internal_missing_months = sum(
            max(month_ordinal(current) - month_ordinal(previous) - 1, 0)
            for previous, current in zip(source_months[:-1], source_months[1:])
        )
        if internal_missing_months:
            warnings.append(
                "선택 기간의 점수 계열에 "
                f"{internal_missing_months}개 월이 내부 누락돼 연속 월 계산에서 제외했다."
            )
        if missing_scores:
            warnings.append(f"점수가 없는 DB 행 {missing_scores}건을 분석에서 제외했다.")
        missing_prices = sum(item.price is None for item in observations)
        if missing_prices:
            warnings.append(f"선택 기간의 가격 {missing_prices}건이 없어 가격 관련 계산에서 제외했다.")
        if invalid_prices:
            warnings.append(f"숫자로 해석할 수 없는 가격 {invalid_prices}건을 결측 처리했다.")
        if page_id == "indicator_supply":
            warnings.append("현재 DB 조회 결과에는 공식 위기발생 값이 없어 crisis_flag를 비워 두었다.")

        version_payload: list[dict[str, Any]] = [
            observation.model_dump(mode="json") for observation in observations
        ]
        data_version = hashlib.sha256(
            json.dumps(
                version_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return IndicatorSeries(
            page_id=page_id,
            mineral=mineral_ref,
            requested_start_month=start_month,
            requested_end_month=end_month,
            available_start_month=source_months[0],
            available_end_month=source_months[-1],
            source_type="database",
            source_id=f"komis:{page_id}",
            data_version=data_version,
            data_as_of=source_months[-1],
            observations=observations,
            unavailable_page_data=(
                SUPPLY_UNAVAILABLE_PAGE_DATA if page_id == "indicator_supply" else []
            ),
            warnings=warnings,
        )

    def close(self) -> None:
        """백엔드 리포지토리에 close가 있으면 호출한다."""

        close = getattr(self._repository, "close", None)
        if callable(close):
            close()


class DatabaseCompositeIndexDataSource:
    """광물종합지수 3계열(HI001/HI002/HI003)을 기준일로 정렬해 정규화한다."""

    def __init__(self, repository: KomisRawDataRepository) -> None:
        self._repository = repository

    def get_composite_series(
        self,
        *,
        start_date: str | None,
        end_date: str | None,
    ) -> CompositeIndexSeries:
        """세 종합지수 계열을 기준일 기준으로 맞춰 돌려준다."""

        datasets = self._repository.fetch_complete(
            AnalysisPreviewRequest(
                page_id="indicator_composite",
                start_period=start_date.replace("-", "") if start_date else None,
                end_period=end_date.replace("-", "") if end_date else None,
            )
        )
        if len(datasets) != 1 or datasets[0].source_table != "KO_MNRL_SNTHS_INDX":
            raise DataSourceError("unexpected composite index database response")
        values: dict[str, dict[str, float]] = {field: {} for field in COMPOSITE_SHEETS}
        for row in datasets[0].rows:
            field = COMPOSITE_INDEX_CODES.get(str(row.get("indx_se_cd", "")).strip())
            if field is None:
                continue
            item_date = _date_text(row.get("crtr_ymd"))
            item_value = _finite_float_with_grouping(row.get("indx"))
            if item_value is None or item_value <= 0:
                continue
            if item_date in values[field]:
                raise DataSourceError(f"duplicate composite index date {item_date} for {field}")
            values[field][item_date] = item_value
        version_payload = {field: sorted(series.items()) for field, series in values.items()}
        return _build_composite_series(
            values,
            start_date=start_date,
            end_date=end_date,
            source_type="database",
            source_id="komis:indicator_composite",
            data_version=_version(version_payload),
        )


class DatabasePriceForecastDataSource:
    """`KO_MNRL_PRC_PREDC`의 연간/분기 예측가격 행을 정규화한다(2026-08-13 이식)."""

    _QUARTERS = {
        "PE201": "Q1",
        "PE202": "Q2",
        "PE203": "Q3",
        "PE204": "Q4",
    }
    _PRICE_UNITS = {
        "PR001": "USD",
        "PR002": "천불",
        "PR003": "백만불",
        "PR004": "억불",
    }

    def __init__(
        self,
        repository: KomisRawDataRepository,
        *,
        metadata_snapshot_path: str | Path = SNAPSHOT_PATH,
    ) -> None:
        self._repository = repository
        self._catalog = MineralCatalog(Path(metadata_snapshot_path))

    def get_price_forecast_series(
        self,
        *,
        mineral: str,
        horizon: ForecastHorizon,
        start_period: ForecastPeriod | None,
        end_period: ForecastPeriod | None,
    ) -> PriceForecastSeries:
        """문서화된 기간코드로 선택한 예측가격 계열을 돌려준다."""

        mineral_ref = self._catalog.resolve_price_forecast(mineral)
        datasets = self._repository.fetch_complete(
            AnalysisPreviewRequest(
                page_id="forecast_price",
                mineral_code=mineral_ref.code,
            )
        )
        if len(datasets) != 1 or datasets[0].source_table != "KO_MNRL_PRC_PREDC":
            raise DataSourceError("unexpected price forecast database response")

        values: dict[str, float] = {}
        unit_codes: set[str] = set()
        for row in datasets[0].rows:
            row_code = str(row.get("mnrknd_unq_cd", "")).strip()
            if row_code != mineral_ref.code:
                raise DataSourceError(
                    f"unexpected mineral code {row_code!r} in KO_MNRL_PRC_PREDC"
                )
            period_code = str(row.get("prd_se_cd", "")).strip()
            year = str(row.get("crtr_ymd", "")).strip()[:4]
            if len(year) != 4 or not year.isdigit():
                continue
            if horizon == "medium":
                quarter = self._QUARTERS.get(period_code)
                if quarter is None:
                    continue
                period = f"{year}-{quarter}"
            else:
                if period_code != "PE001":
                    continue
                period = year
            if (start_period is not None and period < start_period) or (
                end_period is not None and period > end_period
            ):
                continue
            price = _finite_float(row.get("predc_prc"))
            if price is None or price <= 0:
                continue
            previous = values.get(period)
            if previous is not None and previous != price:
                raise DataSourceError(f"conflicting price forecasts for {period}")
            values[period] = price
            unit_code = str(row.get("prc_unit_cd") or "").strip()
            if unit_code:
                unit_codes.add(unit_code)

        if not values:
            horizon_name = "중기 분기" if horizon == "medium" else "장기 연간"
            raise DataSourceError(
                f"선택한 광종·기간의 {horizon_name} 가격예측 데이터가 현재 DB에 없습니다."
            )
        if len(values) < 2:
            raise DataSourceError("가격예측 분석에는 서로 다른 예측시점이 2개 이상 필요합니다.")
        if len(unit_codes) > 1:
            raise DataSourceError("price forecast rows contain multiple price units")
        periods = sorted(values)
        observations = [
            PriceForecastObservation(period=period, price=values[period])
            for period in periods
        ]
        price_unit = self._PRICE_UNITS.get(next(iter(unit_codes))) if unit_codes else None
        warnings = []
        if price_unit is None:
            warnings.append("가격 단위가 없어 예측가격의 절대 단위는 표시하지 않는다.")
        return PriceForecastSeries(
            mineral=mineral_ref,
            horizon=horizon,
            available_start_period=periods[0],
            available_end_period=periods[-1],
            price_unit=price_unit,
            source_type="database",
            source_id="komis:forecast_price",
            data_version=_version([item.model_dump(mode="json") for item in observations]),
            data_as_of=periods[-1],
            observations=observations,
            warnings=warnings,
        )

    def close(self) -> None:
        """백엔드 리포지토리에 close가 있으면 호출한다."""

        close = getattr(self._repository, "close", None)
        if callable(close):
            close()


class DatabaseMineralMapDataSource:
    """매장량/생산량 행을 톤 환산 기준으로 정규화한다."""

    def __init__(
        self,
        repository: KomisRawDataRepository,
        *,
        metadata_snapshot_path: str | Path = SNAPSHOT_PATH,
    ) -> None:
        self._repository = repository
        snapshot_path = Path(metadata_snapshot_path)
        self._catalog = MineralCatalog(snapshot_path)
        self._country_names = _load_country_names(snapshot_path)

    def get_mineral_map_series(
        self,
        *,
        mineral: str,
        measure: MineralMapMeasure,
        start_year: int | None,
        end_year: int | None,
    ) -> MineralMapSeries:
        """요청 광종·항목·기간의 매장량 또는 생산량 관측을 톤 단위로 돌려준다."""

        mineral_ref = self._catalog.resolve_mineral_map(mineral)
        datasets = self._repository.fetch_complete(
            AnalysisPreviewRequest(
                page_id="map_mineral",
                mineral_code=mineral_ref.code,
                start_period=str(start_year) if start_year else None,
                end_period=str(end_year) if end_year else None,
            )
        )
        table = "KO_RSRC_BURUDG_QUTY" if measure == "reserves" else "KO_RSRC_PRDCTN_QUTY"
        value_column = "burudg_quty_ton" if measure == "reserves" else "prdctn_quty_ton"
        dataset = next((item for item in datasets if item.source_table == table), None)
        if dataset is None:
            raise DataSourceError(f"mineral map database response has no {table}")

        observations_by_key: dict[tuple[int, str], MineralMapObservation] = {}
        for row in dataset.rows:
            row_code = str(row.get("mnrknd_unq_cd", "")).strip()
            if row_code != mineral_ref.code:
                raise DataSourceError(f"unexpected mineral code {row_code!r} in {table}")
            year = int(str(row.get("crtr_yr", ""))[:4])
            country_code = str(row.get("ntn_eng_cd", "")).strip()
            value = _finite_float_with_grouping(row.get(value_column))
            if value is None or value < 0:
                continue
            observation = MineralMapObservation(
                year=year,
                country_code=country_code,
                country_name=_country_name(country_code, None, self._country_names),
                value=value,
                is_total=country_code == "SU",
                is_other=country_code == "OT",
            )
            key = (year, country_code)
            previous = observations_by_key.get(key)
            if previous is not None and previous.value != observation.value:
                raise DataSourceError(f"conflicting mineral map values for {year} {country_code}")
            observations_by_key[key] = observation
        observations = list(observations_by_key.values())
        if not observations:
            raise DataSourceError("선택한 광종·항목·기간의 광물지도 데이터가 현재 DB에 없습니다.")
        years = sorted({item.year for item in observations})
        warnings = []
        if not any(item.is_total for item in observations):
            warnings.append("세계합계 행이 없어 전체 조회 국가의 톤 환산량 합계를 기준으로 계산했다.")
        version_payload = [
            item.model_dump(mode="json")
            for item in sorted(observations, key=lambda value: (value.year, value.country_code))
        ]
        return MineralMapSeries(
            mineral=mineral_ref,
            measure=measure,
            unit="톤",
            available_start_year=years[0],
            available_end_year=years[-1],
            source_type="database",
            source_id="komis:map_mineral",
            data_version=_version(version_payload),
            data_as_of=str(years[-1]),
            observations=observations,
            warnings=warnings,
        )
