# -*- coding: utf-8 -*-
"""분석 데이터소스 공통 계약·정규화 헬퍼 — 외부 저장소
`komis_report_generator/analysis/data_sources/_shared.py` 이식본(2026-08-11).

**원본에서 바뀐 것**
- `SNAPSHOT_PATH`가 원본에서는 `komis_report_generator.search.metadata`(43개 KOMIS
  페이지 챗봇 패키지)에서 왔다. report_gen이 챗봇 패키지를 통째로 끌고 오는 건
  과하므로, analysis 정규화기가 실제로 쓰는 4개 ref만 추린 파생 스냅샷
  (`../resources/komis-metadata.subset.json`)을 기본값으로 둔다. 두 클래스 모두
  `metadata_snapshot_path` 인자를 그대로 받으므로, 나중에 search/ 이식(작업#2)이
  전체 스냅샷을 들여오면 호출부에서 그 경로만 넘기면 된다.
- `RawDataset`/`AnalysisPreviewRequest` 타입 출처가 원본 `analysis.scaffold`에서
  `services/shared/komis_raw.py`로 바뀌었다(그 두 타입과 실제 SQL 리포지토리를
  shared로 옮겼기 때문 — komis_raw.py 상단 주석 참고).
- 원본에 있던 `IndicatorDatabaseRepository`/`CompleteRawDataRepository` Protocol은
  `komis_raw.KomisRawDataRepository` 하나가 두 역할을 다 하므로 생략했다
  (Protocol 정의만 남기고 구현체가 하나면 값어치가 없다).
"""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from ..models import (
    CompositeIndexObservation,
    CompositeIndexSeries,
    MineralRef,
    PageId,
)

_APP_ROOT = Path(__file__).resolve().parents[2]  # .../report_gen/app

#: analysis 정규화기가 쓰는 4개 ref만 담은 파생 스냅샷(파일 안 `_komir_note` 참고).
SNAPSHOT_PATH = _APP_ROOT / "analysis" / "resources" / "komis-metadata.subset.json"

SUPPLY_UNAVAILABLE_PAGE_DATA = [
    "국제가격추이 보조 패널",
    "세계 수요·공급",
    "국내 수입현황",
    "상위 3개국 수입의존도",
    "국가별 생산량 비중",
    "국가별 매장량 비중",
]

COMPOSITE_INDEX_CODES = {
    "HI001": "composite_index",
    "HI002": "major_metals_index",
    "HI003": "minor_metals_index",
}
COMPOSITE_SHEETS = {
    "composite_index": ("광물종합지수",),
    "major_metals_index": ("메이저금속지수",),
    "minor_metals_index": ("희소금속지수", "희유금속지수"),
}


class DataSourceError(RuntimeError):
    """설정된 원천 데이터가 분석 요청을 만족하지 못할 때."""


class IndicatorDataSource(Protocol):
    """정규화된 시장전망/수급안정 지표 계열을 제공한다."""

    def get_series(self, *, page_id, mineral, start_month, end_month): ...


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return " ".join(text.strip().split()).casefold()


