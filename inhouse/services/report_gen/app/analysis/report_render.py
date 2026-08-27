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

from .models import AnalysisSummaryResponse

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
    # 내부용이라 최종 보고서에서 뺀다. 데이터 결측 경고(비교값 없음·비교연도
    # 없음 등)는 독자에게 필요한 정보라 그대로 둔다.
    notes = [warning for warning in response.data_quality.warnings if not warning.startswith("LLM ")]
    if notes:
        lines.append("## 참고")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = ["render_markdown_report"]
