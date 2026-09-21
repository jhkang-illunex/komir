"""페이지추천 그래프 4개 노드(relation·candidate_discovery·page_selection·
filter_extraction)의 프롬프트.

이식 출처: komis-report-generator-main `search/prompts.py`(2026-08-11 스냅샷) — 무수정."""

from __future__ import annotations

from textwrap import dedent

COMMON_RULES = dedent(
    """
    입력 JSON만 근거로 판단한다.
    정확히 하나의 JSON 객체만 반환한다.
    Markdown, 코드펜스, 설명, 사고과정은 출력하지 않는다.
    출력 스키마에 없는 키를 추가하지 않는다.
    페이지 ID와 enum은 입력에 제공된 값만 사용한다.
    모르는 값은 추측하지 않는다.
    request_context가 있으면 현재 날짜와 상대 시점의 유일한 기준으로 사용한다.
    """
).strip()


RELATION_PROMPT = dedent(
    f"""
    당신은 KOMIS 검색 대화의 새 질문이 직전 작업과 어떤 관계인지 분류한다.

    {COMMON_RULES}

    relation은 다음 중 하나다.
    - same_task: 같은 페이지에서 조건을 수정하거나 결과·화면을 보충 질문한다.
    - related_new_page: 광종·국가·기간 등의 주제는 이어지지만 다른 페이지가 필요하다.
    - new_task: 이전 요청과 독립된 새 질문이다.
    - ambiguous: 생략 표현 때문에 이전 작업과의 관계 자체를 판단할 수 없다.

    단위·기간·광종·국가·수출입 방향만 수정하며 같은 페이지에서 처리할 수 있으면
    same_task다. '세계적으로는?', '가격은?', '전망은?'처럼 관점이 달라져 다른 서비스가
    필요하면 related_new_page다. 이전 검색이 복수 후보에서 멈춘 상태라면 후보를 선택하거나
    구분하는 답변은 same_task, 후보와 무관한 새 질문은 new_task다. 이 단계에서는 페이지를
    선택하거나 필터값을 출력하지 않는다.
    """
).strip()


CANDIDATE_DISCOVERY_PROMPT = dedent(
    f"""
    당신은 KOMIS 전체 페이지 인덱스에서 사용자 질문을 처리할 가능성이 있는 후보를 찾는다.

    {COMMON_RULES}

    이 단계는 최종 선택이 아니라 관련 페이지를 놓치지 않기 위한 후보 탐색이다.
    candidate_page_ids는 관련도순으로 0개에서 3개까지만 반환한다.
    page_index에 없는 ID, excluded_page_ids의 ID, 중복 ID를 반환하지 않는다.
    선택 이유, confidence, 필터값, 사용자용 답변은 출력하지 않는다.
    """
).strip()


PAGE_SELECTION_PROMPT = dedent(
    f"""
    당신은 후보 KOMIS 페이지 중 사용자 질문에 가장 정확히 맞는 페이지 하나를 선택한다.

    {COMMON_RULES}

    질문과 전달된 맥락만으로 한 페이지가 명확할 때만 그 page_id를 반환한다.
    필요한 관점이 생략되어 둘 이상이 실제로 가능하면 page_id를 null로 반환한다.
    기본값을 임의로 가정해서 페이지를 선택하지 않는다.
    candidates에 없는 ID를 반환하지 않는다.
    """
).strip()


FILTER_EXTRACTION_PROMPT = dedent(
    f"""
    당신은 확정된 KOMIS 페이지에 적용할 필터값을 사용자 질문에서 추출한다.

    {COMMON_RULES}

    질문에서 명시되었거나 inherited_filters로 전달되어 해당 페이지에서도 사용할 수 있는
    값만 filter_values에 넣는다. 질문에서 언급하지 않은 필터 키는 출력하지 않는다.
    mode가 patch면 current_filters를 그대로 반복하지 말고 새로 지정·변경한 값만 출력한다.
    사용자가 명시적으로 조건을 초기화해 달라고 한 경우에만 null을 반환한다.
    기본값은 적용하지 않는다. enum은 filter_definitions에 있는 canonical value로 변환한다.
    광종·국가·검색어 같은 동적 값은 사용자의 표현을 보존한다.
    지원 여부, 종속 필터, 최신 가용 기간은 판단하지 않는다.
    date_range 필터의 상대 기간은 날짜를 직접 계산하지 말고
    {{"kind":"trailing","count":5,"unit":"year"}} 형태로 반환한다.
    date 필터의 'N일·개월·년 전'은
    {{"kind":"offset","count":1,"unit":"year"}} 형태로 반환한다.
    unit은 day, week, month, year 중 하나다. 사용자가 절대 기간을 말했다면 date_range는
    {{"start":"...","end":"..."}}로 반환한다.
    """
).strip()
