"""수급위기진단 · 수요예측 — stub(2026-08-27).

붙일 대상: `services/commodity_api`(`/commodities/{cc}/diagnosis`, `/forecast`,
`/geo-index`) — 구 `dashboard_expire/streamlit_app.py`(모델 재현·설명가능성 데모)의
로직이 그 API 로 이식돼 있으므로, 이 화면은 API 호출 결과를 그리는 쪽으로 만든다
(모델을 다시 재적합하지 않는다).

2026-08-27 사용자 피드백(main-agent 경유): 화면 문구(st.info/st.markdown)에
내부 구현 용어(API 경로·엔드포인트명·yhat·SHAP 등)나 파일 경로가 그대로
노출돼 있었다 — 개발 계획·연동 대상 메모는 이 docstring에만 남기고, 화면
문구는 일반 사용자가 읽는 안내문으로 분리했다. 구 `dashboard_expire/
streamlit_app.py`의 설명가능성(SHAP) 화면 이식 여부는 아직 별도 결정 전.
"""
from __future__ import annotations

import streamlit as st

st.title("수급위기진단 · 수요예측")
st.info(
    "준비 중입니다 — 5개 핵심광물(구리·니켈·코발트·리튬·희토류)의 수급위기 진단 등급과 "
    "12개월 수입 예측을 곧 이 화면에서 확인하실 수 있습니다.",
    icon=":material/construction:",
)
st.markdown(
    """
- 광종을 선택하면 최신 진단 등급·위험 점수와 최근 위기지수 추이를 보여드립니다.
- 앞으로 12개월간의 수입 물량·금액 예측을 그래프로 보여드립니다.
- 예측 근거를 더 자세히 볼 수 있는 화면 추가는 검토 중입니다.
"""
)
