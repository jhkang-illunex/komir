# -*- coding: utf-8 -*-
"""`AnalysisSummaryResponse`(구조화 JSON) → Markdown 보고서 텍스트 렌더러 —
2026-08-26 신설.

사용자 지시("보고서는 DB에 저장하지 않고 MD 형태로 풍부한 표현력을 가진
텍스트로 바로 response에 작성")에 따라, `routers/_common.py::run_summary`가
`AnalysisSummaryService.analyze()`의 결과를 이 함수로 감싸 `AnalysisReportResponse.
report`에 담는다. 계산·검증·프롬프트 레이어(`summary.py`/`prompts.py`)는
그대로 두고 렌더링만 여기서 한다 — LLM에게 직접 MD를 쓰게 하면 `_validate_
llm_summary`의 근거 검증 계약을 벗어나므로 하지 않는다(검증된
`SummaryNarrative` 문장을 그대로 옮겨 담을 뿐, 새 문장을 짓지 않는다)."""
from __future__ import annotations

import logging
import re

from .map_presentation import QUANTITY_SCALES, compact_quantity, scaled_quantity
from .models import AnalysisSummaryResponse, Metric, ReportTable, ReportTableColumn

_log = logging.getLogger(__name__)

_SECTION_TITLES = {
    "core_diagnosis": "핵심 진단",
    "major_changes": "주요 변화",
    "current_position": "현재 위치",
}

#: 2026-09-09 발주처 피드백(오전 2차) — 광물자원가격 4종은 섹션명을 발주처
#: 템플릿 흐름("가격 요약 → 최근 변화 → 변동 구간")에 맞춘다. 다른 8종
#: page_id는 위 `_SECTION_TITLES` 그대로(이번 피드백 범위 밖).
_PRICE_PAGE_IDS = ("price_base_metals", "price_minor_metals", "price_iron_energy", "price_other")
_PRICE_SECTION_TITLES = {
    "core_diagnosis": "가격 요약",
    "major_changes": "최근 변화",
    "current_position": "변동 구간",
}

#: 2026-09-10 main-agent 지시(2026-09-09 오전 2차 피드백 결정 번복) — 발주처
#: 원본 업무지시서 §3.1(오전 2차 피드백보다 상위 문서)이 "주요 지표" 표를
#: 정확히 이 9개 항목으로 명시하고 있었다. 표 자체를 껐던 이전 결정이 그
#: 요구사항을 놓친 것으로 판단돼 다시 켠다 — 단, 전체 key_metrics를 그대로
#: 노출하던 다른 8종과 달리 이 9개 화이트리스트 순서·라벨로만 표시한다
#: (`Metric.label`은 API 응답에도 쓰이는 값이라 안 건드리고, 이 표시용
#: 라벨은 렌더링 계층에만 둔다 — `_MINERAL_MAP_UNIT_LABELS`·
#: `_SECTION_TITLES_OVERRIDES`와 같은 로컬 오버라이드 패턴).
_PRICE_KEY_METRIC_ORDER = (
    "latest_price", "week_avg_change_pct", "month_avg_change_pct",
    "year_avg_change_pct", "price_streak_length", "period_high",
    "period_low", "drawdown_from_period_high_pct", "recent_volatility_pct",
    # 2026-09-13 사용자 결정 — 비교광종을 넣었을 때만 생기는
    # "{비교광종} 대비 조회기간 변화율차"도 표에 노출한다(라벨은 광종명이
    # 들어가 동적이라 `_PRICE_KEY_METRIC_LABELS`가 아니라 metric.label 사용).
    "compare_overall_change_pct",
)
_PRICE_KEY_METRIC_LABELS = {
    "latest_price": "현재가격", "week_avg_change_pct": "전주 대비",
    "month_avg_change_pct": "전월 대비", "year_avg_change_pct": "전년 대비",
    "price_streak_length": "연속 추세", "period_high": "최고가",
    "period_low": "최저가", "drawdown_from_period_high_pct": "낙폭",
    "recent_volatility_pct": "변동성",
}

