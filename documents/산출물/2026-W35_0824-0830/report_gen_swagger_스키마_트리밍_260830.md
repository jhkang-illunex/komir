# report_gen Swagger 요청 스키마 트리밍 (2026-08-30)

## 배경
사용자가 `/api/v1/analysis/prices/base-metals`의 Swagger 예시 바디를 보고
지적: 필요없는 필드가 다 나온다(`observations`·`price_unit`·
`price_criterion`·`price_criterion_serial`·`compare_price_criterion`·
`compare_observations`·`trade_direction`·`geo_events`·
`komis_period_comparisons`·`komis_trade_totals`가 `komis_response`와
나란히 노출) — 지워달라.

## 원인
`MineralDateRangeSummaryRequest`(`app/routers/analysis.py`) 하나를
price_base_metals/minor_metals/iron_energy/other·map_korea·map_global
6개 엔드포인트가 공유해서, price 전용 필드가 map 엔드포인트 Swagger에도,
map_korea 전용 `trade_direction`이 price 엔드포인트 Swagger에도 그대로
노출되고 있었다. 여기에 오늘(2026-08-30) `komis_response`를 도입하면서
손 매핑 전용 필드(`observations`·`price_unit`·`price_criterion`·
`price_criterion_serial`·`compare_price_criterion`·
`compare_observations`·`geo_events`·`komis_period_comparisons`·
`komis_trade_totals`)가 전부 불필요해졌는데도 그대로 남아 있었다.

## 변경
`_DateRangeMineralRequest`(공통 베이스: mineral·mineral_name·start_date·
end_date·komis_response)를 만들고, 페이지별로 진짜 필요한 필드만 얹은
3개 하위 클래스로 쪼갰다:

| 클래스 | 대상 | 추가 필드 |
|---|---|---|
| `PriceSummaryRequest` | price_base_metals/minor_metals/iron_energy/other | compare_mineral·compare_mineral_name |
| `DomesticTradeSummaryRequest` | map_korea | trade_direction |
| `GlobalTradeSummaryRequest` | map_global | (없음) |

`compare_mineral`(코드)은 남겼다 — KOMIS `komis_response`의
`data.compareMnrl`엔 비교광종의 가격만 있고 내부 코드가 없어서 여전히
호출자가 명시해야 한다. `price_criterion_serial`은 어디서도 읽히지
않는 완전 죽은 필드임을 확인(`grep`으로 다운스트림 참조 0건)하고
제거했다.

내부 `AnalysisSummaryRequest`(`app/analysis/models.py`)는 그대로
뒀다 — `komis_dump_smoke_test.py` 회귀 하네스(395콤보)가 옛 손 매핑
필드로 계속 검증하고, 라우터 모델은 `.model_dump()`로 그 상위집합의
부분집합만 채워 넘기는 관계라 내부 스키마를 넓게 유지해도 공개 API
계약엔 안 드러난다.

같은 필드를 재사용하는 얇은 별칭 라우터(`app/routers/report_data.py`,
`/api/v1/prices/*`·`/api/v1/maps/*`)도 같이 갱신했다.

## 검증
- `TestClient`로 OpenAPI 스키마 직접 조회 — `PriceSummaryRequest`는
  9개 필드(`request_id`·`analysis_scope`·`mineral`·`mineral_name`·
  `start_date`·`end_date`·`compare_mineral`·`compare_mineral_name`·
  `komis_response`)만 남음, 옛 `MineralDateRangeSummaryRequest`는
  스키마에서 완전히 사라짐 확인.
- 니켈 데이터로 `/api/v1/analysis/prices/base-metals` end-to-end
  호출 — **실제 LLM 경로까지 확인**(`llm_refined=True` 로그, DB
  `cfg_prompt` 13건 로드 확인). 5개 근거(전일·전주·전월·전년·조회기간
  전체변동)를 LLM이 2문장으로 압축해서 서술 — `SECTION_SENTENCE_RANGES`
  의 (1,3) 상한을 건드리지 않기로 한 이전 판단이 실측으로 확인됐다
  (LLM이 여러 근거를 한 문장에 압축하는 설계 의도가 실제로 작동함).
- 구리 데이터로 `/api/v1/analysis/domestic-trade`(트리밍된
  `DomesticTradeSummaryRequest`) end-to-end 호출 정상.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 커밋
`app/routers/analysis.py`·`app/routers/report_data.py` — main-agent
승인 후 재빌드·재기동 필요.
