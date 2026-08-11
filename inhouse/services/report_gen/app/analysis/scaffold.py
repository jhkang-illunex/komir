# -*- coding: utf-8 -*-
"""원천데이터 미리보기 서비스 — 외부 저장소
`komis_report_generator/analysis/scaffold.py`의 `AnalysisScaffoldService` 이식본
(2026-08-11).

**이 파일은 여전히 스텁이다.** 원본에서도 `analyze()`는 지표 계산과 LLM 분석문
생성 자리를 TODO로 비워둔 채 원천 행만 돌려준다(`calculated_indicators=[]`,
`analysis=None`) — 병합계획 문서 §0이 사용자에게 "리포트 생성은 스텁"이라고 이미
정정한 그 부분이다. 없는 기능을 있는 것처럼 포장하지 않기 위해 원본의 TODO 주석을
그대로 남겼다.

실제로 동작하는 리포트 경로는 이 파일이 아니라 `app/generator.py`에 있다
(komir 자신의 산출물 테이블 + jinja2 템플릿 조립 → `out_report` 적재).

원본 `scaffold.py`의 나머지(SQL 스펙·`PostgresRawDataRepository`·
`AnalysisPreviewRequest`·`RawDataset`·`_coerce_period`)는 rag_chat 등 다른
서비스도 쓸 수 있게 `services/shared/komis_raw.py`로 옮겨 이식했다.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.komis_raw import (  # noqa: E402
    _PAGE_DATASETS,
    AnalysisPreviewPageId,
    AnalysisPreviewRequest,
    KomisRawDataRepository,
    RawDataAccessError,
    RawDataset,
    StrictModel,
)

__all__ = [
    "AnalysisPreviewPageId",
    "AnalysisPreviewRequest",
    "AnalysisPreviewResponse",
    "AnalysisScaffoldService",
    "KomisRawDataRepository",
    "RawDataAccessError",
    "RawDataset",
]


class AnalysisPreviewResponse(StrictModel):
    """원천 데이터셋과 (아직 비어 있는) 분석 필드."""

    status: Literal["raw_data_loaded"] = "raw_data_loaded"
    page_id: AnalysisPreviewPageId
    applied_filters: dict[str, str | int]
    datasets: list[RawDataset]
    calculated_indicators: list[dict[str, Any]] = Field(default_factory=list)
    analysis: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AnalysisScaffoldService:
    """계산·서술 단계가 골격 상태인 동안 원천 데이터 미리보기만 조립한다."""

    def __init__(self, repository: KomisRawDataRepository | None = None) -> None:
        self._repository = repository or KomisRawDataRepository()

    def analyze(self, request: AnalysisPreviewRequest) -> AnalysisPreviewResponse:
        """해당 페이지의 원천 데이터셋을 읽고 적용/무시된 필터를 알려준다."""

        datasets = self._repository.fetch(request)

        # TODO: 페이지별 원천데이터에 맞는 지표 산출 코드를 연결한다.
        calculated_indicators: list[dict[str, Any]] = []

        # TODO: 계산된 지표와 공식 설명을 전달해 LLM 분석문을 생성한다.
        #       (komir 이식 시 주: LLM 호출은 반드시 services/shared/llm_client.py의
        #        KomirJsonLLM을 쓸 것 — 클라이언트 2벌 금지)
        analysis = None

        supported_filters = {
            name for spec in _PAGE_DATASETS[request.page_id] for name in spec.filter_columns
        } | {"start_period", "end_period"}
        ignored = sorted(request.requested_filters().keys() - supported_filters)
        applied_filters = {
            key: value
            for key, value in request.requested_filters().items()
            if key in supported_filters
        }
        warnings = [f"현재 DB 골격에서 적용하지 않은 필터: {', '.join(ignored)}"] if ignored else []
        return AnalysisPreviewResponse(
            page_id=request.page_id,
            applied_filters=applied_filters,
            datasets=datasets,
            calculated_indicators=calculated_indicators,
            analysis=analysis,
            warnings=warnings,
        )

    def close(self) -> None:
        """백엔드 리포지토리 자원을 해제한다."""

        self._repository.close()