#: 2026-09-09 main-agent 승인(B-5) — 나머지 6종도 각 페이지 실제 절 내용에 맞춰
#: 업무지시서 블록명에 가깝게 표시명을 바꾼다. `_SECTION_TITLES`(범용 기본값)를
#: 깔고 여기 등록된 page_id만 덮어쓴다 — 신규 page_id가 추가돼도 등록을 잊으면
#: 그냥 범용 이름으로 렌더링될 뿐 죽지 않는다.
_SECTION_TITLES_OVERRIDES: dict[str, dict[str, str]] = {
    "indicator_composite": {
        "core_diagnosis": "지수 요약",
        # 2026-09-10 발주처 피드백[4] 반영 후 이 절은 메이저·희소 "하위지수"만이
        # 아니라 광물종합지수 자체의 변화도 지수별로 담아 "하위지수 변화"라는
        # 이름이 더 이상 정확하지 않다 — "지수별 변화"로 개칭.
        "major_changes": "지수별 변화",
        "current_position": "지수 위치",
    },
    "indicator_market": {
        "core_diagnosis": "현재 단계",
        "major_changes": "단계 변화",
        "current_position": "주요 변동 특징",
    },
    "indicator_supply": {
        "core_diagnosis": "현재 수급 단계",
        "major_changes": "단계 변화",
        "current_position": "구성요소 변화",
    },
    "map_korea": {
        "core_diagnosis": "수입 현황",
        "major_changes": "수입 집중도",
        "current_position": "수출 현황",
    },
    "map_global": {
        "core_diagnosis": "글로벌 교역 현황",
        "major_changes": "주요 교역 루트",
        "current_position": "기간 변화",
    },
    "map_mineral": {
        # core_diagnosis는 measure(매장량/생산량)에 따라 동적으로 정해진다 —
        # 아래 `_MINERAL_MAP_MEASURE_TITLES` 참고, 여기엔 안 둔다.
        "major_changes": "국가별 순위 및 변화",
        "current_position": "집중도 변화",
    },
}

#: major_changes 안의 특정 evidence_id 문장을 별도 "## " 절로 분리해 보여줄
#: page_id → (evidence_id, 분리 절 제목) — 2026-09-10 사용자 지시로 map_global
#: (한국 관련 루트)에 이어 map_mineral(주요 변화)도 같은 패턴이 필요해졌다.
#: `_SECTION_TITLES_OVERRIDES`처럼 등록에 없는 page_id는 그냥 영향받지 않는다.
#: 2026-09-15 발주처 피드백(대상 5) — map_mineral "주요 변화"는 증감국
#: 근거가 국가당 1개(최대 4개)로 쪼개지고 1위 vs 기타 총정리 문장이 붙어
#: evidence_id가 여러 개가 됐다. 값은 (분리할 evidence_id 튜플, 절 제목).
_MAJOR_CHANGES_SPLIT_SECTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "map_global": (("korea_route_rank",), "한국 관련 루트"),
    "map_mineral": (
        ("extreme_increase_1", "extreme_increase_2", "extreme_decrease_1", "extreme_decrease_2", "volatility_country", "top_country_vs_others"),
        "주요 변화",
    ),
    "map_korea": (("trade_scale_trend",), "수입·수출 규모 추이"),
}

#: 렌더링에서 통째로 숨길 절 — 2026-09-10 사용자 지시로 map_global의 "기간
#: 변화"(대부분 "조회기간에 관측일이 1건뿐이라 계산하지 않았다"는 정보량
#: 없는 결측 문장뿐)에 이어 map_mineral의 "집중도 변화"도 뺀다.
#: `SummaryNarrative`는 9개 page_id 공유 스키마라 절마다 min_length=1
#: 제약이 있어(계산 레이어는 그대로 두고 항상 최소 1개 근거를 채운다)
#: 렌더링 단계에서만 건너뛴다.
_HIDDEN_SECTIONS: dict[str, frozenset[str]] = {
    "map_global": frozenset({"current_position"}),
    "map_mineral": frozenset({"current_position"}),
}

#: map_mineral 전용 — `_analyze_mineral_map`이 applied_filters["measure"]에
#: `MineralMapMeasure`("reserves"/"production") 원문을 그대로 싣는다(summary.py
#: 참고). 등록에 없는 값(신규 measure 추가 등)은 범용 "핵심 진단"으로 폴백한다.
_MINERAL_MAP_MEASURE_TITLES = {
    "reserves": "세계 매장량 현황",
    "production": "세계 생산량 현황",
}

#: applied_filters의 보조 필드를 사람이 읽을 라벨로 바꾼다 — 매핑에 없는
#: 키는 원래 이름을 그대로 쓴다(신규 필드 추가 시 여기 등록을 잊어도 죽지 않음).
_FILTER_LABELS = {
    "price_criterion": "가격기준",
    "measure": "측정항목",
    "unit": "단위",
    "forecast_horizon": "예측기간구분",
    "compare_mineral": "비교광종",
    "compare_price_criterion": "비교광종 가격기준",
    "price_group": "그룹",
    "trade_direction": "조회방향",
    # 2026-09-10 사용자 제보(report-summary-agent 경유) — map_korea가
    # 2026-08-31부터 applied_filters에 채워온 3개 키가 이 매핑에 등록이
    # 안 돼 있어 "**period_unit**: 년별"처럼 영문 키가 그대로 노출되고
    # 있었다(위 "등록을 잊어도 죽지 않는다"는 설계가 실제로는 조용히
    # 낡은 라벨을 서빙하는 함정이 됐다) — `_map_korea_query_filters()`
    # (input_data.py) 반환값 그대로.
    "period_unit": "기간 단위",
    "country_filter": "국가 필터",
    "scope_filter": "품목 범위",
}


