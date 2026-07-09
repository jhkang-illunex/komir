# META — geo_ingest_check_260707 (샘플 10건 파이프라인 검증)
- 생성: 2026-07-07, 격리 GEO_DATA에서 `python -m geo ingest` → `extract --provider rule`
- 목적: classify.py(날짜/발행처/광종)·llm/rule.py(국지창 광종탐지, war/quota 단어경계) 버그 수정 검증
- 입력: documents/ 대표 10건(조달청 4개 날짜형식·WoodMac니켈·IEA·EU SCRREEN코발트·Argus·AsianMetal리튬·광업요람2024)
  — 원본 PDF는 documents/에 있으므로 여기엔 추출텍스트(.txt)만 tgz로 보존
- 결과: archived 9 + empty 1(광업요람=스캔본, 당시 OCR 미구현) / 이벤트 14건(war 오탐 제거 후)
- 상세: 지정학위기지수_데이터수집현황_260707.md §7-4·§7-5
