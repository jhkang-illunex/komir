# META — report_gen 풀 검증(2026-09-13)

- **생성 배경**: 사용자가 "검증을 요청할때 마다 이런식으로 오류를 찾아 내면 내가
  검증된거라고 어떻게 믿어... 제대로 다시 풀 검증해"라고 명시적으로 요구. 슬라이드
  (pptx) 편집 검증이 아니라 report_gen 서비스 자체의 핵심 계산 로직을 전수 검증.
- **재현 명령**:
  ```bash
  cd komir/inhouse/report_gen
  python3 /path/to/full_verify.py   # 이 폴더의 full_verify.py
  ```
  `D`(income_data/komis 덤프 경로)·`PHASE2`(Phase2 우라늄·흑연 등 덤프 경로)는
  스크립트 상단에 절대경로로 고정돼 있음.
- **원칙(advisor 검토 반영)**: expected(정답) 쪽은 이 스크립트 안에서 새로 작성한
  코드로만 raw KOMIS JSON을 읽는다(report_gen의 `input_data.py` 파서나 기존
  `komis_dump_smoke_test.py`의 `adapt_*` 함수를 재사용하지 않음 — 재사용하면 그
  전처리의 버그가 그대로 "정답"이 돼 통과되는 위험이 있음, 실제로 map_korea에서
  있었던 일). actual(실제) 쪽은 `AnalysisSummaryRequest(komis_response=...)` 패스
  스루로만 호출 — 이것이 실 라우터가 실제로 받는 유일한 입력 모양.
- **커버리지**: 715개 (page_id, 아이템) 조합, 3,465개 독립 재계산 체크.
  price_base_metals(174)·price_minor_metals(1867, 692개 관측치×avg옵션 5종 조합
  포함)·price_iron_energy(9)·price_other(21)·indicator_market(72, 광종 36개
  전부)·indicator_supply(69)·map_korea(435, 광종×수입/수출 전부)·map_global(292)·
  map_mineral(526, 광종×매장량/생산량 전부) — 표본 1건이 아니라 해당 덤프에 있는
  모든 항목.
- **결과 파일**: `full_verify_result.json` — page_id별 집계(`summary`)와 불일치
  전체 목록(`fails`), 체크 전체 원본(`all`) 포함.
- **발견·조치**: 본문 보고서(`report_gen_풀검증_보고서_260913.md`) 참고. 실제
  발견된 버그 2건 중 1건(map_mineral 300자 초과)은 이 세션에서 즉시 수정·재검증
  완료, 1건(price 시리즈 avg_opt≠DAY일 때 현재가·등락률 기준 불일치)은 제품
  설계 결정이 필요해 수정하지 않고 사용자에게 보고.
- **삭제 금지**: `artifact-provenance-policy` 메모리 원칙에 따라 이 evidence
  폴더는 삭제하지 않는다.