def _finite_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _finite_float_with_grouping(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _database_month_text(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return f"{value.year:04d}-{value.month:02d}"
    text = str(value).strip()
    for pattern in ("%Y%m", "%Y%m%d", "%Y-%m", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, pattern)
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DataSourceError(f"cannot parse database month value: {value!r}") from exc
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _date_text(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    for pattern in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d")
    except ValueError as exc:
        raise DataSourceError(f"cannot parse index date: {value!r}") from exc


def _version(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class MineralCatalog:
    """메타데이터 스냅샷에서 광종 별칭·외부코드를 해석한다."""

    def __init__(self, snapshot_path: Path = SNAPSHOT_PATH) -> None:
        try:
            snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataSourceError(f"cannot load mineral metadata: {exc}") from exc
        refs = snapshot.get("refs")
        if not isinstance(refs, dict):
            raise DataSourceError("mineral metadata snapshot has no refs object")
        self._refs: Mapping[str, object] = refs

    def resolve(self, page_id: PageId, token: str) -> MineralRef:
        """시장전망/수급안정 지표의 광종 토큰을 해석한다."""

        ref_name = (
            "metadata.indicators.market_minerals"
            if page_id == "indicator_market"
            else "metadata.indicators.supply_minerals"
        )
        return self._resolve_ref(ref_name, token)

    def resolve_mineral_map(self, token: str) -> MineralRef:
        """광물지도의 광종 토큰을 해석한다."""

        return self._resolve_ref("metadata.maps.mineral_map_minerals", token)

    def _resolve_ref(self, ref_name: str, token: str) -> MineralRef:
        ref = self._refs.get(ref_name)
        if not isinstance(ref, dict) or not isinstance(ref.get("options"), list):
            raise DataSourceError(f"mineral metadata is missing {ref_name}")

        needle = _normalized(token)
        matches: list[dict[str, object]] = []
        for option in ref["options"]:
            if not isinstance(option, dict):
                continue
            variants = [
                option.get("value"),
                option.get("label"),
                option.get("external_value"),
                *(option.get("aliases") or []),
            ]
            if needle in {_normalized(value) for value in variants if value is not None}:
                matches.append(option)
        if len(matches) != 1:
            raise DataSourceError(
                f"mineral {token!r} resolved to {len(matches)} values for {ref_name}"
            )
        match = matches[0]
        return MineralRef(code=str(match["external_value"]), name=str(match["value"]))


def _build_composite_series(
    values: Mapping[str, Mapping[str, float]],
    *,
    start_date: str | None,
    end_date: str | None,
    source_type: str,
    source_id: str,
    data_version: str,
    source_file: str | None = None,
    source_sheets: list[str] | None = None,
    warnings: list[str] | None = None,
) -> CompositeIndexSeries:
    missing = set(COMPOSITE_SHEETS) - set(values)
    if missing:
        raise DataSourceError(f"composite index series are missing: {sorted(missing)}")
    all_dates = sorted(set().union(*(series.keys() for series in values.values())))
    common_dates = sorted(set.intersection(*(set(series) for series in values.values())))
    if not all_dates:
        raise DataSourceError("선택한 기간의 광물종합지수 데이터가 현재 조회 원천에 없습니다.")
    if not common_dates:
        raise DataSourceError("광물종합·메이저금속·희소금속지수의 공통 기준일 데이터가 없습니다.")
    filtered_dates = [
        item
        for item in common_dates
        if (start_date is None or item >= start_date) and (end_date is None or item <= end_date)
    ]
    if not filtered_dates:
        raise DataSourceError("no composite index values found for the requested period")
    effective_warnings = list(warnings or [])
    if len(common_dates) != len(all_dates):
        effective_warnings.append("세 지수의 관측일이 일치하는 날짜만 분석에 사용했다.")
    observations = [
        CompositeIndexObservation(
            date=item,
            composite_index=values["composite_index"][item],
            major_metals_index=values["major_metals_index"][item],
            minor_metals_index=values["minor_metals_index"][item],
        )
        for item in filtered_dates
    ]
    return CompositeIndexSeries(
        available_start_date=common_dates[0],
        available_end_date=common_dates[-1],
        source_type=source_type,
        source_id=source_id,
        data_version=data_version,
        data_as_of=filtered_dates[-1],
        source_file=source_file,
        source_sheets=source_sheets or [],
        observations=observations,
        warnings=effective_warnings,
    )


def _load_country_names(snapshot_path: Path) -> dict[str, str]:
    """메타데이터 스냅샷에서 국가코드→표시명 매핑을 읽는다."""

    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        options = snapshot["refs"]["metadata.information.all_countries"]["options"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise DataSourceError(f"cannot load country metadata: {exc}") from exc
    return {
        str(item["external_value"]): str(item["value"])
        for item in options
        if isinstance(item, dict) and item.get("external_value") and item.get("value")
    }


def _country_name(code: str, raw_name: object, names: Mapping[str, str]) -> str:
    if code == "SU" or raw_name == "_TOTAL_":
        return "세계합계"
    if code == "OT" or raw_name == "_ETC_":
        return "기타"
    text = str(raw_name or "").strip()
    return text or names.get(code, code)
