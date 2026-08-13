# -*- coding: utf-8 -*-
"""분석문 생성 지시문과 근거로 한정된 payload — 외부 저장소
`komis_report_generator/analysis/prompts.py` 이식본(2026-08-13).

**원본에서 뺀 것**: `NARRATIVE_INSTRUCTIONS`·`build_narrative_payload()`.
둘은 profile_id 기반 분석 경로(`AnalysisResponse`/`NarrativeOutput`) 전용인데,
외부repo에서도 5개 운영 엔드포인트가 아니라
`experiments/analysis_summary_evaluation/profile_service.py`만 쓴다(2026-08-13
grep 실측) — 소비자 없는 코드를 들여오지 않는다(CLAUDE.md §4).

그 밖에는 지시문 문구·출력계약(section_sentence_ranges 등)까지 원본 그대로다.
import 경로만 상대경로로 바꿨다.
"""
from __future__ import annotations

from typing import Any

from .additional_summary import SummaryPageContext
from .models import AnalysisSummaryResponse
from .policy import PagePolicy

SUMMARY_COMMON_INSTRUCTIONS = """\
당신은 KOMIS 수치를 단순히 읽어 주는 사람이 아니라,
확인된 근거 사이의 관계를 설명하는 분석 편집기다.
- allowed_evidence에 있는 사실만 사용하고 각 문장에 사용한 evidence_id를 표시한다.
- 관련 근거 2~3개를 한 문장에 연결해 대비, 지속 여부, 현재 위치 또는 구조적 의미를 설명한다.
- 모든 근거를 항목별로 다시 나열하지 말고, 수치가 보여 주는 핵심 판단을 먼저 쓴다.
- 숫자, 기간, 단계, 순위, 변화 방향을 바꾸거나 새로 만들지 않는다.
- 원본 DB 행, 내부 테이블명, 제공되지 않은 원인·사건·단위·발생확률을 추정하지 않는다.
- 같은 수치나 판단을 다른 섹션에서 반복하지 않는다.
- `확인할 수 있다`, `나타났다`만 반복하지 말고 `~지만`, `~인 반면`, `따라서`로 관계를 분명히 한다.
- `YYYY-MM` 형식의 기준월은 숫자를 바꾸지 않고 `YYYY년 M월`로 자연스럽게 쓴다.
- 분석범위, 데이터 결측, 면책 문구는 본문에 쓰지 않는다.
- 최근 한 달 변화만으로 장기 `추세`라고 표현하지 않는다.
"""

MARKET_SUMMARY_INSTRUCTIONS = """\
- core_diagnosis는 현재 중장기 가격위험 단계와 최근 변화가 같은 방향인지 한 문장으로 판단한다.
- major_changes는 단계 유지·전환과 가장 큰 변화를 연결해
  현재 상태가 형성된 흐름을 한 문장으로 설명한다.
- current_position은 최근 가격 움직임과 조회기간 평균 대비 점수를 연결하되
  인과관계로 단정하지 않는다.
- 단기 점수 개선에도 평균보다 위험이 높으면
  `단기 완화에도 평균보다 높은 위험`처럼 남은 약점을 분명히 쓴다.
- 단계 유지 자체를 정체·고착으로 해석하지 않고 위험 단계가 지속됐다고만 설명한다.
- 최대 월간 변화와 최근 단계 전환의 시점이 다르면 인과관계 없이 시간 순서로 구분한다.
"""

SUPPLY_SUMMARY_INSTRUCTIONS = """\
- core_diagnosis는 현재 수급 단계와 최근 수급 안정성 변화를 연결해 한 문장으로 판단한다.
- major_changes는 단계 유지·전환과 가장 큰 변화를 연결해
  현재 상태의 지속성과 변곡점을 한 문장으로 설명한다.
- current_position은 최근 가격 움직임과 조회기간 평균 대비 안정성을 연결하되
  원인으로 단정하지 않는다.
- 단기 개선에도 평균보다 안정성이 낮으면 `단기 반등에도 평균 수준을 회복하지 못함`을 분명히 쓴다.
- 단계 유지 자체를 정체·고착으로 해석하지 않고 수급 단계가 지속됐다고만 설명한다.
- 최대 월간 변화와 최근 단계 전환의 시점이 다르면 인과관계 없이 시간 순서로 구분한다.
"""

COMPOSITE_SUMMARY_INSTRUCTIONS = """\
- core_diagnosis는 현재 지수와 단기·1년 방향을 연결해 한 문장으로 판단한다.
- major_changes는 종합지수와 메이저·희소금속 하위지수의 움직임을 연결해
  어느 쪽 변화가 두드러졌는지 1~2문장으로 설명한다.
- current_position은 조회기간 고저점 위치와 단기·장기 방향을 연결해 현재 수준의 의미를 판단한다.
- 하위지수의 방향이 다르면 전체 지수만으로 가려지는 차별화를 명시하되 원인을 추정하지 않는다.
"""

