# report_gen composite/mineral-map/price-forecast — 스키마 트리밍 + 정렬 버그 수정 (2026-08-31)

## 배경
사용자: "api v1 analysis price-forecast swagger에 아직도 파라메터가
여러개 있는데? mineral말고도 더 있는데?" — 어제(8/30) Swagger 트리밍은
price_*/map_korea/map_global 6개 엔드포인트(`MineralDateRangeSummaryRequest`
계열)만 했고, 형제 클래스 3개(`CompositeIndexSummaryRequest`·
`MineralMapSummaryRequest`·`PriceForecastSummaryRequest`)는 빠뜨렸다.

## 스키마 트리밍
komis_response로 완전히 대체된 손 매핑 전용 `observations` 필드를 3개
클래스 전부에서 제거했다. 나머지 필드는 개별 감사 결과 전부 "진짜
필요"거나 "여전히 유효한 선택 기능"이라 남겼다:

| 클래스 | 제거 | 유지 이유 |
|---|---|---|
| `CompositeIndexSummaryRequest` | `observations` | `start_date`/`end_date`(선택 필터)만 남음 — mineral 개념 자체가 없는 페이지 |
| `MineralMapSummaryRequest` | `observations` | `mineral`·`measure`는 응답 본문에 없는 조회 파라미터라 필수 유지. `unit`은 자동채움 폴백/오버라이드로 유효. `secondary_measure_observations`/`secondary_unit`(매장량·생산량 교차비교, PDF §4)은 komis_response가 아직 커버 못 하는 유일한 기능이라 그대로 남김 |
| `PriceForecastSummaryRequest` | `observations` | `mineral`·`forecast_horizon`은 응답 본문에서 안정적으로 못 구분하는 조회 파라미터라 필수 유지. `price_unit`은 응답에 없는 값이지만 있으면 가격 문장에 단위를 붙여주는 살아있는 선택 필드(`_forecast_price_text` 참고, price_criterion_serial 같은 죽은 필드 아님)라 남김 |

`PriceForecastObservation`처럼 `mnrkndKornNm`(한글명)이 응답에 있는데
안 뽑고 있던 것도 발견 — `_parse_komis_price_forecast_response`가
mineral_name도 반환하도록 확장(price 파서와 같은 자동채움 패턴).

## 부수 발견 — 정렬 순서 버그 2건(가격 파서 latest_price 버그와 동일 원인)
검증 중 forecast_price 응답 헤더가 **"start_period: 2028-Q4 ·
end_period: 2001-Q1"**로 뒤바뀐 걸 발견했다. 원인은 `_analyze_price_
forecast`/`_analyze_price`/`_analyze_composite` 셋 다 같은 패턴이었다 —
`series.observations`에 **필터링만 하고 정렬 안 한** 리스트를 그대로
넣어놓고, `applied_filters`/`DataQuality`는 `series.observations[0]`/
`[-1]`으로 시작/끝을 읽었다. KOMIS 원본(`defaultMnrl`·`data[]`·
`tableData`)이 최신순(내림차순)이라 이 값들이 뒤집혀 나왔다 — 어제
고친 `_parse_komis_price_response`의 `latest_price` 버그와 정확히 같은
원인 클래스다.

- `계산 자체는 무관했다` — `calculate_price_summary`/`calculate_price_
  forecast_summary`/`calculate_composite_summary` 전부 내부에서 이미
  독립적으로 정렬해서 쓰고 있어(예: `sorted(series.observations, ...)`)
  근거 문장·수치는 전부 정상이었다. 깨진 건 응답의 `applied_filters`/
  `data_quality`(API 계약상 필드, 마크다운엔 일부만 노출)뿐이다.
- 세 곳(`_analyze_price`·`_analyze_composite`·`_analyze_price_forecast`)
  전부 `series` 조립 직전에 observations를 날짜/기간순으로 직접 정렬하도록
  고쳤다. `map_mineral`은 연도 값 SET을 정렬해 쓰는 별개 패턴이라 원래
  안전했고, `map_korea`/`map_global`도 날짜 SET을 정렬해 써서 안전했다
  (전수 감사 완료 — 이 클래스 버그는 이 3곳이 전부).

## 검증
- 니켈 forecast_price를 komis_response로 재현 — 헤더가
  "start_period: 2001-Q1 · end_period: 2028-Q4"로 정정됨 확인.
  mineral_name("니켈") 자동채움도 확인.
- composite-index·mineral-map·price-forecast 3종 전부 실제 evidence
  데이터로 TestClient end-to-end 재현 — 전부 `status=ok`, 실제 LLM
  경로(`llm_refined=True`)까지 확인.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 커밋
`app/routers/analysis.py`(3개 클래스 트리밍)·`app/analysis/summary.py`
(파서 mineral_name 확장 + 정렬 버그 3곳 수정) — main-agent 승인 후
재빌드·재기동 필요.
