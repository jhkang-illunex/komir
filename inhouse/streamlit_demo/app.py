"""komir 개발 데모 — Streamlit 멀티페이지 엔트리포인트(st.navigation).

실행:
    KOMIR_RAG_CHAT_BASE_URL=http://localhost:18002 streamlit run inhouse/streamlit_demo/app.py

페이지는 `views/` 아래 파일 하나가 화면 하나다(2026-08-27 멀티페이지 전환). 지금
실제로 동작하는 건 챗봇(`views/chat.py`)뿐이고 나머지 넷은 자리만 잡아둔 stub —
각 stub 파일 상단에 그 화면이 보여줄 내용을 적어뒀다. 공통 사이드바(rag_chat
연결 상태)는 여기서 그리고, 페이지 전용 컨트롤(챗봇의 프로필·모드 등)은 각
view 가 자기 사이드바 구역에 덧붙인다.

`st.set_page_config` 는 엔트리포인트에서만 부른다(view 파일에서 부르면 오류).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Streamlit 은 이 파일을 스크립트로 실행하므로(패키지 컨텍스트 없음) inhouse/ 를
# sys.path 에 넣어 `streamlit_demo.*` 절대 import 가 cwd 와 무관하게 동작하게 한다.
# view 파일들은 같은 프로세스에서 실행되므로 여기서 한 번 넣으면 전부 보인다.
# (view 는 이 파일을 import 하면 안 된다 — set_page_config/navigation 이 중복 실행됨.
#  공유 헬퍼는 api_client.client_from_env() 처럼 별도 모듈에 둔다.)
_INHOUSE_ROOT = Path(__file__).resolve().parents[1]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

from shared.logging_config import configure_logging  # noqa: E402

# 2026-08-28 사용자 지적("LLM 경과 같은 부분은 로깅으로 기록") 대응 — 지금까지
# streamlit_demo 는 오류를 st.error/st.warning으로 화면에만 보여주고 서버 콘솔
# 로그가 전혀 없었다(report_gen·rag_chat과 같은 공통 모듈 재사용, 중복 설정 방지
# 위해 프로세스당 1회만 적용되도록 이미 멱등 처리돼 있음). 엔트리포인트에서 한 번
# 부르면 이후 실행되는 모든 view 의 `logging.getLogger(__name__)` 가 이 설정을
# 물려받는다.
configure_logging()

import streamlit as st  # noqa: E402

from streamlit_demo.api_client import client_from_env  # noqa: E402

st.set_page_config(
    page_title="komir 개발 데모",
    page_icon="⛏️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { max-width: 1080px; padding-top: 2.5rem; padding-bottom: 3rem; }
    [data-testid="stSidebar"] { border-right: 1px solid rgba(128, 128, 128, 0.2); }
    </style>
    """,
    unsafe_allow_html=True,
)


_VIEWS = Path(__file__).resolve().parent / "views"

pages = st.navigation(
    {
        "AI 서비스": [
            st.Page(str(_VIEWS / "chat.py"), title="챗봇", icon=":material/chat:", default=True),
            st.Page(str(_VIEWS / "report_demo.py"), title="요약보고서 데모", icon=":material/summarize:"),
            st.Page(str(_VIEWS / "diagnosis_forecast.py"), title="수급위기진단 · 수요예측", icon=":material/monitoring:"),
        ],
        "관리": [
            st.Page(str(_VIEWS / "prompt_admin.py"), title="프롬프트 관리", icon=":material/tune:"),
            st.Page(str(_VIEWS / "data_admin.py"), title="데이터 관리", icon=":material/database:"),
            st.Page(str(_VIEWS / "etl_status.py"), title="ETL 처리 현황", icon=":material/sync_alt:"),
        ],
    }
)

with st.sidebar:
    st.caption("운영 화면이 아닌 개발·시연용 데모입니다.")
    client = client_from_env()
    if client.health():
        st.success(f"rag_chat 연결됨 · {client.base_url}", icon=":material/check_circle:")
    else:
        st.error(f"rag_chat 연결 안 됨 · {client.base_url}", icon=":material/error:")

pages.run()
