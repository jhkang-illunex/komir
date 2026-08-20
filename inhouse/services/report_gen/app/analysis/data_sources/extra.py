# -*- coding: utf-8 -*-
"""광물자원가격·국내/글로벌 수급지도 3종의 DB 정규화기 — komir 자체 추가
(2026-08-19, 이식 아님).

외부repo(`komis_report_generator`)는 `/prices`·`/domestic-trade`·`/global-trade`를
501 스텁으로만 남겨뒀다(참고할 원본 정규화기가 없다). `database.py`(이식본)와
같은 규약(`RawDataset` → 정규화된 Series/Observation, `DataSourceError`로 실패
통일)을 따르되, 이 파일에 있는 것은 komir가 새로 짠 것이다 — 원본과 섞이지
않도록 파일을 분리했다(`database.py`의 "원본에서 바뀐 것은 import 뿐" 주장을
깨지 않기 위함).

광종 코드 해석은 기존 5종처럼 `resources/komis-metadata.subset.json`의 정적
스냅샷(별칭 매칭)을 쓰지 않는다 — 이 3종이 쓰는 `ai_mnrl_mst`·`ai_prc_mnrl_map`·
`ai_hs_mnrl_map`은 스냅샷보다 최신인 라이브 매핑 테이블이라(2026-08-19에 KOMIS가
채움) `KomisRawDataRepository.resolve_*()`로 DB에서 직접 조회한다 — 정확한
`MNRKND_UNQ_CD`만 받는다(별칭 매칭 없음).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.komis_raw import (  # noqa: E402
    AnalysisPreviewRequest,
    KomisRawDataRepository,
)

from ..models import (  # noqa: E402
    MineralRef,
    PriceObservation,
    PriceSeries,
    TradeCountryObservation,
    TradeMapSeries,
)
from ._shared import (  # noqa: E402
    DataSourceError,
    _country_name,
    _date_text,
    _finite_float,
    _load_country_names,
    _version,
    SNAPSHOT_PATH,
)


def _resolve_mineral(repository: KomisRawDataRepository, mineral_code: str) -> MineralRef:
    resolved = repository.resolve_mineral(mineral_code)
    if resolved is None:
        raise DataSourceError(f"{mineral_code!r}에 대응하는 광종 정보가 없다.")
    code, name = resolved
    return MineralRef(code=code, name=name)


class DatabasePriceDataSource:
    """`KO_MNRL_PRC`의 일별 가격 행을 정규화한다."""

    def __init__(self, repository: KomisRawDataRepository) -> None:
        self._repository = repository

    def get_price_series(
        self,
        *,
        mineral: str,
        start_date: str | None,
        end_date: str | None,
    ) -> PriceSeries:
        mineral_ref = _resolve_mineral(self._repository, mineral)
        serials = self._repository.resolve_price_criterion_serials(mineral_ref.code)
        if not serials:
            raise DataSourceError(f"{mineral_ref.name}({mineral_ref.code})에 매핑된 가격기준이 없다.")
        # 광종 1건에 가격기준이 여럿(예: 텅스텐 7건)이면 가장 이른 번호를 쓴다 —
        # 발주 5광종은 전부 1건뿐이라 이 분기가 실제로 갈리지 않는다(2026-08-19 실측).
        serial = serials[0]
        datasets = self._repository.fetch_complete(
            AnalysisPreviewRequest(
                page_id="price_base_metals",
                price_criterion_serial=serial,
                start_period=start_date.replace("-", "") if start_date else None,
                end_period=end_date.replace("-", "") if end_date else None,
            )
        )
        if len(datasets) != 1 or datasets[0].source_table != "KO_MNRL_PRC":
            raise DataSourceError("unexpected price database response")

        observations_by_date: dict[str, PriceObservation] = {}
        for row in datasets[0].rows:
            row_serial = row.get("mnrl_prc_crtr_sn")
            if row_serial is None or int(row_serial) != serial:
                raise DataSourceError(f"unexpected price criterion {row_serial!r} in KO_MNRL_PRC")
            item_date = _date_text(row.get("crtr_ymd"))
            if item_date in observations_by_date:
                raise DataSourceError(f"duplicate price date {item_date} for serial {serial}")
            observations_by_date[item_date] = PriceObservation(
                date=item_date,
                commerce_price=_finite_float(row.get("cmerc_prc")),
                lowest_price=_finite_float(row.get("lowst_prc")),
                highest_price=_finite_float(row.get("hghst_prc")),
                inventory=_finite_float(row.get("invt")),
            )
        if not observations_by_date:
            raise DataSourceError(f"선택한 기간의 {mineral_ref.name} 가격 데이터가 현재 DB에 없습니다.")
        dates = sorted(observations_by_date)
        observations = [observations_by_date[item] for item in dates]
        return PriceSeries(
            mineral=mineral_ref,
            price_criterion_serial=serial,
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="database",
            source_id="komis:price",
            data_version=_version([item.model_dump(mode="json") for item in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )

    def close(self) -> None:
        close = getattr(self._repository, "close", None)
        if callable(close):
            close()


class _TradeMapDataSource:
    """`DatabaseDomesticTradeDataSource`/`DatabaseGlobalTradeDataSource` 공통 조립부."""

    _PAGE_ID: str
    _SOURCE_TABLE: str
    _SOURCE_ID: str

    def __init__(
        self,
        repository: KomisRawDataRepository,
        *,
        metadata_snapshot_path: str | Path = SNAPSHOT_PATH,
    ) -> None:
        self._repository = repository
        self._country_names = _load_country_names(Path(metadata_snapshot_path))

    def _fetch_rows(self, hs_codes: list[str], start_date: str | None, end_date: str | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for hs_code in hs_codes:
            datasets = self._repository.fetch_complete(
                AnalysisPreviewRequest(
                    page_id=self._PAGE_ID,
                    hs_code=hs_code,
                    start_period=start_date.replace("-", "") if start_date else None,
                    end_period=end_date.replace("-", "") if end_date else None,
                )
            )
            if len(datasets) != 1 or datasets[0].source_table != self._SOURCE_TABLE:
                raise DataSourceError(f"unexpected trade map database response for {hs_code}")
            rows.extend(datasets[0].rows)
        return rows

    def _build_series(
        self,
        mineral_ref: MineralRef,
        observations_by_key: dict[tuple[str, str], TradeCountryObservation],
    ) -> TradeMapSeries:
        if not observations_by_key:
            raise DataSourceError(f"선택한 기간의 {mineral_ref.name} 수급지도 데이터가 현재 DB에 없습니다.")
        observations = list(observations_by_key.values())
        dates = sorted({item.date for item in observations})
        return TradeMapSeries(
            page_id=self._PAGE_ID,  # type: ignore[arg-type]
            mineral=mineral_ref,
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="database",
            source_id=self._SOURCE_ID,
            data_version=_version(
                [item.model_dump(mode="json") for item in sorted(observations, key=lambda o: (o.date, o.country_code))]
            ),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )


class DatabaseDomesticTradeDataSource(_TradeMapDataSource):
    """`KO_CSTM_CMMRC`(국내 수급지도, 관세청)의 국가별 수출입 행을 정규화한다."""

    _PAGE_ID = "map_korea"
    _SOURCE_TABLE = "KO_CSTM_CMMRC"
    _SOURCE_ID = "komis:map_korea"

    def get_domestic_trade_series(
        self,
        *,
        mineral: str,
        start_date: str | None,
        end_date: str | None,
    ) -> TradeMapSeries:
        mineral_ref = _resolve_mineral(self._repository, mineral)
        hs_codes = self._repository.resolve_hs_codes(mineral_ref.code)
        if not hs_codes:
            raise DataSourceError(f"{mineral_ref.name}({mineral_ref.code})에 매핑된 HS코드가 없다.")
        rows = self._fetch_rows(hs_codes, start_date, end_date)

        observations_by_key: dict[tuple[str, str], TradeCountryObservation] = {}
        for row in rows:
            item_date = _date_text(row.get("crtr_ymd"))
            country_code = str(row.get("trgt_ntn_cd", "")).strip()
            key = (item_date, country_code)
            incm_weig = _finite_float(row.get("incm_weig")) or 0.0
            incm_amt = _finite_float(row.get("incm_amt")) or 0.0
            exp_weig = _finite_float(row.get("exp_weig")) or 0.0
            exp_amt = _finite_float(row.get("exp_amt")) or 0.0
            existing = observations_by_key.get(key)
            if existing is None:
                observations_by_key[key] = TradeCountryObservation(
                    date=item_date,
                    country_code=country_code,
                    country_name=_country_name(country_code, row.get("trgt_ntn"), self._country_names),
                    import_weight=incm_weig,
                    import_amount=incm_amt,
                    export_weight=exp_weig,
                    export_amount=exp_amt,
                )
            else:
                # 같은 (일자·상대국)이 HS코드별로 여러 행 나오면 그 광종의 세부
                # 품목(예: "리튬 품목A"/"품목B")을 합산한 값이 광종 전체 수치다.
                observations_by_key[key] = TradeCountryObservation(
                    date=item_date,
                    country_code=country_code,
                    country_name=existing.country_name,
                    import_weight=(existing.import_weight or 0.0) + incm_weig,
                    import_amount=(existing.import_amount or 0.0) + incm_amt,
                    export_weight=(existing.export_weight or 0.0) + exp_weig,
                    export_amount=(existing.export_amount or 0.0) + exp_amt,
                )
        return self._build_series(mineral_ref, observations_by_key)

    def close(self) -> None:
        close = getattr(self._repository, "close", None)
        if callable(close):
            close()


class DatabaseGlobalTradeDataSource(_TradeMapDataSource):
    """`KO_UN_CMMRC`(글로벌 수급지도, UN Comtrade)의 국가별 수입 행을 정규화한다.

    이 테이블은 한국 기준이 아니라 임의의 두 나라 사이 양자무역(reporter↔partner)
    이다 — "글로벌 공급망에서 어느 나라가 주요 수출국인가"를 보려고
    `IMXPRT_SE_CD='I'`(수입) 행만 골라 **상대국(수출측, TRGT_NTN_NM)** 기준으로
    묶는다(텅스텐 실데이터로 검증).

    ⚠ **HS코드 자릿수가 `KO_CSTM_CMMRC`와 다르다**(2026-08-19 실측) —
    `ai_hs_mnrl_map`은 관세청 HSK 10자리(예: `8101100000`)인데 `KO_UN_CMMRC`는
    UN Comtrade 국제표준 HS **6자리**(예: `810110`)를 쓴다. 10자리 그대로
    필터하면 텅스텐(실데이터 있는 광종)도 0행이 나온다 — 앞 6자리로 잘라
    중복제거한 뒤 조회한다.
    """

    _PAGE_ID = "map_global"
    _SOURCE_TABLE = "KO_UN_CMMRC"
    _SOURCE_ID = "komis:map_global"

    def get_global_trade_series(
        self,
        *,
        mineral: str,
        start_date: str | None,
        end_date: str | None,
    ) -> TradeMapSeries:
        mineral_ref = _resolve_mineral(self._repository, mineral)
        hsk_codes = self._repository.resolve_hs_codes(mineral_ref.code)
        if not hsk_codes:
            raise DataSourceError(f"{mineral_ref.name}({mineral_ref.code})에 매핑된 HS코드가 없다.")
        hs_codes = sorted({code[:6] for code in hsk_codes if len(code) >= 6})
        rows = self._fetch_rows(hs_codes, start_date, end_date)

        observations_by_key: dict[tuple[str, str], TradeCountryObservation] = {}
        for row in rows:
            if str(row.get("imxprt_se_cd", "")).strip() != "I":
                continue
            item_date = _date_text(row.get("crtr_ymd"))
            country_code = str(row.get("exp_ntn_cd", "")).strip()
            country_name = str(row.get("trgt_ntn_nm") or "").strip() or country_code
            key = (item_date, country_code)
            weig = _finite_float(row.get("weig")) or 0.0
            amt = _finite_float(row.get("amt")) or 0.0
            existing = observations_by_key.get(key)
            if existing is None:
                observations_by_key[key] = TradeCountryObservation(
                    date=item_date,
                    country_code=country_code,
                    country_name=country_name,
                    import_weight=weig,
                    import_amount=amt,
                )
            else:
                observations_by_key[key] = TradeCountryObservation(
                    date=item_date,
                    country_code=country_code,
                    country_name=existing.country_name,
                    import_weight=(existing.import_weight or 0.0) + weig,
                    import_amount=(existing.import_amount or 0.0) + amt,
                )
        return self._build_series(mineral_ref, observations_by_key)

    def close(self) -> None:
        close = getattr(self._repository, "close", None)
        if callable(close):
            close()
