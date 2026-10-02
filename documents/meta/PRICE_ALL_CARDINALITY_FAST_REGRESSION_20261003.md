# Price criterion cardinality / inventory series fast regression (2026-10-03)

## Scope

- 검증 포트: `18012`
- 운영 포트 `18002`: 변경하지 않음
- 검증 이미지: `komir-rag-chat:capability-data-audit-r28`
- 범위: 가격 기준 cardinality의 `REPRESENTATIVE` / `EXPLICIT` / `ALL`
- 전체 57건 replay: 수행하지 않음

## Root cause

가격 `ALL` 요청은 r25에서 다음까지는 보존됐다.

`SemanticRequirement(criterion_mode=ALL) → AAST args → ActionSlots(ALL)`

그러나 MCP 경계에서 ALL의 선택된 serial에 대한 provenance 상태를 단일
criterion 경로로 계산하지 않아, 알려진 source가 `unverified/source_unavailable`로
열화됐다. 또한 source의 한 행에 있는 `lowst_prc`, `hghst_prc`, `cmerc_prc`가
하나의 `price`로 축약될 위험이 있었다.

재현 source 확인:

- 니켈 valid criterion serial: `502`
- source table: `KO_MNRL_PRC`
- 같은 관측일에 `lowst_prc`, `hghst_prc`, `cmerc_prc`가 각각 존재

## Applied common changes

1. `criterion_mode=ALL`의 provenance를 전체 선택 serial 집합 기준으로 판정.
2. ALL에서 source-owned low/high/normal measure를 별도 typed row로 정규화.
3. serial, criterion label, measure identity를 normalized row에 보존.
4. Semantic IR의 price field contract에 `price_measure`,
   `price_measure_label`, `price_criterion`, `price_criterion_serial` 추가.
5. REPRESENTATIVE/EXPLICIT source에 identity field가 없을 때 Gemma가
   부가 필드를 과잉 요청해도 기존 가격 series를 실패시키지 않도록 optional
   projection 처리.

## Deterministic tests

- `167 passed, 72 subtests passed`
- 신규 테스트: `test_price_criterion_cardinality.py`
- compileall 및 `git diff --check`: 통과

## r28 Fast Regression

| case | result |
|---|---|
| 최근 1년 니켈 모든 가격 추이 | `EXECUTION_PASS`; 3개 measure row가 날짜별로 유지된 typed trace 확인 |
| 최근 1년 니켈 가격 추이 | `EXECUTION_PASS`; 대표 series 13개 월 집계 |
| 니켈 criterion 502 최근 1년 추이 | `EXECUTION_PASS`; explicit series 13개 월 집계 |
| ADD27 | `EXECUTION_PASS`; regression 없음 |
| MP01 | `EXECUTION_PASS`; regression 없음 |
| Direct price | `EXECUTION_PASS`; regression 없음 |
| ADD01 | 기존 `projection_field_unavailable:value` 유지 |
| ADD49 | 기존 `projection_field_unavailable:price` 유지 |
| 최근 1년 니켈 재고 추이 | `semantic_plan_incomplete` 유지 |

ALL의 내부 typed trace에는 `row_count=783` 및
`date`, `price`, `price_measure`, `price_measure_label`, `price_criterion`,
`price_criterion_serial`이 확인됐다. 이는 261개 관측일 × 3개 source measure다.

다만 최종 SSE의 월 집계 블록은 현재 `date/price`로 축약되어 measure label이
표시되지 않는 잔여 presentation 경계가 있다. 따라서 ALL은 내부 series 보존과
실행은 통과했지만, 최종 사용자 표시까지 완전한 cardinality 보존으로 판정하지
않는다.

## Inventory boundary

`최근 1년간 니켈 재고 추이`는 SemanticRequirement에 기간이 있으나 현재 등록된
capability가 `inventory.latest`(단일 최신 관측)뿐이다. 실제 r28에서는
`inventory.latest + trailing_months(12)`가 `semantic_plan_incomplete`로 종료됐다.
가격 수정으로 이를 `inventory.latest`로 우회하지 않았다. 재고 시계열은 기존
architecture 안에서 별도 typed series contract가 필요하므로 이번 iteration의
가격 cardinality 수정 대상에서 제외했다.

