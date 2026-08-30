# report_gen price-forecast — forecast_horizon도 komis_response에서 자동 판별 (2026-08-31)

## 배경
사용자가 트리밍 후에도 price-forecast Swagger 예시를 계속 지적("아직도
파라메터가 여러개 있는데?"). 어제(8/30) `observations` 제거 후 남은
필드(mineral·mineral_name·forecast_horizon·start_period·end_period·
price_unit)를 다시 감사했다.

## 재확인한 결론
`mineral`은 여전히 진짜 필요하다(응답 본문에 코드 없음, 한글명만).
그런데 `forecast_horizon`("medium"/"long")은 다시 보니 실제로 자동
판별이 가능했다 — 이미 있던 검증 로직(`models.py::validate_period`의
"medium이면 전부 -Q 포함, long이면 전부 -Q 미포함" 체크) 자체가
"기간 형식이 horizon을 구분한다"는 사실에 의존하고 있었다. 즉
`getListPricePredc`의 `crtrPrd`가 분기("28년 4Q")냐 연("2028년")이냐만
보면 medium/long을 코드가 직접 판별할 수 있는데, 이걸 안 쓰고
호출자에게 다시 물어보고 있었다.

## 변경
`_analyze_price_forecast`가 komis_response로 파싱한 관측치의 `period`
형식("-Q" 포함 여부)에서 `forecast_horizon`을 자동 판별하도록 추가
(호출자 명시값이 있으면 그쪽 우선). `models.py::validate_period`의
"forecast_horizon 필수" 검사도 `komis_response`가 있으면 예외를
허용하도록 좁혔다(map_korea/global의 mineral 자동채움과 완전히 같은
패턴). 손 매핑 경로(komis_response 없이 `observations`만 보내는 경우)
는 형식을 알 방법이 없어 여전히 필수 — 정직하게 유지했다.

## 검증
- 니켈 데이터로 `{"mineral": "MNRL0006", "komis_response": <원본>}`
  만(`forecast_horizon` 생략) 호출 — `status=ok`, "예측기간구분:
  medium"으로 정확히 자동 판별됨 확인.
- `komis_response` 없이 `forecast_horizon` 생략하면(내부
  `AnalysisSummaryRequest` 직접 테스트) 여전히 정상 거부 확인(퇴행
  없음).
- 최종 스키마 감사(OpenAPI) — `PriceForecastSummaryRequest`는
  `mineral` 하나만 필수, 나머지 8개 필드(request_id·analysis_scope·
  mineral_name·forecast_horizon·start_period·end_period·price_unit·
  komis_response) 전부 선택.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 커밋
`app/analysis/models.py`(validate_period 예외)·`app/analysis/summary.py`
(`_analyze_price_forecast` horizon 자동판별)·`app/routers/analysis.py`
(forecast_horizon 필드 선택화+docstring) — main-agent 승인 후 재빌드·
재기동 필요.