def _trim_trailing_zero(text: str) -> str:
    """2026-09-13 사용자 지시 — "전체 공통 소수점 이하 3자리에서 반올림
    표시할 때 소수점 이하 2번째 자리가 0이면 생략"(예: 45.70 → 45.7,
    0.00 → 0). `additional_summary.py::_trim_trailing_zero`와 로직이
    같다 — 이 파일은 그 모듈을 import하지 않는다는 기존 원칙(아래
    2026-09-09 주석 참고)이라 로직만 그대로 복제한다."""

    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".")


def _format_metric_row(value: float | int | str | None, unit: str | None) -> tuple[str, str]:
    """(값 문자열, 단위 문자열) — `unit="ratio"`(0.0356 같은 소수)는 표에서
    읽기 힘들어(2026-08-26 KOMIS 실데이터 회귀 테스트(/unlazy)에서 발견 —
    본문 문장은 "3.56%"인데 표는 "0.04"로 나와 서로 안 맞아 보였다) 백분율로
    바꿔 본문 서술과 같은 단위로 맞춘다."""

    if value is None:
        return "-", unit or ""
    if unit == "ratio" and isinstance(value, (int, float)):
        return _trim_trailing_zero(f"{value * 100:,.2f}"), "%"
    if isinstance(value, float):
        # 2026-09-09 main-agent 지적(C-9) — price_* 4종은 이미 `_quantity()`
        # (정수면 소숫점 생략)로 "16,780.00"류 표기를 없앴는데, 이 함수는
        # 비price 페이지 "주요 지표" 표 전용이라 그 정리가 안 닿아 있었다
        # ("75,818,972.00"·"770,200,000.00" 등 재발 지점). 같은 규칙을 여기
        # 한 곳에만 적용하면 표를 쓰는 6개 페이지 전부에 일괄 반영된다 —
        # additional_summary.py::_quantity()를 import하지 않고 로직만
        # 그대로 복제한다(렌더링 계층이 그 모듈에 의존하지 않게 유지).
        if value.is_integer():
            return f"{int(value):,}", unit or ""
        return _trim_trailing_zero(f"{value:,.2f}"), unit or ""
    return str(value), unit or ""


#: (?<!니)다\.(?=\s|$) — "다." 앞이 "니"가 아니면서(이미 "입니다."인 것과
#: 구분) 뒤가 공백 또는 문자열 끝인 것만 문장 종결로 본다("단계다"처럼 단어
#: 중간의 "다"는 애초에 "다." 형태가 아니라 매치되지 않는다).
_COPULA_SENTENCE_END_RE = re.compile(r"(?<!니)다\.(?=\s|$)")


def _to_polite_copula(text: str) -> str:
    """정의문의 평서형 계사("...자료다.")를 존댓말("...자료입니다.")로
    바꾼다(2026-08-31 사용자 지시 — 제목 줄 어투가 본문 LLM 정제 문장의
    "-습니다"체와 안 맞는다는 지적). `KOMIR_PAGE_CONTEXTS`(komir_summary.py)·
    `ADDITIONAL_PAGE_CONTEXTS`(additional_summary.py, 외부repo "무수정 이식"이라
    원문을 못 고침)·정책 YAML(`resources/policies/*.yaml`)의 정의문이 전부 이
    "...(명사)다." 계사 종결형이라 — 범용 한국어 활용 변환이 아니라 이 특정
    종결형(계사 "이다"의 "-다"체)에만 적용되는 정확한 규칙이다. 이 형태가
    아니면(예: 동사 활용형) 원문 그대로 둔다 — 잘못된 변환보다 무변환이 안전
    하다.

    2026-09-09 main-agent 재검증(B-3) — indicator_supply.yaml의 정의문이
    두 문장(둘 다 "...지표다.")인데, 예전 구현은 문자열 끝만 보고 치환해
    (`text.endswith("다.")`) 중간 문장은 그대로 남아 있었다("...분류하는
    지표다. 광종별 ... 강한 지표다."에서 앞 문장만 비격식체로 잔존) —
    395콤보 렌더링을 `(?<!니)다\\.` 정규식으로 스캔해 발견. 문자열 끝
    검사 대신 정규식으로 텍스트 안의 모든 계사 종결을 치환한다."""

    return _COPULA_SENTENCE_END_RE.sub("입니다.", text)


