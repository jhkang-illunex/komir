# -*- coding: utf-8 -*-
"""검증된 계산 + LLM 분석문 생성 서비스 — 외부 저장소
`komis_report_generator/analysis/summary.py` 이식본(2026-08-13).

5개 분석요약 엔드포인트(시장동향지표·수급동향지표·광물종합지수·광물지도·가격예측)가
전부 이 파일의 `AnalysisSummaryService.analyze()` 하나로 들어온다.

**원본에서 바뀐 것 3가지**

1. **LLM 클라이언트**: `search.llm.JsonLLM`(httpx 기반 별도 구현) →
   `services/shared/llm_client.KomirJsonLLM`. 두 타입은 `invoke(task=, instructions=,
   payload=, output_model=, max_tokens=) -> LLMInvocation` 시그니처가 같게 설계돼
   있어 호출부는 손대지 않았다(`rag_chat`의 `page_recommend/graph.py`가 8/11에 쓴
   같은 방식 — LLM 호출 클라이언트를 2벌 만들지 않는다).
2. **import 경로**: 절대(`komis_report_generator.analysis.*`) → 상대(`.`).
3. **`_refine_with_llm`의 예외 처리 범위**(⚠ 실질적 차이): 원본은 `LLMError`만
   잡는다. 그런데 komir의 `KomirJsonLLM`은 JSON 파싱·스키마 검증 실패만
   `LLMOutputError(LLMError)`로 바꾸고, 그 아래 `OpenAICompatChat.complete()`가
   내는 **전송 계층 오류는 그대로 통과시킨다**(실측: 재시도 소진 시 맨
   `RuntimeError`, 타임아웃·커넥션 오류는 `requests.RequestException`). 그대로
   두면 vLLM이 죽었을 때 규칙기반 요약으로 우아하게 물러나지 않고 API가 500을
   낸다 — 그래서 `RuntimeError`/`OSError`까지 잡아 원본이 의도한 폴백 동작을
   유지한다(`LLMError`·`requests.RequestException`이 각각 그 하위형이다).

계산 로직·검증 규칙(`_validate_llm_summary`)·문구는 원본 그대로다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.llm_client import KomirJsonLLM, LLMError  # noqa: E402

from .additional_summary import (  # noqa: E402
    ADDITIONAL_PAGE_CONTEXTS,
    EvidenceClaim,
    SummaryPageContext,
    calculate_composite_summary,
    calculate_mineral_map_summary,
    calculate_price_forecast_summary,
)
from .data_sources import (  # noqa: E402
    CompositeIndexDataSource,
    IndicatorDataSource,
    MineralMapDataSource,
    PriceForecastDataSource,
)
from .indicators import months_are_contiguous, percent_change  # noqa: E402
from .models import (  # noqa: E402
    AnalysisSummaryRequest,
    AnalysisSummaryResponse,
    DataQuality,
    DetectedPattern,
    GradeResult,
    IndicatorObservation,
    IndicatorSeries,
    Metric,
    MineralRef,
    OmittedIndicator,
    SourceInfo,
    SummaryNarrative,
    SummaryPageId,
    SummarySentence,
)
from .policy import PagePolicy, load_page_policy  # noqa: E402
from .prompts import build_summary_payload, summary_instructions  # noqa: E402

SectionId = Literal["core_diagnosis", "major_changes", "current_position"]


@dataclass(frozen=True, slots=True)
class _EvidenceClaim:
    id: str
    section: SectionId
    fact: str


@dataclass(slots=True)
class _CalculatedSummary:
    grade: GradeResult | None
    claims: list[_EvidenceClaim]
    key_metrics: list[Metric]
    detailed_metrics: list[Metric]
    patterns: list[DetectedPattern]
    omitted: list[OmittedIndicator]


def _number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _metric(
    metric_id: str,
    label: str,
    value: float | int | str | None,
    *,
    unit: str | None = None,
    basis: str | None = None,
    status: Literal["available", "insufficient_data"] = "available",
) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        status=status,
        value=round(value, 6) if isinstance(value, float) else value,
        unit=unit,
        basis=basis,
    )


def _filter_hash(page_id: str, filters: dict[str, str | None]) -> str:
    canonical = json.dumps(
        {"page_id": page_id, "filters": filters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _grade_for_summary(
    series: IndicatorSeries,
    observation: IndicatorObservation,
    policy: PagePolicy,
) -> GradeResult | None:
    if (
        series.page_id == "indicator_supply"
        and observation.score <= 1
    ):
        return None
    return policy.classify(observation.score)


def _score_meaning(page_id: str, change: float) -> str:
    if change == 0:
        return "점수와 지표가 나타내는 상태에 변화가 없었다"
    if page_id == "indicator_market":
        return (
            "중장기 가격위험이 낮아지는 방향으로 움직였다"
            if change > 0
            else "중장기 가격위험이 높아지는 방향으로 움직였다"
        )
    return (
        "수급 안정성이 강화되는 방향으로 움직였다"
        if change > 0
        else "수급 안정성이 약해지는 방향으로 움직였다"
    )


def _score_position_meaning(page_id: str, difference: float) -> str:
    if difference == 0:
        return (
            "중장기 가격위험이 조회기간 평균 수준이다"
            if page_id == "indicator_market"
            else "수급 안정성이 조회기간 평균 수준이다"
        )
    if page_id == "indicator_market":
        return (
            "중장기 가격위험이 조회기간 평균보다 낮은 수준이다"
            if difference > 0
            else "중장기 가격위험이 조회기간 평균보다 높은 수준이다"
        )
    return (
        "수급 안정성이 조회기간 평균보다 높은 수준이다"
        if difference > 0
        else "수급 안정성이 조회기간 평균보다 낮은 수준이다"
    )


def _change_phrase(value: float) -> str:
    if value > 0:
        return f"{_number(value)}점 올라"
    if value < 0:
        return f"{_number(abs(value))}점 내려"
    return "변동 없이"


def _supply_auxiliary_metrics(series: IndicatorSeries) -> list[Metric]:
    auxiliary = series.supply_auxiliary
    if series.page_id != "indicator_supply" or auxiliary is None:
        return []
    metrics: list[Metric] = []
    if auxiliary.international_prices:
        latest = auxiliary.international_prices[-1]
        metrics.append(
            _metric(
                "supply_international_price_latest",
                "국제가격 최신값",
                latest.price,
                basis=latest.month,
            )
        )
    if auxiliary.domestic_imports:
        latest_import = auxiliary.domestic_imports[-1]
        metrics.extend(
            [
                _metric(
                    "supply_domestic_import_weight_latest",
                    "국내 수입중량 최신값",
                    latest_import.import_weight_ton,
                    unit="톤",
                    basis=str(latest_import.year),
                ),
                _metric(
                    "supply_domestic_import_amount_latest",
                    "국내 수입금액 최신값",
                    latest_import.import_amount_million_usd,
                    unit="백만USD",
                    basis=str(latest_import.year),
                ),
            ]
        )
    if auxiliary.world_balances:
        latest_balance = auxiliary.world_balances[-1]
        metrics.extend(
            [
                _metric(
                    "supply_world_demand_latest",
                    "세계 수요 최신값",
                    latest_balance.demand_thousand_ton,
                    unit="천톤",
                    basis=str(latest_balance.year),
                ),
                _metric(
                    "supply_world_supply_latest",
                    "세계 공급 최신값",
                    latest_balance.supply_thousand_ton,
                    unit="천톤",
                    basis=str(latest_balance.year),
                ),
                _metric(
                    "supply_world_balance_latest",
                    "세계 수급 과부족 최신값",
                    latest_balance.balance_thousand_ton,
                    unit="천톤",
                    basis=str(latest_balance.year),
                ),
            ]
        )
    if auxiliary.top_three_dependency_percent is not None:
        dependency_year = (
            str(auxiliary.import_dependencies[0].year)
            if auxiliary.import_dependencies
            else None
        )
        metrics.append(
            _metric(
                "supply_top_three_import_dependency",
                "상위 3개국 수입의존도",
                auxiliary.top_three_dependency_percent,
                unit="%",
                basis=dependency_year,
            )
        )
    return metrics


def _classify_series(
    series: IndicatorSeries,
    policy: PagePolicy,
) -> list[GradeResult | None]:
    return [_grade_for_summary(series, item, policy) for item in series.observations]


def _calculate_summary(series: IndicatorSeries, policy: PagePolicy) -> _CalculatedSummary:
    observations = series.observations
    current = observations[-1]
    previous = observations[-2] if len(observations) >= 2 else None
    grades = _classify_series(series, policy)
    grade = grades[-1]
    omitted: list[OmittedIndicator] = []
    patterns: list[DetectedPattern] = []

    current_grade_metric = _metric(
        "current_grade",
        "현재 단계",
        grade.label if grade else None,
        status="available" if grade else "insufficient_data",
    )
    key_metrics = [
        _metric("current_score", "현재 점수", current.score, unit="점"),
        current_grade_metric,
    ]
    detailed_metrics = [*key_metrics]

    current_fact = (
        f"{current.month} {series.mineral.name} {policy.name}는 "
        f"{_number(current.score)}점"
    )
    if grade is None:
        current_fact += "이며 0~1점 구간은 현재 데이터만으로 단계를 확정하지 않는다."
        omitted.append(
            OmittedIndicator(
                id="current_grade",
                reason="0~1점 구간은 현재 다운로드·기준정보만으로 단계를 확정하지 않는다.",
            )
        )
    else:
        current_fact += f"으로 {grade.label} 단계다."
    claims = [_EvidenceClaim("current_state", "core_diagnosis", current_fact)]

    contiguous_pairs = [
        (before, after, before_grade, after_grade)
        for before, after, before_grade, after_grade in zip(
            observations[:-1],
            observations[1:],
            grades[:-1],
            grades[1:],
            strict=True,
        )
        if months_are_contiguous(before.month, after.month)
    ]
    score_change: float | None = None
    if previous is not None:
        score_change = current.score - previous.score
        comparison = (
            "최근 한 달"
            if months_are_contiguous(previous.month, current.month)
            else "직전 관측치 대비"
        )
        score_fact = (
            f"{comparison}에는 점수가 {_change_phrase(score_change)} "
            f"{_score_meaning(series.page_id, score_change)}."
        )
        key_metrics.append(
            _metric(
                "latest_score_change",
                "최근 점수 변화",
                score_change,
                unit="점",
                basis=f"{previous.month} 대비",
            )
        )
        claims.append(_EvidenceClaim("latest_score_change", "core_diagnosis", score_fact))
    else:
        claims.append(
            _EvidenceClaim(
                "latest_score_change",
                "core_diagnosis",
                "이전 관측치가 없어 최근 점수 변화는 계산하지 않았다.",
            )
        )
        omitted.append(
            OmittedIndicator(id="latest_score_change", reason="이전 관측치가 없다.")
        )

    streak = 0
    if grade is not None:
        streak = 1
        for index in range(len(observations) - 1, 0, -1):
            before_grade = grades[index - 1]
            if (
                before_grade is None
                or before_grade.label != grade.label
                or not months_are_contiguous(
                    observations[index - 1].month,
                    observations[index].month,
                )
            ):
                break
            streak += 1
        streak_basis = "조회범위 내 최소 " if streak == len(observations) else ""
        streak_fact = f"{grade.label} 단계는 {streak_basis}{streak}개월 연속 유지됐다."
        streak_metric = _metric(
            "current_grade_streak",
            "현재 단계 연속기간",
            streak,
            unit="개월",
        )
    else:
        streak_fact = "현재 단계가 확인되지 않아 단계 유지기간은 계산하지 않았다."
        streak_metric = _metric(
            "current_grade_streak",
            "현재 단계 연속기간",
            None,
            unit="개월",
            status="insufficient_data",
        )
        omitted.append(
            OmittedIndicator(
                id="current_grade_streak",
                reason="현재 단계가 확인되지 않았다.",
            )
        )
    key_metrics.append(streak_metric)
    if grade is not None:
        claims.append(_EvidenceClaim("grade_streak", "major_changes", streak_fact))

    transitions = [
        pair
        for pair in contiguous_pairs
        if pair[2] is not None and pair[3] is not None and pair[2].label != pair[3].label
    ]
    key_metrics.append(
        _metric("grade_transition_count", "단계 전환 횟수", len(transitions), unit="회")
    )
    if transitions:
        before, after, before_grade, after_grade = transitions[-1]
        assert before_grade is not None and after_grade is not None
        transition_fact = (
            f"가장 최근에는 {after.month}에 {before_grade.label}에서 "
            f"{after_grade.label} 단계로 전환됐다."
        )
        patterns.append(
            DetectedPattern(
                code="latest_grade_transition",
                label="가장 최근 단계 전환",
                evidence=[
                    f"{before.month} {before_grade.label}",
                    f"{after.month} {after_grade.label}",
                ],
            )
        )
    else:
        transition_fact = "조회기간의 연속 월 구간에서는 단계 전환이 확인되지 않았다."
    claims.append(_EvidenceClaim("grade_transition", "major_changes", transition_fact))

    if contiguous_pairs:
        largest = max(contiguous_pairs, key=lambda pair: abs(pair[1].score - pair[0].score))
        largest_change = largest[1].score - largest[0].score
        largest_fact = (
            f"조회기간 중 월간 점수 변화 폭이 가장 컸던 때는 {largest[1].month}로, "
            f"직전월보다 {_change_phrase(largest_change)} 움직였다."
        )
        key_metrics.append(
            _metric(
                "largest_monthly_score_change",
                "최대 월간 점수 변화",
                largest_change,
                unit="점",
                basis=f"{largest[0].month} 대비 {largest[1].month}",
            )
        )
        patterns.append(
            DetectedPattern(
                code="largest_monthly_score_change",
                label="조회기간 최대 월간 점수 변화",
                evidence=[largest_fact],
            )
        )
    else:
        largest_fact = "연속된 월 데이터가 없어 최대 월간 점수 변화는 계산하지 않았다."
        omitted.append(
            OmittedIndicator(
                id="largest_monthly_score_change",
                reason="연속된 월 데이터가 없다.",
            )
        )
    claims.append(
        _EvidenceClaim("largest_monthly_score_change", "major_changes", largest_fact)
    )

    price_change = (
        percent_change(current.price, previous.price)
        if previous is not None and months_are_contiguous(previous.month, current.month)
        else None
    )
    if price_change is not None:
        price_direction = (
            "올랐다"
            if price_change > 0
            else "내렸다"
            if price_change < 0
            else "같았다"
        )
        price_fact = (
            f"같은 최근 한 달 동안 가격은 {_number(abs(price_change) * 100)}% "
            f"{price_direction}."
        )
        key_metrics.append(
            _metric(
                "latest_price_change_rate",
                "최근 가격 변화율",
                price_change,
                unit="ratio",
                basis=f"{previous.month} 대비",
            )
        )
        claims.append(
            _EvidenceClaim("latest_price_change", "current_position", price_fact)
        )
    else:
        omitted.append(
            OmittedIndicator(
                id="latest_price_change_rate",
                reason="비교 가능한 연속 월 가격이 없다.",
            )
        )

    period_average = sum(item.score for item in observations) / len(observations)
    difference_from_average = current.score - period_average
    key_metrics.append(
        _metric(
            "period_average_score",
            "조회기간 평균 점수",
            period_average,
            unit="점",
            basis=f"{observations[0].month}~{observations[-1].month}",
        )
    )
    if difference_from_average > 0:
        average_comparison = (
            f"평균 {_number(period_average)}점보다 "
            f"{_number(difference_from_average)}점 높아"
        )
    elif difference_from_average < 0:
        average_comparison = (
            f"평균 {_number(period_average)}점보다 "
            f"{_number(abs(difference_from_average))}점 낮아"
        )
    else:
        average_comparison = f"평균 {_number(period_average)}점과 같아"
    position_detail = (
        f"현재 점수 {_number(current.score)}점은 조회기간 {average_comparison}, "
        f"{_score_position_meaning(series.page_id, difference_from_average)}."
    )
    if score_change is None or score_change == 0:
        position_fact = position_detail
    else:
        if series.page_id == "indicator_market":
            recent_position = (
                "최근 한 달 중장기 가격위험은 낮아졌"
                if score_change > 0
                else "최근 한 달 중장기 가격위험은 높아졌"
            )
        else:
            recent_position = (
                "최근 한 달 수급 안정성은 강화됐"
                if score_change > 0
                else "최근 한 달 수급 안정성은 약해졌"
            )
        if difference_from_average == 0:
            connector = "으며"
        elif score_change * difference_from_average > 0:
            connector = "고"
        else:
            connector = "지만"
        position_fact = f"{recent_position}{connector}, {position_detail}"

    score_changes = [after.score - before.score for before, after, _, _ in contiguous_pairs]
    rising = sum(change > 0 for change in score_changes)
    falling = sum(change < 0 for change in score_changes)
    flat = sum(change == 0 for change in score_changes)
    detailed_metrics.extend(
        [
            *key_metrics[2:],
            _metric("score_rising_months", "점수 상승 월", rising, unit="개월"),
            _metric("score_falling_months", "점수 하락 월", falling, unit="개월"),
            _metric("score_flat_months", "점수 보합 월", flat, unit="개월"),
            _metric("observation_count", "유효 관측월", len(observations), unit="개월"),
            _metric(
                "current_vs_period_average",
                "평균 대비 현재 점수",
                difference_from_average,
                unit="점",
                basis=f"조회기간 평균 {_number(period_average)}점 대비",
            ),
        ]
    )
    detailed_metrics.extend(_supply_auxiliary_metrics(series))
    claims.append(
        _EvidenceClaim("period_average_position", "current_position", position_fact)
    )

    return _CalculatedSummary(
        grade=grade,
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=detailed_metrics,
        patterns=patterns,
        omitted=omitted,
    )


def _deterministic_narrative(
    claims: list[_EvidenceClaim] | list[EvidenceClaim],
) -> SummaryNarrative:
    grouped: dict[SectionId, list[SummarySentence]] = {
        "core_diagnosis": [],
        "major_changes": [],
        "current_position": [],
    }
    for claim in claims:
        grouped[claim.section].append(
            SummarySentence(text=claim.fact, evidence_ids=[claim.id])
        )
    return SummaryNarrative(**grouped)


_NUMBER_PATTERN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
_FORBIDDEN_SUMMARY_TERMS = (
    "경계까지",
    "경계거리",
    "방향 일치율",
    "상관계수",
    "추세",
)
_GRADE_LABELS = {"신중", "주의", "중립", "관심", "기회", "긴장", "안정", "원활"}


def _number_tokens(text: str) -> set[str]:
    result: set[str] = set()
    for token in _NUMBER_PATTERN.findall(text):
        is_percent = token.endswith("%")
        raw = token.rstrip("%").replace(",", "")
        try:
            normalized = str(Decimal(raw).normalize())
        except InvalidOperation:
            normalized = raw
        result.add(f"{normalized}%" if is_percent else normalized)
    return result


def _validate_llm_summary(
    candidate: SummaryNarrative,
    claims: list[_EvidenceClaim] | list[EvidenceClaim],
    *,
    page_id: SummaryPageId,
) -> str | None:
    claim_map = {claim.id: claim for claim in claims}
    sections: list[tuple[SectionId, list[SummarySentence]]] = [
        ("core_diagnosis", candidate.core_diagnosis),
        ("major_changes", candidate.major_changes),
        ("current_position", candidate.current_position),
    ]
    sentences = [sentence for _, values in sections for sentence in values]
    if page_id == "map_mineral":
        if not 5 <= len(sentences) <= 8:
            return "광물지도 출력은 전체 5~8문장이어야 한다."
        if not 2 <= len(candidate.major_changes) <= 3:
            return "광물지도 주요 변화는 2~3문장이어야 한다."
        if not 2 <= len(candidate.current_position) <= 3:
            return "광물지도 현재 위치·의미는 2~3문장이어야 한다."
    else:
        section_ranges = {
            "indicator_market": ((1, 1), (1, 1), (1, 1)),
            "indicator_supply": ((1, 1), (1, 1), (1, 1)),
            "indicator_composite": ((1, 1), (1, 2), (1, 1)),
            "forecast_price": ((1, 1), (1, 1), (1, 1)),
        }[page_id]
        for (_, values), (minimum, maximum) in zip(
            sections,
            section_ranges,
            strict=True,
        ):
            if not minimum <= len(values) <= maximum:
                return "섹션별 분석문 수가 출력 계약과 일치하지 않는다."
    used_ids: list[str] = []
    for section, values in sections:
        for sentence in values:
            if any(term in sentence.text for term in _FORBIDDEN_SUMMARY_TERMS):
                return "본문에서 제외한 지표를 언급했다."
            referenced = [claim_map.get(evidence_id) for evidence_id in sentence.evidence_ids]
            if any(claim is None for claim in referenced):
                return "존재하지 않는 evidence_id를 사용했다."
            typed_references = [claim for claim in referenced if claim is not None]
            if any(claim.section != section for claim in typed_references):
                return "evidence_id를 다른 출력 섹션에 사용했다."
            evidence_text = " ".join(claim.fact for claim in typed_references)
            if not _number_tokens(sentence.text) <= _number_tokens(evidence_text):
                return "근거에 없는 숫자나 날짜를 사용했다."
            mentioned_grades = {label for label in _GRADE_LABELS if label in sentence.text}
            allowed_grades = {label for label in _GRADE_LABELS if label in evidence_text}
            if not mentioned_grades <= allowed_grades:
                return "근거에 없는 단계명을 사용했다."
            used_ids.extend(sentence.evidence_ids)
    if page_id == "map_mineral":
        required_ids = {
            claim.id for claim in claims if getattr(claim, "required", False)
        }
        if not required_ids <= set(used_ids):
            return "필수 evidence_id를 모두 사용하지 않았다."
    elif Counter(used_ids) != Counter(claim_map.keys()):
        return "모든 evidence_id를 정확히 한 번씩 사용하지 않았다."
    elif len(claims) >= 4 and not any(
        len(sentence.evidence_ids) >= 2 for sentence in sentences
    ):
        return "관련 근거를 결합한 분석 문장이 없다."
    if "current_state" not in {
        evidence_id
        for sentence in candidate.core_diagnosis
        for evidence_id in sentence.evidence_ids
    }:
        return "핵심 진단에 현재 상태 근거가 없다."
    return None


class AnalysisSummaryService:
    """Calculate a page-scoped summary and optionally refine it with verified LLM output."""

    def __init__(
        self,
        data_source: IndicatorDataSource | None,
        *,
        composite_source: CompositeIndexDataSource | None = None,
        mineral_map_source: MineralMapDataSource | None = None,
        price_forecast_source: PriceForecastDataSource | None = None,
        llm: KomirJsonLLM | None = None,
    ) -> None:
        self._data_source = data_source
        self._composite_source = composite_source
        self._mineral_map_source = mineral_map_source
        self._price_forecast_source = price_forecast_source
        self._llm = llm

    def analyze(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Calculate the summary appropriate for the requested page."""

        if request.page_id == "indicator_composite":
            return self._analyze_composite(request)
        if request.page_id == "map_mineral":
            return self._analyze_mineral_map(request)
        if request.page_id == "forecast_price":
            return self._analyze_price_forecast(request)
        return self._analyze_indicator(request)

    def _analyze_indicator(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load an indicator series and build its validated summary response."""

        if self._data_source is None or request.mineral is None:
            raise ValueError("indicator analysis data source is not configured")
        series = self._data_source.get_series(
            page_id=request.page_id,
            mineral=request.mineral,
            start_month=request.start_month,
            end_month=request.end_month,
        )
        policy = load_page_policy(request.page_id)
        calculated = _calculate_summary(series, policy)
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "start_month": request.start_month or series.observations[0].month,
            "end_month": request.end_month or series.observations[-1].month,
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_month", request.start_month),
                ("end_month", request.end_month),
            )
            if value is None
        ]
        missing_data = [*series.unavailable_page_data]
        if series.price_criterion is None:
            missing_data.append("가격 기준")
        if series.price_unit is None:
            missing_data.append("가격 단위")
        quality_status: Literal["available", "partial", "insufficient"] = "partial"
        if len(series.observations) < 2:
            quality_status = "insufficient"
        elif not missing_data and not series.warnings:
            quality_status = "available"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=policy.policy_version,
            page_definition=policy.definition,
            grade=calculated.grade,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_month=series.available_start_month,
                available_end_month=series.available_end_month,
                effective_start_month=series.observations[0].month,
                effective_end_month=series.observations[-1].month,
                missing_data=missing_data,
                warnings=series.warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=policy.analysis_constraints,
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, policy, calculated.claims)

    def _analyze_composite(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load a composite-index series and build its validated summary response."""

        if self._composite_source is None:
            raise ValueError("composite index analysis data source is not configured")
        series = self._composite_source.get_composite_series(
            start_date=request.start_date,
            end_date=request.end_date,
        )
        calculated = calculate_composite_summary(series)
        context = ADDITIONAL_PAGE_CONTEXTS["indicator_composite"]
        applied_filters = {
            "start_date": request.start_date or series.observations[0].date,
            "end_date": request.end_date or series.observations[-1].date,
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_date", request.start_date),
                ("end_date", request.end_date),
            )
            if value is None
        ]
        effective_warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "available" if len(series.observations) >= 4 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=MineralRef(code="COMPOSITE", name="광물종합지수"),
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_date=series.available_start_date,
                available_end_date=series.available_end_date,
                effective_start_date=series.observations[0].date,
                effective_end_date=series.observations[-1].date,
                warnings=effective_warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _analyze_mineral_map(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load a mineral-map series and build its validated summary response."""

        if (
            self._mineral_map_source is None
            or request.mineral is None
            or request.measure is None
        ):
            raise ValueError("mineral map analysis data source is not configured")
        series = self._mineral_map_source.get_mineral_map_series(
            mineral=request.mineral,
            measure=request.measure,
            start_year=request.start_year,
            end_year=request.end_year,
        )
        calculated = calculate_mineral_map_summary(series)
        context = ADDITIONAL_PAGE_CONTEXTS["map_mineral"]
        years = sorted({item.year for item in series.observations})
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "measure": series.measure,
            "start_year": str(request.start_year or years[0]),
            "end_year": str(request.end_year or years[-1]),
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_year", request.start_year),
                ("end_year", request.end_year),
            )
            if value is None
        ]
        effective_warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "available" if len(years) >= 2 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_year=series.available_start_year,
                available_end_year=series.available_end_year,
                effective_start_year=years[0],
                effective_end_year=years[-1],
                warnings=effective_warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _analyze_price_forecast(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load forecast prices and build a validated forecast summary."""
        if (
            self._price_forecast_source is None
            or request.mineral is None
            or request.forecast_horizon is None
        ):
            raise ValueError("price forecast analysis data source is not configured")
        series = self._price_forecast_source.get_price_forecast_series(
            mineral=request.mineral,
            horizon=request.forecast_horizon,
            start_period=request.start_period,
            end_period=request.end_period,
        )
        calculated = calculate_price_forecast_summary(series)
        context = ADDITIONAL_PAGE_CONTEXTS["forecast_price"]
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "forecast_horizon": series.horizon,
            "start_period": request.start_period or series.observations[0].period,
            "end_period": request.end_period or series.observations[-1].period,
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_period", request.start_period),
                ("end_period", request.end_period),
            )
            if value is None
        ]
        warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "partial" if warnings else "available"
        )
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_period=series.available_start_period,
                available_end_period=series.available_end_period,
                effective_start_period=series.observations[0].period,
                effective_end_period=series.observations[-1].period,
                missing_data=["가격 단위"] if series.price_unit is None else [],
                warnings=warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None:
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _refine_with_llm(
        self,
        response: AnalysisSummaryResponse,
        policy: PagePolicy | SummaryPageContext,
        claims: list[_EvidenceClaim] | list[EvidenceClaim],
    ) -> AnalysisSummaryResponse:
        """Request LLM refinement and accept only evidence-valid output."""

        validation_error = None
        evidence_payload = [
            {
                "evidence_id": claim.id,
                "section": claim.section,
                "fact": claim.fact,
                "required": getattr(claim, "required", True),
            }
            for claim in claims
        ]
        for _ in range(2):
            try:
                invocation = self._llm.invoke(
                    task="analysis_summary",
                    instructions=summary_instructions(response.page_id),
                    payload=build_summary_payload(
                        response=response,
                        policy=policy,
                        allowed_evidence=evidence_payload,
                        previous_validation_error=validation_error,
                    ),
                    output_model=SummaryNarrative,
                    max_tokens=1200,
                )
            # ⚠ 원본은 LLMError만 잡는다. komir의 KomirJsonLLM은 그 아래
            #   OpenAICompatChat.complete()의 전송 오류(재시도 소진 시 맨
            #   RuntimeError, 타임아웃·커넥션은 requests.RequestException →
            #   OSError 하위형)를 감싸지 않고 그대로 올린다 — 여기서 같이 잡지
            #   않으면 vLLM 장애 때 폴백 대신 API가 500을 낸다.
            #   (LLMError 자체도 RuntimeError 하위형이라 함께 처리된다.)
            except (LLMError, RuntimeError, OSError):
                return self._with_warning(
                    response,
                    "LLM 분석요약 생성에 실패해 검증된 규칙 기반 요약을 반환했다.",
                )
            validation_error = _validate_llm_summary(
                invocation.output,
                claims,
                page_id=response.page_id,
            )
            if validation_error is None:
                return response.model_copy(
                    update={"summary": invocation.output, "llm_refined": True}
                )
        return self._with_warning(
            response,
            "LLM 분석요약이 근거 검증을 통과하지 못해 규칙 기반 요약을 반환했다. "
            f"검증 사유: {validation_error or '확인되지 않음'}",
        )

    @staticmethod
    def _with_warning(
        response: AnalysisSummaryResponse,
        warning: str,
    ) -> AnalysisSummaryResponse:
        quality = response.data_quality.model_copy(
            update={"warnings": [*response.data_quality.warnings, warning]}
        )
        return response.model_copy(update={"data_quality": quality})

    def close(self) -> None:
        """Close the LLM and each configured data source when supported."""

        for target in (
            self._llm,
            self._data_source,
            self._composite_source,
            self._mineral_map_source,
            self._price_forecast_source,
        ):
            close = getattr(target, "close", None)
            if callable(close):
                close()
