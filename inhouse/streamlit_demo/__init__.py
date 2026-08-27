"""komir 챗봇 개발·시연용 Streamlit 클라이언트(운영 화면 아님).

`mine_ws/komis-report-generator-main/streamlit_demo/`를 2026-08-27 이식했다. 원본은
komis-report-generator 의 `/api/v1/chatbot/query`(JSON 단발, 페이지추천 전용)를
불렀지만, komir 챗봇(`services/rag_chat`)은 `/pubchat`·`/prichat` SSE 스트림
(session → status* → delta* → table*/image* → done)이라 클라이언트·렌더링을 그
계약에 맞춰 다시 썼다. 원본의 분석요약 탭(`analysis.py`)은 이식하지 않았다 —
report_gen 분석 API 가 2026-08-26 에 요청(observations 바디)·응답(status+MD) 계약을
전부 바꿔 옛 화면이 그대로 붙지 않는다(별도 작업).

2026-08-27 멀티페이지(st.navigation)로 전환 — `app.py` 가 엔트리포인트, 화면은
`views/*.py` 하나가 페이지 하나: chat(동작) · report_demo · prompt_admin ·
diagnosis_forecast · data_admin(넷은 stub, 각 파일 상단에 붙일 대상·보여줄 내용 명시).

실행(cwd 무관, app.py 가 inhouse/ 를 sys.path 에 넣는다):
    KOMIR_RAG_CHAT_BASE_URL=http://localhost:18002 streamlit run inhouse/streamlit_demo/app.py
"""
