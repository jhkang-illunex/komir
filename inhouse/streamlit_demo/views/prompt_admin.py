"""프롬프트 관리 — stub(2026-08-27).

붙일 대상: Postgres `ai_cfg.cfg_prompt`(report_gen 분석요약 LLM 프롬프트, 페이지별
8종 + 공통 1종 + price_group). report_gen 은 기동 시 또는 `POST /admin/prompts/reload`
호출 시에만 캐시를 갱신하므로, 편집 저장 후 reload 호출까지가 한 세트다.
"""
from __future__ import annotations

import streamlit as st

st.title("프롬프트 관리")
st.info("준비 중 — ai_cfg.cfg_prompt 의 프롬프트를 열람·편집·저장하고 report_gen 캐시를 다시 읽게 하는 화면입니다.", icon=":material/construction:")
st.markdown(
    """
- 프롬프트 목록(page_id별) 열람 · 버전/수정시각 표시
- 편집 → 저장(`ai_cfg.cfg_prompt` upsert) → `POST /admin/prompts/reload`
- 챗봇 쪽 프롬프트(route/verify/reformulate/SYSTEM_PROMPT)는 현재 코드 상수 — DB화 여부는 미정
"""
)
