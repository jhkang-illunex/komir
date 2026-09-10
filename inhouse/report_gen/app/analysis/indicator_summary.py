"""API 입력에서 시장·수급 지표를 계산해 LLM 보고서용 근거를 만든다.

이 모듈은 정규화된 입력을 결정론적으로 계산하는 단계만 담당한다. 생성한
``EvidenceClaim``은 ``summary.py``가 프롬프트와 함께 LLM에 전달하고, 그 결과를
근거와 대조해 검증한다. 이 모듈 자체는 외부 IO나 LLM 호출을 수행하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ._metrics import capped_key_metrics
from .additional_summary import EvidenceClaim, _number, _quantity
from .indicators import months_are_contiguous, percent_change
from .models import (DetectedPattern, GradeResult, IndicatorSeries, Metric, OmittedIndicator)
from .policy import PagePolicy

@dataclass(slots=True)
class _CalculatedSummary:
    grade: GradeResult
    claims: list[EvidenceClaim]
    key_metrics: list[Metric]
    detailed_metrics: list[Metric]
    patterns: list[DetectedPattern]
    omitted: list[OmittedIndicator]



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



def _score_meaning(page_id: str, change: float) -> str:
    # 2026-09-09 main-agent 승인(B-3) — 과거형 "-았/었다"→"-았/었습니다"는
    # 어간 구분 없이 안전한 변환(report_gen_to_polite_copula_gotcha_260901
    # 함정은 계사/현재형에서만 발생, 과거형은 해당 없음).
    if change == 0:
        return "점수와 지표가 나타내는 상태에 변화가 없었습니다"
    if page_id == "indicator_market":
        return (
            "중장기 가격위험이 낮아지는 방향으로 움직였습니다"
            if change > 0
            else "중장기 가격위험이 높아지는 방향으로 움직였습니다"
        )
    return (
        "수급 안정성이 강화되는 방향으로 움직였습니다"
        if change > 0
        else "수급 안정성이 약해지는 방향으로 움직였습니다"
    )



def _score_position_meaning(page_id: str, difference: float) -> str:
    # 2026-09-09 main-agent 승인(B-3) — 계사 "수준이다"→"수준입니다"(어간이
    # 아니라 명사+계사 "이다"이므로 안전한 변환).
    if difference == 0:
        return (
            "중장기 가격위험이 조회기간 평균 수준입니다"
            if page_id == "indicator_market"
            else "수급 안정성이 조회기간 평균 수준입니다"
        )
    if page_id == "indicator_market":
        return (
            "중장기 가격위험이 조회기간 평균보다 낮은 수준입니다"
            if difference > 0
            else "중장기 가격위험이 조회기간 평균보다 높은 수준입니다"
        )
    return (
        "수급 안정성이 조회기간 평균보다 높은 수준입니다"
        if difference > 0
        else "수급 안정성이 조회기간 평균보다 낮은 수준입니다"
    )



def _change_phrase(value: float) -> str:
    # 2026-09-09 사용자 지시 — price_* 4종에 적용한 "정수면 소숫점 생략"을
    # 나머지 페이지에도 동일 적용(공통화). 지수 점수("점")는 등락률(%)과
    # 달리 raw quantity이므로 `_number` 대신 `_quantity`를 쓴다.
    if value > 0:
        return f"{_quantity(value)}점 올라"
    if value < 0:
        return f"{_quantity(abs(value))}점 내려"
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
) -> list[GradeResult]:
    # 2026-09-02 skeptic 2차 감사 SC-R2-005: 036eb231e 이후 policy.classify()는
    # 실패 시 None이 아니라 PolicyError를 던지고, indicator_market/supply
    # 둘 다 grade_rules가 [score_min, score_max]를 빈틈없이 덮어(IndicatorObservation.
    # score도 pydantic이 이미 그 범위로 강제) None이 나올 경로가 없다 — 이 함수의
    # 반환값은 항상 완전히 채워진 GradeResult 리스트다.
    return [policy.classify(item.score) for item in series.observations]



def _calculate_summary(series: IndicatorSeries, policy: PagePolicy) -> _CalculatedSummary:
    observations = series.observations
    current = observations[-1]
    previous = observations[-2] if len(observations) >= 2 else None
    grades = _classify_series(series, policy)
    grade = grades[-1]
    omitted: list[OmittedIndicator] = []
    patterns: list[DetectedPattern] = []

    current_grade_metric = _metric(
        "current_grade", "현재 단계", grade.label, status="available"
    )
    key_metrics = [
        _metric("current_score", "현재 점수", current.score, unit="점"),
        current_grade_metric,
    ]
    detailed_metrics = [*key_metrics]

    # 2026-09-10 사용자 지시 — 발주처 업무지시서 §3.2 원문 그대로("[기준월]
    # 기준 [광종]의 시장동향지표는 [점수]점으로, 현재 [단계]에 해당합니다")
    # 맞추기 위해 "기준"·"의"·"현재"·"~에 해당합니다"를 추가(이전엔
    # "{month} {mineral} {policy}는 ...단계입니다"로 그 네 요소가 빠져 있었다).
    current_fact = (
        f"{current.month} 기준 {series.mineral.name}의 {policy.name}는 "
        f"{_quantity(current.score)}점으로, 현재 {grade.label} 단계에 해당합니다."
    )
    claims = [EvidenceClaim("current_state", "core_diagnosis", current_fact, required=True)]

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
        is_contiguous = months_are_contiguous(previous.month, current.month)
        pct_change = score_change / previous.score * 100 if previous.score != 0 else None
        previous_lead = "최근 한 달에는 전월" if is_contiguous else f"직전 관측치({previous.month})"
        if score_change > 0:
            point_change = f"{_quantity(score_change)}점 상승해"
        elif score_change < 0:
            point_change = f"{_quantity(abs(score_change))}점 하락해"
        else:
            point_change = "점수 변동 없이"
        score_fact = (
            f"{previous_lead} {_quantity(previous.score)}점 대비 {point_change} "
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
        if pct_change is not None:
            # key_metrics가 아니라 detailed_metrics에만 담는다 — 이 페이지의
            # key_metrics는 8개 상한(`models.py::AnalysisSummaryResponse.
            # key_metrics`)인데 이미 8개가 꽉 차 있어(2026-09-01 실측: 여기
            # 추가했더니 뒤에서 채워지는 "조회기간 평균 점수"가 조용히
            # 밀려났다 — composite 가중치 작업 때와 같은 종류의 회귀) 그
            # 근거를 detailed_metrics로만 남긴다. 값 자체는 위 서사 문장에
            # 이미 그대로 노출돼 있다.
            detailed_metrics.append(
                _metric(
                    "latest_score_change_percent",
                    "최근 점수 변화율",
                    pct_change,
                    unit="%",
                    basis=f"{previous.month} 대비",
                )
            )
        claims.append(EvidenceClaim("latest_score_change", "core_diagnosis", score_fact, required=True))
    else:
        claims.append(
            EvidenceClaim(
                "latest_score_change",
                "core_diagnosis",
                "이전 관측치가 없어 최근 점수 변화는 계산하지 않았습니다.",
                required=True,
            )
        )
        omitted.append(
            OmittedIndicator(id="latest_score_change", reason="이전 관측치가 없다.")
        )

    streak = 1
    for index in range(len(observations) - 1, 0, -1):
        before_grade = grades[index - 1]
        if before_grade.label != grade.label or not months_are_contiguous(
            observations[index - 1].month,
            observations[index].month,
        ):
            break
        streak += 1
    streak_basis = "조회범위 내 최소 " if streak == len(observations) else ""
    streak_fact = f"{grade.label} 단계는 {streak_basis}{streak}개월 연속 유지됐습니다."
    key_metrics.append(
        _metric("current_grade_streak", "현재 단계 연속기간", streak, unit="개월")
    )
    claims.append(EvidenceClaim("grade_streak", "major_changes", streak_fact, required=True))

    transitions = [
        pair for pair in contiguous_pairs if pair[2].label != pair[3].label
    ]
    key_metrics.append(
        _metric("grade_transition_count", "단계 전환 횟수", len(transitions), unit="회")
    )
    if transitions:
        before, after, before_grade, after_grade = transitions[-1]
        transition_fact = (
            f"가장 최근에는 {after.month}에 {before_grade.label}에서 "
            f"{after_grade.label} 단계로 전환됐습니다."
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
        transition_fact = "조회기간의 연속 월 구간에서는 단계 전환이 확인되지 않았습니다."
    claims.append(EvidenceClaim("grade_transition", "major_changes", transition_fact, required=True))

    if contiguous_pairs:
        largest = max(contiguous_pairs, key=lambda pair: abs(pair[1].score - pair[0].score))
        largest_change = largest[1].score - largest[0].score
        largest_fact = (
            f"조회기간 중 월간 점수 변화 폭이 가장 컸던 때는 {largest[1].month}로, "
            f"직전월보다 {_change_phrase(largest_change)} 움직였습니다."
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
        largest_fact = "연속된 월 데이터가 없어 최대 월간 점수 변화는 계산하지 않았습니다."
        omitted.append(
            OmittedIndicator(
                id="largest_monthly_score_change",
                reason="연속된 월 데이터가 없다.",
            )
        )
    claims.append(
        EvidenceClaim("largest_monthly_score_change", "major_changes", largest_fact, required=True)
    )

    # 2026-09-01 신설 — 발주처 제안요청서(구 PDF) §2-3의 "주요 요인으로는
    # [가격리스크/세계 수급비율/세계 공급 편중도/국내 수입증가율/국내 수입국
    # 편중도 등]의 변동성이 확대된 결과로 분석됩니다" 문구를 그대로 옮겨
    # 반영했었다. `getChartDataSpdmStbt` 기반 supply_auxiliary가 있을 때만
    # (indicator_supply 전용) 그 중 실제로 계산 가능한 두 요인(국내
    # 수입증가율·국내 수입국 편중도)만 쓴다 — 나머지 3개(가격리스크는 핵심
    # 관측치와 중복이라 별도 서술 안 함, 세계 수급비율·세계 공급 편중도는
    # 대응 모델 필드 자체가 없음)는 evidence가 없어 언급하지 않는다
    # (§`models.py`의 `SupplyAuxiliaryData` docstring). 수입국 편중도는 이번
    # 표본에 연도별 비교값이 없어(단일 연도 스냅샷) 변동 여부를 알 수
    # 없으므로 구조적 사실(현재 집중도 수준)로만 덧붙인다 — composite의
    # 구성 광종 가중치와 같은 구분.
    #
    # 2026-09-09 발주처 업무지시서 §2.2("가격변동의 주요요인" 삭제·"원인으로
    # 분석됩니다"→"해당 항목의 변동이 함께 확인됩니다" 순화 매핑표) 대응 —
    # 위 "주요 요인으로는 ... 분석됩니다"는 이 업무지시서가 명시적으로 겨냥한
    # 바로 그 인과 단정 패턴이었다(§3.2 정합화 점검 중 재발견). 구 제안요청서
    # 문구보다 이 업무지시서(더 최신·발주처 확정본)가 우선한다 — "주요
    # 요인으로는"·"분석된다"를 빼고 §2.2 매핑표의 "동반 확인" 어투로
    # 바꿨다(수치·근거는 그대로, 인과관계 단정만 제거).
    if series.page_id == "indicator_supply" and series.supply_auxiliary is not None:
        imports = sorted(series.supply_auxiliary.domestic_imports, key=lambda item: item.year)
        dependencies = series.supply_auxiliary.import_dependencies
        import_growth_fact = None
        if len(imports) >= 2:
            latest_import, previous_import = imports[-1], imports[-2]
            import_growth = percent_change(
                latest_import.import_weight_ton, previous_import.import_weight_ton
            )
            if import_growth is not None:
                growth_direction = "감소" if import_growth < 0 else "증가"
                import_growth_fact = (
                    f"화면상 확인되는 국내 수입량은 {previous_import.year}년 대비 "
                    f"{latest_import.year}년 {_number(abs(import_growth) * 100)}% "
                    f"{growth_direction}해, 이 변동이 수급동향지표 변화와 함께 확인됩니다"
                )
                detailed_metrics.append(
                    _metric(
                        "supply_import_weight_yoy_change",
                        "국내 수입량 전년 대비 증감률",
                        import_growth,
                        unit="ratio",
                        basis=f"{previous_import.year}년 대비 {latest_import.year}년",
                    )
                )
        top_three = series.supply_auxiliary.top_three_dependency_percent
        concentration_fact = None
        if top_three is not None and dependencies:
            top_names = "·".join(item.country_name for item in dependencies[:3])
            # 2026-09-02 skeptic 2차 감사 SC-R2-004: share_percent 분모가 세계
            # 총액이 아니라 이 표에 나열된 국가들의 소계라(§docstring), 나열국이
            # 3개 이하면 상위 3개국 합이 정의상 항상 100%에 가깝다 — 실측 측정이
            # 아니라 계산 방식의 항등식인데 "집중된 구조다"로 쓰면 실제 편중도
            # 측정처럼 읽힌다. 발주처 제공 실측 덤프는 갈륨 1건(5개국)뿐이라 다른
            # 광종에서 3개국 이하가 실제로 나오는지 확인은 못 했지만, 나오더라도
            # 오도되지 않도록 나열국 수가 3 이하면 한정어를 붙인다.
            if len(dependencies) <= 3:
                concentration_fact = (
                    f"나열된 수입국({top_names}) 전체 기준 수입의존도는 "
                    f"{_number(top_three)}%입니다"
                )
            else:
                concentration_fact = (
                    f"상위 3개국({top_names}) 수입의존도는 {_number(top_three)}%로 집중된 구조입니다"
                )
        if import_growth_fact and concentration_fact:
            claims.append(
                EvidenceClaim(
                    "supply_key_factors",
                    "current_position",
                    f"{import_growth_fact}. {concentration_fact}.",
                    required=True,
                )
            )
        elif import_growth_fact:
            claims.append(
                EvidenceClaim("supply_key_factors", "current_position", f"{import_growth_fact}.", required=True)
            )
        elif concentration_fact:
            claims.append(
                EvidenceClaim(
                    "supply_key_factors",
                    "current_position",
                    f"국내 수입국 편중도를 보면 {concentration_fact}.",
                    required=True,
                )
            )

    price_change = (
        percent_change(current.price, previous.price)
        if previous is not None and months_are_contiguous(previous.month, current.month)
        else None
    )
    if price_change is not None:
        price_direction = (
            "올랐습니다"
            if price_change > 0
            else "내렸습니다"
            if price_change < 0
            else "같았습니다"
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
            EvidenceClaim("latest_price_change", "current_position", price_fact, required=True)
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
            f"평균 {_quantity(period_average)}점보다 "
            f"{_quantity(difference_from_average)}점 높아"
        )
    elif difference_from_average < 0:
        average_comparison = (
            f"평균 {_quantity(period_average)}점보다 "
            f"{_quantity(abs(difference_from_average))}점 낮아"
        )
    else:
        average_comparison = f"평균 {_quantity(period_average)}점과 같아"
    position_detail = (
        f"현재 점수 {_quantity(current.score)}점은 조회기간 {average_comparison}, "
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
                basis=f"조회기간 평균 {_quantity(period_average)}점 대비",
            ),
        ]
    )
    detailed_metrics.extend(_supply_auxiliary_metrics(series))
    claims.append(
        EvidenceClaim("period_average_position", "current_position", position_fact, required=True)
    )

    return _CalculatedSummary(
        grade=grade,
        claims=claims,
        key_metrics=capped_key_metrics(key_metrics, page_id=f"{series.page_id}:{series.mineral.name}"),
        detailed_metrics=detailed_metrics,
        patterns=patterns,
        omitted=omitted,
    )
