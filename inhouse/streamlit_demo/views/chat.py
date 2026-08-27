"""챗봇 페이지 — rag_chat /pubchat·/prichat SSE 를 실시간으로 그린다.

렌더링 로직은 `streamlit_demo/chatbot.py`(원본 komis-report-generator-main 이식본)에
있고, 이 view 는 페이지 전용 사이드바 컨트롤(프로필·모드·새 대화·세션 정보)만
덧붙여 그 함수를 부른다. 공통 사이드바(서버 연결 상태)는 app.py 가 그린다.
"""
from __future__ import annotations

import streamlit as st

from streamlit_demo.api_client import ENDPOINT_BY_PROFILE, client_from_env
from streamlit_demo.chatbot import render_chatbot, reset_chat

with st.sidebar:
    st.divider()
    profile = st.radio(
        "프로필",
        ("public", "private"),
        index=0,
        format_func=lambda p: f"{p}  ({ENDPOINT_BY_PROFILE[p]})",
        help="public: 라이선스 제한 문서(Argus) 제외 · private: 전체 코퍼스. 두 프로필은 같은 대화 세션을 공유합니다.",
    )
    mode = st.selectbox(
        "모드",
        ("auto", "document", "page"),
        index=0,
        help="auto: 의도분류 LLM 이 문서 Q&A / 페이지 안내를 고름",
    )
    if st.button("새 대화", icon=":material/add_comment:", use_container_width=True):
        reset_chat()
        st.rerun()
    session_id = st.session_state.get("session_id")
    if session_id:
        with st.expander("세션 정보"):
            st.code(session_id, language=None)

render_chatbot(client_from_env(), profile=profile, mode=mode)
