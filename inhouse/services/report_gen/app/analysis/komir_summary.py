# -*- coding: utf-8 -*-
"""광물자원가격·국내/글로벌 수급지도 3종의 결정론적(비-LLM) 요약 계산 — komir 자체
추가(2026-08-19, 이식 아님).

`additional_summary.py`(외부repo 무수정 이식본)와 나란히 쓰는 파일이다 — 그 파일은
"원본에서 바뀐 것은 import 경로 1줄뿐"이라고 명시하고 있어, 원본에 없는 이 3종의
계산 로직을 거기에 섞지 않았다. 계산 스타일(`EvidenceClaim`으로 근거를 절에
배정, `AdditionalCalculatedSummary`로 반환)은 그 파일의 `calculate_mineral_map_
summary` 등을 따른다 — 재사용 가능한 헬퍼(`EvidenceClaim`·`SummaryPageContext`·
`AdditionalCalculatedSummary`·`_number`·`_quantity`)는 새로 만들지 않고 그 파일에서
가져다 쓴다.
"""
from __future__ import annotations

import re as _re
from datetime import date as _date, timedelta as _timedelta

from .additional_summary import (
    AdditionalCalculatedSummary,
    EvidenceClaim,
    SummaryPageContext,
    _korean_date,
    _number,
    _quantity,
    _topic,
)


def _subject(name: str) -> str:
    """`_topic()`(은/는)과 같은 받침 규칙의 이/가 버전 — `additional_summary.py`에는
    없어서 komir 자체 파일인 여기 둔다(2026-08-26, KOMIS 실데이터 회귀 테스트
    (/unlazy)에서 "캐나다이"·"호주이" 등 49건 발견 후 추가)."""

    final = name[-1]
    codepoint = ord(final)
    has_batchim = 0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 != 0
    return f"{name}{'이' if has_batchim else '가'}"
from .models import (
    DetectedPattern,
    GeoEventObservation,
    Metric,
    PriceGroupMineralObservation,
    PriceKomisPeriodComparisons,
    PriceSeries,
    TradeKomisTotals,
    TradeMapSeries,
)

# 2026-08-28: `direction`은 실제 `geo_event` 데이터 확인 결과 7개 값의 깨끗한
# 통제 어휘라(`GeoEventObservation` docstring 참고) 라벨링이 안전하다.
_DIRECTION_LABELS = {
    "supply_down": "공급 감소",
    "supply_up": "공급 증가",
    "price_down": "가격 하락",
    "price_up": "가격 상승",
    "demand_down": "수요 감소",
    "demand_up": "수요 증가",
    "neutral": "동향 변화",
}

# 2026-08-28 데이터 품질 확인(`report_gen_구조개선_작업기록_260828_보강.md`
# 참고) — severity>=2.0 표본 7,917건 실측: source가 비어있는(GDELT 원천) 행의
# `evidence_quote`는 84.3%가 실제로는 문장이 아니라 URL 슬러그
# ("trump-says-50-per-cent-tariff-..." 류)였고, 한국어 비율은 KOMIS(3.3%)·
# PPS(0.3%) 두 출처만 예외적으로 높았다(평균 0.895, 나머지는 전부 0.0에
# 수렴). 반대로 이 두 출처 안에서는 한국어 비율이 0.3 밑으로 떨어지는
# 예외가 0건이었다 — source 이름을 하드코딩하는 대신 텍스트 자체의 한글
# 비율로 판별하면 같은 효과를 소스 이름과 무관하게 얻는다(새 한국어 출처가
# 추가돼도 재사용 가능).
_QUOTE_KOREAN_RATIO_THRESHOLD = 0.3
# 슬러그(하이픈으로 이어붙인 영소문자/숫자 토큰 4개 이상, 공백 없음) 방어용
# 2차 체크 — 한글 비율 체크만으로도 실측 표본에서는 전부 걸러졌지만, 어쩌다
# 한글 단어가 슬러그에 섞여 들어오는 경우까지 방어한다.
_SLUG_RE = _re.compile(r"^[a-z0-9]+(-[a-z0-9]+){3,}$")


def _korean_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha() or ("가" <= c <= "힣")]
    if not letters:
        return 0.0
    korean = sum(1 for c in letters if "가" <= c <= "힣")
    return korean / len(letters)


def _quote_passes_quality(quote: str | None) -> bool:
    """`evidence_quote`를 "주요 요인" 절에 보강 문구로 붙여도 되는 품질인지 —
    한글 비율 임계치를 넘고 슬러그 패턴이 아니어야 한다(실측 근거는 위 상수
    주석·`report_gen_구조개선_작업기록_260828_보강.md` 참고)."""

    if not quote or not quote.strip():
        return False
    stripped = quote.strip()
    if _SLUG_RE.match(stripped.lower()):
        return False
    return _korean_ratio(stripped) >= _QUOTE_KOREAN_RATIO_THRESHOLD


# "주요 요인" 절에 인용할 최소 심각도 — 이 밑이면 "주요"라 부르기엔 미미하다고
# 판단해 claim 자체를 만들지 않는다(2026-08-28, 품질 확인에 쓴 표본 임계치와
# 동일하게 맞춤).
_PRICE_DRIVER_MIN_SEVERITY = 2.0
_PRICE_DRIVER_MAX_EVENTS = 2

