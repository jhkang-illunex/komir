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

from .models import AnalysisSummaryResponse

_log = logging.getLogger(__name__)

_SECTION_TITLES = {
    "core_diagnosis": "핵심 진단",
    "major_changes": "주요 변화",
    "current_position": "현재 위치",
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
        return f"{value:,.2f}", unit or ""
    return str(value), unit or ""


def render_markdown_report(response: AnalysisSummaryResponse) -> str:
    """검증된 `AnalysisSummaryResponse` 1건을 사람이 읽는 Markdown 보고서로 렌더링한다."""

    lines: list[str] = []
    lines.append(f"# {response.mineral.name} 분석 요약 — {response.page_definition}")
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

    for key, title in _SECTION_TITLES.items():
        sentences = getattr(response.summary, key)
        if not sentences:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.append(" ".join(sentence.text for sentence in sentences))
        lines.append("")

    if response.key_metrics:
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
