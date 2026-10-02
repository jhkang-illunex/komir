# Capability Data Audit Pending — 2026-10-03

이 문서는 Fast Regression에서 Capability/Projection 계층 수정 대상으로 확정하지
않은 항목을 다음 Data Audit으로 넘기기 위한 목록이다. `no_data`나 mapping 부재를
`TRUE_DATA_ABSENCE`로 확정하지 않는다. 각 항목은 실제 trace의 반환 사유를 보존한다.

| QA | entity | metric | requested period | operation | capability | returned reason |
|---|---|---|---|---|---|---|
| ADD01 | 리튬 | price | latest/current | latest lookup | `price.series` | `price_criterion_mapping_missing` |
| ADD49 | 구리 | price | latest/current | latest lookup | `price.series` | `projection_field_unavailable:value` (criterion/source mapping trace 선행) |
| GM13 | 코발트 | price, production, import, document | current/latest 및 현황 | briefing/composite | `price.series`, `resource.rank`, `trade.country_rank`, `document.retrieve` | price branch `price_criterion_mapping_missing`; 나머지 branch는 부분 성공 |
| GM05 | 망간 | use + import-country rank | unspecified/current | document + country rank | `document.retrieve`, `trade.country_rank` | `projection_field_unavailable:country`; trade evidence가 국가행 contract를 충족하지 않음 |
| MP04 | 니켈 | price + production YoY | latest/trailing comparison | side-by-side + YoY | `price.series`, `resource.yoy` | resource branch `retrieval unavailable: no_data` / dependency unavailable |
| ADD03 | 아연 | price | 2010년 이후~현재 | arg-max/date selection | `price.series` | `retrieval unavailable: no_data` |
| PF01 | 니켈 | price + forecast.price | current + next month | forecast composite | `price.series`, `forecast.price` | 외부 전망 source/capability data 미확보 |
| PF02 | 니켈 | price + forecast.price | trailing 6 months + future horizon | temporal continuation/composite | `price.series`, `forecast.price` | forecast metric/period source contract 미확보 |
| PF03 | 니켈 | price + forecast.price | current vs forecast horizon | comparison | `price.series`, `forecast.price` | `no_comparable_rows`; 외부 전망 날짜 교집합 미확보 |
| CN04 | 수입 의존도 높은 광종 집합 | import dependency + forecast.price | current/forecast period | filter + forecast map | `trade.concentration`, `forecast.price` | 외부 전망 source/evidence 미확보 |
| CN05 | 리튬 | import country rank + forecast.price | current/forecast period | country rank + forecast | `trade.country_rank`, `price.series`, `forecast.price` | price criterion/source mapping 및 forecast source contract 미확보 |
| CN07 | 리튬 | price + forecast.price + news | current/forecast period | forecast + document retrieval | `price.series`, `forecast.price`, `document.retrieve` | 외부 전망 source/evidence 미확보 |
| GM12 | 2차전지 광물 5종 집합 | price + forecast.price | current/forecast period | map + forecast composite | `price.series`, `forecast.price` | 외부 전망 또는 indicator source contract 미확보 |

## 분류 원칙

- `price_criterion_mapping_missing`은 유효한 가격기준 serial이 원천 mapping에서
  확인될 때까지 기본값을 추정하지 않는다.
- `projection_field_unavailable:country`는 데이터가 없다는 뜻이 아니라, 현재
  evidence가 `trade.country_rank`의 국가행 output contract를 충족하지 않는다는
  뜻이다. 실제 source와 evidence provenance를 별도로 점검한다.
- `retrieval unavailable: no_data`는 현재 snapshot/기간에서 조회 결과가 없다는
  반환 사유일 뿐이며, 다음 Data Audit에서 `DATA_ABSENT`, `PERIOD_NO_DATA`,
  `PERIOD_INSUFFICIENT`, `DATA_ACCESS_FAILURE`, `DATA_QUALITY_BLOCKED` 중 하나로
  재분류한다.
- Renderer-only 항목과 format 문제는 이 목록의 데이터 부재로 섞지 않는다.