KOMIR_PAGE_CONTEXTS = {
    # 2026-08-27: 실제 KOMIS 사이트맵 확인 결과 "price" 1개가 서로 다른 서브메뉴
    # 2개(광물자원가격 > 비철금속/희소금속)를 합쳐 다루고 있어 분리했다 — 계산
    # 로직(`calculate_price_summary`)은 두 그룹이 동일해 그대로 공유하고, 페이지
    # 정책(이름·정의·정책버전)만 KOMIS 실제 구분(LME 기준 vs 품목·규격 기준)에
    # 맞춰 따로 둔다.
    "price_base_metals": SummaryPageContext(
        page_id="price_base_metals",
        name="광물자원가격(비철금속)",
        definition="선택한 비철금속(LME 기준)의 일별 실거래가·최저가·최고가 추이를 보여주는 자료다.",
        analysis_constraints=[
            "제공된 가격 계열과 선택 기간만 사용한다.",
            "외부 사건을 가격 변화의 원인으로 추정하지 않는다.",
            "가격 단위·기준이 없으면 절대 수준을 해석하지 않는다.",
        ],
        policy_version="price-base-metals-summary-v1",
    ),
    "price_minor_metals": SummaryPageContext(
        page_id="price_minor_metals",
        name="광물자원가격(희소금속)",
        definition="선택한 희소금속(품목·규격 기준)의 일별 실거래가·최저가·최고가 추이를 보여주는 자료다.",
        analysis_constraints=[
            "제공된 가격 계열과 선택 기간만 사용한다.",
            "외부 사건을 가격 변화의 원인으로 추정하지 않는다.",
            "가격 단위·기준이 없으면 절대 수준을 해석하지 않는다.",
        ],
        policy_version="price-minor-metals-summary-v1",
    ),
    # 2026-08-28: "광물자원가격" 대메뉴의 나머지 실제 서브메뉴 2개 — 이전엔
    # gaps_not_covered_by_report_gen에 미커버로 기록돼 있었다. name/definition은
    # page_recommend registry(price_iron_energy.yaml·price_other.yaml)의
    # routing.summary·keywords를 근거로 썼다(임의 추정 금지).
    "price_iron_energy": SummaryPageContext(
        page_id="price_iron_energy",
        name="광물자원가격(철광석 및 에너지)",
        definition="선택한 철광석·유연탄·우라늄(품목 기준)의 일별 실거래가·최저가·최고가 추이를 보여주는 자료다.",
        analysis_constraints=[
            "제공된 가격 계열과 선택 기간만 사용한다.",
            "외부 사건을 가격 변화의 원인으로 추정하지 않는다.",
            "가격 단위·기준이 없으면 절대 수준을 해석하지 않는다.",
        ],
        policy_version="price-iron-energy-summary-v1",
    ),
    "price_other": SummaryPageContext(
        page_id="price_other",
        name="광물자원가격(기타)",
        definition="선택한 금·은·백금족·흑연(기준시장 기준)의 일별 실거래가·최저가·최고가 추이를 보여주는 자료다.",
        analysis_constraints=[
            "제공된 가격 계열과 선택 기간만 사용한다.",
            "외부 사건을 가격 변화의 원인으로 추정하지 않는다.",
            "가격 단위·기준이 없으면 절대 수준을 해석하지 않는다.",
        ],
        policy_version="price-other-summary-v1",
    ),
    "map_korea": SummaryPageContext(
        page_id="map_korea",
        name="국내 수급지도",
        definition="선택한 광종을 한국이 어느 나라와 수입 또는 수출 거래를 하는지(조회 방향 기준) 국가별 금액·중량으로 보여주는 자료다.",
        analysis_constraints=[
            "관세청 원천에 있는 상대국·기간만 분석한다.",
            "수입/수출 집중도(상위국 비중)를 공급망 리스크로 단정하지 않고 사실만 서술한다.",
        ],
        policy_version="map-korea-summary-v2",
    ),
    "map_global": SummaryPageContext(
        page_id="map_global",
        name="글로벌 수급지도",
        definition=(
            "선택한 광종의 전세계 UN Comtrade 양자무역 기록에서 원산지→도착지 "
            "루트별 규모를 보여주고, 그중 대한민국이 관련된 루트의 순위를 "
            "별도로 표시하는 자료다."
        ),
        analysis_constraints=[
            "한국 기준이 아니라 전세계 보고국 기준 데이터다 — 이 점을 서술에서 흐리지 않는다.",
            "UN Comtrade 원천에 있는 루트(원산국-도착국 쌍)·기간만 분석한다.",
        ],
        policy_version="map-global-summary-v2",
    ),
    "price_group": SummaryPageContext(
        page_id="price_group",
        name="그룹 가격 요약",
        definition="비철금속 또는 희소금속 그룹 전체 광종의 전주·전월 가격 등락을 모아 보여주는 자료다.",
        analysis_constraints=[
            "제공된 광종별 등락률만 사용하고 원자료를 다시 계산하지 않는다.",
            "가격 변동의 원인(수급 이슈, 환율, 지정학 이벤트 등)은 evidence에 없으므로 추정하지 않는다.",
        ],
        policy_version="price-group-summary-v1",
    ),
}

_GROUP_LABELS = {"base_metals": "비철금속", "minor_metals": "희소금속"}


def calculate_price_group_summary(
    group: str, observations: list[PriceGroupMineralObservation]
) -> AdditionalCalculatedSummary:
    """그룹(비철금속/희소금속) 전체 광종의 가격 등락을 요약 — 2026-08-27 신설
    (PDF §1-2 "전체광종(필요시)" 대응, PDF 지침 점검(/unlazy)에서 발견한 gap).

    개별 광종의 raw 가격 계열이 아니라 이미 계산된 광종별 전주·전월 등락률
    (`PriceGroupMineralObservation`)을 입력으로 받아 그룹 평균·최대상승·
    최대하락 광종만 계산한다 — "주요 요인"(가격 변동 원인)은 다른 7종
    페이지와 같은 이유로 계산 근거가 없어 의도적으로 만들지 않는다."""

    if not observations:
        raise ValueError("price group summary requires at least one mineral observation")

    group_label = _GROUP_LABELS.get(group, group)
    avg_week = sum(o.week_change_pct for o in observations) / len(observations)
    month_values = [o.month_change_pct for o in observations if o.month_change_pct is not None]
    avg_month = sum(month_values) / len(month_values) if month_values else None

    def _direction(value: float) -> str:
        return "상승" if value > 0 else "하락" if value < 0 else "보합"

    core_fact = (
        f"{group_label} 가격은 전주 대비 평균 {_number(abs(avg_week))}% {_direction(avg_week)}"
    )
    if avg_month is not None:
        core_fact += f", 전월 대비 평균 {_number(abs(avg_month))}% {_direction(avg_month)}했다."
    else:
        core_fact += "했다."
    claims = [EvidenceClaim("current_state", "core_diagnosis", core_fact, required=True)]
    key_metrics = [_price_metric("avg_week_change_pct", "전주 대비 평균 등락률", avg_week, unit="%")]
    if avg_month is not None:
        key_metrics.append(_price_metric("avg_month_change_pct", "전월 대비 평균 등락률", avg_month, unit="%"))

    risers = sorted((o for o in observations if o.week_change_pct > 0), key=lambda o: -o.week_change_pct)
    decliners = sorted((o for o in observations if o.week_change_pct < 0), key=lambda o: o.week_change_pct)
    flats = [o for o in observations if o.week_change_pct == 0]
    riser_names = "·".join(o.mineral_name for o in risers[:3])
    decliner_pool = decliners if decliners else flats
    decliner_label = "하락세" if decliners else "보합세"
    decliner_names = "·".join(o.mineral_name for o in decliner_pool[:3])
    # 조사(이/가·은/는)는 `_subject()`/`_topic()`으로 받침을 본다 — 2026-08-27
    # skeptic 감사(SC-011)에서 "구리이 전주 대비…"처럼 "이"가 하드코딩돼 있던 것을
    # 고쳤다(다른 페이지는 이미 두 헬퍼를 쓴다).
    if riser_names and decliner_names:
        claims.append(
            EvidenceClaim(
                "group_movers",
                "major_changes",
                f"광종별로는 {_subject(riser_names)} 강세를 보인 반면, {_topic(decliner_names)} {decliner_label}를 기록했다.",
                required=True,
            )
        )
    elif riser_names:
        claims.append(
            EvidenceClaim(
                "group_movers",
                "major_changes",
                f"광종별로는 {_subject(riser_names)} 강세를 보였다.",
                required=True,
            )
        )
    elif decliner_names:
        claims.append(
            EvidenceClaim(
                "group_movers",
                "major_changes",
                f"광종별로는 {_subject(decliner_names)} {decliner_label}를 기록했다.",
                required=True,
            )
        )

    if risers and decliners:
        top_riser, top_decliner = risers[0], decliners[0]
        extreme_fact = (
            f"{_subject(top_riser.mineral_name)} 전주 대비 {_number(top_riser.week_change_pct)}%로 "
            f"가장 높은 상승 폭을 나타냈고, {_subject(top_decliner.mineral_name)} "
            f"{_number(abs(top_decliner.week_change_pct))}% 내리며 가장 큰 낙폭을 보였다."
        )
        claims.append(EvidenceClaim("extreme_movers", "major_changes", extreme_fact))
    elif risers:
        top_riser = risers[0]
        claims.append(
            EvidenceClaim(
                "extreme_movers",
                "major_changes",
                f"{_subject(top_riser.mineral_name)} 전주 대비 {_number(top_riser.week_change_pct)}%로 가장 높은 상승 폭을 나타냈다.",
            )
        )
    elif decliners:
        top_decliner = decliners[0]
        claims.append(
            EvidenceClaim(
                "extreme_movers",
                "major_changes",
                f"{_subject(top_decliner.mineral_name)} {_number(abs(top_decliner.week_change_pct))}% 내리며 가장 큰 낙폭을 보였다.",
            )
        )

    claims.append(
        EvidenceClaim(
            "group_composition",
            "current_position",
            f"조회된 {len(observations)}개 광종 중 상승 {len(risers)}개, "
            f"하락 {len(decliners)}개, 보합 {len(flats)}개다.",
            required=True,
        )
    )
    key_metrics.append(_price_metric("riser_count", "상승 광종 수", len(risers)))
    key_metrics.append(_price_metric("decliner_count", "하락 광종 수", len(decliners)))

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=key_metrics,
        patterns=[],
        omitted=[],
        warnings=[],
    )


