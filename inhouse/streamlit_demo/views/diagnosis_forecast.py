"""수급위기진단 · 수요예측 — stub(2026-08-27).

붙일 대상: `services/commodity_api`(`/commodities/{cc}/diagnosis`, `/forecast`,
`/geo-index`) — 구 `dashboard_expire/streamlit_app.py`(모델 재현·설명가능성 데모)의
로직이 그 API 로 이식돼 있으므로, 이 화면은 API 호출 결과를 그리는 쪽으로 만든다
(모델을 다시 재적합하지 않는다).
"""
from __future__ import annotations

import streamlit as st

st.title("수급위기진단 · 수요예측")
st.info("준비 중 — 5광종 진단 등급(4단계 경보)·12개월 수입 예측·지정학 위기지수를 commodity_api 로 조회해 표시할 화면입니다.", icon=":material/construction:")
st.markdown(
    """
- 광종(CU/NI/CO/LI/REE) 선택 → 최신 진단 등급·위험점수·사유, 주간 위기지수 추이
- 12개월 수입물량/금액 예측(yhat·구간) 차트
- 구 `dashboard_expire/streamlit_app.py` 의 설명가능성(SHAP) 화면 이식 여부는 별도 결정
"""
)
