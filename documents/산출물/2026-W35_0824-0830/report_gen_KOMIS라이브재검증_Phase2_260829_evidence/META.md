# META — report_gen_KOMIS라이브재검증_Phase2_260829_evidence/

- `collected_iron_other_day_raw_260829.json`: Playwright로 komis.or.kr
  `/Komis/RsrcPrice/IronOre`(철광석 및 에너지: 우라늄·유연탄·철)·
  `/Komis/RsrcPrice/EtcMnrl`(기타: 금·루테늄·백금·은·팔라듐·흑연)을
  라이브 접속해 각 광종×가격기준의 `getMnrlPrcByMnrkndUnqCd`(avgOpt=DAY)
  원본 응답을 캡처(10건, 2026-08-29). 정적 덤프 자체가 없는 페이지라(
  `income_data/komis/MANIFEST.json`에 파일 無) 이게 유일한 실데이터
  검증 근거.
- `collected_minor_spotcheck_raw_260829.json`: price_minor_metals 대표
  스팟체크(리튬·코발트) 라이브 캡처 6건.
- 두 파일 전부 `dataAvg.stdMap.{DAY,WEEK,MONTH,YEAR}` 존재 확인(모든 콤보),
  일별 행의 `invt`(재고량) 필드가 base_metals(6대 LME 전통금속) 외에는
  **전량 "0.00"**임을 확인(신규 발견 — 상위 문서 참고).
- 상위 문서: `report_gen_KOMIS라이브재검증_Phase2_260829.md`.
- 삭제 금지(artifact-provenance-policy).
