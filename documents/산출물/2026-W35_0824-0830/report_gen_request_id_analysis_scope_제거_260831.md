# report_gen — request_id/analysis_scope를 전 엔드포인트 요청 스키마에서 제거 (2026-08-31)

## 배경
사용자가 price-forecast Swagger를 계속 지적했다. `komis_response`
말고 남은 `request_id`·`analysis_scope`·`mineral_name`·
`forecast_horizon`·`start_period`·`end_period`·`price_unit`을 재감사한
결과, `mineral_name`/`forecast_horizon`/`start_period`/`end_period`/
`price_unit`은 이미 전부 선택이고(어제 확인) 실제 기능이 있는 필드지만,
`request_id`·`analysis_scope` 이 둘은 **캐스터가 값을 넣어도 아무
효과가 없는 필드**임을 재확인했다.

## 근거
- `analysis_scope: Literal["page_only"]` — 타입 자체가 `"page_only"`
  하나뿐이라 캐스터가 다른 값을 보낼 수조차 없다. 사실상 상수인데
  요청 필드로 노출돼 있었다.
- `request_id`는 실제 HTTP 응답(`AnalysisReportResponse`)이
  `{status, report}` 딱 2개 필드뿐이라 캐스터가 보낸 값을 응답에서
  **절대 확인할 수 없다** — 서버 로그에는 남지만(`분석요약 완료
  request_id=...`) 캐스터 입장에서는 보이지도 않는 값을 요청에 넣을
  이유가 없다.

이 두 필드는 12개 엔드포인트가 공유하는 `AnalysisEndpointRequest`
베이스 클래스에 있었다 — 하나 고치면 전부 적용되는 구조.

## 변경
`AnalysisEndpointRequest`에서 `request_id`/`analysis_scope` 필드
제거. 내부 `AnalysisSummaryRequest`(models.py)는 그대로 뒀다 — 자체
기본값(`request_id` 자동 uuid4, `analysis_scope="page_only"`)이 있어서
라우터가 이 두 키를 안 실어 보내도 그대로 정상 동작한다(다른 필드
제거 때와 동일한 안전 패턴).

## 검증
- price-forecast 최종 필드: `mineral`(필수) + `mineral_name`·
  `forecast_horizon`·`start_period`·`end_period`·`price_unit`·
  `komis_response`(전부 선택) = 7개(구 9개에서 2개 감소).
- **12개 엔드포인트 전부** 스키마 재조회로 `request_id`/`analysis_scope`
  완전히 사라짐 확인(로그인 필요라 이번 komis_response 확장 대상이
  아니었던 indicator_market/supply 포함 — 이 둘도 같은 베이스 클래스를
  공유해서 자동으로 같이 정리됐다).
- 니켈 데이터로 price-forecast end-to-end 재현 — `status=ok`, 실제
  LLM 경로까지 정상.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 커밋
`app/routers/analysis.py`(`AnalysisEndpointRequest`에서 2개 필드 제거,
미사용 `uuid4` import 정리) — main-agent 승인 후 재빌드·재기동 필요.