_TITLE_FILTER_KEYS = frozenset({
    "mineral", "mineral_code", "start_date", "end_date", "start_month", "end_month", "start_year", "end_year",
})


def _extra_filters(response: AnalysisSummaryResponse) -> list[tuple[str, str]]:
    """상단 보조 정보로 보여줄 (라벨, 값) — 비철금속/희소금속처럼 같은 광종이라도
    조회조건(가격기준·품목/스펙 등)이 그룹별로 다를 수 있어 요청 바디에 실려 온
    값이 있으면 표시한다(`applied_filters`는 자유 텍스트 dict라 mineral/mineral_code/
    날짜 범위는 제목·본문에 이미 드러나므로 그 외 필드만)."""

    return [
        (_FILTER_LABELS.get(key, key), value)
        for key, value in response.applied_filters.items()
        if key not in _TITLE_FILTER_KEYS and value
    ]


def _grade_text(response: AnalysisSummaryResponse) -> str | None:
    if response.grade is None:
        return None
    return f"{response.grade.label} ({_trim_trailing_zero(f'{response.grade.score:,.2f}')}점)"


def _section_titles(response: AnalysisSummaryResponse) -> dict[str, str]:
    """page_id별 절 키 → 표시 제목(순서 포함). 숨김 절(`_HIDDEN_SECTIONS`)은 빠진다."""

    if response.page_id in _PRICE_PAGE_IDS:
        return dict(_PRICE_SECTION_TITLES)
    section_titles = {**_SECTION_TITLES, **_SECTION_TITLES_OVERRIDES.get(response.page_id, {})}
    if response.page_id == "map_mineral":
        measure = response.applied_filters.get("measure")
        section_titles["core_diagnosis"] = _MINERAL_MAP_MEASURE_TITLES.get(
            measure, _SECTION_TITLES["core_diagnosis"]
        )
    for hidden_key in _HIDDEN_SECTIONS.get(response.page_id, frozenset()):
        if response.page_id == "map_global" and any("single_snapshot" not in sentence.evidence_ids for sentence in response.summary.current_position):
            # 2026-09-13 사용자 지시 — "참고:" 접두어 제거.
            section_titles[hidden_key] = "연도별 교역액 변화"
        else:
            section_titles.pop(hidden_key, None)
    return section_titles


def _section_blocks(response: AnalysisSummaryResponse) -> list[tuple[str, list, bool]]:
    """본문 절을 (표시 제목, 문장 목록, 목록형 여부) 순서대로 — 2026-09-16 두 렌더러
    (`render_markdown_report`·`render_plain_report`)가 공유하도록 루프에서 분리. 빈 절은
    생략된다.

    - major_changes 분리 절: 2026-09-10 사용자 지시(map_global 한국 관련 루트·map_mineral
      주요 변화, 같은 패턴) — 특정 evidence_id 문장을 major_changes의 나머지 서술과 같은
      문단에 묶지 말고 별도 절로 뺀다. JSON 계약(`SummaryNarrative.major_changes`)은
      그대로 두고(스키마가 3개 절 고정이라 4번째 절을 추가하면 다른 8종 page_id까지
      건드리게 된다) 렌더링 단계에서만 evidence_id 기준으로 거른다 — 계산·검증 레이어의
      "값이 있을 때만" 로직(komir_summary.py/summary.py)은 그대로라 근거 자체가 없으면
      이 절도 자연히 생략된다.
    - 목록형: 2026-08-31 사용자 지시 — "현재 위치"는 통계 확장(변동성·단기 매매압력·
      백분위·낙폭국면·재고해석 등)으로 최대 9문장까지 늘었는데 공백으로 이어붙여 한
      문단으로 렌더링하면 읽기 힘들다. 이 절의 문장들은 원래부터 각 문장이 서로 다른
      독립 주제라 문단보다 목록이 자연스럽다(3문장 이하면 문단 유지). core_diagnosis·
      major_changes는 서술 흐름을 의도한 절이라 문단 형태."""

    blocks: list[tuple[str, list, bool]] = []
    for key, title in _section_titles(response).items():
        sentences = getattr(response.summary, key)
        if not sentences:
            continue
        split = _MAJOR_CHANGES_SPLIT_SECTIONS.get(response.page_id)
        if split and key == "major_changes":
            evidence_ids, split_title = split
            split_sentences = [s for s in sentences if any(eid in s.evidence_ids for eid in evidence_ids)]
            other_sentences = [s for s in sentences if s not in split_sentences]
            if other_sentences:
                blocks.append((title, other_sentences, False))
            if split_sentences:
                blocks.append((split_title, split_sentences, False))
            continue
        blocks.append((title, list(sentences), key == "current_position" and len(sentences) > 3))
    return blocks


