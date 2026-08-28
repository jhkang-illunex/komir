# META — report_gen_KOMIS라이브재검증_Phase1_260828_evidence/

- `recollected_base_metals_day_raw_260828.json`: Playwright로 komis.or.kr을
  라이브 접속해 재수집한 동/아연/알루미늄/연/주석(5광종) × 가격기준별
  `getMnrlPrcByMnrkndUnqCd`(avgOpt=DAY) 원본 응답 11건. 정적 덤프
  `income_data/komis/komis_01_base_metals.json`(git 미추적, 로컬 전용)의
  0행 공백을 이 파일 내용으로 패치했다 — 원본 komis_01_base_metals.json
  자체는 gitignore 영역이라 레포에 없고, 이 원천 캡처만 보존한다.
- `harness_summary_260828.json`: 패치 후 `komis_dump_smoke_test.py` 재실행
  결과 요약(페이지별 count/ok/no_data/internal_error/mismatches).
  `internal_errors: 58→0`, 전 페이지 `mismatches: 0`.
- `harness_sample_entries_260828.json`: 대표 표본 2건(동|LME 3개월,
  가돌리늄) 전체 결과(request/expected/key_metrics/report_markdown) —
  동 표본은 스크린샷(-0.70%/+0.98%/+5.11%/+42.84%)과 정확히 일치.
- 상위 문서: `report_gen_KOMIS라이브재검증_Phase1_260828.md`.
- 삭제 금지(artifact-provenance-policy).
