# META — live_copper_lme3m_getMnrlPrcByMnrkndUnqCd_raw_260828.json

- **생성**: 2026-08-28, Playwright(Chromium)로 komis.or.kr/Komis/RsrcPrice/BaseMetals를
  라이브 접속(비철금속 > 동 > LME 3개월)해 `#btnSearch` 클릭 시 발생하는 모든
  XHR 응답을 `page.on("response")`로 가로채 raw JSON 그대로 저장.
- **재현 스크립트**: 세션 스크래치 `live_copper_capture.py`(레포에 커밋 안 함,
  1회성 조사 스크립트 — 필요 시 이 문서의 절차대로 재작성 가능).
- **정본 아님**: 조사 증거 스냅샷. 실제 요청/응답 캡처 시점의 raw 값이며
  이후 KOMIS 데이터가 갱신되면 재현 시 수치가 달라진다.
- **핵심 발견 위치**: 배열 인덱스 `[3]`(페이지 최초 로드 시 기본값, 니켈·LME
  CASH)과 `[5]`(동 라디오 선택 + LME 3개월 select + 검색 버튼 클릭으로 실제
  트리거된 것, 스크린샷과 동일 조건)의 `body.dataAvg.stdMap` — `DAY`/`WEEK`/
  `MONTH`/`YEAR` 키에 KOMIS가 서버에서 미리 계산한 등락 비교값
  (`flctnPrc`/`flctnPrcnt`)이 들어있다. `[5]`의 값이 스크린샷 4개 수치와
  정확히 일치(DAY -0.70%, WEEK +0.98%, MONTH +5.11%, YEAR +42.84%).
  상위 문서(`report_gen_price_base_metals_부실요약_원인조사_260828.md`) 참고.
- 삭제 금지(artifact-provenance-policy).