def _log_diagnostics(response: AnalysisSummaryResponse) -> None:
    """독자 응답에는 안 싣는 경고·정제 여부를 서버 로그로만 남긴다(두 렌더러 공용)."""

    # 2026-08-27 skeptic 감사 SC-016: `notices`(= 페이지 정책의 analysis_constraints,
    # "제공된 가격 계열과 선택 기간만 사용한다." 같은 LLM 작성 제약)와 LLM 정제
    # 실패 경고("… 검증 사유: 존재하지 않는 evidence_id …")는 독자용이 아니라
    # 내부용이라 최종 보고서에서 뺀다.
    # 2026-08-28 감사(P2, 라운드1 후속): 데이터 결측 경고(비교값 없음·비교연도
    # 없음 등)도 "조회기간에 한 달 또는 1년 비교값이 없어 중장기 비교를
    # 제외했다"처럼 계산기/검증기가 쓰는 그대로의 문구라 "## 참고" 절에 그대로
    # 노출하면 발주처 PDF 템플릿(§1-1~2-3, §1~4) 어디에도 없는 메타 각주 톤이
    # 되어 최종 문서 톤과 어긋난다(2026-08-28 report_gen_출력품질감사 SC-016
    # 재확인). 정보 자체는 서버 로그로는 여전히 남기되(운영 관측성 유지),
    # 독자용 렌더링에서는 전부 뺀다 — 관측 부족은 이미 본문 문장 개수·내용
    # 자체가 조용히 반영한다(예: price 페이지는 비교 불가 시 major_changes에
    # "비교 가능한 이전 가격이 없어 등락률은 계산하지 않았다"를 본문 문장으로
    # 자연스럽게 포함, 별도 각주가 필요 없다).
    for warning in response.data_quality.warnings:
        kind = "LLM" if warning.startswith("LLM ") else "데이터 결측"
        _log.warning(
            "%s 경고(독자 응답에는 미노출) %s(page_id=%s, mineral=%s): %s",
            kind, response.request_id, response.page_id, response.mineral.code, warning,
        )

    # 2026-08-28 감사(P1, SC-018 — 공개 계약은 절대 안 건드리는 범위로 한정된
    # 내부 전용 개선): 공개 `{status, report}` 응답은 `llm_refined`를 아예 안
    # 실어 클라이언트가 이번 응답이 LLM 정제인지 규칙기반 폴백인지 구분할
    # 수 없다(price_group처럼 근거 4개 이상일 때 검증 실패로 조용히 폴백되는
    # 사례 실측 — 프롬프트를 아무리 튜닝해도 반영 안 되는 것처럼 보이는 원인).
    # 계약 자체를 바꿔 `llm_refined` 필드를 추가하는 게 근본 해결이지만 그건
    # 프론트 계약을 건드리므로 이 세션에서 임의로 결정하지 않는다("다음 주
    # 논의 필요" 목록에 기록) — 대신 실패 시에만이 아니라 매 요청마다 구조화
    # 로그 1줄을 남겨, 폴백 문구가 없는 성공 케이스와 실제로 구분되도록 하고
    # (기존엔 폴백 시에만 로그가 남아 "로그 없음=성공"을 신뢰할 수 없었다),
    # page_id별 LLM 정제율을 로그 집계만으로 산출할 수 있게 한다.
    _log.info(
        "분석요약 완료 request_id=%s page_id=%s mineral=%s llm_refined=%s",
        response.request_id, response.page_id, response.mineral.code, response.llm_refined,
    )



#: 2026-09-16 사용자 지시 — 평문 보고서(`render_plain_report`)에서 상승/하락 계열 어휘에
#: 색을 입힌다. 색 → 어휘 목록. 국내 시세 관행(상승=적색, 하락=청색)을 따른다. 어휘는
#: 문장 안 부분 문자열로 매치되므로("상승했으며"→"<font color='red'>상승</font>했으며")
#: 활용형까지 한 항목으로 잡힌다. 부정문("감소하지 않았다")도 어휘 자체는 색칠된다 —
#: 방향 판정을 새로 하지 않고 어휘만 표시하는 단순 규칙이라는 뜻(의도적).
TONE_COLORS: dict[str, tuple[str, ...]] = {
    "red": ("상승", "상향", "증가", "급등", "반등", "강세", "올랐", "늘어", "늘었"),
    "blue": ("하락", "하향", "감소", "급락", "약세", "내렸", "줄어", "줄었"),
}
#: 색 마크업 템플릿(프론트 요구 형식). `{color}`·`{word}` 자리표시자.
TONE_TAG = "<font color='{color}'>{word}</font>"
_WORD_COLOR = {word: color for color, words in TONE_COLORS.items() for word in words}
_TONE_RE = re.compile("|".join(re.escape(word) for word in sorted(_WORD_COLOR, key=len, reverse=True)))