def calculate_price_summary(
    series: PriceSeries,
    *,
    compare_series: PriceSeries | None = None,
    geo_events: list[GeoEventObservation] | None = None,
    komis_period_comparisons: PriceKomisPeriodComparisons | None = None,
) -> AdditionalCalculatedSummary:
    """Calculate deterministic evidence and metrics for a price series.

    `compare_series`(2026-08-26 신설) — KOMIS 희소금속 페이지의 "비교광종"
    기능 대응. 원본 KOMIS 응답은 기본 계열이 `data.defaultMnrl`, 비교 계열이
    `data.compareMnrl` 키 아래 같은 레코드 shape으로 온다(사용자 확인,
    2026-08-26) — 이 서버는 DB를 거치지 않으므로 그 두 계열을 요청 바디의
    `observations`(=defaultMnrl 상당)·`compare_observations`(=compareMnrl
    상당)로 그대로 받는다. 비교광종이 있을 때만 `current_position`에 두
    계열의 조회기간 전체 변화율을 나란히 비교하는 근거 1건을 추가한다 —
    날짜가 정확히 일치하지 않을 수 있어 일별 대비가 아니라 "첫 관측 대비
    마지막 관측" 전체 변화율로 비교한다(둘 다 항상 계산 가능).

    `geo_events`(2026-08-28 신설) — PDF §1-1 "가격 변동의 주요 요인" 대응.
    `_PRICE_DRIVER_MIN_SEVERITY` 이상인 이벤트 중 severity 상위
    `_PRICE_DRIVER_MAX_EVENTS`건(main-agent 결정: 품질이 아니라 severity만으로
    선택 — "가장 심각한 이벤트"라는 의미를 지키기 위해)을 골라 `major_changes`에
    근거를 추가한다. 문장은 `direction`(클린 통제 어휘)만으로 항상 만들 수
    있는 결정론적 한국어 템플릿이 기본이고, `evidence_quote`는 `_quote_passes_
    quality()`를 통과할 때만 보강 문구로 덧붙인다(원 데이터의 84%가 URL
    슬러그라 그대로 인용하면 안 됨 — `report_gen_구조개선_작업기록_260828_
    보강.md` 참고).

    `komis_period_comparisons`(2026-08-28 추가조사 확정) — 있으면 전주/전월/
    전년평균 대비 근거를 이 계산기의 롤링창 재계산 대신 KOMIS 제공값으로
    만든다(라이브 재현으로 산식이 다름을 확정, `report_gen_price_base_metals_
    부실요약_원인조사_260828.md` 참고). 문장 템플릿은 자체 계산 경로와
    완전히 동일해 prompts.py 지침은 그대로 쓴다."""

    observations = sorted(series.observations, key=lambda item: item.date)
    latest = observations[-1]
    if latest.commerce_price is None:
        raise ValueError("price summary requires the latest observation to have commerce_price")

    def _avg_before(days: int) -> tuple[float, tuple[str, ...]] | None:
        """`days`일 이내 이전 관측치의 평균과, 그 계산에 실제로 쓰인 관측일
        목록을 함께 돌려준다 — 목록은 관측치가 희소해 여러 기간(전주·전월·전년)이
        같은 관측치로 수렴하는지 판별하는 데 쓴다(2026-08-28 감사 P2)."""

        cutoff = _shift_date(latest.date, -days)
        window = [
            item
            for item in observations[:-1]
            if item.commerce_price is not None and item.date >= cutoff
        ]
        if not window:
            return None
        avg = sum(item.commerce_price for item in window) / len(window)
        return avg, tuple(item.date for item in window)

    claims = [
        EvidenceClaim(
            # id는 "current_state" — 다른 7종 페이지(indicator_market 등)가 전부
            # core_diagnosis의 첫 근거를 이 id로 고정하고, `summary.py::
            # _validate_llm_summary`도 "current_state가 core_diagnosis에 있어야
            # 한다"를 페이지 무관 공통 규칙으로 검사한다(2026-08-26 LLM 배선
            # 전에는 이 규칙을 이 페이지가 안 태워서 안 드러났던 불일치 — 배선하며
            # "latest_price"였던 걸 맞춰 고쳤다. Metric id "latest_price"는
            # 별개 네임스페이스라 그대로 둔다).
            "current_state",
            "core_diagnosis",
            # 일자는 한글 표기(2026-08-27 반복 루프 1회차: LLM이 근거의 "2026-08-24"
            # 원형을 그대로 베껴 지침 "YYYY년 M월 D일" 위반 8건 — 근거부터 한글로).
            f"{_korean_date(latest.date)} 기준 {series.mineral.name} 실거래가는 {_number(latest.commerce_price)}이다.",
            required=True,
        )
    ]
    key_metrics = [_price_metric("latest_price", "최신 가격", latest.commerce_price)]

    if len(observations) >= 2 and observations[-2].commerce_price is not None:
        prior = observations[-2].commerce_price
        prior_date = observations[-2].date
        change = _pct(latest.commerce_price, prior)
        if change is not None:
            # 2026-08-26 KOMIS 실데이터 회귀 테스트(/unlazy, "하나하나 체크")에서
            # 발견: 요청 바디의 observations가 항상 진짜 일별 간격이라는 보장이
            # 없다(예: KOMIS 평균옵션=WEEK로 조회한 데이터를 그대로 넣으면 각
            # observation이 실제로는 7일 간격인데도 "전일(그 날짜) 대비"라고
            # 표현해 오해를 준다 — 라이브 테스트로 실제 재현: "전일(2012-12-24)
            # 대비"인데 기준일은 2012-12-31). 직전 관측치와 정확히 하루
            # 차이일 때만 "전일"이라 하고, 아니면 지표 페이지(_calculate_
            # summary)와 같은 관용구인 "직전 관측치 대비"로 표현한다.
            is_truly_next_day = prior_date == _shift_date(latest.date, -1)
            comparison_label = (
                f"전일({_korean_date(prior_date)})" if is_truly_next_day else f"직전 관측치({_korean_date(prior_date)})"
            )
            claims.append(
                EvidenceClaim(
                    "day_over_day",
                    "major_changes",
                    f"{comparison_label} 대비 {_signed_pct(change)} 변동했다.",
                    required=True,
                )
            )
            metric_label = "전일대비" if is_truly_next_day else "직전관측치대비"
            key_metrics.append(_price_metric("day_over_day_change_pct", metric_label, change * 100, unit="%"))

    # 2026-08-28 감사(P2)에서 발견: 관측치가 희소하면 전주·전월·전년 창이 전부
    # 같은 단일 이전 관측치로 수렴하는데, 이를 별개로 계산된 통계인 것처럼
    # 문장·지표를 반복 인용하면 부자연스럽다 — 이미 같은 관측일 집합으로 인용한
    # 기간이 있으면 건너뛴다(가장 짧은 기간의 라벨만 남긴다, "week_avg/month_avg/
    # year_avg 중 evidence에 있는 항목만 골라 쓴다"는 prompts.py 지시와 호환).
    # 2026-08-28 추가조사 확정 — `komis_period_comparisons`에 해당 기간이 있으면
    # 그 값을 그대로 쓰고 롤링창 재계산(`_avg_before`)·희소관측 dedup은 건너뛴다
    # (KOMIS 제공값은 매번 독립적으로 서버가 계산한 값이라 우리 관측 윈도우가
    # 겹치는지 여부와 무관하다 — dedup은 자체 계산 폴백 경로에만 의미가 있다).
    _KOMIS_PERIOD_FIELD = {"week_avg": "week", "month_avg": "month", "year_avg": "year"}
    _avg_windows_seen: set[tuple[str, ...]] = set()
    for days, label, metric_id in ((7, "전주평균", "week_avg"), (30, "전월평균", "month_avg"), (365, "전년평균", "year_avg")):
        komis_avg = getattr(komis_period_comparisons, _KOMIS_PERIOD_FIELD[metric_id], None) if komis_period_comparisons else None
        if komis_avg is not None:
            change = komis_avg.change_pct / 100
            claims.append(
                EvidenceClaim(
                    metric_id,
                    "major_changes",
                    f"{label}({_number(komis_avg.average_price)}) 대비 {_signed_pct(change)} 수준이다.",
                )
            )
            key_metrics.append(_price_metric(f"{metric_id}_change_pct", f"{label}대비", change * 100, unit="%"))
            continue
        result = _avg_before(days)
        if result is None:
            continue
        avg, window_dates = result
        if window_dates in _avg_windows_seen:
            continue
        _avg_windows_seen.add(window_dates)
        change = _pct(latest.commerce_price, avg)
        if change is None:
            continue
        claims.append(
            EvidenceClaim(
                metric_id,
                "major_changes",
                f"{label}({_number(avg)}) 대비 {_signed_pct(change)} 수준이다.",
            )
        )
        key_metrics.append(_price_metric(f"{metric_id}_change_pct", f"{label}대비", change * 100, unit="%"))

    # 2026-08-27: PDF 지침 점검(/unlazy)에서 발견한 gap 수정 — PDF는 "[기간]
    # 연속 [상승세/하락세/보합세]"를 요구하는데, day_over_day는 직전 관측
    # 1건과의 비교만 하고 연속기간 자체는 계산하지 않았다. 순수하게 관측치
    # 방향(오름/내림/보합)만으로 계산 가능해 indicator 페이지의 grade_streak
    # 패턴을 가격 계열에 맞게 적용한다("원인" 추정과 달리 시계열만으로 계산
    # 가능한 통계라 이전 "주요 요인 미구현" 갭과는 성격이 다르다).
    directions: list[str | None] = []
    for prev, cur in zip(observations, observations[1:]):
        if prev.commerce_price is None or cur.commerce_price is None:
            directions.append(None)
            continue
        diff = cur.commerce_price - prev.commerce_price
        directions.append("up" if diff > 0 else "down" if diff < 0 else "flat")
    if directions and directions[-1] is not None:
        latest_direction = directions[-1]
        streak = 1
        for direction in reversed(directions[:-1]):
            if direction != latest_direction:
                break
            streak += 1
        if streak >= 2:
            streak_start = observations[-streak - 1]
            gap_days = (
                _date.fromisoformat(latest.date) - _date.fromisoformat(streak_start.date)
            ).days / streak
            if gap_days <= 3:
                unit = "일"
            elif gap_days <= 10:
                unit = "주"
            else:
                unit = "개월"
            trend_label = {"up": "상승세", "down": "하락세", "flat": "보합세"}[latest_direction]
            claims.append(
                EvidenceClaim(
                    "price_streak",
                    "major_changes",
                    f"{streak}{unit} 연속 {trend_label}를 보이고 있다.",
                )
            )
            key_metrics.append(_price_metric("price_streak_length", "연속 추세 기간", streak, unit=unit))

    if geo_events:
        # `SummaryNarrative.major_changes`는 절 전체(모델 하드 제약, models.py)가
        # 최대 5문장이고, 규칙기반 폴백 경로(`_deterministic_narrative`)는 근거
        # 1개=문장 1개로 그대로 옮기므로 이미 day_over_day·week/month/year평균·
        # price_streak만으로 5개에 닿을 수 있다(관측치가 창마다 달라지는
        # 경우) — 새 근거를 무조건 추가하면 그 경로가 `ValidationError`로
        # 죽는다(2026-08-28 실측 재현). 남은 자리만큼만 추가해 절대 넘지 않는다.
        _MAJOR_CHANGES_HARD_CAP = 5
        room = _MAJOR_CHANGES_HARD_CAP - sum(1 for claim in claims if claim.section == "major_changes")
        selected = sorted(
            (event for event in geo_events if event.severity >= _PRICE_DRIVER_MIN_SEVERITY),
            key=lambda event: event.severity,
            reverse=True,
        )[: max(0, min(_PRICE_DRIVER_MAX_EVENTS, room))]
        for index, event in enumerate(selected, start=1):
            direction_label = _DIRECTION_LABELS.get(event.direction, "동향 변화")
            fact = (
                f"조회기간 중 {event.country}에서 {direction_label} 흐름과 맞물린 "
                f"사안이 있었다({_korean_date(event.obs_date)} 기준)."
            )
            if _quote_passes_quality(event.evidence_quote):
                quote = event.evidence_quote.strip()
                # SummarySentence.text 상한(300자) 안에 안전하게 들어가도록
                # 보강 문구 길이를 제한한다(템플릿 문장 자체가 이미 40~60자).
                if len(quote) > 200:
                    quote = quote[:200].rstrip() + "…"
                fact = f"{fact} 관련 보도: {quote}"
            claims.append(
                EvidenceClaim(
                    f"price_driver_event_{index}",
                    "major_changes",
                    fact,
                    required=True,
                )
            )

    if not any(claim.section == "major_changes" for claim in claims):
        # `SummaryNarrative`는 3개 절 전부 최소 1개 근거를 요구한다(models.py) —
        # 비교 가능한 이전 관측이 없는 경우(관측 1건뿐 등)를 대비한 폴백.
        claims.append(
            EvidenceClaim(
                "no_comparable_period",
                "major_changes",
                "비교 가능한 이전 가격이 없어 등락률은 계산하지 않았다.",
            )
        )

    # 2026-08-29 main-agent 처방(라이브 재검증 260828에서 발견한 period_range
    # 버그) — KOMIS는 최근 구간의 hghstPrc/lowstPrc를 0.00(미제공)으로 보낼 때가
    # 있는데, 예전엔 그 관측치들을 그냥 걸러내고 남은(대개 옛 구간) highest_price/
    # lowest_price만으로 범위를 계산해 "최고가가 현재가보다 낮다" 같은 모순이
    # 나왔다. 이제 관측치 전체(실거래가가 있는 것 기준)에 최고·최저가가 빠짐없이
    # 있을 때만 그 값을 쓰고, 하나라도 빠지면(커버리지 불완전) 요청받은
    # commerce_price 전체 범위로 폴백한다 — 일부 날짜만 반영한 왜곡된 범위 대신
    # 항상 우리가 가진 데이터 전체 기준의 정직한 답을 낸다.
    #
    # 2026-08-30 후속 버그 수정 — 위 처방은 `is not None`만 확인해 KOMIS가
    # "미제공"을 채우는 문자열 "0.00"(파싱하면 float 0.0, None이 아님)을 정상
    # 데이터로 오인했다. 실거래로 KOMIS 원본을 그대로(값 변환만 하고 0.00은
    # 안 거르고) 보내면 "최고 0.00, 최저 0.00"이 나오거나(전부 0.00일 때),
    # 조회기간 일부만 0.00이어도 그 관측치가 `min()`을 오염시켜 최저가만
    # 조용히 0.00으로 깨졌다(최고가는 0.00이 max를 못 이기니 안 깨져서 더
    # 눈치채기 어려움) — `inventory`가 이미 쓰는 값 기반 게이트(0/0.0도
    # 결측 취급)를 여기도 동일 적용한다.
    observations_with_price = [item for item in observations if item.commerce_price is not None]
    has_full_hilo_coverage = bool(observations_with_price) and all(
        item.highest_price not in (None, 0, 0.0) and item.lowest_price not in (None, 0, 0.0)
        for item in observations_with_price
    )
    patterns: list[DetectedPattern] = []
    period_high = period_low = None
    if has_full_hilo_coverage:
        period_high = max(item.highest_price for item in observations_with_price)
        period_low = min(item.lowest_price for item in observations_with_price)
        range_fact = f"조회기간 중 최고 {_number(period_high)}, 최저 {_number(period_low)}였다."
    elif observations_with_price:
        period_high = max(item.commerce_price for item in observations_with_price)
        period_low = min(item.commerce_price for item in observations_with_price)
        # 최고가·최저가(hghst/lowst) 원천이 불완전해 실거래가 기준으로 대신
        # 계산했음을 문구로 구분한다 — "KOMIS 공식 최고/최저"인 것처럼 단정하지
        # 않는다(main-agent 지시).
        range_fact = f"조회기간 관측치(실거래가) 기준 최고 {_number(period_high)}, 최저 {_number(period_low)}였다."
    if period_high is not None and period_low is not None:
        claims.append(
            EvidenceClaim(
                "period_range",
                "current_position",
                range_fact,
            )
        )
        if period_high > period_low and latest.commerce_price is not None:
            position = (latest.commerce_price - period_low) / (period_high - period_low)
            if position >= 0.9:
                patterns.append(
                    DetectedPattern(
                        code="near_period_high",
                        label="조회기간 고점 근접",
                        evidence=["period_range", "current_state"],
                    )
                )
            elif position <= 0.1:
                patterns.append(
                    DetectedPattern(
                        code="near_period_low",
                        label="조회기간 저점 근접",
                        evidence=["period_range", "current_state"],
                    )
                )
    else:
        claims.append(
            EvidenceClaim(
                "no_price_range",
                "current_position",
                "최고가·최저가 정보가 없어 조회기간 범위는 계산하지 않았다.",
            )
        )

    # 2026-08-28 추가조사(`report_gen_price_base_metals_부실요약_원인조사_260828.md`)
    # 확정 — LME 재고량(`PriceObservation.inventory`)이 관측치에 담겨 있어도
    # 계산기가 전혀 안 읽던 구조적 공백을 메운다. 직전 관측치(`observations[-2]`)가
    # 아니라 "latest 이전 중 inventory가 있는 가장 최근 관측"을 찾는다 — 재고량은
    # 가격과 달리 결측일 수 있어 바로 앞 관측치에 없을 수 있다(라이브 재현으로
    # invtPrcnt 산식이 이 방식의 일별 등락률과 소수점까지 정확히 일치함을 확인,
    # 672/672 표본). "LME"·"톤" 같은 단위·거래소를 문장에 하드코딩하지 않는다 —
    # 이 계산기는 다른 가격 지표(day_over_day 등)에서도 단위를 안 쓴다(prompts.py
    # 지침·PDF 원문 어디에도 단위 표기가 없는 것과 같은 관행).
    #
    # 2026-08-29 Phase2 라이브 재검증에서 발견·main-agent 승인 — KOMIS는 전통 LME
    # 6대 비철금속(니켈·동·아연·알루미늄·연·주석) 외 광종은 `invt`(재고량)를 매
    # 관측일 "0.00"으로 채워 보낸다(값이 없을 때 0.00을 채우는 KOMIS 전역 관행 —
    # 16개 광종/가격기준 콤보 전수로 확인. `lowest_price`/`highest_price`는 이
    # 커밋 당시 같은 패턴이라고 여기 적었지만 실제로는 안 그랬다 — 2026-08-30
    # 사용자 실측 재현으로 발견해 위 `has_full_hilo_coverage` 쪽에도 동일하게
    # 값 기반 게이트를 뒤늦게 적용했다). 0을 실측값으로 취급하면
    # "재고량은 0.00이다"라는 사실상 거짓 문장이 나가므로(가돌리늄 표본에서
    # 실제 발생 확인) `inventory`가 0이면 latest든 prior 탐색이든 결측(None)과
    # 동일하게 취급한다. 페이지 하드코딩(`page_id == "price_base_metals"`) 대신
    # 값 기반 게이트를 쓴다 — 지금은 관측 사실이지 코드 계약이 아니라, KOMIS가
    # 다른 광종에도 재고량을 채우기 시작하면 코드 수정 없이 자동 반영된다.
    latest_inventory = latest.inventory if latest.inventory not in (None, 0, 0.0) else None
    if latest_inventory is not None:
        current_position_count = sum(1 for claim in claims if claim.section == "current_position")
        if current_position_count < 3:  # SummaryNarrative.current_position 하드 제약(models.py)
            prior_inventory_obs = next(
                (
                    item
                    for item in reversed(observations[:-1])
                    if item.inventory not in (None, 0, 0.0)
                ),
                None,
            )
            inventory_fact = f"{_korean_date(latest.date)} 기준 재고량은 {_number(latest_inventory)}이다."
            inventory_change_pct = None
            if prior_inventory_obs is not None:
                inv_change = _pct(latest_inventory, prior_inventory_obs.inventory)
                if inv_change is not None:
                    is_truly_next_day = prior_inventory_obs.date == _shift_date(latest.date, -1)
                    inv_comparison_label = (
                        f"전일({_korean_date(prior_inventory_obs.date)})"
                        if is_truly_next_day
                        else f"직전 관측치({_korean_date(prior_inventory_obs.date)})"
                    )
                    inventory_fact = f"{inventory_fact} {inv_comparison_label} 대비 {_signed_pct(inv_change)} 변동했다."
                    inventory_change_pct = inv_change * 100
            claims.append(EvidenceClaim("inventory_level", "current_position", inventory_fact))
            key_metrics.append(_price_metric("inventory_level", "재고량", latest_inventory))
            if inventory_change_pct is not None:
                key_metrics.append(_price_metric("inventory_change_pct", "재고량 등락률", inventory_change_pct, unit="%"))

    if compare_series is not None:
        compare_observations = sorted(compare_series.observations, key=lambda item: item.date)
        primary_first, primary_last = observations[0], observations[-1]
        compare_first, compare_last = compare_observations[0], compare_observations[-1]
        primary_overall = _pct(primary_last.commerce_price, primary_first.commerce_price)
        compare_overall = _pct(compare_last.commerce_price, compare_first.commerce_price)
        if primary_overall is not None and compare_overall is not None:
            claims.append(
                EvidenceClaim(
                    "compare_overall_change",
                    "current_position",
                    f"같은 조회기간 동안 {_topic(compare_series.mineral.name)} "
                    f"{_signed_pct(compare_overall)} 변동한 반면, {_topic(series.mineral.name)} "
                    f"{_signed_pct(primary_overall)} 변동했다.",
                )
            )
            key_metrics.append(
                _price_metric(
                    "compare_overall_change_pct",
                    f"{compare_series.mineral.name} 대비 조회기간 변화율차",
                    (primary_overall - compare_overall) * 100,
                    unit="%p",
                )
            )
        else:
            claims.append(
                EvidenceClaim(
                    "compare_no_overall_change",
                    "current_position",
                    f"{compare_series.mineral.name}과의 비교는 두 계열 모두 관측치가 "
                    "2건 이상이어야 계산할 수 있어 이번에는 계산하지 않았다.",
                )
            )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=key_metrics,
        patterns=patterns,
        omitted=[],
        warnings=[],
    )