MINERAL_MAP_SUMMARY_INSTRUCTIONS = """\
- 세계 전체 규모의 변화와 상위 국가 집중도 변화를 연결해 분포가 넓어졌는지 집중됐는지 판단한다.
- required=true인 근거는 반드시 사용하고, optional 근거는 핵심 흐름에 필요할 때만 선택한다.
- 같은 섹션의 관련 근거는 한 문장에 최대 3개까지 연결할 수 있으며, 근거를 단순 나열하지 않는다.
- 한 근거에 서로 다른 국가의 변화가 함께 있으면 두 문장으로 나누되 같은 내용을 반복하지 않는다.
- core_diagnosis는 현재 세계 규모와 기간 변화를 연결해 1~2문장으로 쓴다.
- major_changes는 현재 상위 국가의 규모·비중·순위를 2~3문장으로 설명한다.
- current_position은 국가별 기간 변화와 집중도 변화를 연결하고 그 의미를 2~3문장으로 쓴다.
- 전체는 5~8문장으로 쓰며 같은 수치나 판단을 다른 섹션에서 반복하지 않는다.
- `상위 국가 중심`, `특정 한 국가가 압도하지 않음` 같은 판단은 이를 뒷받침하는 비중과 함께 쓴다.
- 비교연도 값이 없는 국가를 0으로 보거나 매장량·생산량이 새로 생겼다고 표현하지 않는다.
- 매장량·생산량의 수치 변화는 `성장`보다 `증가` 또는 `감소`로 표현한다.
"""

PRICE_FORECAST_SUMMARY_INSTRUCTIONS = """\
- core_diagnosis는 전망 시작·종료 변화와 경로 전환을 연결해
  전체 방향과 경로의 안정성을 한 문장으로 판단한다.
- major_changes는 첫 예측값과 고점·저점을 연결해
  어느 시점에 상승·하락 압력이 두드러지는지 한 문장으로 설명한다.
- current_position은 마지막 값의 고저 범위 내 위치를 이용해
  전망 종단부가 강세·약세 어느 쪽에 가까운지 설명한다.
- 예측가격을 확정된 실제가격처럼 표현하지 말고 `예측된다`, `전망된다`, `제시됐다`로 구분한다.
- 예측 정확도, 발생확률, 외부 사건과 가격 변화의 원인을 추정하지 않는다.
- 전체 변화율과 중간 등락을 구분하고, 중간 반등만으로 전체 전망 방향을 뒤집어 설명하지 않는다.
- 예측기간의 등락을 `확정`, `실현`, `발생`으로 표현하지 않는다.
- 제공되지 않은 가격 단위나 결측정보를 본문에 추가하지 않는다.
"""


def summary_instructions(page_id: str) -> str:
    """Select narrative instructions appropriate for a summary page."""

    page_instructions = {
        "indicator_market": MARKET_SUMMARY_INSTRUCTIONS,
        "indicator_supply": SUPPLY_SUMMARY_INSTRUCTIONS,
        "indicator_composite": COMPOSITE_SUMMARY_INSTRUCTIONS,
        "map_mineral": MINERAL_MAP_SUMMARY_INSTRUCTIONS,
        "forecast_price": PRICE_FORECAST_SUMMARY_INSTRUCTIONS,
    }
    return SUMMARY_COMMON_INSTRUCTIONS + page_instructions[page_id]


def build_summary_payload(
    *,
    response: AnalysisSummaryResponse,
    policy: PagePolicy | SummaryPageContext,
    allowed_evidence: list[dict[str, str]],
    previous_validation_error: str | None = None,
) -> dict[str, Any]:
    """Build an evidence-bounded payload for summary refinement."""

    if response.page_id == "map_mineral":
        required_ids = [
            item["evidence_id"]
            for item in allowed_evidence
            if item.get("required") is True
        ]
        output_contract: dict[str, Any] = {
            "mode": "select_and_synthesize",
            "required_evidence_ids": required_ids,
            "optional_evidence_ids": [
                item["evidence_id"]
                for item in allowed_evidence
                if item.get("required") is not True
            ],
            "max_evidence_ids_per_sentence": 3,
            "section_sentence_ranges": {
                "core_diagnosis": [1, 2],
                "major_changes": [2, 3],
                "current_position": [2, 3],
            },
            "total_sentence_range": [5, 8],
        }
    else:
        section_ranges = {
            "indicator_market": {
                "core_diagnosis": [1, 1],
                "major_changes": [1, 1],
                "current_position": [1, 1],
            },
            "indicator_supply": {
                "core_diagnosis": [1, 1],
                "major_changes": [1, 1],
                "current_position": [1, 1],
            },
            "indicator_composite": {
                "core_diagnosis": [1, 1],
                "major_changes": [1, 2],
                "current_position": [1, 1],
            },
            "forecast_price": {
                "core_diagnosis": [1, 1],
                "major_changes": [1, 1],
                "current_position": [1, 1],
            },
        }[response.page_id]
        output_contract = {
            "mode": "synthesize_all",
            "required_evidence_ids": [
                item["evidence_id"] for item in allowed_evidence
            ],
            "max_evidence_ids_per_sentence": 3,
            "section_sentence_ranges": section_ranges,
            "require_combined_evidence_sentence": True,
        }
    payload: dict[str, Any] = {
        "page_policy": {
            "page_id": policy.page_id,
            "name": policy.name,
            "definition": policy.definition,
            "analysis_constraints": policy.analysis_constraints,
            "policy_version": policy.policy_version,
        },
        "analysis_scope": response.analysis_scope,
        "mineral": response.mineral.model_dump(mode="json"),
        "applied_filters": response.applied_filters,
        "data_quality": response.data_quality.model_dump(mode="json"),
        "output_contract": output_contract,
        "allowed_evidence": allowed_evidence,
    }
    if previous_validation_error:
        payload["previous_validation_error"] = previous_validation_error
    return payload