#: 평문 줄 나누기 — 계산기가 한 `Sentence`에 두 문장을 붙여 두는 경우가 있어("…고가권에
#: 속합니다. 조회기간 중 가장 큰 하락은 …") 종결어미 "다." 뒤 공백에서 줄을 나눈다.
#: 숫자 표기("2.04억톤")·날짜에는 "다."가 없어 오분할되지 않는다.
_PLAIN_LINE_SPLIT_RE = re.compile(r"(?<=다\.)\s+")


def _plain_lines(text: str) -> list[str]:
    return [part for part in _PLAIN_LINE_SPLIT_RE.split(text) if part]


#: 2026-09-16 사용자 제보 — "2021~2025년"·"약 4.3억톤~약 4.38억톤"처럼 문장 중간의
#: 단일 `~`를 GFM 렌더러(remark-gfm singleTilde 기본값 등)가 취소선으로 그린다.
#: rag_chat `streaming.py::_escape_tildes`와 같은 규칙으로 `\~` 이스케이프(이미
#: 이스케이프된 것은 건드리지 않음). 평문 뷰어에서는 `\~`가 그대로 보일 수 있으나
#: 프로젝트 공통 결정(챗봇과 동일)이라 따른다.
_UNESCAPED_TILDE_RE = re.compile(r"(?<!\\)~")


def _escape_tildes(text: str) -> str:
    return _UNESCAPED_TILDE_RE.sub(r"\\~", text)


def colorize_tone(text: str) -> str:
    """`TONE_COLORS` 어휘를 `TONE_TAG`로 감싼다(한 번만 훑으므로 중첩 태그 없음)."""

    return _TONE_RE.sub(lambda m: TONE_TAG.format(color=_WORD_COLOR[m.group(0)], word=m.group(0)), text)


#: 2026-09-16 사용자 지시 — 처음엔 "시장동향지표, 수급위기지표 … 해당 단어는 볼드"로
#: 지표 명칭을 볼드했으나, 같은 날 예시로 정정: 볼드 대상은 명칭이 아니라 **지표 값과
#: 단계 명칭**이다("시장동향지표는 <b>1.73</b>점으로, 현재 <b>신중</b> 단계"). 지표 명칭
#: 목록은 값 위치를 찾는 앵커로 쓴다(계산 모듈 문장 템플릿에서 수집). "수급위기지표"는
#: 코드상 "수급동향지표"로 표기되지만 사용자가 부른 이름이라 함께 둔다.
INDICATOR_TERMS: tuple[str, ...] = (
    "시장동향지표", "수급동향지표", "수급위기지표",
    "광물종합지수", "메이저금속지수", "희소금속지수", "가격강도지수",
)
#: 단계 명칭 — `resources/policies/indicator_market.yaml`(신중·주의·중립·관심·기회)·
#: `indicator_supply.yaml`(긴장·주의·관심·안정·원활)의 grade label. 문장 안에서 " 단계"
#: 바로 앞("현재 신중 단계", "주의 단계로")이거나 "에서 " 앞("신중에서 주의 단계로",
#: 전환 문장)일 때만 볼드해 일반 명사 "관심"·"주의"의 오탐을 막는다.
GRADE_LABELS: tuple[str, ...] = ("신중", "주의", "중립", "관심", "기회", "긴장", "안정", "원활")
#: 볼드 마크업 템플릿 — `TONE_TAG`와 같은 HTML 태그 방식(프론트가 `<font>`를 그리는 렌더러).
BOLD_TAG = "<b>{word}</b>"
_INDICATOR_ALT = "|".join(re.escape(term) for term in sorted(INDICATOR_TERMS, key=len, reverse=True))
#: "<지표명><조사> <숫자>(점|포인트)" — 지표 명칭 바로 뒤의 값만(다른 숫자는 손대지 않음).
_INDICATOR_VALUE_RE = re.compile(rf"(?P<head>(?:{_INDICATOR_ALT})[은는이가]\s+)(?P<num>-?[\d,]+(?:\.\d+)?)(?=점|포인트)")
_GRADE_ALT = "|".join(re.escape(label) for label in GRADE_LABELS)
_GRADE_RE = re.compile(rf"(?<![가-힣])(?P<grade>{_GRADE_ALT})(?=\s+단계|에서\s)")


