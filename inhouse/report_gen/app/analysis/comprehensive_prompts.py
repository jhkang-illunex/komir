# -*- coding: utf-8 -*-
"""AI 종합분석·주간뉴스 LLM 지시문 + 출력계약.

기존 5종 요약(`prompts.py`)의 evidence_id 단위 정밀 인용 계약은 여기서는 쓰지
않는다 — WORKLOG(2026-08-13)가 기록한 대로 그 계약은 종합지수 페이지에서만도
로컬 gemma-4-26b 기준 ~1/10 실패율을 낸다(근거 7개를 4문장에 정확히 1회씩
배치해야 하는 빡빡한 계약 때문). 이 기능은 광종 5개 × 매주 도는 배치성 호출이라
같은 정밀도를 요구하면 실패율이 배로 뛴다. 대신 "제공된 사실만 쓰고 숫자를
바꾸지 않는다"는 핵심 규율만 유지하고, 문장 수·근거ID 배치 같은 형식 계약은
느슨하게 둔다 — 실패하면 규칙기반 문장으로 폴백한다(`comprehensive.py`).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

OVERVIEW_INSTRUCTIONS = """\
당신은 핵심광물 수급위기 대시보드의 AI 종합분석 문구를 작성하는 편집기다.
- payload의 사실(수치·단계·광종명)만 사용하고 새 사건·원인·수치를 만들지 않는다.
- core_diagnosis: 종합 위기지수 현재값과 전주 대비 변화, 현재 최고위험 광종을
  한 문장으로 연결한다("종합 위기지수 63.2, 전주 대비 +2.3p 상승, 리튬이 가장
  높은 수준" 같은 형태). 전주 대비 값이 없으면 그 부분은 생략한다.
- 판단 없이 수치만 나열하지 말고, 상승/하락 방향과 그 의미(리스크 확대/완화)를
  분명히 쓴다.
- 존재하지 않는 인과관계(예: 특정 사건이 지수를 올렸다)를 단정하지 않는다 —
  방향과 수준만 서술한다.
- 1문장, 90자 이내로 쓴다.
"""

NEWS_CARD_INSTRUCTIONS = """\
당신은 광종별 주간 뉴스를 요약하는 편집기다. payload의 이벤트 목록(evidence)만
근거로 쓰고, 목록에 없는 사실·수치·기업명·국가명을 만들지 않는다.
- headline: 이번 주 해당 광종에서 가장 중요한 결론을 25자 내외 1줄로 압축한다.
  구체적 사실(무엇이 일어났는지)을 쓰고 "동향", "이슈" 같은 공허한 표현은 피한다.
- driver_up: 가격/공급 리스크를 끌어올린 요인 1개를 1문장으로 쓴다(evidence 중
  direction이 'supply_down'이거나 리스크를 높이는 이벤트 위주로 선택).
- driver_down: 반대로 압력을 완화하는 요인이 evidence에 있으면 1문장, 없으면
  null로 둔다(억지로 만들지 않는다).
- evidence에 없는 국가·기업·수치를 추정하지 않는다.
"""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OverviewNarrative(StrictModel):
    """종합진단 LLM 출력 계약(느슨함 — 문장 1개만)."""

    core_diagnosis: str = Field(min_length=1, max_length=120)


class NewsCardNarrative(StrictModel):
    """뉴스카드 1건 LLM 출력 계약."""

    headline: str = Field(min_length=1, max_length=60)
    driver_up: str | None = Field(default=None, max_length=200)
    driver_down: str | None = Field(default=None, max_length=200)


def build_overview_payload(
    *,
    composite_index: float,
    composite_index_change: float | None,
    top_commodity_name: str,
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    """종합진단 프롬프트용 근거 payload — alerts는 광종별 {name, alert_level, idx_value}."""

    return {
        "composite_index": round(composite_index, 1),
        "composite_index_change": (
            round(composite_index_change, 1) if composite_index_change is not None else None
        ),
        "top_commodity_name": top_commodity_name,
        "alerts": alerts,
    }


def build_news_card_payload(
    *,
    commodity_name: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """뉴스카드 프롬프트용 근거 payload — events는 상위 severity 이벤트만(최대 8건)."""

    return {
        "commodity_name": commodity_name,
        "evidence": [
            {
                "event_type": e.get("event_type"),
                "direction": e.get("direction"),
                "target": e.get("target"),
                "severity": e.get("severity"),
                "text": e.get("evidence_quote"),
            }
            for e in events
        ],
    }
