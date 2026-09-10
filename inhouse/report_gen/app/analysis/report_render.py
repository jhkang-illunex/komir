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

from .models import AnalysisSummaryResponse

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
        "major_changes": "하위지수 변화",
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
}


def _format_metric_row(value: float | int | str | None, unit: str | None) -> tuple[str, str]:
    """(값 문자열, 단위 문자열) — `unit="ratio"`(0.0356 같은 소수)는 표에서
    읽기 힘들어(2026-08-26 KOMIS 실데이터 회귀 테스트(/unlazy)에서 발견 —
    본문 문장은 "3.56%"인데 표는 "0.04"로 나와 서로 안 맞아 보였다) 백분율로
    바꿔 본문 서술과 같은 단위로 맞춘다."""

    if value is None:
        return "-", unit or ""
    if unit == "ratio" and isinstance(value, (int, float)):
        return f"{value * 100:,.2f}", "%"
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
        return f"{value:,.2f}", unit or ""
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


def render_markdown_report(response: AnalysisSummaryResponse) -> str:
    """검증된 `AnalysisSummaryResponse` 1건을 사람이 읽는 Markdown 보고서로 렌더링한다."""

    lines: list[str] = []
    lines.append(f"# {response.mineral.name} 분석 요약 — {_to_polite_copula(response.page_definition)}")
    lines.append("")
    # 비철금속/희소금속처럼 같은 광종이라도 조회조건(가격기준·품목/스펙 등)이
    # 그룹별로 다를 수 있다 — 요청 바디에 실려 온 값이 있으면 상단에 표시한다
    # (`applied_filters`는 자유 텍스트 dict라 mineral/mineral_code/날짜 범위는
    # 위 제목·섹션에 이미 드러나므로 여기선 그 외 필드만 보조 정보로 보여준다).
    extra_filters = {
        key: value
        for key, value in response.applied_filters.items()
        if key not in {"mineral", "mineral_code", "start_date", "end_date", "start_month", "end_month", "start_year", "end_year"}
        and value
    }
    if extra_filters:
        lines.append(
            " · ".join(
                f"**{_FILTER_LABELS.get(key, key)}**: {value}" for key, value in extra_filters.items()
            )
        )
        lines.append("")
    if response.grade is not None:
        lines.append(f"**현재 단계**: {response.grade.label} ({response.grade.score:,.2f}점)")
        lines.append("")

    if response.page_id in _PRICE_PAGE_IDS:
        section_titles = _PRICE_SECTION_TITLES
    else:
        section_titles = {**_SECTION_TITLES, **_SECTION_TITLES_OVERRIDES.get(response.page_id, {})}
        if response.page_id == "map_mineral":
            measure = response.applied_filters.get("measure")
            section_titles["core_diagnosis"] = _MINERAL_MAP_MEASURE_TITLES.get(
                measure, _SECTION_TITLES["core_diagnosis"]
            )
    for key, title in section_titles.items():
        sentences = getattr(response.summary, key)
        if not sentences:
            continue
        if response.page_id == "map_global" and key == "major_changes":
            # 2026-09-10 사용자 지시 — 대한민국 관련 루트(korea_route_rank)를
            # "주요 교역 루트"와 같은 문단에 묶지 말고 별도 섹션으로 빼서
            # 표시한다. JSON 계약(`SummaryNarrative.major_changes`)은 그대로
            # 두고(스키마가 3개 절 고정이라 4번째 절을 추가하면 다른 8종
            # page_id까지 건드리게 된다) 렌더링 단계에서만 evidence_id 기준
            # 으로 걸러 별도 "## " 블록으로 나눈다 — 계산·검증 레이어의
            # "값이 있을 때만" 로직(komir_summary.py)은 그대로 유지되므로,
            # 근거 자체가 없으면 이 블록도 자연히 생략된다.
            korea_sentences = [s for s in sentences if "korea_route_rank" in s.evidence_ids]
            other_sentences = [s for s in sentences if s not in korea_sentences]
            if other_sentences:
                lines.append(f"## {title}")
                lines.append("")
                lines.append(" ".join(sentence.text for sentence in other_sentences))
                lines.append("")
            if korea_sentences:
                lines.append("## 한국 관련 루트")
                lines.append("")
                lines.append(" ".join(sentence.text for sentence in korea_sentences))
                lines.append("")
            continue
        lines.append(f"## {title}")
        lines.append("")
        if key == "current_position" and len(sentences) > 3:
            # 2026-08-31 사용자 지시 — "현재 위치"는 통계 확장(변동성·단기
            # 매매압력·백분위·낙폭국면·재고해석 등, 2026-09-09부터 평균 대비
            # 위치는 major_changes로 이동)으로 최대 9문장까지 늘었는데,
            # 기존처럼 공백으로 이어붙여 한 문단으로 렌더링하면 읽기 힘들다.
            # 이 절의 문장들은 major_changes(의도적으로 한 문장에 여러 근거를
            # 잇는 서술형)와 달리 원래부터 각 문장이 서로 다른 독립 주제(범위·
            # 재고·변동성·추세 등)라 문단보다 목록이 자연스럽다. core_diagnosis·
            # major_changes는 문장 수가 적고(최대 1~3개) 서술 흐름을 의도한
            # 절이라 문단 형태를 그대로 둔다(3문장 이하면 이 절도 문단 유지).
            for sentence in sentences:
                lines.append(f"- {sentence.text}")
        else:
            lines.append(" ".join(sentence.text for sentence in sentences))
        lines.append("")

    # 2026-09-10 main-agent 지시 — 2026-09-09 오전 2차 피드백으로 광물자원가격
    # 4종의 "주요 지표" 표를 껐었는데, 발주처 원본 업무지시서 §3.1(그 피드백보다
    # 상위 문서)이 9개 항목 표를 명시하고 있어 그 결정을 뒤집는다. price_* 4종은
    # 전체 key_metrics가 아니라 `_PRICE_KEY_METRIC_ORDER` 화이트리스트 순서·
    # 라벨로만 표시하고, 나머지 8종은 기존대로 key_metrics 전체를 그대로 낸다.
    if response.page_id in _PRICE_PAGE_IDS:
        by_id = {metric.id: metric for metric in response.key_metrics}
        rows = [
            (metric_id, by_id[metric_id])
            for metric_id in _PRICE_KEY_METRIC_ORDER
            if metric_id in by_id
        ]
        if rows:
            lines.append("## 주요 지표")
            lines.append("")
            lines.append("| 지표 | 값 | 단위 |")
            lines.append("|---|---|---|")
            for metric_id, metric in rows:
                value_text, unit_text = _format_metric_row(metric.value, metric.unit)
                lines.append(f"| {_PRICE_KEY_METRIC_LABELS[metric_id]} | {value_text} | {unit_text} |")
            lines.append("")
    elif response.key_metrics:
        lines.append("## 주요 지표")
        lines.append("")
        lines.append("| 지표 | 값 | 단위 |")
        lines.append("|---|---|---|")
        for metric in response.key_metrics:
            value_text, unit_text = _format_metric_row(metric.value, metric.unit)
            lines.append(f"| {metric.label} | {value_text} | {unit_text} |")
        lines.append("")

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

    return "\n".join(lines).strip() + "\n"


__all__ = ["render_markdown_report"]