def emphasize_indicators(text: str) -> str:
    """지표 명칭 뒤의 값(`_INDICATOR_VALUE_RE`)과 단계 명칭(`_GRADE_RE`)을 `BOLD_TAG`로
    감싼다. 각 규칙이 한 번씩만 훑고 대상이 겹치지 않아 중첩 태그는 생기지 않는다."""

    text = _INDICATOR_VALUE_RE.sub(lambda m: m.group("head") + BOLD_TAG.format(word=m.group("num")), text)
    return _GRADE_RE.sub(lambda m: BOLD_TAG.format(word=m.group("grade")), text)


#: 평문 보고서의 문장 줄 구분자 — Markdown 하드 브레이크(공백 2개+줄바꿈). 단락 구분은 "\n\n".
PLAIN_LINE_BREAK = "  \n"


def render_plain_report(response: AnalysisSummaryResponse) -> str:
    """검증된 `AnalysisSummaryResponse` 1건을 **평문** 보고서로 렌더링한다 — 2026-09-16
    사용자 지시("모든 보고서에서 report 안의 md에 새 포맷: ① heading 제거 ② 섹션 문자열은
    줄 단위·단락 단위로 구분한 평문 ③ 상승/하락 등은 `<font color='red'>` 식 커스텀
    색 지정"). `render_markdown_report`(Markdown, 제목·`##` 절 포함)는 그대로 두고 이
    함수를 `routers/_common.py`가 `report`에 쓴다 — 둘 다 유지(사용자 지시).

    형식: 제목·절 제목 없음. 절 하나가 단락 하나(빈 줄로 구분), 단락 안에서는 문장
    하나가 한 줄(`_plain_lines` — 한 Sentence에 붙은 복수 문장도 나눔). 줄 구분자는
    `PLAIN_LINE_BREAK`("  \n", Markdown 하드 브레이크) — 2026-09-16 사용자 제보("문장
    단위로 줄바꿈이 되어 있어야 하는데 한 줄로 붙어 보인다"): 프론트가 `<font>` 태그를
    그리려면 Markdown+HTML 렌더러인데 Markdown은 단일 "\n"을 공백으로 접는다. 문장 끝
    공백 2개는 평문 뷰어에서는 보이지 않고 Markdown 뷰어에서는 줄바꿈이 된다. 상단 보조
    정보(조회조건·현재 단계)는 내지 않는다(2026-09-16 후속 지시 — Markdown 렌더러에만
    남는다). 문장 순서·내용·절 구성(분리 절·숨김 절)은 Markdown 렌더러와 동일
    (`_section_blocks` 공유), 문장 텍스트는 `colorize_tone`(상승/하락 색)·
    `emphasize_indicators`(지표 값·단계 명칭 볼드)·`_escape_tildes`(단일 `~`→`\\~`)만 거친다."""

    # 2026-09-16 사용자 지시("기존 첫 번째 heading은 표시 안 되게") — Markdown 렌더러의
    # 제목 자리에 있던 상단 보조 정보(조회조건 "가격기준: LME CASH · …"·"현재 단계: …")
    # 단락을 평문에서는 내지 않는다. 본문 절만 단락으로 나간다.
    paragraphs: list[str] = []
    for _title, sentences, _as_list in _section_blocks(response):
        paragraphs.append(PLAIN_LINE_BREAK.join(
            _escape_tildes(emphasize_indicators(colorize_tone(line)))
            for sentence in sentences for line in _plain_lines(sentence.text)
        ))

    _log_diagnostics(response)
    return "\n\n".join(paragraphs).strip() + "\n"


def render_markdown_report(response: AnalysisSummaryResponse) -> str:
    """검증된 `AnalysisSummaryResponse` 1건을 사람이 읽는 Markdown 보고서로 렌더링한다."""

    lines: list[str] = []
    lines.append(f"# {response.mineral.name} 분석 요약 — {_to_polite_copula(response.page_definition)}")
    lines.append("")
    extra_filters = _extra_filters(response)
    if extra_filters:
        lines.append(" · ".join(f"**{label}**: {value}" for label, value in extra_filters))
        lines.append("")
    grade_text = _grade_text(response)
    if grade_text:
        lines.append(f"**현재 단계**: {grade_text}")
        lines.append("")

    for title, sentences, as_list in _section_blocks(response):
        lines.append(f"## {title}")
        lines.append("")
        if as_list:
            for sentence in sentences:
                lines.append(f"- {sentence.text}")
        else:
            lines.append(" ".join(sentence.text for sentence in sentences))
        lines.append("")

    # "주요 지표" 표는 2026-09-16부터 본문에 넣지 않는다 — `build_key_metrics_table()`
    # 이 `AnalysisReportResponse.table`로 따로 낸다(아래 함수 docstring 참고).

    _log_diagnostics(response)

    return "\n".join(lines).strip() + "\n"


