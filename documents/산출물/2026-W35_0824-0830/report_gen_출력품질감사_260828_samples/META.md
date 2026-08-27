# report_gen 출력 품질 감사 — 라이브 응답 표본 (2026-08-28)

## 무엇인가
`report_gen_출력품질감사_260828.md`(같은 주차 폴더)의 Phase 1 증거 원본. 12개
page_id 각각 2~3개 variant, 총 26건의 `POST /api/v1/analysis/*` 응답을 그대로 저장.
`_index.json`이 파일 목록·page_id 매핑을 담는다.

## 생성 방법(재현)
- 대상: `komir-report-gen-test` 컨테이너(포트 18003, 2026-08-28 12종 page_id 코드
  빌드 — Phase 0에서 `/prices/iron-energy`·`/price-group` 200 응답으로 최신 확인).
- 방법: `curl -X POST http://localhost:18003/api/v1/analysis/<path>` 를 **순차**
  실행(병렬 호출 시 `analysis_lock` 경합으로 가짜 TIMEOUT 발생 가능 — 실제로 순차
  진행해 TIMEOUT 0건).
- payload: `inhouse/streamlit_demo/report_gen_client.py::PAGE_SPECS[<page_id>]
  .observations_example`을 base variant로, 관측치를 3~4건으로 늘리거나 극단값·
  희소값으로 바꾼 것을 variant로 사용(각 파일 `request` 필드에 실제 보낸 payload
  그대로 보존).
- 각 파일 스키마: `{"request": {...보낸 payload...}, "http_status": 200,
  "response": {"status": "ok"|"NO_DATA"|..., "report": "<Markdown 또는 null>"}}`.

## 판정 근거
파일명의 판정(정상/개선필요)은 `report_gen_출력품질감사_260828.md` 본문에 있다 —
이 폴더는 원자료 보존용이고, PDF 템플릿(`AI 통계분석 요약 답변_광물가격전망지표.pdf`,
`AI 통계분석 요약답변_수급지도광물지도.pdf`) 대비 문장 품질 판정은 본문 참고.

## 주의
- LLM 정제 결과는 비결정적이라(temperature 0이어도 vLLM 배치 영향) 같은 payload를
  재실행하면 문장이 달라질 수 있다 — `llm_refined` 여부는 이 표본에 없다(공개
  계약 `{status,report}`만 담음). 필요하면 `docker exec -w /app -e PYTHONPATH=/app
  komir-report-gen-test python -c "..."`로 `AnalysisSummaryService.analyze()`를
  같은 request로 재호출해 확인할 것([[report_gen_llm_required_evidence_priority_260828]]
  기법).
- artifact-provenance-policy 적용 — 삭제 금지.
