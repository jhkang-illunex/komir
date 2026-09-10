# -*- coding: utf-8 -*-
"""보고서 생성 흐름: 입력 정규화 → 수치·근거 계산 → LLM 정제 → 구조화 응답.

KOMIS 파싱은 input_data, 시장·수급 계산은 indicator_summary가 담당한다.
공개 Markdown 변환은 report_render에서 수행하며 여기서는 출력 계약을 유지한다.
프롬프트 설정은 요청당 한 번 확정하고, LLM 실패 시 계산된 서사를 반환한다.
과거 직접 호출자와의 호환을 위해 이동한 내부 함수도 재노출한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal, TYPE_CHECKING

from pydantic import ValidationError

_log = logging.getLogger(__name__)

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from common.config import get_settings  # noqa: E402
from common.llm_client import KomirJsonLLM, LLMError  # noqa: E402

from .budget import ANALYSIS_LLM_TIMEOUT_SECONDS  # noqa: E402
from .additional_summary import (  # noqa: E402
    AdditionalCalculatedSummary,
    EvidenceClaim,
    SectionId,
    SummaryPageContext,
    _at_or_before,
    _load_mineral_index_weights,
    _number,
    _shift_month,
    _shift_year,
    _top_weighted_minerals_text,
    calculate_composite_summary,
    calculate_mineral_map_summary,
    calculate_price_forecast_summary,
)
from .errors import DataSourceError

if TYPE_CHECKING:
    from .data_sources._shared import (  # noqa: E402
        CompositeIndexDataSource,
        DomesticTradeDataSource,
        GlobalTradeDataSource,
        IndicatorDataSource,
        MineralMapDataSource,
        PriceDataSource,
        PriceForecastDataSource,
    )

from .komir_summary import (  # noqa: E402
    _detect_granularity,
    _pct,
    calculate_domestic_trade_summary,
    calculate_global_trade_summary,
    calculate_price_group_summary,
    calculate_price_summary,
)
from .models import (  # noqa: E402
    AnalysisSummaryRequest,
    AnalysisSummaryResponse,
    CompositeIndexObservation,
    CompositeIndexSeries,
    DataQuality,
    GradeResult,
    IndicatorObservation,
    IndicatorSeries,
    Metric,
    MineralMapObservation,
    MineralMapSeries,
    MineralRef,
    PriceForecastObservation,
    PriceForecastSeries,
    PriceGroupMineralObservation,
    PriceObservation,
    PriceSeries,
    SourceInfo,
    SummaryNarrative,
    SummaryPageId,
    SummarySentence,
    SupplyAuxiliaryData,
    TradeCountryObservation,
    TradeMapSeries,
)
from .policy import PagePolicy, load_page_policy  # noqa: E402
from .prompts import (  # noqa: E402
    apply_page_config,
    build_summary_payload,
    effective_page_context,
    resolve_page_config,
    page_prompt_scope,
    summary_instructions,
)

from .indicator_summary import (
    _CalculatedSummary,
    _metric,
    _score_meaning,
    _score_position_meaning,
    _change_phrase,
    _supply_auxiliary_metrics,
    _classify_series,
    _calculate_summary,
)
from .input_data import (
    normalize_price_request,
    _observations_from_request,
    _komis_period_comparisons_from_request,
    _komis_trade_totals_from_request,
    _komis_num,
    _komis_num_comma,
    _komis_zero_to_none,
    _komis_crtr_ymd_to_date,
    _komis_rows_to_observations,
    _KomisPriceParsed,
    _parse_komis_price_response,
    _parse_komis_map_korea_response,
    _map_korea_query_filters,
    _parse_komis_map_global_response,
    _parse_komis_map_global_bar_chart_top_country,
    _parse_komis_map_global_route_shares,
    _mineral_map_unit_label,
    _mineral_map_value_key,
    _mineral_map_country_observation,
    _parse_komis_mineral_map_response,
    _parse_komis_map_mineral_snapshot_response,
    _parse_komis_map_mineral_share_response,
    _parse_komis_composite_response,
    _komis_ymd_to_month,
    _parse_komis_indicator_list_response,
    _parse_komis_market_response,
    _parse_komis_supply_response,
    _parse_komis_supply_snapshot_response,
    _parse_komis_price_forecast_response,
    _supply_auxiliary_from_request,
)

def _calculate_or_no_data(page_id: str, calculate, /, *args, **kwargs):
    """`calculate_*`가 데이터 조건 미충족(관측 1건뿐·국가 3개 미만·총액 0 등)으로
    던지는 `ValueError`를 `DataSourceError`(→ 응답 `NO_DATA`)로 바꾼다.

    2026-08-27 skeptic 감사(SC-003)에서 실측: 이 ValueError들이 그대로 새어
    `routers/_common.py`에서 스택트레이스+`INTERNAL_ERROR`로 보고돼, "코드가
    죽었다"는 신호(G2 게이트)와 정당한 데이터 부족이 구분되지 않았다. pydantic
    `ValidationError`도 ValueError 하위형이지만 그건 응답 모델 조립 실패 = 진짜
    코드 버그이므로 그대로 통과시킨다(INTERNAL_ERROR로 남아야 게이트가 잡는다)."""

    try:
        return calculate(*args, **kwargs)
    except ValidationError:
        raise
    except ValueError as exc:
        raise DataSourceError(f"{page_id}: 요청 데이터로는 요약을 계산할 수 없다 — {exc}") from exc


def _data_version(payload: object) -> str:
    """요청 바디 observations의 내용 해시 — DB판 `data_sources/_shared._version`과
    같은 목적(캐시/변경감지용 지문)이지만, 이제 DB를 안 거치니 여기서 자체 계산한다."""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _build_mineral_map_secondary_series(
    request: AnalysisSummaryRequest, primary_series: MineralMapSeries
) -> MineralMapSeries | None:
    """`komis_snapshot_response`(교차비교용 반대 measure 스냅샷)가 있으면
    보조 `MineralMapSeries`를 만든다 — 없으면 `None`.

    2026-09-09 복잡성 해소(사용자 지시 — "JSON 받아서 전처리하는 루틴이
    너무 복잡해지는 것 같다") — `_analyze_mineral_map` 본문에 조건문 하나로
    40줄 가까이 박혀 있던 블록을 분리했다. 호출부는 이 함수 하나뿐이지만
    (2026-08-31 옛 `secondary_measure_observations`(손입력)를 대체) 이름이
    붙은 함수로 빼는 것 자체가 `_analyze_mineral_map`의 주 흐름(원본
    시리즈 조립 → 보조 시리즈 → market_share → 계산 → 응답 조립)을 한
    눈에 보이게 한다 — 순수 리팩터, 계산·문구 변경 없음.

    연도는 primary 계열의 최신연도로 붙인다 — `calculate_mineral_map_
    summary`의 교차비교 게이트가 그 연도(`current_year`) 데이터를
    찾으므로 구조적으로 맞다(`models.py`의 `komis_snapshot_response`
    필드 docstring 참고)."""

    if request.komis_snapshot_response is None:
        return None
    secondary_measure = "production" if request.measure == "reserves" else "reserves"
    snapshot_year = primary_series.available_end_year
    secondary_raw, secondary_unit = _parse_komis_map_mineral_snapshot_response(
        request.komis_snapshot_response, secondary_measure, snapshot_year
    )
    if not secondary_raw:
        return None
    secondary_observations = _observations_from_request(
        MineralMapObservation, request, raw=secondary_raw, field_name="komis_snapshot_response"
    )
    secondary_years = sorted({o.year for o in secondary_observations})
    return MineralMapSeries(
        mineral=primary_series.mineral,
        measure=secondary_measure,
        unit=secondary_unit or request.unit or primary_series.unit,
        available_start_year=secondary_years[0],
        available_end_year=secondary_years[-1],
        source_type="api",
        source_id="api:request",
        data_version=_data_version([o.model_dump(mode="json") for o in secondary_observations]),
        data_as_of=str(secondary_years[-1]),
        observations=secondary_observations,
        warnings=[],
    )


#: (?<!니)다\.(?=\s|$) — report_render.py::_to_polite_copula와 같은 규칙으로
#: "이미 격식체(-니다.)"는 제외하고, 문장 끝(공백 또는 문자열 끝) 앞의 "다."만
#: 비격식 종결로 본다.
_RESIDUAL_INFORMAL_ENDING_RE = re.compile(r"(?<!니)다\.(?=\s|$)")

#: 2026-09-09 main-agent 승인(B-3) — `calculate_composite_summary`(frozen,
#: additional_summary.py)가 실제로 만드는 문장 종결 어미 전수 조사 결과.
#: `report_gen_to_polite_copula_gotcha_260901` 함정(어간 안 가리는 기계적
#: "다."→"입니다." 치환)을 피하려고, 이 계산기가 만드는 정확한 종결 문자열만
#: 하나씩 나열해 대응하는 격식체로 바꾼다 — 일반 문법 변환기가 아니다. 새
#: 문장 패턴이 추가되면(계산기 코드 변경) 여기 없는 종결은 그대로 통과하고
#: 경고 로그만 남는다(`_apply_polite_endings` 참고) — 변환 실패로 요청을
#: 죽이지 않는다.
_COMPOSITE_POLITE_ENDINGS = {
    # current_state: "...포인트다." (계사)
    "포인트다": "포인트입니다",
    # medium_long_term_contrast: _relative_level()의 "...수준이다." (계사)
    "수준이다": "수준입니다",
    # composite_recent_changes·weekly/monthly_subindex_comparison: _change_verb()
    "올랐다": "올랐습니다",
    "내렸다": "내렸습니다",
    "없었다": "없었습니다",
    # yearly_subindex_comparison: "...더 높았다." (과거형)
    "높았다": "높았습니다",
    # index_top_weighted_minerals: "...민감한 구조다." (계사)
    "구조다": "구조입니다",
    # period_range_position: "...% 높다." (형용사 현재형, 자음어간 "높-")
    "높다": "높습니다",
    # overall_pattern: year_word 3분기(형용사 현재형)
    "낮다": "낮습니다",
    "같다": "같습니다",
    # overall_pattern 부가문장(과거형)
    "달랐다": "달랐습니다",
    "있었다": "있었습니다",
}

#: 2026-09-09 main-agent 승인(B-3) — `calculate_mineral_map_summary`(frozen)
#: 전수 조사 결과. 위와 같은 원칙(명시적 나열, 기계적 치환 금지).
_MINERAL_MAP_POLITE_ENDINGS = {
    # current_state: "...{unit}이다." (계사)
    "이다": "입니다",
    # period_total_change: rate_word/latest_word(과거형)
    "증가했다": "증가했습니다",
    "감소했다": "감소했습니다",
    "없었다": "없었습니다",
    # current_leaders(1위다.)·third_country(3위다.): "...위다." (계사)
    "위다": "위입니다",
    # current_leaders: "...%포인트다." (계사)
    "포인트다": "포인트입니다",
    # leading_country_changes·concentration_change: _point_change_phrase()(과거형)
    "높아졌다": "높아졌습니다",
    "낮아졌다": "낮아졌습니다",
    # leading_country_changes의 rank_text(과거형)
    "바뀌었다": "바뀌었습니다",
    "유지했다": "유지했습니다",
    # current_concentration_structure 3분기 + 고정 종결
    "분포다": "분포입니다",  # 계사
    "아니다": "아닙니다",  # 부정 계사(불규칙 활용 — "아니입니다"가 아니다)
    "%다": "%입니다",  # 계사
    "차지한다": "차지합니다",  # "하다" 동사 현재형
    # cross_measure_comparison 두 분기
    "분류된다": "분류됩니다",  # "되다" 동사 현재형
    "국가다": "국가입니다",  # 계사
}


def _apply_polite_endings(
    calculated: AdditionalCalculatedSummary,
    suffix_map: dict[str, str],
    *,
    context: str,
) -> None:
    """`calculated.claims`의 각 `EvidenceClaim.fact`를 `suffix_map`으로 격식체
    변환한다 — frozen 계산기(additional_summary.py) 자체는 못 고치므로 결과를
    받은 뒤 이 계층에서 문장만 다시 짓는 post-processing(2026-09-09 main-agent
    승인 B-3, `_append_mineral_map_extreme_change`와 같은 방식 — `EvidenceClaim`
    은 frozen dataclass라 텍스트만 바꿀 순 없고 새 인스턴스로 교체한다).

    `report_render.py::_to_polite_copula`처럼 문자열 끝만 보지 않는다 — 한
    claim.fact가 여러 문장을 이어붙인 경우(예: map_mineral의 current_leaders가
    "...1위다. ...%포인트다."처럼 두 문장)가 있어, 텍스트 전체에서 일치하는
    자리를 전부 바꾼다(`_to_polite_copula`가 정의문 2문장짜리에서 앞 문장을
    놓쳤던 것과 같은 함정 — 2026-09-09 B-3 검증 중 발견·수정, `report_gen_
    to_polite_copula_gotcha_260901` 참고).

    매핑에 없는 종결이 남으면(향후 계산기 변경 등) 요청을 죽이지 않고 경고
    로그만 남긴다 — 변환 실패보다 원문 그대로 노출이 안전하다(조건 2)."""

    compiled = [
        (re.compile(re.escape(informal) + r"\.(?=\s|$)"), f"{formal}.")
        for informal, formal in suffix_map.items()
    ]
    new_claims = []
    for claim in calculated.claims:
        text = claim.fact
        for pattern, replacement in compiled:
            text = pattern.sub(replacement, text)
        if _RESIDUAL_INFORMAL_ENDING_RE.search(text):
            _log.warning(
                "B-3 격식체 변환: %s claim=%s에 매핑되지 않은 비격식 종결이 남았다: %r",
                context,
                claim.id,
                text,
            )
        new_claims.append(EvidenceClaim(claim.id, claim.section, text, claim.required))
    calculated.claims = new_claims


def _mineral_map_extreme_change_countries(series: MineralMapSeries) -> tuple[str | None, str | None] | None:
    """조회기간 첫 해→마지막 해 사이 매장량/생산량이 가장 크게 늘거나
    준 국가를 (증가국, 감소국)으로 찾는다 — 둘 다 없으면(전 국가 무변화)
    전체가 `None`, 한쪽 방향이 아예 없으면(예: 전부 증가만 하고 감소한
    국가가 하나도 없음) 그쪽만 `None`으로 채워 반환한다.

    2026-09-09 발주처 업무지시서 §3.3 ③④ 대응(사용자 승인) —
    `calculate_mineral_map_summary`(프로즌)는 상위 3개국 개별 변화만
    다뤄서, PDF 예시의 콩고민주공화국처럼 top3 밖에서 급증한 국가는
    잡지 못한다. 절대량 변화(현재값-시작값, 결측은 0 취급) 기준으로
    전체 국가를 본다 — 비율로 하면 조회기간에 새로 나타난 국가(시작값
    0)가 나눗셈 0으로 계산 자체가 안 된다.

    2026-09-10 사용자 지적("주요 변화 섹션이 안 나온다", main-agent 경유
    재현 — 동/구리 2024~2025 단기 윈도우와 리튬 매장량 2019~2025 둘 다
    같은 원인으로 재현) —
    원래는 "증가국과 감소국이 둘 다 있어야만" 근거를 냈는데, 광물자원
    특성상(매장량은 장기적으로 늘기만 하거나, 짧은 최근 2개년 윈도우는
    거의 다 줄기만 하는 경우가 흔하다) 한쪽 방향이 아예 없는 조회가
    드물지 않다 — 이 경우 "주요 변화" 섹션 전체가 통째로 사라지는 것보다
    있는 쪽만이라도 보여주는 게 사용자 의도에 맞는다."""

    filtered = [o for o in series.observations if not o.is_total and not o.is_other]
    years = sorted({o.year for o in filtered})
    if len(years) < 2:
        return None
    start_year, current_year = years[0], years[-1]
    start_values = {o.country_code: o.value for o in filtered if o.year == start_year}
    current_values = {o.country_code: o.value for o in filtered if o.year == current_year}
    names = {o.country_code: o.country_name for o in filtered}
    codes = set(start_values) | set(current_values)
    if len(codes) < 2:
        return None
    changes = {code: current_values.get(code, 0.0) - start_values.get(code, 0.0) for code in codes}
    max_increase_code = max(codes, key=lambda code: changes[code])
    max_decrease_code = min(codes, key=lambda code: changes[code])
    increase_name = names[max_increase_code] if changes[max_increase_code] > 0 else None
    decrease_name = names[max_decrease_code] if changes[max_decrease_code] < 0 else None
    if increase_name is None and decrease_name is None:
        return None
    return increase_name, decrease_name


def _append_mineral_map_extreme_change(calculated: AdditionalCalculatedSummary, series: MineralMapSeries) -> None:
    """`_mineral_map_extreme_change_countries` 결과가 있으면 major_changes
    근거·주요 지표를 덧붙인다(계산기 프로즌 파일은 안 건드리고 호출자가
    결과에 추가하는 방식 — `AdditionalCalculatedSummary`는 frozen
    dataclass가 아니라 이 방식이 가능하다). 증가·감소 한쪽만 있으면 그
    한쪽만 문장·지표로 낸다."""

    extreme = _mineral_map_extreme_change_countries(series)
    if extreme is None:
        return
    max_increase_country, max_decrease_country = extreme
    measure_name = "매장량" if series.measure == "reserves" else "생산량"
    if max_increase_country and max_decrease_country:
        fact = (
            f"조회기간 중 {measure_name}이 가장 크게 증가한 국가는 {max_increase_country}이며, "
            f"가장 크게 감소한 국가는 {max_decrease_country}입니다."
        )
    elif max_increase_country:
        fact = f"조회기간 중 {measure_name}이 가장 크게 증가한 국가는 {max_increase_country}입니다."
    else:
        fact = f"조회기간 중 {measure_name}이 가장 크게 감소한 국가는 {max_decrease_country}입니다."
    calculated.claims.append(
        EvidenceClaim("extreme_change_countries", "major_changes", fact, required=True)
    )
    # key_metrics·detailed_metrics는 계산기(additional_summary.py)가 만들
    # 때부터 별개 리스트(detailed_metrics = [*key_metrics, 추가 항목])라
    # 두 곳에 각각 추가해야 한다 — 한쪽만 덮어쓰면 다른 항목이 사라진다.
    new_metrics = []
    if max_increase_country:
        new_metrics.append(Metric(id="max_increase_country", label="최대 증가 국가", status="available", value=max_increase_country))
    if max_decrease_country:
        new_metrics.append(Metric(id="max_decrease_country", label="최대 감소 국가", status="available", value=max_decrease_country))
    calculated.key_metrics.extend(new_metrics)
    calculated.detailed_metrics.extend(new_metrics)


def _mineral_map_latest_year_change(series: MineralMapSeries) -> tuple[float, int, int] | None:
    """직전 연도 대비 세계 합계 변화율("전년 대비 변화율") — (변화율, 직전연도,
    최근연도), 없으면 `None`.

    2026-09-10 사용자 지시 — `calculate_mineral_map_summary`(프로즌)는 이 값을
    `period_total_change`(core_diagnosis, "조회기간 전체 변화율") 서사 문장
    안에서만 계산하고(3개 연도 이상일 때만, `previous_year != start_year`
    조건) 별도 key_metric으로 내보내지 않는다. "주요 지표" 표에 항상
    노출해야 해서 여기서 독립적으로 다시 계산한다 —
    `_mineral_map_extreme_change_countries`와 같은 결로 프로즌 파일의 사설
    헬퍼(`_by_year`/`_world_total`/`_percent_change`)는 재사용하지 않고
    `series.observations`를 직접 본다. 조회기간이 연도 2개뿐이면 이 값은
    `period_world_total_change`(조회기간 전체 변화율)와 같아지지만, 사용자가
    항상 이 라벨을 보길 원해 조건 분기 없이 매번 계산한다."""

    filtered = [o for o in series.observations if not o.is_total and not o.is_other]
    years = sorted({o.year for o in filtered})
    if len(years) < 2:
        return None
    latest_year, previous_year = years[-1], years[-2]
    latest_total = sum(o.value for o in filtered if o.year == latest_year)
    previous_total = sum(o.value for o in filtered if o.year == previous_year)
    if previous_total == 0:
        return None
    return (latest_total - previous_total) / previous_total, previous_year, latest_year


def _append_mineral_map_latest_year_change(calculated: AdditionalCalculatedSummary, series: MineralMapSeries) -> None:
    """`_mineral_map_latest_year_change` 결과가 있으면 "주요 지표"에 "전년
    대비 변화율" 1건을 덧붙인다(서사 문장은 이미 `period_total_change`
    claim이 다루므로 여기선 metric만 추가한다)."""

    result = _mineral_map_latest_year_change(series)
    if result is None:
        return
    change, previous_year, latest_year = result
    metric = _metric(
        "latest_year_total_change",
        "전년 대비 변화율",
        change,
        unit="ratio",
        basis=f"{previous_year} 대비 {latest_year}",
    )
    calculated.key_metrics.append(metric)
    calculated.detailed_metrics.append(metric)


def _append_composite_period_value_comparison(
    calculated: AdditionalCalculatedSummary, series: CompositeIndexSeries
) -> None:
    """`calculate_composite_summary`(프로즌)는 전주/전월/전년 대비 등락률만
    key_metrics(`weekly_composite_change` 등)로 내고, 비교 시점의 실제
    지수값 자체는 서사에 없다.

    2026-09-10 발주처 피드백([3], 권가영 사원) — "전주 [전주 평균지수] 대비
    [증감률]% [상승/하락], 전월 ..., 전년 동기 ..."처럼 값과 등락률을 함께
    밝히는 문장을 core_diagnosis에 추가해달라는 요청.

    `_at_or_before`/`_shift_month`/`_shift_year`(프로즌 파일의 날짜 헬퍼)를
    그대로 재사용해 `calculate_composite_summary`가 이미 고른 비교 시점
    (전주=7일 전, 전월=달력상 한 달 전, 전년=달력상 1년 전 시점 이전 최근
    관측치)과 항상 일치시킨다 — 날짜 선택 로직을 따로 재구현하면 이 문장의
    등락률이 같은 보고서의 `weekly_composite_change` 등 기존 지표와
    미묘하게 어긋날 위험이 있다(map_mineral의 `_mineral_map_latest_year_
    change`와 달리 여기서는 그 위험을 감수할 이유가 없어 프로즌 헬퍼를
    그대로 가져다 쓴다 — 순수 날짜 계산 함수라 결합 부담이 없다)."""

    observations = sorted(series.observations, key=lambda item: item.date)
    current = observations[-1]
    current_date = date.fromisoformat(current.date)
    week = _at_or_before(observations[:-1], current_date - timedelta(days=7))
    month = _at_or_before(observations[:-1], _shift_month(current_date, -1))
    year = _at_or_before(observations[:-1], _shift_year(current_date, -1))

    pieces = []
    for label, compared in (("전주", week), ("전월", month), ("전년 동기", year)):
        if compared is None:
            continue
        change = _pct(current.composite_index, compared.composite_index)
        if change is None:
            continue
        direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
        pieces.append(
            f"{label} {_number(compared.composite_index)}포인트 대비 "
            f"{_number(abs(change) * 100)}% {direction}"
        )
    if not pieces:
        return
    fact = ", ".join(pieces) + "했습니다."
    calculated.claims.append(
        EvidenceClaim("period_value_comparison", "core_diagnosis", fact, required=True)
    )


#: 2026-09-10 발주처 피드백[4] — "메이저금속지수끼리, 희소금속지수끼리, 광물종합
#: 지수끼리 각각 따로" 서술해달라는 요청과 정면으로 부딪히는 4개 claim(전부
#: `calculate_composite_summary` 프로즌 산출, major_changes). 새로 추가하지
#: 않고 아래 `_replace_composite_subindex_narrative`가 통째로 대체한다.
_COMPOSITE_MIXED_SUBINDEX_CLAIM_IDS = frozenset(
    {
        "composite_recent_changes",
        "weekly_subindex_comparison",
        "monthly_subindex_comparison",
        "yearly_subindex_comparison",
        "index_top_weighted_minerals",
    }
)


def _replace_composite_subindex_narrative(
    calculated: AdditionalCalculatedSummary, series: CompositeIndexSeries
) -> None:
    """`calculate_composite_summary`(프로즌)의 major_changes 근거 4종
    (`_COMPOSITE_MIXED_SUBINDEX_CLAIM_IDS`)은 "메이저금속지수는 ~한 반면
    희소금속지수는 ~"처럼 세 지수를 한 문장 안에서 섞어 비교한다.

    2026-09-10 발주처 피드백([4], 권가영 사원) — "각 지수가 오르는 추세인지
    아닌지 근거 기반으로 간략히 표출, 지수별로 하나의 문장/영역으로 묶어서
    '[지수명] 포인트 + 등락률(+추이) + 관련 광종' 형태로, 3개 지수를 한
    문단에 섞지 말 것"이라는 요청은 이 4종 claim이 만드는 바로 그 "섞인"
    형태를 지적한 것이라, 새 문장을 추가하는 대신 광물종합·메이저금속·
    희소금속 지수별로 자기완결적인 문장 3개로 완전히 대체한다(숫자 자체는
    이미 올바르므로 key_metrics/detailed_metrics는 손대지 않는다).

    비교 시점은 `_append_composite_period_value_comparison`과 동일하게
    `_at_or_before`/`_shift_month`/`_shift_year`(프로즌 날짜 헬퍼)를 그대로
    재사용해 같은 보고서 안의 `weekly_composite_change` 등 기존 지표와
    기준일이 어긋나지 않게 한다. "오르는 추세"라는 표현은 그대로 옮기지
    않는다 — "추세"는 `_FORBIDDEN_SUMMARY_TERMS`(evidence에 없는 인과·상관
    표현 차단용)에 있어 문자 그대로 쓰면 LLM 출력이 검증기에서 매번
    기각된다. "상승/하락 흐름"·"뚜렷한 방향성 없이 등락을 반복"(가격 페이지
    RSI 문구, `_ma_rsi_fact`와 동일 어휘)으로 대체한다.

    새 문장을 하나도 만들 수 없으면(조회기간에 전주·전월·전년 비교 시점이
    전혀 없음 — 이 경우 프로즌 계산기는 데이터와 무관한 `index_top_weighted_
    minerals`만 major_changes에 남겨 `SummaryNarrative.major_changes`
    min_length=1을 충족시켜 둔 상태다) 원래 claim을 그대로 두고 아무것도
    지우지 않는다 — 대체할 문장이 없는데 원본만 지우면 major_changes가
    통째로 비어 조립이 깨진다."""

    observations = sorted(series.observations, key=lambda item: item.date)
    current = observations[-1]
    current_date = date.fromisoformat(current.date)
    prior = observations[:-1]
    week = _at_or_before(prior, current_date - timedelta(days=7))
    month = _at_or_before(prior, _shift_month(current_date, -1))
    year = _at_or_before(prior, _shift_year(current_date, -1))

    index_weights = _load_mineral_index_weights()
    specs = (
        ("composite_index_trend", "광물종합지수", "composite_index", index_weights.get("MNRL", []), 3),
        ("major_metals_index_trend", "메이저금속지수", "major_metals_index", index_weights.get("MAJOR", []), 2),
        ("minor_metals_index_trend", "희소금속지수", "minor_metals_index", index_weights.get("RARE", []), 2),
    )

    new_narrative_claims: list[EvidenceClaim] = []
    for claim_id, label, attr, weights, limit in specs:
        current_value = getattr(current, attr)
        pieces = []
        changes = []
        for period_label, compared in (("전주", week), ("전월", month), ("전년", year)):
            if compared is None:
                continue
            change = _pct(current_value, getattr(compared, attr))
            if change is None:
                continue
            changes.append(change)
            direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
            pieces.append(f"{period_label} 대비 {_number(abs(change) * 100)}% {direction}")
        if not pieces:
            continue
        fact = f"{label}는 {_number(current_value)}포인트로, " + ", ".join(pieces) + "했습니다."
        if len(changes) >= 2:
            if all(change > 0 for change in changes):
                fact += " 최근 조회기간 동안 상승 흐름을 이어가고 있습니다."
            elif all(change < 0 for change in changes):
                fact += " 최근 조회기간 동안 하락 흐름을 이어가고 있습니다."
            elif all(change == 0 for change in changes):
                fact += " 최근 조회기간 동안 보합 흐름을 이어가고 있습니다."
            else:
                fact += " 뚜렷한 방향성 없이 등락을 반복하고 있습니다."
        if weights:
            fact += f" 구성 광종은 {_top_weighted_minerals_text(weights, limit)} 등입니다."
        new_narrative_claims.append(EvidenceClaim(claim_id, "major_changes", fact, required=True))

    if not new_narrative_claims:
        return
    calculated.claims = [
        claim for claim in calculated.claims if claim.id not in _COMPOSITE_MIXED_SUBINDEX_CLAIM_IDS
    ] + new_narrative_claims


def _source_info_from_series(
    series: IndicatorSeries | CompositeIndexSeries | MineralMapSeries | PriceForecastSeries | PriceSeries | TradeMapSeries,
) -> SourceInfo:
    """6개 응답조립 지점(indicator·composite·mineral_map·forecast·price·trade_map)이
    바이트 단위로 반복하던 `SourceInfo(...)` 조립을 하나로(2026-09-08 SC-DEEP-007:
    이 6종 series 모델이 모두 같은 이름의 출처 메타 필드를 갖고 있어 성립한다 —
    `price_group`은 series가 아니라 request에서 직접 조립해 이 헬퍼 대상이 아니다)."""

    return SourceInfo(
        type=series.source_type,
        id=series.source_id,
        data_version=series.data_version,
        as_of=series.data_as_of,
        file=series.source_file,
        sheets=series.source_sheets,
    )


def _filter_hash(page_id: str, filters: dict[str, str | None]) -> str:
    canonical = json.dumps(
        {"page_id": page_id, "filters": filters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deterministic_narrative(
    claims: list[EvidenceClaim],
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
    "주요 요인",
    "요인으로",
    "원인으로 분석",
    "함에 따라",
)
_GRADE_LABELS = {"신중", "주의", "중립", "관심", "기회", "긴장", "안정", "원활"}
# 2026-08-28 작업C(main-agent 조사) — "근거 4개 이상이면 최소 1문장은 근거
# 2개를 결합해야 한다"(SC-018) 규칙이 모든 page_id에 무차별 적용됐는데,
# price_group은 `PRICE_GROUP_SUMMARY_INSTRUCTIONS`(prompts.py)가 "group_movers·
# extreme_movers를 근거에 있는 그대로 옮겨 쓴다"(근거 1개=문장 1개, 결합 금지
# 취지)를 지시하고 `major_changes` 절 자체가 최대 2문장이라, 근거 4개 이상일
# 때 "각자 따로 쓰기"와 "누군가는 합쳐 쓰기"를 동시에 만족하는 게 구조적으로
# 불가능하다 — 실측(26건 표본 재전송) 결과 price_group은 매번 100% 폴백,
# 우연이 아니라 예정된 실패였다. 이 규칙에서만 예외 처리한다("모든 evidence_id
# 정확히 1회 사용" 체크는 여전히 걸린다 — 안전장치로 유효해 유지).
_COMBINED_SENTENCE_EXEMPT_PAGES = {"price_group"}


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
    claims: list[EvidenceClaim],
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
    # 섹션별 문장수 계약은 `prompts.py::resolve_page_config`(코드 기본값 + DB
    # 오버레이) 한 곳에서 온다 — LLM에 보내는 output_contract와 이 검증기가 같은
    # 값을 보게 하기 위해서다(2026-08-27 skeptic 감사 SC-005 → 같은 날 DB화 2단계).
    cfg = resolve_page_config(page_id)
    if page_id == "map_mineral":
        total_min, total_max = cfg.total_sentence_range or (5, 8)
        if not total_min <= len(sentences) <= total_max:
            return f"광물지도 출력은 전체 {total_min}~{total_max}문장이어야 한다."
        major_min, major_max = cfg.section_sentence_ranges["major_changes"]
        if not major_min <= len(candidate.major_changes) <= major_max:
            return f"광물지도 주요 변화는 {major_min}~{major_max}문장이어야 한다."
        position_min, position_max = cfg.section_sentence_ranges["current_position"]
        if not position_min <= len(candidate.current_position) <= position_max:
            return f"광물지도 현재 위치·의미는 {position_min}~{position_max}문장이어야 한다."
    else:
        for section, values in sections:
            minimum, maximum = cfg.section_sentence_ranges[section]
            if not minimum <= len(values) <= maximum:
                return "섹션별 분석문 수가 출력 계약과 일치하지 않는다."
    used_ids: list[str] = []
    # 등급명 검사는 등급이 있는 지표 페이지에만 — map_mineral 등에서 "안정된 수준"의
    # "안정"이 등급명으로 오인돼 폴백되는 사례가 실 LLM 384건 회귀에서 나왔다(2026-08-27
    # 반복 루프 1회차; PDF 템플릿 자체가 매장량 서술에 "안정된 수준"을 쓴다).
    check_grade_labels = page_id in ("indicator_market", "indicator_supply")
    for section, values in sections:
        for sentence in values:
            if any(term in sentence.text for term in _FORBIDDEN_SUMMARY_TERMS):
                return "본문에서 제외한 지표를 언급했다."
            if any(re.search(rf"\b{re.escape(claim_id)}\b", sentence.text) for claim_id in claim_map):
                # 2026-08-27 반복 루프 1회차: "(current_state)"처럼 id를 본문에 적는 사례 17건.
                return "본문(text)에 evidence_id를 적었다 — evidence_ids 필드에만 적어야 한다."
            referenced = [claim_map.get(evidence_id) for evidence_id in sentence.evidence_ids]
            if any(claim is None for claim in referenced):
                return "존재하지 않는 evidence_id를 사용했다."
            typed_references = [claim for claim in referenced if claim is not None]
            if any(claim.section != section for claim in typed_references):
                return "evidence_id를 다른 출력 섹션에 사용했다."
            evidence_text = " ".join(claim.fact for claim in typed_references)
            if not _number_tokens(sentence.text) <= _number_tokens(evidence_text):
                return "근거에 없는 숫자나 날짜를 사용했다."
            if check_grade_labels:
                mentioned_grades = {label for label in _GRADE_LABELS if label in sentence.text}
                allowed_grades = {label for label in _GRADE_LABELS if label in evidence_text}
                if not mentioned_grades <= allowed_grades:
                    return "근거에 없는 단계명을 사용했다."
            # 2026-09-10 사용자 지시 — indicator_market의 latest_score_change
            # 근거는 점수 하락과 위험 상승(또는 그 반대)을 반비례 관계 설명
            # 없이 한 문장으로 이으면 사용자에게 방향이 반대로 읽혀 혼동을
            # 준다는 지적(발주처 피드백[5])으로 "이 지표는 점수가 낮을수록
            # 위험이 커지는 구조입니다."를 근거 문장에 넣어뒀다. 그런데 이
            # 문장이 evidence_id 하나(latest_score_change) 안의 자유 텍스트라
            # LLM 정제 단계에서 조용히 병합·삭제될 수 있음을 실측으로 확인
            # (2026-09-10, LLM_BASE_URL 컨테이너 접속 버그를 고친 뒤 실LLM
            # 재검증 중 재현) — evidence_id 커버리지 검사만으로는 이 사고를
            # 못 잡는다(같은 id를 인용하면서 안의 문구만 지워도 통과). 그
            # 근거의 fact 자체에 이 반비례 설명 문구가 들어있는 문장이면
            # (score_change != 0인 indicator_market 케이스에서만 존재)
            # 출력 문장도 그 문구를 그대로 담고 있어야 한다 — 없으면 검증
            # 실패로 안전하게 규칙 기반 폴백으로 보낸다.
            if page_id == "indicator_market" and "latest_score_change" in sentence.evidence_ids:
                required_clause = "점수가 낮을수록 위험이 커지는"
                score_claim = claim_map.get("latest_score_change")
                if (
                    score_claim is not None
                    and required_clause in score_claim.fact
                    and required_clause not in sentence.text
                ):
                    return "점수-위험 반비례 설명 문장을 누락했다."
            used_ids.extend(sentence.evidence_ids)
    if page_id == "map_mineral":
        required_ids = {claim.id for claim in claims if claim.required}
        if not required_ids <= set(used_ids):
            return "필수 evidence_id를 모두 사용하지 않았다."
    elif Counter(used_ids) != Counter(claim_map.keys()):
        return "모든 evidence_id를 정확히 한 번씩 사용하지 않았다."
    elif (
        page_id not in _COMBINED_SENTENCE_EXEMPT_PAGES
        and len(claims) >= 4
        and not any(len(sentence.evidence_ids) >= 2 for sentence in sentences)
    ):
        return "관련 근거를 결합한 분석 문장이 없다."
    if "current_state" not in {
        evidence_id
        for sentence in candidate.core_diagnosis
        for evidence_id in sentence.evidence_ids
    }:
        return "핵심 진단에 현재 상태 근거가 없다."
    return None


def _build_response(
    request: AnalysisSummaryRequest,
    series,
    calculated,
    context: PagePolicy | SummaryPageContext,
    *,
    mineral: MineralRef,
    applied_filters: dict,
    defaulted_filters: list[str],
    page_definition: str,
    grade: GradeResult | None,
    data_quality: DataQuality,
) -> AnalysisSummaryResponse:
    """페이지별 계산·품질 판정 이후의 공통 응답 조립. 출력 필드는 그대로 유지한다."""
    return AnalysisSummaryResponse(
        request_id=request.request_id,
        page_id=request.page_id,
        analysis_scope=request.analysis_scope,
        mineral=mineral,
        applied_filters=applied_filters,
        defaulted_filters=defaulted_filters,
        filter_hash=_filter_hash(request.page_id, applied_filters),
        source=_source_info_from_series(series),
        policy_version=context.policy_version,
        page_definition=page_definition,
        grade=grade,
        data_quality=data_quality,
        summary=_deterministic_narrative(calculated.claims),
        key_metrics=calculated.key_metrics,
        detailed_metrics=calculated.detailed_metrics,
        detected_patterns=calculated.patterns,
        omitted_indicators=calculated.omitted,
        notices=context.analysis_constraints,
    )


class AnalysisSummaryService:
    """Calculate a page-scoped summary and optionally refine it with verified LLM output."""

    def __init__(
        self,
        data_source: IndicatorDataSource | None = None,
        *,
        composite_source: CompositeIndexDataSource | None = None,
        mineral_map_source: MineralMapDataSource | None = None,
        price_forecast_source: PriceForecastDataSource | None = None,
        price_source: PriceDataSource | None = None,
        domestic_trade_source: DomesticTradeDataSource | None = None,
        global_trade_source: GlobalTradeDataSource | None = None,
        llm: KomirJsonLLM | None = None,
    ) -> None:
        self._data_source = data_source
        self._composite_source = composite_source
        self._mineral_map_source = mineral_map_source
        self._price_forecast_source = price_forecast_source
        # 아래 3개는 komir 자체 추가(2026-08-19) — §모듈 docstring 4번 참고.
        self._price_source = price_source
        self._domestic_trade_source = domestic_trade_source
        self._global_trade_source = global_trade_source
        self._llm = llm
        self._deadlines = threading.local()

    @property
    def uses_llm(self) -> bool:
        """LLM 정제가 배선돼 있는지 — `routers/_common.py`가 lock 인수 뒤 남은
        예산이 LLM 1회분보다 짧을 때 포기할지 결정하는 데 쓴다(R2-F2)."""

        return self._llm is not None

    def analyze(
        self,
        request: AnalysisSummaryRequest,
        *,
        deadline: float | None = None,
    ) -> AnalysisSummaryResponse:
        """Calculate the summary appropriate for the requested page.

        `deadline`(`time.monotonic()` 기준, 선택) — `routers/_common.py`가 요청당
        예산을 넘긴다. `_refine_with_llm`이 LLM 호출 전마다 남은 예산이 호출 1회
        상한보다 짧으면 호출을 건너뛰고 규칙기반으로 돌아간다(Pass 3 R3-F1: 이전엔
        정제 2루프 × repair 2회가 예산 밖까지 lock을 쥘 수 있었다). 스레드별로
        보관한다 — 서비스 객체는 공유되고 하네스는 동시 호출한다."""

        self._deadlines.value = deadline
        try:
            with page_prompt_scope(request.page_id):
                return self._dispatch(request)
        finally:
            self._deadlines.value = None

    def _dispatch(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        if request.page_id == "indicator_composite":
            return self._analyze_composite(request)
        if request.page_id == "map_mineral":
            return self._analyze_mineral_map(request)
        if request.page_id == "forecast_price":
            return self._analyze_price_forecast(request)
        if request.page_id in ("price_base_metals", "price_minor_metals", "price_iron_energy", "price_other"):
            return self._analyze_price(request)
        if request.page_id == "map_korea":
            return self._analyze_domestic_trade(request)
        if request.page_id == "map_global":
            return self._analyze_global_trade(request)
        if request.page_id == "price_group":
            return self._analyze_price_group(request)
        return self._analyze_indicator(request)

    def _analyze_indicator(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load an indicator series and build its validated summary response."""

        # 2026-09-01 신설 — indicator_supply는 komis_snapshot_response
        # (`getChartDataSpdmStbt`)가 있으면 그 안의 `chartSpdmStbt`에서
        # mineral 코드·이름을 자동 채운다(§`SupplyIndicatorSummaryRequest`
        # docstring). 같은 응답에서 보조패널(수입량/수입액·수입국 비중)도
        # 함께 뽑아 둔다 — 아래 `series` 조립에서 쓴다.
        snapshot_mineral_code: str | None = None
        snapshot_mineral_name: str | None = None
        supply_auxiliary_raw: dict | None = None
        if request.page_id == "indicator_supply" and request.komis_snapshot_response is not None:
            supply_auxiliary_raw, snapshot_mineral_code, snapshot_mineral_name = (
                _parse_komis_supply_snapshot_response(request.komis_snapshot_response)
            )
        mineral_code = request.mineral or snapshot_mineral_code
        if mineral_code is None:
            raise DataSourceError("indicator analysis requires mineral in the request body")
        mineral_name = request.mineral_name or snapshot_mineral_name or mineral_code
        raw_observations = None
        if request.komis_response is not None:
            parser = (
                _parse_komis_market_response
                if request.page_id == "indicator_market"
                else _parse_komis_supply_response
            )
            raw_observations = parser(request.komis_response)
        observations = _observations_from_request(IndicatorObservation, request, raw=raw_observations)
        if request.start_month:
            observations = [o for o in observations if o.month >= request.start_month]
        if request.end_month:
            observations = [o for o in observations if o.month <= request.end_month]
        if not observations:
            raise DataSourceError("indicator analysis: 필터 적용 후 observations가 비었다")
        months = sorted(o.month for o in observations)
        # komis_snapshot_response로 이미 뽑아 둔 보조패널이 있으면 그쪽을
        # 우선한다 — 손 매핑 `supply_auxiliary`는 그게 없을 때만의 폴백.
        if supply_auxiliary_raw:
            try:
                supply_auxiliary = SupplyAuxiliaryData.model_validate(supply_auxiliary_raw)
            except Exception as exc:  # noqa: BLE001 — pydantic ValidationError 등
                raise DataSourceError(
                    f"{request.page_id}: komis_snapshot_response에서 뽑은 보조패널이 "
                    f"SupplyAuxiliaryData와 맞지 않는다: {exc}"
                ) from exc
        else:
            supply_auxiliary = _supply_auxiliary_from_request(request)
        series = IndicatorSeries(
            page_id=request.page_id,
            mineral=MineralRef(code=mineral_code, name=mineral_name),
            requested_start_month=request.start_month,
            requested_end_month=request.end_month,
            available_start_month=months[0],
            available_end_month=months[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=months[-1],
            observations=observations,
            supply_auxiliary=supply_auxiliary,
            price_unit=request.price_unit,
            price_criterion=request.price_criterion,
            unavailable_page_data=request.unavailable_page_data or [],
            warnings=[],
        )
        # YAML 등급 정책에 DB 오버레이(이름·정의·제약·버전)를 입힌다 — 등급 밴드는
        # 판정 로직이라 YAML 그대로(2026-08-27 프롬프트 DB화 2단계).
        policy = apply_page_config(load_page_policy(request.page_id))
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
        response = _build_response(
            request, series, calculated, policy,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
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
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, calculated.claims)

    def _analyze_composite(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load a composite-index series and build its validated summary response."""

        raw_observations = request.observations
        if request.komis_response is not None:
            raw_observations = _parse_komis_composite_response(request.komis_response)
        observations = _observations_from_request(CompositeIndexObservation, request, raw=raw_observations)
        if request.start_date:
            observations = [o for o in observations if o.date >= request.start_date]
        if request.end_date:
            observations = [o for o in observations if o.date <= request.end_date]
        if not observations:
            raise DataSourceError("composite index analysis: 필터 적용 후 observations가 비었다")
        # 2026-08-31 forecast_price와 같은 원인으로 발견·수정 — KOMIS
        # tableData/defaultMnrl류 응답은 정렬 순서를 보장 안 해서, series에
        # 넣기 전에 직접 날짜순 정렬해야 아래 applied_filters의
        # series.observations[0]/[-1]이 실제 시작/끝과 맞는다.
        observations = sorted(observations, key=lambda item: item.date)
        dates = [item.date for item in observations]
        series = CompositeIndexSeries(
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )
        calculated = _calculate_or_no_data(request.page_id, calculate_composite_summary, series)
        _apply_polite_endings(calculated, _COMPOSITE_POLITE_ENDINGS, context="indicator_composite")
        _append_composite_period_value_comparison(calculated, series)
        _replace_composite_subindex_narrative(calculated, series)
        context = effective_page_context("indicator_composite")
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
        response = _build_response(
            request, series, calculated, context,
            mineral=MineralRef(code="COMPOSITE", name="광물종합지수"),
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
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
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, calculated.claims)

    def _analyze_mineral_map(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load a mineral-map series and build its validated summary response."""

        if request.mineral is None or request.measure is None:
            raise DataSourceError("mineral map analysis requires mineral and measure in the request body")
        # 2026-08-30 신설(사용자 지시로 price의 komis_response 패턴을 나머지
        # 페이지로 확장) — `getListMapMnrlChartData` 원본 응답을 그대로 받으면
        # observations·unit을 직접 만든다. 없으면(하위호환) 기존처럼 손으로
        # 채운 필드를 그대로 쓴다.
        raw_observations = request.observations
        komis_unit = None
        if request.komis_response is not None:
            raw_observations, komis_unit = _parse_komis_mineral_map_response(
                request.komis_response, request.measure
            )
        unit = request.unit or komis_unit
        if not unit:
            raise DataSourceError("mineral map analysis requires unit in the request body")
        observations = _observations_from_request(MineralMapObservation, request, raw=raw_observations)
        if request.start_year:
            observations = [o for o in observations if o.year >= request.start_year]
        if request.end_year:
            observations = [o for o in observations if o.year <= request.end_year]
        if not observations:
            raise DataSourceError("mineral map analysis: 필터 적용 후 observations가 비었다")
        years = sorted({o.year for o in observations})
        series = MineralMapSeries(
            mineral=MineralRef(code=request.mineral, name=request.mineral_name or request.mineral),
            measure=request.measure,
            unit=unit,
            available_start_year=years[0],
            available_end_year=years[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=str(years[-1]),
            observations=observations,
            warnings=[],
        )
        secondary_series = _build_mineral_map_secondary_series(request, series)
        market_share = None
        if request.komis_share_response is not None:
            market_share = _parse_komis_map_mineral_share_response(request.komis_share_response) or None
        calculated = _calculate_or_no_data(
            request.page_id,
            calculate_mineral_map_summary,
            series,
            secondary_series=secondary_series,
            market_share=market_share,
        )
        _apply_polite_endings(calculated, _MINERAL_MAP_POLITE_ENDINGS, context="map_mineral")
        _append_mineral_map_extreme_change(calculated, series)
        _append_mineral_map_latest_year_change(calculated, series)
        context = effective_page_context("map_mineral")
        # 2026-09-09 복잡성 해소 — `years`는 위에서 이미 계산됐다(`series.
        # observations`가 그 `observations`와 동일 리스트라 재계산은 항상
        # 같은 값을 냈다, 중복 계산 제거).
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
        response = _build_response(
            request, series, calculated, context,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
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
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, calculated.claims)

    def _analyze_price_forecast(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load forecast prices and build a validated forecast summary."""
        if request.mineral is None:
            raise DataSourceError("price forecast analysis requires mineral in the request body")
        raw_observations = request.observations
        komis_mineral_name = None
        if request.komis_response is not None:
            raw_observations, komis_mineral_name = _parse_komis_price_forecast_response(request.komis_response)
        observations = _observations_from_request(PriceForecastObservation, request, raw=raw_observations)
        if request.start_period:
            observations = [o for o in observations if o.period >= request.start_period]
        if request.end_period:
            observations = [o for o in observations if o.period <= request.end_period]
        if not observations:
            raise DataSourceError("price forecast analysis: 필터 적용 후 observations가 비었다")
        # 2026-08-31 예외 — `crtrPrd`가 분기("28년 4Q")/연("2028년") 형식
        # 자체로 medium/long을 이미 구분해서 담고 있어(§models.py
        # validate_period의 "-Q" 검사가 이 사실에 의존), komis_response로
        # 받은 관측치의 period 형식에서 forecast_horizon을 자동 판별한다
        # (호출자 명시값이 있으면 그쪽 우선). 손 매핑 경로(komis_response
        # 없음)만 이 형식을 알 방법이 없어 여전히 필수다.
        forecast_horizon = request.forecast_horizon or (
            ("medium" if any("-Q" in o.period for o in observations) else "long")
            if request.komis_response is not None
            else None
        )
        if forecast_horizon is None:
            raise DataSourceError("price forecast analysis requires forecast_horizon in the request body")
        # 2026-08-31 실측 발견·수정: KOMIS는 getListPricePredc를 최신순
        # (내림차순)으로 주는데(가격 파서의 latest_price 버그와 같은
        # 원인), 여기서 observations를 정렬 안 하고 그대로 series에
        # 넣어서 아래 applied_filters의 "start_period"/"end_period"가
        # 뒤바뀌어 나왔다(2028-Q4가 시작, 2001-Q1이 끝으로 표시). 계산기
        # (calculate_price_forecast_summary)는 내부에서 이미 정렬해 써서
        # 무관했지만, 이 표시용 값은 직접 정렬해야 한다.
        observations = sorted(observations, key=lambda item: item.period)
        periods = [item.period for item in observations]
        series = PriceForecastSeries(
            mineral=MineralRef(
                code=request.mineral,
                name=request.mineral_name or komis_mineral_name or request.mineral,
            ),
            horizon=forecast_horizon,
            available_start_period=periods[0],
            available_end_period=periods[-1],
            price_unit=request.price_unit,
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=periods[-1],
            observations=observations,
            warnings=[],
        )
        calculated = _calculate_or_no_data(request.page_id, calculate_price_forecast_summary, series)
        context = effective_page_context("forecast_price")
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
        response = _build_response(
            request, series, calculated, context,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
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
        )
        if self._llm is None:
            return response
        return self._refine_with_llm(response, calculated.claims)

    # ────────────────────────────────────────────────────────────────
    # 아래 3개 메서드는 komir 자체 추가(2026-08-19, 이식 아님) — §모듈 docstring
    # 4번 참고. `_analyze_composite`와 같은 모양(grade 없는 페이지)을 따른다.
    # ────────────────────────────────────────────────────────────────

    def _analyze_price(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Load a price series and build its validated summary response."""

        if request.mineral is None:
            raise DataSourceError("price analysis requires mineral in the request body")
        parsed = normalize_price_request(request)
        observations = _observations_from_request(PriceObservation, request, raw=parsed.observations)
        if request.start_date:
            observations = [o for o in observations if o.date >= request.start_date]
        if request.end_date:
            observations = [o for o in observations if o.date <= request.end_date]
        if not observations:
            raise DataSourceError("price analysis: 필터 적용 후 observations가 비었다")
        # 2026-08-31 forecast_price와 같은 원인으로 발견·수정 — KOMIS
        # defaultMnrl은 최신순(내림차순)이라, series에 넣기 전에 직접
        # 날짜순 정렬해야 아래 applied_filters/DataQuality의
        # series.observations[0]/[-1]이 실제 시작/끝과 맞는다
        # (calculate_price_summary 내부는 이미 정렬해 써서 계산 자체는
        # 이 버그와 무관했다).
        observations = sorted(observations, key=lambda item: item.date)
        dates = [item.date for item in observations]
        series = PriceSeries(
            page_id=request.page_id,
            mineral=MineralRef(
                code=request.mineral,
                name=parsed.mineral_name,
            ),
            price_criterion_serial=request.price_criterion_serial or 0,
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
            price_unit=parsed.price_unit,
        )
        # 2026-08-26: KOMIS 광물자원가격 "비교광종" 대응(price_* 4종 공통,
        # 2026-08-30 확인) — 원본 응답의 `compareMnrl`에
        # 해당하는 `compare_observations`가 있을 때만 두 번째 PriceSeries를
        # 조립해 비교 근거를 계산한다(§`komir_summary.py::calculate_price_summary`).
        compare_series = None
        if parsed.compare_observations:
            if request.compare_mineral is None:
                raise DataSourceError("price analysis: compare_observations가 있으면 compare_mineral도 필요하다")
            compare_obs = _observations_from_request(
                PriceObservation,
                request,
                raw=parsed.compare_observations,
                field_name="compare_observations",
            )
            compare_dates = sorted(o.date for o in compare_obs)
            compare_series = PriceSeries(
                page_id=request.page_id,
                mineral=MineralRef(
                    code=request.compare_mineral,
                    name=parsed.compare_mineral_name,
                ),
                price_criterion_serial=0,
                available_start_date=compare_dates[0],
                available_end_date=compare_dates[-1],
                source_type="api",
                source_id="api:request",
                data_version=_data_version([o.model_dump(mode="json") for o in compare_obs]),
                data_as_of=compare_dates[-1],
                observations=compare_obs,
                warnings=[],
            )
        komis_period_comparisons = _komis_period_comparisons_from_request(
            request, raw=parsed.komis_period_comparisons
        )
        price_position_settings = get_settings()
        calculated = _calculate_or_no_data(
            request.page_id,
            calculate_price_summary,
            series,
            compare_series=compare_series,
            komis_period_comparisons=komis_period_comparisons,
            srch_avg_opt=request.srch_avg_opt,
            srch_field=request.srch_field,
            srch_start_date=request.srch_start_date,
            srch_end_date=request.srch_end_date,
            price_position_low_pct=price_position_settings.PRICE_POSITION_LOW_PCT,
            price_position_high_pct=price_position_settings.PRICE_POSITION_HIGH_PCT,
        )
        context = effective_page_context(request.page_id)
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "start_date": request.start_date or series.observations[0].date,
            "end_date": request.end_date or series.observations[-1].date,
        }
        # 비철금속(예: "LME CASH")·희소금속(예: "Lithium Carbonate")은 같은
        # 광종이라도 조회조건(가격기준·품목/스펙)이 서로 다를 수 있다 —
        # 요청 바디의 자유 텍스트를 그대로 표시 필터에 실어 보고서에 남긴다
        # (report_render.py가 applied_filters를 보고서 상단에 렌더링한다).
        # 2026-08-30 사용자 지적("LME쪽이 안 보인다") — komis_response 경로가
        # dataAvg.INFO.prcCrtr를 안 채워서 이 줄이 항상 비어 있었다.
        price_criterion = parsed.price_criterion
        if price_criterion:
            applied_filters["price_criterion"] = price_criterion
        if compare_series is not None:
            applied_filters["compare_mineral"] = compare_series.mineral.name
            compare_price_criterion = parsed.compare_price_criterion
            if compare_price_criterion:
                applied_filters["compare_price_criterion"] = compare_price_criterion
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
            "available" if len(series.observations) >= 2 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        # 2026-08-31 사용자 지적 — "평균옵션이 입력으로 들어오는데 타이틀엔
        # '일별'이 하드코딩돼 있다." `KOMIR_PAGE_CONTEXTS`의 정의문 4종은
        # 전부 "...일별 실거래가..." 정적 문자열이라, 실제 조회 단위가
        # 주/월/분기/년이어도 "일별"로 고정 표시되고 있었다. `srch_avg_opt`
        # (명시 입력, 없으면 관측치 날짜 간격 추론)로 판별한 실제 단위로
        # "일별"을 치환한다 — 4개 정의문 전부 "일별"이 "실거래가" 바로
        # 앞에 정확히 1번만 있어 안전하게 치환된다.
        granularity_unit, _ = _detect_granularity(series.observations, srch_avg_opt=request.srch_avg_opt)
        page_definition = context.definition.replace("일별", f"{granularity_unit}별")
        response = _build_response(
            request, series, calculated, context,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            page_definition=page_definition,
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
        )
        # 기본 요약도 전체 기간 → 최근 구간 순서로 읽히도록 정리한다.
        changes = response.summary.major_changes
        by_id = {sentence.evidence_ids[0]: sentence for sentence in changes
                 if len(sentence.evidence_ids) == 1}
        streak, trend = by_id.get("price_streak"), by_id.get("ma_trend")
        if streak is not None and trend is not None and streak.text.endswith("보이고 있습니다."):
            recent = SummarySentence(
                text="최근에는 " + streak.text.removesuffix("보이고 있습니다.")
                     + "보이고 있으며, " + trend.text.removeprefix("최근에는 "),
                evidence_ids=["price_streak", "ma_trend"],
            )
            changes = [sentence for sentence in changes if sentence not in (streak, trend)] + [recent]
        changes = sorted(changes, key=lambda sentence: "period_overall_change" not in sentence.evidence_ids)
        response.summary.major_changes = changes
        # 2026-08-26부터 LLM 정제를 태운다(§모듈 docstring 4번) — 발주처 KOMIS
        # 템플릿 PDF를 근거로 `prompts.py`에 이 3종 전용 지시문·출력계약을
        # 마련했다. forecast_price와 같은 패턴으로 `len(claims) < 5` 같은 최소
        # 근거수 게이트는 두지 않는다 — 이 페이지들의 claim 수는 원래 3~6개뿐이라
        # 그 게이트를 그대로 쓰면 사실상 영구히 규칙기반에 머문다. quality_status
        # 가 "insufficient"(관측치 부족)일 때만 건너뛴다.
        if self._llm is None or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, calculated.claims)

    @staticmethod
    def _trade_series_from_request(
        request: AnalysisSummaryRequest,
        page_id: Literal["map_korea", "map_global"],
    ) -> tuple[TradeMapSeries, dict | None]:
        """`_analyze_domestic_trade`/`_analyze_global_trade` 공통 request→Series 조립.

        2026-08-26: DB(`KO_CSTM_CMMRC`/`KO_UN_CMMRC`) 조회 대신 요청 바디의
        `observations`(TradeCountryObservation 리스트)로 직접 조립한다.

        2026-08-30 신설(사용자 지시로 price의 komis_response 패턴 확장) —
        `getListKoreaData`/`getListDataNation` 원본 응답이 있으면
        observations와 komis_trade_totals(총액 절단 처방, Phase3)를 둘 다
        직접 파싱한다. 반환값에 raw komis_trade_totals dict를 같이 얹어
        호출부가 `_komis_trade_totals_from_request(request, raw=...)`로
        넘길 수 있게 한다.

        2026-08-31 — `mineral`도 이 응답이 조회 파라미터
        (`srchMnrkndUnqCd`)를 그대로 되돌려주므로 komis_response가 있으면
        자동 채운다(호출자 명시값이 있으면 그쪽 우선, price_*는 응답
        본문에 코드가 없어 이 자동채움이 불가능한 것과 대비된다 —
        `PriceSummaryRequest`는 여전히 `mineral` 필수)."""

        raw_observations = request.observations
        raw_komis_trade_totals = None
        komis_mineral = None
        if request.komis_response is not None:
            parser = _parse_komis_map_korea_response if page_id == "map_korea" else _parse_komis_map_global_response
            raw_observations, raw_komis_trade_totals, komis_mineral = parser(request.komis_response)
        mineral = request.mineral or komis_mineral
        if mineral is None:
            raise DataSourceError(f"{page_id} analysis requires mineral in the request body")
        observations = _observations_from_request(TradeCountryObservation, request, raw=raw_observations)
        if request.start_date:
            observations = [o for o in observations if o.date >= request.start_date]
        if request.end_date:
            observations = [o for o in observations if o.date <= request.end_date]
        if not observations:
            raise DataSourceError(f"{page_id} analysis: 필터 적용 후 observations가 비었다")
        dates = sorted(o.date for o in observations)
        series = TradeMapSeries(
            page_id=page_id,
            mineral=MineralRef(code=mineral, name=request.mineral_name or mineral),
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )
        return series, raw_komis_trade_totals

    def _analyze_domestic_trade(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Load a domestic (KO_CSTM_CMMRC) trade-map series and build its response."""

        series, raw_komis_trade_totals = self._trade_series_from_request(request, "map_korea")
        komis_trade_totals = _komis_trade_totals_from_request(request, raw=raw_komis_trade_totals)
        map_korea_filters = _map_korea_query_filters(
            request.komis_response, series.observations, request.mttr_flow_name
        )
        _period_unit, country_filter_name, scope_label = map_korea_filters
        calculated = _calculate_or_no_data(
            request.page_id,
            calculate_domestic_trade_summary,
            series,
            komis_totals=komis_trade_totals,
            country_filter_name=country_filter_name,
            scope_label=scope_label,
        )
        # 2026-09-08 SC-005: 아래에서 다시 계산하지 않고 위 결과를 그대로 넘긴다
        # (같은 request.komis_response·series.observations로 동일한 값이 나온다).
        return self._respond_trade_map(
            request, series, calculated, effective_page_context("map_korea"), map_korea_filters=map_korea_filters
        )

    def _analyze_global_trade(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Load a global (KO_UN_CMMRC) trade-map series and build its response."""

        series, raw_komis_trade_totals = self._trade_series_from_request(request, "map_global")
        komis_trade_totals = _komis_trade_totals_from_request(request, raw=raw_komis_trade_totals)
        top_country_yearly_trend = None
        if request.komis_bar_chart_response is not None:
            top_country_yearly_trend = _parse_komis_map_global_bar_chart_top_country(
                request.komis_bar_chart_response
            )
        route_shares = None
        if request.komis_route_share_response is not None:
            route_shares = _parse_komis_map_global_route_shares(request.komis_route_share_response) or None
        calculated = _calculate_or_no_data(
            request.page_id,
            calculate_global_trade_summary,
            series,
            komis_totals=komis_trade_totals,
            top_country_yearly_trend=top_country_yearly_trend,
            route_shares=route_shares,
        )
        return self._respond_trade_map(request, series, calculated, effective_page_context("map_global"))

    def _analyze_price_group(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """`page_id="price_group"` — PDF §1-2 그룹(비철금속/희소금속) 요약(2026-08-27 신설)."""

        if request.price_group is None:
            raise DataSourceError("price_group analysis requires price_group in the request body")
        observations = _observations_from_request(PriceGroupMineralObservation, request)
        calculated = _calculate_or_no_data(
            request.page_id, calculate_price_group_summary, request.price_group, observations
        )
        context = effective_page_context("price_group")
        group_label = {"base_metals": "비철금속", "minor_metals": "희소금속"}[request.price_group]
        applied_filters = {"price_group": request.price_group}
        data_version = _data_version([o.model_dump(mode="json") for o in observations])
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=MineralRef(code=request.price_group, name=group_label),
            applied_filters=applied_filters,
            defaulted_filters=[],
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type="api",
                id="api:request",
                data_version=data_version,
                as_of="latest",
                file=None,
                sheets=[],
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status="available",
                observation_count=len(observations),
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
        return self._refine_with_llm(response, calculated.claims)

    def _respond_trade_map(
        self,
        request: AnalysisSummaryRequest,
        series: TradeMapSeries,
        calculated: AdditionalCalculatedSummary,
        context: SummaryPageContext,
        map_korea_filters: tuple[str | None, str | None, str | None] | None = None,
    ) -> AnalysisSummaryResponse:
        """`_analyze_domestic_trade`/`_analyze_global_trade` 공통 응답 조립부.

        `map_korea_filters`는 `page_id="map_korea"`일 때 호출부(`_analyze_domestic_
        trade`)가 이미 계산해 둔 `_map_korea_query_filters()` 결과다(2026-09-08
        SC-005: 이전엔 같은 인자로 여기서 다시 계산했다)."""

        dates = sorted({item.date for item in series.observations})
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "start_date": request.start_date or dates[0],
            "end_date": request.end_date or dates[-1],
        }
        if request.page_id == "map_korea":
            # 2026-09-09 발주처 업무지시서 §3.3 대응으로 report_gen
            # 계산기(calculate_domestic_trade_summary)가 이제 수입·수출을
            # 항상 함께 낸다 — `request.trade_direction`이 와도 더 이상
            # 어느 한쪽만 보여준다는 뜻이 아니라서(2026-08-27에 추가했던
            # "조회방향" 표시가 이제 부정확해진다), 그 표시를 뺐다.
            # `trade_direction` 필드 자체는 다른 소비자(streamlit_demo)
            # 호환을 위해 모델에는 남겨뒀다.
            # 2026-08-31 신설 — 조회필터 4종(기간구분·국가·생산품유형/HS)을
            # 보고서 상단 표에도 노출한다(서사 반영은 calculate_domestic_
            # trade_summary가 이미 처리 — 여기는 메타데이터 표시용).
            assert map_korea_filters is not None, "map_korea 응답은 map_korea_filters가 필요하다"
            period_unit, country_filter_name, scope_label = map_korea_filters
            if period_unit:
                applied_filters["period_unit"] = period_unit
            if country_filter_name:
                applied_filters["country_filter"] = country_filter_name
            if scope_label:
                applied_filters["scope_filter"] = scope_label
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
            "available" if len(dates) >= 1 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = _build_response(
            request, series, calculated, context,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_date=series.available_start_date,
                available_end_date=series.available_end_date,
                effective_start_date=dates[0],
                effective_end_date=dates[-1],
                warnings=effective_warnings,
            ),
        )
        # `_analyze_price`와 같은 패턴으로 LLM 정제를 태운다(§주석 참고,
        # 2026-08-26). single_snapshot(관측 1건뿐) claim만 있어도 claim 수 자체는
        # 항상 3개 이상 확보되므로 별도 최소 근거수 게이트는 두지 않는다.
        if self._llm is None or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, calculated.claims)

    def _refine_with_llm(
        self,
        response: AnalysisSummaryResponse,
        claims: list[EvidenceClaim],
    ) -> AnalysisSummaryResponse:
        """Request LLM refinement and accept only evidence-valid output."""

        validation_error = None
        evidence_payload = [
            {
                "evidence_id": claim.id,
                "section": claim.section,
                "fact": claim.fact,
                "required": claim.required,
            }
            for claim in claims
        ]
        # Pass 3 R3-F2: 출력 계약(DB에서 바꿀 수 있음)으로 모든 근거를 정확히 1회씩
        # 담는 게 산술적으로 불가능하면(근거 수 > Σ절 문장 상한 × 문장당 근거 상한)
        # LLM은 어떤 답을 써도 검증에 떨어진다 — 호출 없이 바로 규칙기반으로.
        cfg = resolve_page_config(response.page_id)
        if response.page_id == "map_mineral":
            capacity = (cfg.total_sentence_range or (5, 8))[1] * cfg.max_evidence_ids_per_sentence
            demand = sum(1 for claim in claims if claim.required)
        else:
            capacity = sum(hi for _, hi in cfg.section_sentence_ranges.values()) * cfg.max_evidence_ids_per_sentence
            demand = len(claims)
        if demand > capacity:
            return self._with_warning(
                response,
                f"LLM 분석요약을 건너뛰었다 — 근거 {demand}개를 출력 계약(문장 상한 합 × 문장당 근거 "
                f"{cfg.max_evidence_ids_per_sentence}개 = {capacity})에 담을 수 없다. DB output_contract를 확인할 것.",
            )
        deadline = getattr(self._deadlines, "value", None)
        for _ in range(2):
            if deadline is not None and (deadline - time.monotonic()) < ANALYSIS_LLM_TIMEOUT_SECONDS:
                # R3-F1: 남은 예산이 LLM 호출 1회 상한보다 짧으면 호출하지 않는다 —
                # 클라이언트는 어차피 TIMEOUT을 받고 lock만 예산 너머까지 쥐게 된다.
                return self._with_warning(
                    response,
                    "LLM 분석요약을 건너뛰었다 — 요청 예산 안에 LLM 호출을 마칠 수 없어 규칙 기반 요약을 반환했다.",
                )
            try:
                invocation = self._llm.invoke(
                    task="analysis_summary",
                    instructions=summary_instructions(response.page_id),
                    payload=build_summary_payload(
                        response=response,
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
