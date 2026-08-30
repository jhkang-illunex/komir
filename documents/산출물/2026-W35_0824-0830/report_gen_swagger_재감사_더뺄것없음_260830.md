# report_gen — Swagger 필드 재감사(2차): 기간 필터 6쌍 이후 남은 필드 전수 점검 (2026-08-30)

## 배경
기간 필터 6쌍(start_date/end_date 등, 커밋 0d0568a50) 제거 직후 사용자
요청: "다른 페이지도 Swagger 필드 더 줄일 데 있는지 재감사해줘." 이번엔
음성 결과(더 뺄 게 없다)가 예상됐지만, 이 세션에서 "이미 다 했다"는
가정 없이 매번 실측으로 재검증해서 실제로 값을 낸 전례(mineral 자동화·
forecast_horizon 자동화·미사용 API·request_id/analysis_scope·기간필터
6쌍)가 있어 같은 방식으로 전수 재점검했다.

## 방법
8개 요청 스키마(12개 엔드포인트가 공유) 전 필드를 `TestClient`로
Swagger 재조회해 목록을 뽑고, 각 필드를 `grep`으로 `summary.py`/
`komir_summary.py`/`models.py`에서 실제 소비 지점을 추적했다.

## 결과 — 전부 실사용 확인, 제거 대상 없음

| 클래스 | 필드 | 근거 |
|---|---|---|
| IndicatorSummaryRequest | price_unit·price_criterion | `summary.py:1332-1358`, 결측 시 `missing_data`에 반영 |
| | unavailable_page_data | `summary.py:1334,1355` → `series.unavailable_page_data` |
| | supply_auxiliary | `summary.py:572-584,695-696,1077` — `_supply_auxiliary_metrics`까지 배선 |
| | start_month/end_month | 이 페이지엔 komis_response가 없어(로그인 필요) 손 매핑 `observations`를 좁히는 **유일한** 필터 경로 — 기간필터 6쌍과 달리 komis_response로 대체될 수 없어 제거 대상 아님 |
| MineralMapSummaryRequest | secondary_measure_observations·secondary_unit | `summary.py:1564-1577` — 매장량/생산량 교차비교(PDF §4) 실기능, 데모 UI엔 아직 안 붙었을 뿐 죽은 코드 아님(2026-08-27 신설 당시부터 같은 결론) |
| | unit | `summary.py:1526` — komis_response 자동채움의 오버라이드(요청값 우선) |
| PriceForecastSummaryRequest | price_unit | `summary.py:1714,1769` — 결측 시 "가격 단위" missing_data |
| PriceSummaryRequest | compare_mineral_name | `summary.py:1874` — `request.compare_mineral_name or request.compare_mineral`, 데모는 안 보내지만(코드만 보냄) 실제 KOMIS 연동 캐스터를 위한 표시명 오버라이드로 유효 |
| DomesticTradeSummaryRequest | trade_direction | `summary.py:2049,2140` — map_korea 전용 방향 선택, 응답 자체엔 안 드러나 호출자 의도 필수(2026-08-27 결론 그대로) |
| PriceGroupSummaryRequest | price_group·observations | 그룹 요약의 유일한 입력 경로, 둘 다 필수급 |

`mineral_name`(price_*·forecast_price)은 이미 komis_response가 있으면
자동채움되는 선택 필드다(`request.mineral_name or komis_mineral_name or
request.mineral`) — 기간필터처럼 "이미 통제된 걸 또 통제"하는 중복이
아니라 "값 표시를 오버라이드"하는 기능이라 기간필터와 성격이 다르다
(재확인, 기존 결론 불변).

## 별도로 검토했다가 기각한 안 — `komis_response`를 required로 바꾸는 것
6개 페이지(price_*·map_korea/global·composite·map_mineral·forecast_price)에서
`observations`가 이미 제거돼 지금은 `komis_response`가 사실상 유일한
데이터 입력 경로다. "그럼 Swagger에 required로 명시하는 게 더
정직하지 않나"를 검토했지만 **기각**한다 — FastAPI는 라우터 레벨
`Field(...)` 필수 필드가 비어 있으면 엔드포인트 함수(`run_summary`)에
도달하기 전에 자체 422를 반환한다. 이건 2026-08-26 사용자 지시로
확립된 "HTTP 상태 코드는 전부 항상 200, 성공/실패는 바디의 status로만
구분"이라는 계약(§`routers/_common.py` 모듈 docstring)을 어기는
회귀다. 지금처럼 optional로 두고 `komis_response`가 없으면
`_analyze_*`가 `DataSourceError`를 던져 `_common.py`가 이를
`NO_DATA`로 매핑하는 현재 경로가 계약을 지킨다 — 현행 유지가 맞다.

## 결론
기간 필터 6쌍 제거 이후 남은 필드는 전부 실사용·실기능이 확인됐다.
추가로 뺄 필드 없음(음성 결과, 근거 있음).

## 검증
코드 변경 없음(순수 감사) — 커밋·재빌드 불필요.