def calculate_domestic_trade_summary(
    series: TradeMapSeries, *, direction: str = "import", komis_totals: TradeKomisTotals | None = None
) -> AdditionalCalculatedSummary:
    """국내(관세청) 수급지도 계열 계산 — `direction`으로 수입/수출을 고른다.

    2026-08-27: PDF 지침 점검(/unlazy)에서 발견한 버그 수정 — 이전에는
    `direction_label="수입"`이 하드코딩돼 있어 KOMIS 화면에서 수출 방향으로
    조회해도 보고서는 항상 "수입총액"으로 렌더링됐다(실측: 수출 73건 중
    "수출총액" 문구 0건). 이제 `direction`에 따라 읽는 금액 필드
    (`import_amount`/`export_amount`)와 라벨("수입"/"수출") 둘 다 바뀐다.

    `komis_totals`(2026-08-29 Phase3 라이브 재검증 확정) — KOMIS `list`
    응답이 최대 30행까지만 국가를 주는데(정적덤프 145콤보 전수 재검증
    결과 9건이 영향, 최악 5.8% 과소) 같은 응답에 진짜 총액(`sumIncmAmt`/
    `sumExpAmt`)이 함께 온다. 있으면 관측치 합산 대신 이 값을 최신 관측일의
    총액으로 쓴다 — top1/3/5 비중의 분모가 정확해진다. `previous_total`
    (기간변화율 비교 대상)은 과거 시점 KOMIS 총액을 받을 방법이 없어
    여전히 관측치 합산이다(하위호환, `report_gen_KOMIS라이브재검증_
    Phase3_260829.md` §1 참고)."""

    direction_label = "수입" if direction == "import" else "수출"
    amount_field = "import_amount" if direction == "import" else "export_amount"

    def _amount(item) -> float:
        return getattr(item, amount_field) or 0.0

    dates = sorted({item.date for item in series.observations})
    latest_date = dates[-1]
    latest_rows = [item for item in series.observations if item.date == latest_date]
    ranking = sorted(latest_rows, key=_amount, reverse=True)
    komis_total = getattr(komis_totals, amount_field, None) if komis_totals else None
    total = komis_total if komis_total not in (None, 0, 0.0) else sum(_amount(item) for item in ranking)
    if total <= 0 or len(ranking) < 1:
        raise ValueError("trade map summary requires a positive total amount")

    claims = [
        EvidenceClaim(
            "current_state",
            "core_diagnosis",
            f"{_korean_date(latest_date)} 기준 {series.mineral.name} {direction_label}총액은 {_quantity(total)}(단위 미상)이다.",
            required=True,
        )
    ]
    key_metrics = [_price_metric("total_amount", f"{direction_label}총액", total)]

    top_n = ranking[: min(3, len(ranking))]
    if top_n:
        top1 = top_n[0]
        top1_share = _amount(top1) / total
        claims.append(
            EvidenceClaim(
                "top1_country",
                "major_changes",
                f"{_subject(top1.country_name)} {_quantity(_amount(top1))}({_number(top1_share * 100)}%)로 "
                f"1위 {direction_label}국이다.",
                required=True,
            )
        )
        key_metrics.append(_price_metric("top1_share_pct", f"1위국 {direction_label}비중", top1_share * 100, unit="%"))
    if len(top_n) >= 3:
        cr3 = sum(_amount(item) for item in top_n) / total
        names = "·".join(item.country_name for item in top_n)
        claims.append(
            EvidenceClaim(
                "top3_concentration",
                "major_changes",
                f"상위 3개국({names})이 전체의 {_number(cr3 * 100)}%를 차지한다.",
                required=True,
            )
        )
        key_metrics.append(_price_metric("top3_share_pct", f"상위3국 {direction_label}비중", cr3 * 100, unit="%"))
    top5_n = ranking[: min(5, len(ranking))]
    if len(top5_n) >= 5:
        cr5 = sum(_amount(item) for item in top5_n) / total
        claims.append(
            EvidenceClaim(
                "top5_concentration",
                "major_changes",
                f"상위 5개국까지 합산하면 전체의 {_number(cr5 * 100)}%를 차지한다.",
            )
        )
        key_metrics.append(_price_metric("top5_share_pct", f"상위5국 {direction_label}비중", cr5 * 100, unit="%"))

    patterns: list[DetectedPattern] = []
    if top_n and _amount(top_n[0]) / total >= 0.5:
        patterns.append(
            DetectedPattern(
                code="single_country_concentration",
                label=f"1개국 {direction_label} 과반 집중",
                evidence=["top1_country"],
            )
        )

    if len(dates) >= 2:
        previous_date = dates[-2]
        previous_total = sum(
            _amount(item) for item in series.observations if item.date == previous_date
        )
        change = _pct(total, previous_total)
        if change is not None:
            claims.append(
                EvidenceClaim(
                    "period_total_change",
                    "current_position",
                    f"직전 관측일({_korean_date(previous_date)}) 대비 {direction_label}총액이 {_signed_pct(change)} 변동했다.",
                )
            )
            key_metrics.append(
                _price_metric("period_total_change_pct", f"직전 대비 {direction_label}총액 변동", change * 100, unit="%")
            )
    else:
        claims.append(
            EvidenceClaim(
                "single_snapshot",
                "current_position",
                "조회기간에 관측일이 1건뿐이라 기간별 변화는 계산하지 않았다.",
            )
        )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=key_metrics,
        patterns=patterns,
        omitted=[],
        warnings=[],
    )


