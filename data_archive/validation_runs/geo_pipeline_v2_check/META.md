# META — geo_pipeline_v2_check (파이프라인 v2 검증: opendataloader+OCR+LLM)
- 생성: 2026-07-07, 동일 10샘플로 `geo ingest`(opendataloader 배치+easyocr 폴백) → `extract`(vLLM gemma, 동시 8)
- 결과: archived 10/10(스캔본 광업요람도 OCR로 텍스트 확보), 관련문서 7건 → 이벤트 29건(LLM)
- 당시 코드: extractors.py(opendataloader_batch_convert/ocr_pdf_text 신설), ingest.py(precompute_pdf_texts),
  config/models.yaml(provider=openai_compat 전환), extract.py(ThreadPoolExecutor)
- 상세: 데이터수집현황 §9 도입부, WORKLOG 2026-07-07
