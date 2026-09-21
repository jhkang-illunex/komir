"""그래프 결과 → 사용자용 한국어 추천문 렌더링.

이식 출처: komis-report-generator-main `search/renderer.py`(2026-08-11 스냅샷) —
임포트 경로만 바꿨고 로직 무수정.

2026-08-28(documents/order/chatbot_rule.txt 유형7 "메뉴 안내" 반영): 경로 표기에
"KOMIS > " 루트 접두를 붙이고(계층형 경로 요구사항), 페이지 확정 시 이동 안내
문구 1줄을 추가했다 — 그 외 그래프·라우팅 구조와 나머지 문구는 그대로 둔다
(사용자 지시: 기존 페이지 안내 경로 유지)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .filters import display_filter_value
from .models import FilterDisplay, PageDefinition, RecommendationItem

KOMIS_BASE_URL = "https://www.komis.or.kr"


def page_url(page: PageDefinition) -> str:
    """Build the navigable URL for an internal or external page definition."""

    target = page.identity.navigation.target
    if page.identity.external or target.startswith(("http://", "https://")):
        return target
    base = f"{KOMIS_BASE_URL}{target}"
    if page.identity.navigation.method == "GET" and page.identity.navigation.params:
        return f"{base}?{urlencode(page.identity.navigation.params)}"
    return base


def build_recommendation(
    page: PageDefinition,
    *,
    effective_filters: dict[str, Any] | None = None,
    defaulted_filters: dict[str, Any] | None = None,
    missing_required_filters: list[str] | None = None,
) -> RecommendationItem:
    """Build a display-ready recommendation from a page and resolved filters."""

    effective = effective_filters or {}
    defaulted = defaulted_filters or {}
    filter_display = [
        FilterDisplay(
            key=item.semantic_key,
            label=item.label,
            value=effective[item.semantic_key],
            display_value=display_filter_value(
                page,
                item.semantic_key,
                effective[item.semantic_key],
                defaulted=item.semantic_key in defaulted,
            ),
            defaulted=item.semantic_key in defaulted,
        )
        for item in page.filters
        if item.semantic_key in effective
    ]
    missing_keys = set(missing_required_filters or [])
    missing_labels = [item.label for item in page.filters if item.semantic_key in missing_keys]
    return RecommendationItem(
        page_id=page.page_id,
        page_name=page.identity.name,
        section=page.identity.section,
        url=page_url(page),
        navigation_method=page.identity.navigation.method,
        navigation_params=page.identity.navigation.params,
        reason=page.routing.summary,
        suggested_filters=effective,
        defaulted_filters=defaulted,
        filter_display=filter_display,
        missing_required_filters=sorted(missing_keys),
        missing_required_filter_labels=missing_labels,
        available_data=page.outputs.available_data_labels,
        presentation_summary=page.presentation.summary,
        presentation=page.presentation.panels,
        screen_guidance=(
            [control.description for control in page.screen.controls] if page.screen else []
        ),
        caveats=page.policies.caveats,
        login_required=page.identity.login_required,
        external=page.identity.external,
        mutation=page.policies.mutation,
    )


def render_selected(item: RecommendationItem) -> str:
    """Render a single selected page with filters and usage guidance."""

    lines = [
        f"추천 페이지는 `KOMIS > {item.section} > {item.page_name}`입니다.",
        item.reason,
        f"페이지 주소: {item.url}",
    ]
    if item.navigation_method == "POST" and item.navigation_params:
        params = " · ".join(f"{key}={value}" for key, value in item.navigation_params.items())
        lines.append(f"이동 방법: KOMIS 마이페이지에서 `{item.page_name}` 선택 ({params})")
    explicit_filters = [entry for entry in item.filter_display if not entry.defaulted]
    if explicit_filters:
        filters = " · ".join(f"{entry.label} `{entry.display_value}`" for entry in explicit_filters)
        lines.append(f"입력할 필터: {filters}")
    if any(entry.defaulted for entry in item.filter_display):
        defaults = " · ".join(
            f"{entry.label} `{entry.display_value}`"
            for entry in item.filter_display
            if entry.defaulted
        )
        lines.append(f"별도 언급이 없어 적용한 기준: {defaults}")
    if item.missing_required_filter_labels:
        lines.append(f"페이지에서 선택할 값: {', '.join(item.missing_required_filter_labels)}")
    if item.available_data:
        lines.append(f"확인 가능한 데이터: {', '.join(item.available_data)}")
    if item.presentation_summary:
        lines.append(f"화면 구성: {item.presentation_summary}")
    for panel in item.presentation:
        lines.append(f"- {panel.label}: {panel.description}")
    if item.screen_guidance:
        lines.append("화면 사용:")
        lines.extend(f"- {guidance}" for guidance in item.screen_guidance)
    if item.caveats:
        lines.append("확인할 점:")
        lines.extend(f"- {caveat}" for caveat in item.caveats)
    if item.login_required:
        lines.append("이 페이지는 KOMIS 로그인 후 이용할 수 있습니다.")
    if item.external:
        lines.append("KOMIS에서 외부 사이트로 이동하는 서비스입니다.")
    if item.mutation == "account_change":
        lines.append(
            "현재는 이동 경로만 안내하며, 계정 설정 변경은 로그인 후 직접 진행해야 합니다."
        )
    else:
        lines.append(
            "현재는 페이지 안내 단계이므로 실제 수치나 게시물 내용은 원 화면에서 확인해야 합니다."
        )
    lines.append("바로 이동하시겠어요? 위 페이지 주소를 눌러 이동하실 수 있습니다.")
    return "\n".join(lines)


def render_ambiguous(items: list[RecommendationItem]) -> str:
    """Render multiple plausible pages when selection remains ambiguous."""

    lines = ["질문만으로는 페이지를 하나로 확정하기 어려워 관련 페이지를 함께 안내합니다."]
    for item in items:
        login = " 로그인 필요." if item.login_required else ""
        lines.append(f"- `KOMIS > {item.section} > {item.page_name}`: {item.reason}{login}")
        lines.append(f"  주소: {item.url}")
        if item.navigation_method == "POST" and item.navigation_params:
            params = " · ".join(f"{key}={value}" for key, value in item.navigation_params.items())
            lines.append(f"  이동 파라미터: {params}")
    lines.append("설명을 비교한 뒤 원하는 관점의 페이지에서 직접 확인해 주세요.")
    return "\n".join(lines)


def render_relation_ambiguous(item: RecommendationItem) -> str:
    """Ask whether a question continues the prior page or starts a new search."""

    return (
        "이번 질문이 이전 검색을 이어가는 것인지 새로운 페이지를 찾는 것인지 확정하기 "
        f"어렵습니다. 이전에 선택한 페이지는 `KOMIS > {item.section} > {item.page_name}`이며, "
        f"{item.reason} 이어서 확인하려는 조건이나 새로 찾으려는 정보 종류를 알려주세요."
    )


def render_not_found() -> str:
    """Render guidance for a question that matches no registered page.

    2026-09-03(documents/기획문서/order/rag_chatbot/대화형검색시스템 예상질문
    고도화.pdf ①메뉴안내 5문항, 사용자 승인 후 문구 정렬) — 발주처 문서가
    지정한 실패 문구를 그대로 쓴다."""

    return "요청하신 메뉴 경로를 확인하지 못했습니다. 상단 전체메뉴에서 확인해 주십시오."
