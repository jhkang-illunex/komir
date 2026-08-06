# -*- coding: utf-8 -*-
"""광종 리스트 API 엔트리 — 설계 단계 스켈레톤.

TODO(구현 단계):
  1) dashboards/streamlit_app.py의 load_geo/load_diagnosis_level/load_diagnosis_alert/
     load_delta_ew/load_forecast 로직을 그대로 옮겨 라우터에 연결(재구현 금지 — 이미
     검증됨: AppTest 헤드리스 검증 통과 이력 있음).
  2) st.cache_data가 하던 "DB mtime 기준 캐시"는 API 서버에서는 in-memory TTL 캐시
     (예: cachetools)나 요청마다 재계산 중 택1 결정 필요 — 예측 조회는 conformal
     보정 포함 시 수 분 걸리므로 캐시 필수.
  3) 성공 기준: 기존 Streamlit 데모와 동일 광종·동일 시점 조회 시 수치 일치(회귀 없음).
"""
raise NotImplementedError("설계 단계 스켈레톤 — 구현은 다음 세션(docs/CONTAINER_ARCHITECTURE.md §8)")
