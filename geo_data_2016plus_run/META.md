# META — geo_data_2016plus_run (2016+ 전체 코퍼스 실행 결과, 보존 지시됨 — 삭제 금지)
- 생성: 2026-07-07~08. documents/ 2016년 이후 보고서 2,385건 + 날짜해결 추가 427건 = 2,812건 투입
- 파이프라인: ingest(opendataloader 배치 → pypdf 폴백 → easyocr 캐시) → extract(vLLM gemma, 동시 8)
- 결과: archived 2,796 / 이벤트 6,510건 / PDF 텍스트확보 100%(odl 97.9%+pypdf 2.1%+ocr 2건)
- 주요 파일: store/manifest.parquet(전체 상태·pub_date_method), store/geo_events.parquet,
  store/pdf_extract_method.parquet(방법별 로그), store/geo_index.parquet(2,087행),
  _ocr_cache/(OCR 결과, 파일해시 키), run.log~run4.log(실행·버그수정 과정 전체)
- 상세: 데이터수집현황 §9~§11, WORKLOG 2026-07-07~08
