# AAST Fast Regression — 2026-10-02

## 범위

- 운영 `18002`: 변경하지 않음
- 검증 포트: `18012`
- 이미지: `komir-rag-chat:aast-content-r6`
- 이미지 ID: `sha256:884650d60ed37f135f1803bea66cbb36b3104e649fbf0fe5c2f101307131488e`
- 공식 content baseline: `27/57 (47.37%)`
- 57건 전체 replay: 수행하지 않음

## 수정 대상

| 대상 | 수정 | 실제 결과 |
|---|---|---|
| MP01 | Coverage Validator가 typed ActionPlan의 동등한 `trade_scope` 및 `period` binding을 보존하도록 비교 | Validator는 통과했으나 실행 후 `projection_field_unavailable:share_percentage`로 무역 branch가 실패하여 CONTENT_PASS 미회복 |
| ADD27 | generic `price_series`의 무기간 “가격 추이”를 trailing 12개월 시계열로 정규화 | CONTENT_PASS 후보 회복: 실제 SSE에 시계열 요약·표·차트가 모두 존재 |

## Live fast regression

| QA | 경로 | 결과 | 시간(초) | 비고 |
|---|---|---|---:|---|
| MP01 | AAST | PARTIAL | 23.88 | coverage valid; trade projection field unavailable |
| ADD27 | Direct/price.series | SUCCESS | 1.57 | `time_series`, 표 1, 차트 1 |
| ADD45 | Navigation | SUCCESS | 2.49 | sentinel regression 없음 |
| REG02 | Direct Capability | SUCCESS | 1.50 | sentinel regression 없음 |
| GM04 | Direct Map | SUCCESS | 14.88 | sentinel regression 없음 |
| CN09 | AAST normal | SUCCESS | 3.37 | sentinel regression 없음 |
| DOC02 | Document/Retrieval | ABSTAIN | 8.36 | `semantic_plan_incomplete`; 문서 sentinel의 기존 실행 변동/계획 문제 |
| MI01 | Document/Retrieval | SUCCESS | 3.54 | sentinel regression 없음 |
| MP06 | AAST composite | PARTIAL | 6.43 | 기존 document projection 문제; 이번 수정 대상 아님 |

## 결론

- ADD27: 시계열 projection 문제는 live SSE에서 회복 확인
- MP01: scope false rejection은 제거되어 validation 단계는 통과했으나, 후속 projection contract 문제로 완전 회복되지 않음
- 확인된 MP01 후속 원인: `trade.country_rank` 결과에 `share_percentage`가 없는 상태에서 AAST가 해당 필드를 projection 요청
- 이 후속 문제는 질문별 특례나 임의 값 보정 없이 별도 공통 projection/capability contract 작업으로 분리해야 함
- 이번 fast regression만으로 공식 `27/57`을 재계산하지 않음
- 예상 baseline 변화: `27 → 최대 29`; 현재 확정적으로 회복된 대상은 ADD27 1건이며 MP01은 보류

## MP01 repair round — r9

### 원인 추적

Capability evidence의 ranking 표에는 다음 두 필드가 함께 존재했습니다.

- canonical: `share_pct`
- 주석 부가 physical column: `share_pct(수입금액 비중(...))`

TypedResult canonicalization 단계에서 두 필드는 모두 보존되었으나, strict projection resolver가 동일 의미 후보를 2개로 보고 `share_percentage`를 거부했습니다. 또한 동일 evidence bundle의 보조 문서 표 행이 ranking 결과에 섞여 `projection_input_incomplete`가 발생했습니다.

### 공통 수정

- canonical alias가 정확히 하나 존재하면 주석 부가 duplicate보다 우선
- `trade.country_rank` TypedResult에서는 `country`와 `share_percentage/share_pct` 계약을 모두 만족하는 행만 ranking rows로 보존
- MP01/질문 문자열/QA ID 분기 없음

### r9 Fast Regression 결과

| QA | 결과 | 시간(초) | 확인 |
|---|---|---:|---|
| MP01 | CONTENT_PASS 후보 / execution success | 10.62 | 가격 시계열 + `country/share_percentage` 표 모두 반환 |
| ADD27 | CONTENT_PASS 후보 유지 | 1.55 | 최근 1년 시계열 요약·표·차트 |
| ADD45 | sentinel success | 2.49 | Navigation |
| REG02 | sentinel success | 1.52 | Direct Capability |
| CN09 | sentinel success | 2.42 | AAST 정상 경로 |

Unit/관련 회귀: `89 passed`. compileall 및 `git diff --check` 통과.

검증 이미지: `komir-rag-chat:aast-content-r9`
이미지 ID: `sha256:2af506411f65d919406f58a4cef261e404da8de96cec5a989eb93eed598a4a88`

공식 full-replay baseline은 변경하지 않아 `27/57 (47.37%)`로 유지합니다. ADD27과 MP01을 full replay에서 재확인하면 잠정 예상치는 `29/57 (50.88%)`입니다.
