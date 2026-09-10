"""API 입력에서 시장·수급 지표를 계산해 LLM 보고서용 근거를 만든다.

이 모듈은 정규화된 입력을 결정론적으로 계산하는 단계만 담당한다. 생성한
``EvidenceClaim``은 ``summary.py``가 프롬프트와 함께 LLM에 전달하고, 그 결과를
근거와 대조해 검증한다. 이 모듈 자체는 외부 IO나 LLM 호출을 수행하지 않는다.
"""
from __future__ import annotations

import statistics
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



def _korean_month(value: str) -> str:
    """ISO 월("YYYY-MM")을 "YYYY년 MM월"로 바꾼다.

    2026-09-10 발주처 피드백[8](공통 날짜서식 스윕, 권가영 사원) — 이
    페이지(시장동향·수급동향지표)의 월 표기가 다른 페이지(가격·수급지도
    등, `additional_summary.py::_korean_date`/`komir_summary.py::
    _korean_year`가 이미 처리)와 달리 여태 raw ISO("2026-07")로 나가고
    있었다. 월(day 없음) 없이 일 단위까지 표시하는 `_korean_date`를 그대로
    쓸 수 없어 월 전용 버전을 만든다 — 패딩 없는 자리수(`_korean_date`와
    동일하게 "07월"이 아니라 "7월")로 다른 페이지와 표기 방식을 맞춘다."""

    year_str, month_str = value.split("-")
    return f"{int(year_str)}년 {int(month_str)}월"


def _change_phrase(value: float) -> str:
    # 2026-09-09 사용자 지시 — price_* 4종에 적용한 "정수면 소숫점 생략"을
    # 나머지 페이지에도 동일 적용(공통화). 지수 점수("점")는 등락률(%)과
    # 달리 raw quantity이므로 `_number` 대신 `_quantity`를 쓴다.
    if value > 0:
        return f"{_quantity(value)}점 올랐습니다"
    if value < 0:
        return f"{_quantity(abs(value))}점 내렸습니다"
    return "변동이 없었습니다"



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



def _price_volatility_pct(observations: list) -> tuple[float, int] | None:
    """가격 데이터 기반 가격 리스크 지수 — 최근 최대 12개월(관측치 13개)
    연속 구간의 월간 가격 수익률 표준편차를 연율화(×sqrt(12))한 값(%).

    2026-09-10 사용자 지시("가격 데이터를 통해 가격 리스크에 대한 계산
    및 표시가 필요합니다. 적절한 지수나 계산식을 반영해주세요") — 기존
    "가격리스크" 요인은 최근 1개월 등락률 1개 값뿐이었다. `komir_summary.
    py::_volatility_fact`(price_* 페이지의 "가격 변동폭", 수익률 표준편차
    ×sqrt(연간 관측 횟수))와 같은 산식을 월 단위 관측(연간 관측 횟수=12)에
    맞게 적용한다 — 같은 계산 방법을 페이지마다 다시 발명하지 않는다.

    연속되지 않는 두 달 사이(결측 구간)는 그 구간의 수익률을 건너뛴다.
    유효 수익률이 3개 미만이면(표준편차가 통계적으로 무의미) `None`."""

    priced = [
        item for item in sorted(observations, key=lambda o: o.month)
        if item.price is not None and item.price > 0
    ]
    window = priced[-13:]
    returns: list[float] = []
    for prev, cur in zip(window, window[1:]):
        if months_are_contiguous(prev.month, cur.month):
            returns.append((cur.price - prev.price) / prev.price)
    if len(returns) < 3:
        return None
    stdev = statistics.stdev(returns)
    annualized = stdev * (12 ** 0.5) * 100
    return annualized, len(returns)


