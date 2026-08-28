# META — report_gen_KOMIS라이브재검증_Phase3_260829_evidence/

- `map_korea_live_capture_260829.json`: Playwright로 `/Komis/MnrlMap/Korea`
  (동 검색)에서 캡처한 전체 JSON XHR 7건 — `getListKoreaData`(국가별 목록,
  `sumIncmAmt`/`sumExpAmt` 반복 필드 포함)·`getLineChartDataKorea`(연도별
  총액 시계열, 2022~2026)·`getListMapKoreaData`(지도 데이터, 같은 sum 필드).
- `map_global_live_capture_260829.json`: `/Komis/MnrlMap/Nation`(동 검색)
  캡처 7건 — `getListDataNation`(양자루트 목록, `sumAmt`/`sumWeig`·1위 루트
  자체 계산된 `amtRate`/`weigRate` 포함)·`getBarChartDataNation`(국가별
  연도 시계열 차트, top-N만).
- `map_mineral_live_capture_260829.json`: `/Komis/MnrlMap/MnrlMap`(동 검색)
  캡처 — positive control(총액 처리가 이미 올바른 패턴, `totalBurudgQuty`
  현재도 존재 확인).
- `total_truncation_gap_stats_260829.json`: 정적 덤프(`income_data/komis/
  komis_06_supply_map_korea.json`·`komis_07_supply_map_global.json`,
  gitignore 영역이라 이 통계 파일이 유일한 레포 내 증거) 전체 콤보에 대해
  "list 가시행 합" vs "KOMIS sum 필드"의 갭%를 전수 계산한 원본 배열 —
  map_korea 146콤보, map_global 73콤보.
- 상위 문서: `report_gen_KOMIS라이브재검증_Phase3_260829.md`.
- 삭제 금지(artifact-provenance-policy).
