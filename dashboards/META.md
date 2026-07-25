# META — 수급위기 진단 대시보드 (프로토타입, 산출물 ③의 선행)
- 생성: 2026-07-12. 갱신: 2026-07-25(보조 신호 노출). 발행: https://claude.ai/code/artifact/a6179ec1-bdc3-4377-9786-d160aa85c16c
- 내용: 5광종 요약 카드(최신 단계·신뢰도·**전환 조기경보 배지**) / **보조 신호 패널**
  (전환 조기경보 방향·방향확률 미니바 + 지정학 급증확률 적응형·고정형 병기, 2026-07-25
  신챔피언 운영 반영 v1.19의 소비자측 마감) / 주간 위기지수 차트(2020~, 단계 리본·지정학
  지수 오버레이·지수 재앵커(v3) 경계 마커·주 선택) / 선택 주 법정 사유 / 최신월 XAI /
  최근 16주 이력 테이블.
- 데이터: warehouse의 out_diagnosis_alert·mart_diagnosis_nowcast·geo_index(주간,
  월요일 앵커 +1일 보정)·**out_aux_early_warning**·**geo_prob.p_burst_adapt** 스냅샷을
  인라인 임베드(자체완결 HTML, 외부 의존 0 — 폐쇄망 게시 가능).
- 재생성: `MSR_DB=<warehouse> python3 dashboards/build_dash.py` (2026-07-25 스크립트화 —
  구 방식의 WORKLOG 수동 쿼리 대체. 주의: 구 스냅샷은 지수 주간이 일요일 앵커라 차트
  오버레이가 전부 미매칭이던 잠재 버그가 있었음 — build_dash가 +1일 보정으로 해소).
