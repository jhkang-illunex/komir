"""챗봇 화면 — rag_chat SSE 스트림(status/delta/table/chart/done)을 실시간으로 그린다.
(2026-09-16: `image`(PNG) 이벤트는 서버에서 제거돼 public/private 모두 table 블록 +
chart 스펙으로 온다 — `_render_chart`가 프론트 참고 구현.)

원본(komis-report-generator-main/streamlit_demo/chatbot.py)은 페이지추천 응답
(`SearchResponse`) 하나를 받아 그렸다. komir 챗봇은 문서 Q&A(스트리밍 답변+인용+표/
차트)와 페이지추천(`done{mode:page, recommendations}`) 두 경로가 같은 SSE 계약으로
오므로, 이벤트 종류별로 렌더러를 두고 히스토리에도 같은 조각(텍스트·표·이미지·
인용·추천)을 저장해 rerun 때 동일하게 다시 그린다.

2026-08-28: SSE status 계약이 문자열 stage(routing/retrieving/verifying/
reformulating/generating, `tools` 필드 있음)에서 정수 4단계로 바뀌었다
(`services/rag_chat/app/routers/chat.py`::`_status_event`, `rag_core/ragkit/
chatbot.py`::`STATUS_STAGES`가 정본) — `{"stage": 1|2|3|4, "label": "질문
조건 확인"|"답변 준비중"|"데이터 분석 중"|"답변 생성 중"}`, `label`은 서버가
이미 한글로 포맷해서 보내므로 클라이언트 쪽 매핑 테이블(STAGE_LABELS)이
필요 없어졌다. `tools` 필드도 사라졌다.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import streamlit as st

from streamlit_demo.api_client import ChatEvent, Profile, RagChatClient, RagChatError

_log = logging.getLogger(__name__)

EXAMPLE_QUESTIONS = (
    "니켈 수급위기 진단등급이 어떻게 되나?",
    "니켈 12개월 수입물량 예측을 표와 함께 보여줘",
    "코발트 세계 생산 1위 국가는?",
    "한국 리튬 수입 현황은 어디서 봐?",
)

#: SSE done.abstain_reason → 사용자에게 보여줄 문구(서버는 이 필드를 포맷하지
#: 않고 코드값 그대로 보낸다 — status.label과 달리 클라이언트에서 매핑 필요).
ABSTAIN_REASON_LABELS = {
    "off_topic": "질문이 핵심광물 수급 범위를 벗어남",
    "unsupported_commodity": "지원하지 않는 광종",
    "no_data_for_period": "해당 기간 데이터 없음",
    "ambiguous": "질문이 모호함",
    "unknown": "원인 미상",
    "generation_error": "답변 생성 중 오류",
}


def reset_chat() -> None:
    st.session_state.chat_messages = []
    st.session_state.session_id = None


def render_chatbot(client: RagChatClient, *, profile: Profile, mode: str) -> None:
    _initialize_state()

    st.title("komir 핵심광물 챗봇")
    st.caption(
        f"프로필 **{profile}** ({'라이선스 제한 문서 제외' if profile == 'public' else '전체 코퍼스'}) · "
        f"모드 **{mode}** — 문서 Q&A 는 인용 근거만 답하고, 페이지 안내는 KOMIS 메뉴를 추천합니다."
    )

    selected_example = _render_examples()
    _render_history()

    typed_question = st.chat_input("광종, 수급위기, 수입 예측, KOMIS 메뉴에 대해 질문해 주세요.")
    question = selected_example or typed_question
    if question:
        _submit_question(client, question, profile=profile, mode=mode)
        st.rerun()


def _initialize_state() -> None:
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("session_id", None)


def _render_examples() -> str | None:
    if st.session_state.chat_messages:
        return None
    st.subheader("이렇게 질문해 보세요")
    columns = st.columns(len(EXAMPLE_QUESTIONS))
    for index, (column, question) in enumerate(zip(columns, EXAMPLE_QUESTIONS, strict=True)):
        if column.button(question, key=f"example-question-{index}", use_container_width=True):
            return question
    return None


def _render_history() -> None:
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            _render_assistant_parts(message) if message["role"] == "assistant" else st.markdown(message["content"])


# ---- 한 턴 실행(스트리밍) -------------------------------------------------------

def _submit_question(client: RagChatClient, question: str, *, profile: Profile, mode: str) -> None:
    st.session_state.chat_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    record: dict[str, Any] = {
        "role": "assistant", "content": "", "tables": [], "charts": [],
        "citations": [], "bogus_citations": [], "recommendations": [], "warnings": [],
        "stages": [], "abstained": False, "profile": profile,
    }
    with st.chat_message("assistant"):
        status_box = st.empty()
        text_box = st.empty()
        media_area = st.container()
        try:
            for event in client.chat_stream(
                question, profile=profile, session_id=st.session_state.session_id, mode=mode,
            ):
                _apply_event(event, record, status_box=status_box, text_box=text_box, media_area=media_area)
        except RagChatError as exc:
            _log.exception("rag_chat 호출 실패(profile=%s, mode=%s)", profile, mode)
            status_box.empty()
            record["content"] = f"요청을 처리하지 못했습니다. {exc}"
            text_box.error(record["content"])
        status_box.empty()
    st.session_state.chat_messages.append(record)


def _apply_event(event: ChatEvent, record: dict[str, Any], *, status_box, text_box, media_area) -> None:
    data = event.data
    if event.event == "session":
        st.session_state.session_id = data.get("session_id")
    elif event.event == "status":
        label = data.get("label") or str(data.get("stage", ""))
        record["stages"].append(label)
        status_box.caption(f"⏳ {label}")
    elif event.event == "delta":
        record["content"] += data.get("delta", "")
        text_box.markdown(record["content"] + "▌")
    elif event.event == "table":
        record["tables"].append(data)
        with media_area:
            _render_table(data)
    elif event.event == "chart":
        # 2026-09-13 /prichat 도입 → 2026-09-16 public 공통 — 구조화 차트 블록(PNG
        # 대신 스펙). 데모가 "프론트"로서 스펙을 직접 그려 명세가 실제로 그려지는지
        # 확인한다.
        record["charts"].append(data)
        with media_area:
            _render_chart(data, record.get("tables", []))
    elif event.event == "done":
        text_box.markdown(record["content"] or "_(응답 없음)_")
        record["citations"] = data.get("citations", [])
        record["bogus_citations"] = data.get("bogus_citations", [])
        record["recommendations"] = data.get("recommendations", [])
        record["warnings"] = data.get("warnings", [])
        record["abstained"] = bool(data.get("abstained"))
        record["abstain_reason"] = data.get("abstain_reason")
        record["mode"] = data.get("mode", "document")
        with media_area:
            _render_details(record)


# ---- 조각 렌더러(라이브·히스토리 공용) -------------------------------------------

def _render_assistant_parts(message: dict[str, Any]) -> None:
    st.markdown(message.get("content") or "_(응답 없음)_")
    for table in message.get("tables", []):
        _render_table(table)
    for chart in message.get("charts", []):
        _render_chart(chart, message.get("tables", []))
    _render_details(message)


def _render_table(table: dict[str, Any]) -> None:
    columns, rows = table.get("columns", []), table.get("rows", [])
    caption = f"표 · 근거 [{table.get('source_index')}]" if table.get("source_index") else "표"
    hint = table.get("chart_hint") or {}
    if hint.get("recommended"):
        alternatives = ", ".join(hint.get("alternatives") or [])
        caption += f" · 추천 차트 {hint['recommended']}" + (f" (대안 {alternatives})" if alternatives else "")
    st.caption(caption)
    st.dataframe(pd.DataFrame(rows, columns=columns), hide_index=True, use_container_width=True)


def _render_chart(chart: dict[str, Any], tables: list[dict[str, Any]]) -> None:
    """`chart` 블록 렌더링 — data_ref가 가리키는 table 블록의 rows_typed/
    columns_meta로 DataFrame을 만들고 spec(kind·x·series·group)대로 그린다.
    `group`이 있으면(연도×국가 등) 계열 하나를 구분값별 열로 펼친다. pie는
    streamlit 기본 차트에 없어 bar로 대신 그리고 캡션에만 표시한다."""

    table = next((t for t in tables if t.get("block_id") == chart.get("data_ref")), None)
    spec = chart.get("spec") or {}
    if not table or not spec.get("series"):
        st.warning("차트 블록이 참조하는 표를 찾지 못했습니다.")
        return
    keys = [c["key"] for c in table.get("columns_meta", [])]
    frame = pd.DataFrame(table.get("rows_typed", []), columns=keys)
    x, group = spec.get("x"), spec.get("group")
    series = [k for k in spec["series"] if k in frame.columns]
    if group in frame.columns and x in frame.columns and series:
        frame = frame.pivot_table(index=x, columns=group, values=series[0], aggfunc="first")
        series = list(frame.columns)
    elif x in frame.columns:
        frame = frame.set_index(x)
    if spec.get("sort_x_ascending"):
        frame = frame.sort_index()
    caption = f"차트(블록·{spec.get('kind')}) · {spec.get('title', '')}"
    if chart.get("source_index"):
        caption += f" · 근거 [{chart['source_index']}]"
    st.caption(caption)
    if spec.get("kind") == "line":
        st.line_chart(frame[series])
    else:
        st.bar_chart(frame[series])


def _render_details(record: dict[str, Any]) -> None:
    if record.get("abstained"):
        reason = record.get("abstain_reason")
        reason_label = ABSTAIN_REASON_LABELS.get(reason, reason)
        if reason == "generation_error":
            message = "근거는 찾았으나 답변 생성 중 오류가 발생해 응답이 중단됐습니다."
        else:
            message = "근거를 찾지 못해 기권한 응답입니다."
            if reason_label:
                message += f" (사유: {reason_label})"
        st.info(message)
    citations = record.get("citations") or []
    if citations:
        with st.expander(f"인용 근거 {len(citations)}건", expanded=False):
            for item in citations:
                meta = " · ".join(
                    str(item[key]) for key in ("as_of", "unit") if item.get(key)
                )
                st.markdown(
                    f"**[{item.get('index')}]** `{item.get('kind')}` {item.get('source')} — "
                    f"{item.get('section')}{(' (' + meta + ')') if meta else ''}"
                )
    bogus = record.get("bogus_citations") or []
    if bogus:
        st.warning(f"근거 범위를 벗어난 인용번호가 제거됐습니다: {bogus}")
    recommendations = record.get("recommendations") or []
    if recommendations:
        with st.expander("추천 메뉴", expanded=True):
            for rec in recommendations:
                st.markdown(f"**{rec.get('section')} › {rec.get('page_name')}**  \n{rec.get('reason', '')}")
                filters = _filter_summary(rec.get("filter_display") or [])
                if filters:
                    st.caption(f"적용 기준 · {filters}")
                if rec.get("url"):
                    st.link_button(f"{rec.get('page_name')} 열기", rec["url"], use_container_width=True)
    for warning in record.get("warnings") or []:
        st.warning(warning)
    stages = record.get("stages") or []
    if stages:
        st.caption("진행 단계: " + " → ".join(stages))


def _filter_summary(filters: list[dict[str, Any]]) -> str:
    return " · ".join(f"{item.get('label')} {item.get('display_value')}" for item in filters)
