# -*- coding: utf-8 -*-
"""정형(RDB) 검색 — 설계 단계 스켈레톤, 완전 신규 개발(기존 rag/README.md가 "구조화
데이터 질문은 스코프 밖"으로 명시적으로 뺐던 부분).

TODO(구현 단계, docs/CONTAINER_ARCHITECTURE.md §5 권고안): 1차는 템플릿 질의만
구현(LLM은 템플릿+파라미터 선택만 담당, 자유형 SQL 생성 금지 — 인젝션·환각 리스크).
템플릿 예시:
  - "{cc} 현재 등급?" → SELECT ... FROM out_diagnosis_alert WHERE commodity_code=:cc
    ORDER BY obs_date DESC LIMIT 1
  - "{cc} 12개월 물량 예측?" → out_import_forecast 조회
  - "{cc} 최근 위기지수?" → geo_index 조회
자유형 NL→SQL(2차 후보)은 읽기전용 계정+화이트리스트 없이는 구현하지 않는다.
"""
raise NotImplementedError("설계 단계 스켈레톤 — 구현은 다음 세션(docs/CONTAINER_ARCHITECTURE.md §8)")
