# META — 수급위기 진단 대시보드 (프로토타입, 산출물 ③의 선행)
- 생성: 2026-07-12. 발행: https://claude.ai/code/artifact/a6179ec1-bdc3-4377-9786-d160aa85c16c
- 내용: 5광종 요약 카드(최신 단계·신뢰도) / 주간 위기지수 차트(2020~, 단계 리본·지정학 지수
  오버레이·주 선택) / 선택 주 법정 사유(모델 원천·확률·기여 병기) / 최신월 XAI(단계 확률 스택바
  + 기여도 다이버징 바) / 최근 16주 이력 테이블.
- 데이터: warehouse의 out_diagnosis_alert(주간 1,632행)·mart_diagnosis_nowcast(XAI)·
  geo_index(주간) 스냅샷을 인라인 임베드(자체완결 HTML, 외부 의존 0 — 폐쇄망 게시 가능).
- 재생성: template의 __DATA__를 새 스냅샷 JSON으로 치환(생성 쿼리는 WORKLOG 2026-07-12 참고).
