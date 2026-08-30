# report_gen — price_criterion 필드도 복원(4차 자동채움 재감사) (2026-08-30)

## 배경
사용자: "다른 페이지도 자동채움 가능한 필드 있는지 다시 확인해줘"
(compare_price_criterion 회귀 복원 직후 4번째 재감사 요청).

## 방법 — 이번엔 "레이어 3층" 교차 대조
3차 감사(음성 결과)와 compare_price_criterion 발견에서 얻은 교훈을
합쳐서, 이번엔 `models.py`(내부 `AnalysisSummaryRequest`)의 필드
전체를 훑고 각 필드가 (a) 해당 라우터 클래스에 노출돼 있는지,
(b) 안 돼 있다면 그게 "의도된 축소"(komis_response로 완전 대체됨,
예: observations·komis_period_comparisons·komis_trade_totals)인지
"놓친 회귀"(내부 로직은 여전히 읽는데 라우터에서만 빠짐)인지
하나하나 판정했다.

## 결과 — price_criterion도 같은 회귀였다
`price_criterion`(기본 광종 자신의 가격기준, 예: "LME CASH")이
`PriceSummaryRequest`에 없었다. `compare_price_criterion`과 **정확히
같은 커밋**(`c76466a47`, 2026-08-30 Swagger 트리밍)에서 같은 근거로
같이 제거됐던 필드 — 그 커밋의 docstring이 둘을 나란히 "손 매핑
전용 필드... 전부 불필요"로 묶어서 지웠다.

차이점: `price_criterion`의 auto-fill(`dataAvg.INFO.prcCrtr`)은 그
트리밍보다 먼저(`ecc4cb8a7`) 이미 들어가 있어서, 이 필드가 없어도
**표시 자체는 안 깨졌다**(구별 포인트 — compare_price_criterion은
auto-fill이 아예 없어서 표시가 완전히 죽었었다). 그래도 `mineral_
name`·`compare_mineral_name`·`compare_price_criterion`(방금 복원)이
전부 "자동채움+오버라이드 가능"인데 `price_criterion`만 "자동채움뿐,
호출자가 다른 값으로 못 바꿈"인 건 비일관적이라 나머지와 맞췄다.

## 다른 페이지 전수 점검 결과(추가 발견 없음)
`models.py`의 나머지 필드를 전부 대조했다 — `price_unit`(price_*
페이지엔 애초에 개념 자체가 없음, `PriceSeries`에 필드가 없어 확인),
`price_criterion_serial`(`.price_criterion_serial` 읽는 곳이 죽은
`data_sources/extra.py`뿐이라 진짜 죽은 필드, 재확인), `komis_period_
comparisons`/`komis_trade_totals`(komis_response 파서가 완전히
대체 — 원래도 "raw 서브객체 손 매핑" 용도였지 오버라이드 개념이
아니었음), `unavailable_page_data`/`supply_auxiliary`(Indicator
전용, 그대로 맞음), `geo_events`(사용자 하드 제약 "안 씁니다" —
의도적으로 라우터에 안 노출, 회귀 아님) — 전부 의도된 축소로 확인,
추가 복원 대상 없음.

## 변경
`app/routers/analysis.py::PriceSummaryRequest`에 `price_criterion:
str | None = None` 필드 추가(요약 계산 로직은 이미 `request.price_
criterion or komis_price_criterion` 폴백을 갖고 있어 별도 코드
변경 불필요 — 필드 노출만 복원).

## 검증
- `PriceSummaryRequest` Swagger 재조회 — `price_criterion` 필드
  노출 확인(6개→7개).
- 니켈 실데이터로 `price_criterion` 없이 호출 → "**가격기준**: LME
  CASH" 자동채움 정상.
- `price_criterion: "커스텀 기준"`을 명시해서 호출 → "**가격기준**:
  커스텀 기준"으로 오버라이드 정상 작동(우선순위 확인).
- `komis_dump_smoke_test.py` 회귀 395콤보(8페이지) 전부 mismatch 0
  유지.

## 커밋
`app/routers/analysis.py` — main-agent 승인 후 재빌드·재기동 필요.