_TABLE_COLUMNS = ("지표", "값", "단위")
_MAP_PAGE_IDS = frozenset({"map_korea", "map_global", "map_mineral"})


def _key_metric_rows(response: AnalysisSummaryResponse) -> list[tuple[str, Metric]]:
    """표에 실을 (표시 라벨, 지표) 목록 — 2026-09-10 main-agent 지시(2026-09-09 오전
    2차 피드백 결정 번복): 발주처 원본 업무지시서 §3.1이 광물자원가격 표를 9개
    항목으로 명시하고 있어 price_* 4종은 `_PRICE_KEY_METRIC_ORDER` 화이트리스트
    순서·라벨로만, 나머지 8종은 key_metrics 전체를 그대로 낸다."""

    if response.page_id in _PRICE_PAGE_IDS:
        by_id = {metric.id: metric for metric in response.key_metrics}
        return [
            (_PRICE_KEY_METRIC_LABELS.get(metric_id, by_id[metric_id].label), by_id[metric_id])
            for metric_id in _PRICE_KEY_METRIC_ORDER
            if metric_id in by_id
        ]
    return [(metric.label, metric) for metric in response.key_metrics]


def _metric_cells(page_id: str, metric: Metric) -> tuple[str, str, int | float | bool | str | None]:
    """(값 표시 문자열, 단위 표시 문자열, 표시 단위 기준 숫자값). 표시 문자열은
    2026-09-16 이전 본문 표와 문자 단위로 동일하다(`_format_metric_row` + 지도 3종
    축약 표기)."""

    value_text, unit_text = _format_metric_row(metric.value, metric.unit)
    typed: int | float | bool | str | None = metric.value
    is_number = isinstance(metric.value, (int, float)) and not isinstance(metric.value, bool)
    if metric.unit == "ratio" and is_number:
        typed = metric.value * 100
    elif page_id in _MAP_PAGE_IDS and is_number and metric.unit in QUANTITY_SCALES:
        value_text, unit_text = compact_quantity(metric.value, metric.unit)
        typed, _ = scaled_quantity(metric.value, metric.unit)
    return value_text, unit_text, typed


def build_key_metrics_table(response: AnalysisSummaryResponse) -> ReportTable | None:
    """"주요 지표" 표를 `ReportTable`로 만든다 — 2026-09-16 사용자 지시("전체 공통
    아웃풋이 수정됐다. report에서 주요 지표는 `table`이라는 별개의 키워드로 출력").
    그 전까지 `render_markdown_report`가 본문 끝에 `## 주요 지표` 절로 붙이던 것을
    떼어 `AnalysisReportResponse.table`로 낸다. 행 선택·라벨·값 표기 규칙은 그대로
    (`_key_metric_rows`·`_metric_cells`). 실을 지표가 없으면 None."""

    rows: list[list[str]] = []
    rows_typed: list[list[int | float | bool | str | None]] = []
    for label, metric in _key_metric_rows(response):
        value_text, unit_text, typed = _metric_cells(response.page_id, metric)
        rows.append([label, value_text, unit_text])
        rows_typed.append([label, typed, unit_text or None])
    if not rows:
        return None
    value_is_number = all(
        cell is None or (isinstance(cell, (int, float)) and not isinstance(cell, bool))
        for _, cell, _ in rows_typed
    )
    columns_meta = [
        ReportTableColumn(key="label", label="지표", display="지표", type="string"),
        ReportTableColumn(key="value", label="값", display="값", type="number" if value_is_number else "string"),
        ReportTableColumn(key="unit", label="단위", display="단위", type="string"),
    ]
    markdown_lines = ["| " + " | ".join(_TABLE_COLUMNS) + " |", "|---|---|---|"]
    markdown_lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return ReportTable(
        columns=list(_TABLE_COLUMNS),
        rows=rows,
        columns_meta=columns_meta,
        rows_typed=rows_typed,
        markdown="\n".join(markdown_lines),
    )


__all__ = [
    "BOLD_TAG", "GRADE_LABELS", "INDICATOR_TERMS", "PLAIN_LINE_BREAK", "TONE_COLORS", "TONE_TAG",
    "build_key_metrics_table", "colorize_tone", "emphasize_indicators",
    "render_markdown_report", "render_plain_report",
]
