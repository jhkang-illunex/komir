# -*- coding: utf-8 -*-
"""분석 계열(series)·관측(observation) 타입 — 외부 저장소
`komis_report_generator/analysis/models.py` 이식본(2026-08-11).

**원본에서 뺀 것**: 요약문 생성기(`analysis/summary.py`·`additional_summary.py`)
전용 모델(`GradeResult`/`Metric`/`DetectedPattern`/`OmittedIndicator`/
`DataQuality`/`SourceInfo`/`Summary*`/`Analysis*Request`/`Analysis*Response`/
`NarrativeOutput`/`PAGE_PROFILES`/`ProfileId`)은 가져오지 않았다 — 그 요약문
엔진 자체를 이번에 이식하지 않았기 때문(사유는 `analysis/__init__.py` 참고).
소비자 없는 타입을 미리 들여오면 죽은 코드가 된다(CLAUDE.md §4 최소 변경).
"""
from __future__ import annotations

from typing import Literal

try:  # pydantic v2
    from typing import Annotated
except ImportError:  # pragma: no cover
    from typing_extensions import Annotated  # type: ignore

from pydantic import BaseModel, ConfigDict, Field

PageId = Literal["indicator_market", "indicator_supply"]
SummaryPageId = Literal[
    "indicator_market",
    "indicator_supply",
    "indicator_composite",
    "map_mineral",
]
Month = Annotated[str, Field(pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")]
MineralMapMeasure = Literal["reserves", "production"]


class StrictModel(BaseModel):
    """정의되지 않은 필드를 거부하는 기반 모델."""

    model_config = ConfigDict(extra="forbid")


class MineralRef(StrictModel):
    """광종의 안정적인 코드와 표시명."""

    code: str
    name: str


class IndicatorObservation(StrictModel):
    """월 단위 지표 점수 1건과 (있으면) 그 시점 가격."""

    month: Month
    score: float = Field(ge=0, le=100)
    price: float | None = None
    crisis_flag: bool | None = None


class IndicatorSeries(StrictModel):
    """출처 메타를 포함한 월별 지표 관측 계열."""

    page_id: PageId
    mineral: MineralRef
    requested_start_month: Month | None = None
    requested_end_month: Month | None = None
    available_start_month: Month
    available_end_month: Month
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[IndicatorObservation] = Field(min_length=1)
    price_unit: str | None = None
    price_criterion: str | None = None
    unavailable_page_data: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompositeIndexObservation(StrictModel):
    """기준일 1건의 광물종합지수와 두 구성지수."""

    date: Day
    composite_index: float = Field(gt=0)
    major_metals_index: float = Field(gt=0)
    minor_metals_index: float = Field(gt=0)


class CompositeIndexSeries(StrictModel):
    """출처 메타를 포함한 광물종합지수 계열."""

    page_id: Literal["indicator_composite"] = "indicator_composite"
    available_start_date: Day
    available_end_date: Day
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[CompositeIndexObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class MineralMapObservation(StrictModel):
    """특정 연도·국가의 광물지도 값(톤 환산)."""

    year: int = Field(ge=1900, le=2100)
    country_code: str
    country_name: str
    value: float = Field(ge=0)
    is_total: bool = False
    is_other: bool = False


class MineralMapSeries(StrictModel):
    """출처 메타를 포함한 광물지도(매장량/생산량) 계열."""

    page_id: Literal["map_mineral"] = "map_mineral"
    mineral: MineralRef
    measure: MineralMapMeasure
    unit: str
    available_start_year: int = Field(ge=1900, le=2100)
    available_end_year: int = Field(ge=1900, le=2100)
    source_type: Literal["file", "database", "api", "snapshot"]
    source_id: str
    data_version: str
    data_as_of: str
    source_file: str | None = None
    source_sheets: list[str] = Field(default_factory=list)
    observations: list[MineralMapObservation] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
