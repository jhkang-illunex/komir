# report_gen 분석요약 API — OpenAPI + Postman 컬렉션 (2026-09-17)

컨테이너 `komir-report-gen-test`(이미지 `komir-report-gen:260916-plain6`, main HEAD
f9db0bc31 — table 키 분리+평문 포맷터 등 어제 반영분 전부 포함)에서 그대로 받았다.

- `openapi.json` — `GET /openapi.json` 원본 그대로.
- `report_gen_분석요약.postman_collection.json` — Postman v2.1. `{{base_url}}` 변수
  기본값 `http://localhost:18003`. 3개 폴더(광물자원가격/광물전망지표/수급·광물지도)
  아래 20개 요청.

## 요청 바디 출처

전부 값을 새로 만들지 않고 `documents/산출물/2026-W37_0907-0913/
report_gen_v13_슬라이드_260913_evidence/refetch_v13_sources.py`가 v13.pptx를 만들 때
실제로 쓴 것과 **동일한 소스 파일·동일 절차**로 재구성했다(`income_data/komis/
komis_{06,08}_*.json`, evidence 폴더의 `raw/*.json`). page_id별 시나리오 20개(가격
4종 baseline/비교광종 8, 광물전망지표 4, 국내수급지도 3, 세계교역지도 3, 광물지도
매장량/생산량 2) 그대로 1:1 대응.

## 검증(2026-09-17)

20개 요청 전부 라이브 컨테이너에 실제로 쳐서 `status=ok`, 응답에 `table` 키(2026-09-16
분리 반영) 포함까지 확인했다(20/20 성공). `refine_with_llm`은 전부 기본값 `false`로
채워 규칙기반 문장을 반환하는 요청이다 — LLM 정제본을 보려면 그 필드만 `true`로
바꿔 재실행하면 된다.

## 참고

- page_id → HTTP 경로 매핑(`indicators/price-forecast`는 스트림릿에서 제외된
  엔드포인트라 이번 20개 요청에 넣지 않았다 — `feedback_forecast_price_exclusion_260903`
  참고): prices/{base-metals,minor-metals,iron-energy,other}, indicators/
  {market,supply,composite-index}, maps/{domestic-trade(=map_korea),
  global-trade(=map_global),mineral}.
- 재생성 스크립트: `/tmp/rg_api_build/{build.py,postman.py}`(세션 임시 위치, 저장소에
  넣지 않음) — 필요하면 동일 로직을 `documents/산출물/`에 정식 스크립트로 옮겨 재사용
  가능하게 할 것.
