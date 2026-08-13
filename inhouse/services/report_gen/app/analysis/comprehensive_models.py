# -*- coding: utf-8 -*-
""""AI 종합분석 및 관련뉴스" 응답 스키마 — 화면 기획안 ver.1.3(11페이지) 대응.

기존 분석요약 5종(`models.py`의 `AnalysisSummaryRequest`/`Response`)과 의도적으로
분리했다 — 그쪽은 광종 1개(`MineralRef`)를 받아 지표 1개를 3섹션 서술로 감싸는
계약(`SummaryPageId`)인데, 이 화면은 5광종 통합 현황 1개 + 광종별 뉴스카드 5개로
모양 자체가 다르다. `SummaryPageId`를 넓혀서 억지로 끼워 맞추면 오늘 검증까지
끝낸 기존 5종 계약(`routers/analysis.py`의 "경로를 바꿀 이유가 없다" 원칙)을
건드리게 된다 — CLAUDE.md §4 최소·외과적 변경 원칙에 따라 새 파일로 둔다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskCategory = Literal["지정학적", "공급망", "시장", "산업영향"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RiskTag(StrictModel):
    """리스크 요인 태그 1건 — 화면기획 "태그형: 핵심 내용만 키워드 형식"."""

    category: RiskCategory
    text: str = Field(min_length=1, max_length=80)


class ComprehensiveOverview(StrictModel):
    """종합진단(현황→원인→대응) — 대시보드 최상단 AI 종합분석."""

    as_of: str = Field(description="geo_index 최신 주간(freq=W) period, YYYY-MM-DD(일요일)")
    composite_index: float = Field(description="5광종 idx_value 평균")
    composite_index_change: float | None = Field(
        default=None, description="전주 대비 변동폭(포인트), 직전 주 데이터 없으면 null"
    )
    top_commodity: str = Field(description="이번 주 idx_value가 가장 높은 광종 코드")
    core_diagnosis: str = Field(description="현황 — 정량 요약 1문장")
    risk_tags: list[RiskTag] = Field(default_factory=list, description="원인 — 리스크 요인 태그")
    response_strategies: list[str] = Field(
        default_factory=list,
        description="대응 — 고정 카탈로그에서 태그 매핑(LLM 생성 아님, policy 성격상 규칙기반)",
    )
    llm_refined: bool = Field(description="core_diagnosis가 LLM 다듬기를 거쳤는지")
    warnings: list[str] = Field(default_factory=list)


class WeeklyNewsCard(StrictModel):
    """광종 1개의 주간 뉴스 카드 — 화면기획 "제목 25자 내외 + 상승/하락 압력 요인"."""

    commodity_code: str
    commodity_name: str
    headline: str = Field(max_length=60, description="핵심 결론 1줄(기획 스펙 25자 내외, 여유를 둠)")
    driver_up: str | None = Field(default=None, description="가격을 움직인 주된 요인(상승 압력)")
    driver_down: str | None = Field(default=None, description="반대/제약 요인(없으면 생략)")
    as_of: str
    llm_refined: bool
    source_count: int = Field(description="이번 주 근거로 쓴 geo_event 건수")


class ComprehensiveDashboardResponse(StrictModel):
    """`GET /api/v1/dashboard/comprehensive` 응답 전체."""

    overview: ComprehensiveOverview
    news: list[WeeklyNewsCard]
    generated_at: str