#: 아라비아 숫자 문자열 뒤 로/으로 조사 — 마지막 자리 숫자를 한글로 읽었을 때
#: 받침 여부로 판정한다(0=영/공·3=삼·6=육은 받침 있어 "으로", 1=일·7=칠·8=팔은
#: ㄹ받침 예외로 "로", 나머지(2·4·5·9)는 받침 없어 "로"). `komir_summary.py::
#: _toward()`는 한글 명사(국가명 등) 끝 받침만 판정하므로 숫자 문자열에는
#: 그대로 쓸 수 없다(마지막 문자가 Hangul 범위 밖이라 항상 "로"로 잘못
#: 빠진다 — "0.980로" 오조사를 advisor 검토로 발견·수정).
_NUMBER_JOSA_TOWARD_BY_LAST_DIGIT = {
    "0": "으로", "3": "으로", "6": "으로",
    "1": "로", "2": "로", "4": "로", "5": "로", "7": "로", "8": "로", "9": "로",
}


def _number_toward(value: str) -> str:
    return value + _NUMBER_JOSA_TOWARD_BY_LAST_DIGIT.get(value[-1], "으로")


#: 2026-09-10 사용자 지시 — HHI 공급 편중도 해석 문구. 임계값(0.15/0.25/0.50)과
#: 문구는 사용자가 제공한 원문 그대로다(국제적으로 통용되는 HHI 관례 구간에
#: 0.50 이상 "극단적 편중" 구간을 사용자가 추가한 것) — 임의로 다듬지 않는다.
def _hhi_classification_sentence(hhi: float) -> str:
    value = _number_toward(_number(hhi, 3))
    if hhi < 0.15:
        return (
            f"국가별 공급망 편중도는 {value}, 특정 국가에 치우치지 않고 "
            "공급처가 안정적으로 다변화되어 있는 상태입니다. 특정 국가의 "
            "지정학적 리스크가 전체 공급망에 미치는 영향은 미미할 것으로 "
            "평가됩니다."
        )
    if hhi < 0.25:
        return (
            f"국가별 공급망 편중도는 {value}, 완만한 편중 경향을 보이고 "
            "있습니다. 아직 위험 수준은 아니나, 상위 공급국 현황에 대한 "
            "지속적인 모니터링이 요구됩니다."
        )
    if hhi < 0.50:
        return (
            f"국가별 공급망 편중도는 {value}, 특정 소수 국가에 대한 "
            "의존도가 상당히 높은 '고편중' 상태입니다. 해당 국가의 수출 "
            "규제나 물류 차질 시 공급망 타격이 우려되므로, 대안국 발굴 등 "
            "리스크 관리가 필요합니다."
        )
    return (
        f"국가별 공급망 편중도는 {value}, 사실상 단일 국가가 공급을 "
        "독점하고 있는 '극단적 편중' 상태입니다. 공급 전반을 특정국에 "
        "전적으로 의존하고 있어, 해당국의 대외 정책이나 환경 변화에 매우 "
        "취약한 구조입니다."
    )


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
        f"{_korean_month(current.month)} 기준 {series.mineral.name}의 {policy.name}는 "
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
        previous_lead = (
            "최근 한 달에는 전월" if is_contiguous else f"직전 관측치({_korean_month(previous.month)})"
        )
        if score_change > 0:
            point_change_clause = f"{_quantity(score_change)}점 상승했습니다."
        elif score_change < 0:
            point_change_clause = f"{_quantity(abs(score_change))}점 하락했습니다."
        else:
            point_change_clause = "점수 변동이 없었습니다."
        meaning_sentence = f"{_score_meaning(series.page_id, score_change)}."
        if series.page_id == "indicator_market" and score_change != 0:
            # 2026-09-10 발주처 피드백[5](권가영 사원) — "34.04점 대비 3.66점
            # 하락해 중장기 가격위험이 높아지는 방향으로 움직였습니다"처럼
            # 점수 하락과 위험 상승을 한 문장 흐름으로 이어 쓰면, 이 지표가
            # "점수 낮을수록 위험 높음"(반비례) 구조라는 걸 모르는 독자는
            # 방향이 왜 반대로 읽히는지 헷갈린다는 지적. 점수 변화 사실
            # 문장과 위험 방향 해석 문장을 분리하고(point_change_clause를
            # 별도 문장으로 종결), 그 사이에 반비례 관계를 짧게 밝히는
            # 문장을 끼워 넣는다. indicator_supply는 점수·안정성이 같은
            # 방향(정비례)이라 이 혼동이 없어 그대로 둔다.
            meaning_sentence = (
                "이 지표는 점수가 낮을수록 위험이 커지는 구조입니다. " + meaning_sentence
            )
        score_fact = (
            f"{previous_lead} {_quantity(previous.score)}점 대비 {point_change_clause} "
            f"{meaning_sentence}"
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
    streak_start_index = len(observations) - 1
    for index in range(len(observations) - 1, 0, -1):
        before_grade = grades[index - 1]
        if before_grade.label != grade.label or not months_are_contiguous(
            observations[index - 1].month,
            observations[index].month,
        ):
            break
        streak += 1
        streak_start_index = index - 1
    streak_basis = "조회범위 내 최소 " if streak == len(observations) else ""
    # 2026-09-10 발주처 피드백[6](권가영 사원) — "19개월 연속 유지됐습니다"처럼
    # 개월 수만 나오면 언제부터 시작됐는지 알 수 없다는 지적. 몇 번째 관측치
    # (`streak_start_index`)에서 연속 구간이 시작됐는지는 이미 위 루프가
    # 추적하므로, 그 관측치의 월을 그대로 시작월로 밝힌다.
    streak_start_month = observations[streak_start_index].month
    streak_fact = (
        f"{_korean_month(streak_start_month)}부터 {grade.label} 단계를 "
        f"{streak_basis}{streak}개월째 유지 중입니다."
    )
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
            f"가장 최근에는 {_korean_month(after.month)}에 {before_grade.label}에서 "
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
            f"조회기간 중 월간 점수 변화 폭이 가장 컸던 때는 {_korean_month(largest[1].month)}로, "
            f"직전월보다 {_change_phrase(largest_change)}."
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
    # 2026-09-10 사용자 지시 — "구성요소 변화"/"주요 변동 특징" 절이 실제로는
    # latest_price_change·period_average_position(둘 다 페이지 성격과 무관한
    # 범용 문장)만 보여주고 있었다. 이제 이 두 절의 실제 목적에 맞는 근거를
    # 우선 채우고, 그 근거가 없을 때만 아래 범용 문장으로 순서대로 폴백한다
    # (섹션이 비는 일은 없게, min 1문장 제약 유지).
    current_position_primary_claim_added = False

    # 2026-09-10 사용자 지시 — 가격 변동은 §3.2의 "가격리스크" 구성요소
    # 소스(수급동향지표 자체+국제가격추이)이기도 해서, supply_auxiliary
    # 유무와 무관하게 항상 계산해 둔다(indicator_market의 "주요 변동
    # 특징"·indicator_supply의 "구성요소 변화" 후보 둘 다에서 재사용).
    price_change = (
        percent_change(current.price, previous.price)
        if previous is not None and months_are_contiguous(previous.month, current.month)
        else None
    )
    price_fact = None
    if price_change is not None:
        price_direction = (
            "올랐습니다"
            if price_change > 0
            else "내렸습니다"
            if price_change < 0
            else "같았습니다"
        )
        # 2026-09-10 사용자 지적 — "같은 최근 한 달"의 "같은"은 직전 문장(현재
        # 단계 절의 최근 점수 변화)을 가리키는 지시어였는데, §3.2 스펙 재정비로
        # 이 문장이 별도 섹션("주요 변동 특징"/"구성요소 변화")의 선두 문장이
        # 되거나 factor_candidates 목록의 한 항목으로 단독 등장할 수 있게 되면서
        # 참조 대상이 사라져 문장이 붕 떴다. "최근 한 달"은 그 자체로 완결된
        # 시점 표현이라 "같은" 없이도 뜻이 통한다(composite의 "최근 한 달 동안
        # 메이저금속지수는..."과 같은 패턴).
        price_fact = (
            f"최근 한 달 동안 가격은 {_number(abs(price_change) * 100)}% "
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
    else:
        omitted.append(
            OmittedIndicator(
                id="latest_price_change_rate",
                reason="비교 가능한 연속 월 가격이 없다.",
            )
        )

    if series.page_id == "indicator_supply":
        # 2026-09-10 사용자 지시 — 업무지시서 §3.2 "구성요소 변화" 템플릿대로
        # 계산 가능한 요인(가격리스크·국내 수입증가율·국내 수입국 편중도·
        # 세계 공급 편중도)을 요인별 별도 근거(EvidenceClaim)로 분리해
        # current_position에 나란히 싣는다(전부 다 오지 않을 수 있다 — 있는
        # 것만). 세계수급비율(세계 수요-공급)은 실측 덤프가 항상 빈 배열이라
        # (2026-09-10 사용자 재확인) 후보에 없다 — 데이터가 없는 요인을
        # 추론으로 채우지 않는다.
        # 2026-09-10 사용자 후속 지시로 요인별 문장을 하나로 합치지 않고
        # 분리했다 — HHI 4단계 해석 문장(추가 60~130자)까지 합치면 4요인
        # 결합 문장이 300자(SummarySentence.text 상한)를 넘을 위험이 커서다
        # (실측: 이전 4요인 결합 문장이 해석문 없이도 이미 272자였다). 분리한
        # 순서(가격리스크→국내 수입증가율→국내 수입국 편중도→세계 공급
        # 편중도)는 "수입의존도(국내 수입국 편중도)와 국가편중도(세계 공급
        # 편중도)가 연속으로 나오게" 요청을 그대로 만족한다(이미 마지막
        # 두 자리가 이 순서였다).
        supply_factor_claims: list[EvidenceClaim] = []
        if price_fact is not None:
            # 2026-09-10 사용자 지시 — 가격리스크 요인에 1개월 등락률뿐 아니라
            # 가격 데이터 기반 계산식(연율화 변동성, _price_volatility_pct)과
            # 기준월 접두어("[YYYY년 MM월] 기준")도 반영한다. market의
            # latest_price_change(공유 변수 price_fact)는 건드리지 않고
            # supply의 요인 문장에만 적용한다.
            price_risk_fact = f"{_korean_month(current.month)} 기준 {price_fact}"
            volatility = _price_volatility_pct(observations)
            if volatility is not None:
                vol_value, vol_months = volatility
                price_risk_fact = (
                    f"{price_risk_fact} 최근 {vol_months}개월 {_number(vol_value)}% "
                    "수준의 가격 변동폭을 보였습니다."
                )
                detailed_metrics.append(
                    _metric(
                        "supply_price_volatility_pct",
                        "가격 변동성(연율화)",
                        vol_value,
                        unit="%",
                        basis=f"최근 {vol_months}개월",
                    )
                )
            supply_factor_claims.append(
                EvidenceClaim(
                    "supply_factor_price_risk", "current_position", price_risk_fact, required=True
                )
            )

        if series.supply_auxiliary is not None:
            # 2026-09-10 사용자 후속 지시("세계 수급비율도 구성요소 변화에
            # 포함") — subChart05(세계 수요-공급)는 원래 5개 요인 스펙 순서상
            # 가격리스크 다음이라 여기 둔다. "과부족"은 KOMIS가 이미 계산해
            # 준 값을 그대로 신뢰하고(subChart02 수입액과 같은 원칙), 없으면
            # 공급-수요로 직접 계산한다. 비어 있으면(갈륨 실측처럼) 조용히
            # 생략 — 다른 요인과 같은 "있으면 반영" 패턴.
            # 단위(천톤)·"과부족" 부호(공급-수요, 양수=과잉)는 2026-09-10
            # 동(CU) 실측(사용자 제공)으로 확정 — 세계 수요 26,751(2024년)이
            # 실제 세계 정제동 생산량(연 약 2,600만~2,700만 톤)과 일치해
            # "천톤" 단위를 확인했고, "과부족" 10개 값 중 8개가 공급-수요와
            # 정확히 일치(나머지 2개는 소수점 반올림 오차 1 — KOMIS가 이미
            # 계산한 값을 그대로 신뢰하는 설계가 맞았다는 근거).
            world_balances = sorted(
                series.supply_auxiliary.world_balances, key=lambda item: item.year
            )
            if world_balances:
                # subChart05는 과거~미래 예측을 함께 담은 다년 시계열이다
                # (동 실측: 2024~2033년 10개년, 2027년 이후는 예측치로 추정
                # 됨) — `[-1]`(최대 연도)을 쓰면 7년 뒤 예측치가 "현재
                # 수급비율"로 잘못 표시된다(실측 재현: 2033년이 뽑혀 나옴).
                # 다른 4개 요인처럼 "현재 관측 시점"(current.month의 연도)에
                # 가장 가까운 연도를 고른다 — 동일 거리면 미래보다 과거를
                # 우선한다(예측치보다 실적/확정치 쪽에 가깝다는 가정).
                current_year = int(current.month[:4])
                latest_balance = min(
                    world_balances,
                    key=lambda item: (abs(item.year - current_year), item.year),
                )
                demand = latest_balance.demand_thousand_ton
                supply = latest_balance.supply_thousand_ton
                balance = latest_balance.balance_thousand_ton
                if balance > 0:
                    world_balance_fact = (
                        f"{latest_balance.year}년 세계 수요는 {_number(demand, 0)}천톤, "
                        f"공급은 {_number(supply, 0)}천톤으로, 공급 과잉 "
                        f"{_number(balance, 0)}천톤 수준입니다."
                    )
                elif balance < 0:
                    world_balance_fact = (
                        f"{latest_balance.year}년 세계 수요는 {_number(demand, 0)}천톤, "
                        f"공급은 {_number(supply, 0)}천톤으로, 공급 부족 "
                        f"{_number(abs(balance), 0)}천톤 수준입니다."
                    )
                else:
                    world_balance_fact = (
                        f"{latest_balance.year}년 세계 수요는 {_number(demand, 0)}천톤, "
                        f"공급은 {_number(supply, 0)}천톤으로, 수급 균형 상태입니다."
                    )
                if demand != 0:
                    ratio = supply / demand * 100
                    world_balance_fact += (
                        f" 세계 수급비율(공급/수요)은 {_number(ratio)}%입니다."
                    )
                detailed_metrics.append(
                    _metric(
                        "supply_world_balance_thousand_ton",
                        "세계 수급 과부족",
                        balance,
                        unit="천톤",
                        basis=f"{latest_balance.year}년",
                    )
                )
                supply_factor_claims.append(
                    EvidenceClaim(
                        "supply_factor_world_balance",
                        "current_position",
                        world_balance_fact,
                        required=True,
                    )
                )

            imports = sorted(series.supply_auxiliary.domestic_imports, key=lambda item: item.year)
            dependencies = series.supply_auxiliary.import_dependencies
            if len(imports) >= 2:
                latest_import, previous_import = imports[-1], imports[-2]
                import_growth = percent_change(
                    latest_import.import_weight_ton, previous_import.import_weight_ton
                )
                if import_growth is not None:
                    growth_direction = "감소" if import_growth < 0 else "증가"
                    import_growth_fact = (
                        f"국내 수입량은 {previous_import.year}년 대비 "
                        f"{latest_import.year}년 {_number(abs(import_growth) * 100)}% "
                        f"{growth_direction}해, 이 변동이 수급동향지표 변화와 함께 확인됩니다."
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
                    supply_factor_claims.append(
                        EvidenceClaim(
                            "supply_factor_import_growth",
                            "current_position",
                            import_growth_fact,
                            required=True,
                        )
                    )

            top_three = series.supply_auxiliary.top_three_dependency_percent
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
                        f"{_number(top_three)}%입니다."
                    )
                else:
                    concentration_fact = (
                        f"상위 3개국({top_names}) 수입의존도는 {_number(top_three)}%로 집중된 구조입니다."
                    )
                supply_factor_claims.append(
                    EvidenceClaim(
                        "supply_factor_import_dependency",
                        "current_position",
                        concentration_fact,
                        required=True,
                    )
                )

            production_shares = series.supply_auxiliary.production_shares
            top_country_share = series.supply_auxiliary.top_country_production_share_percent
            if top_country_share is not None and production_shares:
                # 세계 공급 편중도도 국내 수입국 편중도와 같은 원칙 — 이 표본이
                # 단일 연도 스냅샷이라 "확대/축소" 추세는 알 수 없으므로 현재
                # 수준(1위국 비중)만 서술한다.
                top_row = max(production_shares, key=lambda item: item.production_qty)
                top_country = top_row.country_name
                # 2026-09-10 사용자 지시 — "국가별 비중을 반영한 공급 편중도를
                # 추가, 지수는 HHI이고 생산국의 점유율의 제곱의 합, 0~1 사이값으로
                # 노말라이즈". `production_shares`의 `share_percent`는 이미
                # (KOMIS의 prdtnRt를 신뢰하지 않고) 이 표에 나열된 국가 생산량
                # 합계 대비로 재계산해 둔 값이라 전부 더하면 정확히 100%에
                # 수렴한다(input_data.py 참고) — 그래서 share_percent/100을
                # 분수 점유율로 그대로 써서 제곱합을 구하면 Σ=1인 분포의 성질상
                # 자연히 [1/국가수, 1] 구간(0~1 이내)에 든다. 별도 스케일링·
                # 클램프가 필요 없다(전통적 0~10000 스케일 HHI와 달리 분수
                # 점유율을 직접 쓰는 정의라 이 정규화가 정의상 보장된다).
                production_hhi = sum((row.share_percent / 100.0) ** 2 for row in production_shares)
                # 2026-09-10 사용자 후속 지시 — 단순 수치 문장 대신 4단계 해석
                # 문구(_hhi_classification_sentence)를 붙인다.
                world_supply_fact = (
                    f"{top_row.year}년 국가별 생산량 자료에서 1위는 {top_country}이며, "
                    f"자료에 포함된 국가 생산량 합계의 {_number(top_row.share_percent)}%를 차지합니다. "
                    + _hhi_classification_sentence(production_hhi)
                )
                detailed_metrics.append(
                    _metric(
                        "supply_world_production_top_share",
                        "세계 생산량 1위국 비중",
                        top_country_share,
                        unit="%",
                        basis=top_country,
                    )
                )
                detailed_metrics.append(
                    _metric(
                        "supply_world_production_hhi",
                        "세계 공급 편중도(HHI)",
                        production_hhi,
                        unit="지수",
                        basis=f"{top_row.year}년, {len(production_shares)}개국 비중 제곱합",
                    )
                )
                supply_factor_claims.append(
                    EvidenceClaim(
                        "supply_factor_world_concentration",
                        "current_position",
                        world_supply_fact,
                        required=True,
                    )
                )

        if supply_factor_claims:
            claims.extend(supply_factor_claims)
            current_position_primary_claim_added = True

    # 2026-09-10 사용자 지시 — indicator_market의 "주요 변동 특징"은 가격
    # 관련 지표 변동을 기반으로 쓴다(§3.2 스펙). indicator_supply는 위에서
    # 이미 구성요소 근거를 채웠으면(현재가 구성요소 변화 절이니) 성격이
    # 다른 가격 변동 문장을 더 섞지 않는다 — supply인데 위 factor_candidates
    # 가 전부 비어 있었을 때만(가격 데이터도 supply_auxiliary도 없는 극단적
    # 결측) 여기로 떨어진다.
    if price_fact is not None and not current_position_primary_claim_added:
        claims.append(
            EvidenceClaim("latest_price_change", "current_position", price_fact, required=True)
        )
        current_position_primary_claim_added = True

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
    # 2026-09-10 사용자 지시 — 구성요소/가격변동 근거가 이미 채워졌으면 성격이
    # 다른 "평균 대비 위치" 문장을 더 섞지 않는다. 둘 다 없을 때(비연속월 등
    # 극단적 결측)만 최종 폴백으로 쓴다 — current_position이 빈 채 남는 것을
    # 막는다(min 1문장 제약).
    if not current_position_primary_claim_added:
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