_KOREA_NAMES = {"대한민국", "한국", "Korea", "Korea, Rep.", "South Korea"}
_KOREA_CODES = {"KR", "KOR"}


def _is_korea(code: str | None, name: str | None) -> bool:
    return (code is not None and code.upper() in _KOREA_CODES) or (name in _KOREA_NAMES)


def calculate_global_trade_summary(
    series: TradeMapSeries, *, komis_totals: TradeKomisTotals | None = None
) -> AdditionalCalculatedSummary:
    """글로벌(UN Comtrade) 수급지도 계열 계산 — 원산지→도착지 양자무역 "루트"
    랭킹 + 대한민국 자체 순위 하이라이트.

    2026-08-27: PDF 지침 점검(/unlazy)에서 발견한 gap 수정 — 이전에는
    원산국(수출국)별로 도착지를 뭉개고 집계해 "국가별 총 공급액" 랭킹만
    만들었다. PDF §2(UN Comtrade)는 "미국→독일" 같은 양자 루트 랭킹과
    "대한민국은 세부현황 기준 6위(말레이시아行)...9위(일본行)" 같은 한국
    자체 순위 하이라이트를 요구한다 — 실측 확인(Playwright로 원본
    `getListDataNation` 응답을 직접 조회)했더니 KOMIS 응답 자체에
    `incmNtnNm`(도착국)·`expNtnNm`(원산국) 필드가 이미 함께 온다는 걸
    확인했다(2026-08-27). `TradeCountryObservation.origin_country_*`가 그
    원산국을 담는다 — 이 필드가 없는 관측치(과거 map_korea 스타일 단일축
    데이터)는 이 함수에 넣지 않는다(map_global 전용 어댑터가 채워야 한다).

    `komis_totals`(2026-08-29 Phase3 라이브 재검증 확정) — `getListDataNation`
    응답이 최대 30개 루트까지만 주는데, 정적덤프 73콤보 중 **72건(99%)**이
    영향받고 중앙값 30.6%·최악 69.4% 과소였다(map_korea보다 훨씬 심각 —
    `report_gen_KOMIS라이브재검증_Phase3_260829.md` §1 참고). 같은 응답의
    `sumAmt`가 KOMIS 진짜 총액이다 — 있으면 관측치 합산 대신 이 값을 쓴다.
    `import_amount` 필드를 재사용한다(map_global은 KOMIS가 사실상 수입
    방향만 제공 — 기존 코드도 `item.import_amount`만 읽는다)."""

    dates = sorted({item.date for item in series.observations})
    latest_date = dates[-1]
    latest_rows = [item for item in series.observations if item.date == latest_date]
    ranking = sorted(latest_rows, key=lambda item: item.import_amount or 0.0, reverse=True)
    komis_total = komis_totals.import_amount if komis_totals else None
    total = komis_total if komis_total not in (None, 0, 0.0) else sum(item.import_amount or 0.0 for item in ranking)
    if total <= 0 or len(ranking) < 1:
        raise ValueError("global trade map summary requires a positive total amount")

    def _route_label(item) -> str:
        origin = item.origin_country_name or "출처미상"
        dest = item.country_name
        return f"{origin}→{dest}"

    claims = [
        EvidenceClaim(
            "current_state",
            "core_diagnosis",
            f"{_korean_date(latest_date)} 기준 {series.mineral.name} 세계 교역 총액은 {_quantity(total)}(단위 미상)이다.",
            required=True,
        )
    ]
    key_metrics = [_price_metric("total_amount", "세계 교역 총액", total)]

    top_n = ranking[: min(3, len(ranking))]
    if top_n:
        parts = []
        for rank, item in enumerate(top_n, start=1):
            share = (item.import_amount or 0.0) / total * 100
            # 화살표 표기 뒤엔 '루트'를 붙이고 조사를 쓴다("중국→대한민국로" 같은 조사 오류
            # 방지 — 2026-08-27 반복 루프 3회차, LLM 프롬프트와 같은 규칙).
            parts.append(f"{rank}위는 {_route_label(item)} 루트로 {_quantity(item.import_amount or 0.0)}({_number(share)}%)")
        claims.append(
            EvidenceClaim(
                "top1_country",
                "major_changes",
                "글로벌 교역 규모 " + ", ".join(parts) + "를 기록했다.",
                required=True,
            )
        )
        top1_share = (top_n[0].import_amount or 0.0) / total
        key_metrics.append(_price_metric("top1_share_pct", "1위 루트 비중", top1_share * 100, unit="%"))
    if len(top_n) >= 3:
        cr3 = sum(item.import_amount or 0.0 for item in top_n) / total
        claims.append(
            EvidenceClaim(
                "top3_concentration",
                "major_changes",
                f"상위 3개 루트의 합산 점유율은 {_number(cr3 * 100)}%다.",
                required=True,
            )
        )
        key_metrics.append(_price_metric("top3_share_pct", "상위3루트 비중", cr3 * 100, unit="%"))
    top5_n = ranking[: min(5, len(ranking))]
    if len(top5_n) >= 5:
        cr5 = sum(item.import_amount or 0.0 for item in top5_n) / total
        claims.append(
            EvidenceClaim(
                "top5_concentration",
                "major_changes",
                f"상위 5개 루트의 합산 점유율은 {_number(cr5 * 100)}%다.",
            )
        )
        key_metrics.append(_price_metric("top5_share_pct", "상위5루트 비중", cr5 * 100, unit="%"))

    korea_hits = [
        (rank, item)
        for rank, item in enumerate(ranking, start=1)
        if _is_korea(item.country_code, item.country_name) or _is_korea(item.origin_country_code, item.origin_country_name)
    ]
    if korea_hits:
        top_hits = korea_hits[:2]
        pieces = []
        for rank, item in top_hits:
            share = (item.import_amount or 0.0) / total * 100
            is_origin = _is_korea(item.origin_country_code, item.origin_country_name)
            counterpart = item.country_name if is_origin else (item.origin_country_name or "출처미상")
            suffix = "行" if is_origin else "발"
            if rank <= len(top_n):
                # 이미 top1_country 근거(1~3위 랭킹)에 금액·비중이 있는 루트는 순위·상대국만
                # 적어 같은 숫자를 한 절에서 두 번 쓰지 않는다(2026-08-27 반복 루프 3회차:
                # LLM이 두 근거를 그대로 옮겨 "중국→대한민국 루트가 24,056,…(27.45%)"가
                # 한 절에 두 번 나온 사례 — PDF 예시는 한국이 6·9위라 이 케이스가 없다).
                pieces.append(f"{rank}위({counterpart}{suffix}, 위 랭킹 참조)")
            else:
                pieces.append(f"{rank}위({counterpart}{suffix} {_quantity(item.import_amount or 0.0)}, {_number(share)}%)")
        if len(top_hits) >= 2:
            hits_sum = sum(item.import_amount or 0.0 for _, item in top_hits)
            hits_share = hits_sum / total * 100
            korea_fact = (
                f"대한민국은 세부현황 기준 {pieces[0]}와 {pieces[1]}에 각각 등장하여, "
                f"두 루트 합산 {_quantity(hits_sum)}({_number(hits_share)}%)를 기록했다."
            )
        else:
            korea_fact = f"대한민국은 세부현황 기준 {pieces[0]}로 나타났다."
        claims.append(EvidenceClaim("korea_route_rank", "major_changes", korea_fact))
    else:
        claims.append(
            EvidenceClaim(
                "korea_route_absent",
                "major_changes",
                "대한민국이 포함된 개별 루트는 조회된 상위 데이터에 나타나지 않았다.",
            )
        )

    patterns: list[DetectedPattern] = []
    if top_n and (top_n[0].import_amount or 0.0) / total >= 0.5:
        patterns.append(
            DetectedPattern(
                code="single_route_concentration",
                label="1개 루트 과반 집중",
                evidence=["top1_country"],
            )
        )

    if len(dates) >= 2:
        previous_date = dates[-2]
        previous_total = sum(
            item.import_amount or 0.0 for item in series.observations if item.date == previous_date
        )
        change = _pct(total, previous_total)
        if change is not None:
            claims.append(
                EvidenceClaim(
                    "period_total_change",
                    "current_position",
                    f"직전 관측일({_korean_date(previous_date)}) 대비 세계 교역 총액이 {_signed_pct(change)} 변동했다.",
                )
            )
            key_metrics.append(
                _price_metric("period_total_change_pct", "직전 대비 세계 교역 총액 변동", change * 100, unit="%")
            )
    else:
        claims.append(
            EvidenceClaim(
                "single_snapshot",
                "current_position",
                "조회기간에 관측일이 1건뿐이라 기간별 변화는 계산하지 않았다.",
            )
        )

    return AdditionalCalculatedSummary(
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=key_metrics,
        patterns=patterns,
        omitted=[],
        warnings=[],
    )


def _price_metric(metric_id: str, label: str, value: float | None, *, unit: str | None = None) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        status="available" if value is not None else "insufficient_data",
        value=round(value, 6) if isinstance(value, float) else value,
        unit=unit,
    )


def _pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def _signed_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{_number(value * 100)}%"


def _shift_date(date_text: str, days: int) -> str:
    year, month, day = (int(part) for part in date_text.split("-"))
    return (_date(year, month, day) + _timedelta(days=days)).isoformat()
