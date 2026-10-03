# Typed Capability Output Coverage Audit — 2026-10-03

## 범위

- authoritative Strict baseline: `21/57`
- rag_core golden: `1560/1560`
- 운영 18002: 변경 없음
- 대상: GM14, CN09, IX02, ADD16, ADD25, PF02
- 코드/Registry/Planner/Validator 수정: 없음
- Full QA57 replay: 없음

## Output Coverage Matrix

| QA | Required Outputs | Selected Capability | Declared Capability Outputs | Missing Outputs | Required Composition | Category |
|---|---|---|---|---|---|---|
| GM14 | `PriceOverview`, `ConcentrationMetric`, `CountryShare/import_share` | `price.overview`, `trade.concentration` | `PriceOverview`; concentration spec 미선언 | `CountryShare/import_share` | `trade.country_rank` 추가 후 mineral 기준 join | `WRONG_CAPABILITY_SELECTION` + `OUTPUT_COVERAGE_INCOMPLETE` |
| CN09 | `ChangeMetric/change_pct`, `DocumentEvidence` | `indicator.series`, `document.retrieve` 후보 | `IndicatorSeries`, `DocumentEvidence`; `ChangeMetric` output 미확정 | `change_pct`의 declared producer/type | period_change → change filter → date/evidence join | `OUTPUT_TYPE_MISMATCH` + `MULTI_CAPABILITY_COMPOSITION_MISSING` |
| IX02 | `PriceSeries`, `IndicatorSeries`, 비교 결과 | `price.series`, `indicator.series` | `TimeSeries`, `IndicatorSeries` | declared type coverage는 충족; 비교 right field/dependency 손실 | date 기준 multi-series compare | `DEPENDENCY_BINDING_FAILURE` |
| ADD16 | `ResourceRanking`, population `ScalarMetric`, percentage/share | `resource.rank` × 2 | `ResourceRanking` | scalar denominator 및 percentage result | world rows → aggregate(sum) → ratio/share | `MULTI_CAPABILITY_COMPOSITION_MISSING` |
| ADD25 | 3개 `PriceSeries`, aligned comparison result | `price.series` × 3 | `PriceSeries` | declared output 없음; dependency result 전달 불안정 | date alignment / multi-series compare | `DEPENDENCY_BINDING_FAILURE` + `MODEL_NONDETERMINISM` |
| PF02 | observed `PriceSeries`, forecast series, continuation `TimeSeries` | `price.series`, `forecast.price` | `PriceSeries`; forecast output metadata 미완결(실행 TypedResult는 generic fallback) | `price_forecast` declared output이 1회 누락 | historical → future `temporal_continuation` | `OUTPUT_COVERAGE_INCOMPLETE` + `MODEL_NONDETERMINISM` |

## QA별 판정

### GM14

`trade.country_rank → CountryShare` metadata는 이미 존재한다. 그러나 현재 requirement가
`trade.concentration`으로 선택되어 `ConcentrationMetric`과 `CountryShare` 중 후자가 graph에
포함되지 않는다. concentration의 값을 `import_share`로 alias 처리할 수 없으므로 단순
Registry metadata 보완만으로는 회복되지 않는다.

### CN09

`indicator.series`와 `document.retrieve`는 각각 존재하지만 `period_change` 결과가
`ChangeMetric/change_pct`로 선언·생성된다는 보장이 없다. 따라서 capability coverage보다
calculation output type과 evidence branch composition이 최초 병목이다.

### IX02

두 capability와 기본 output type은 모두 존재한다. 실패는 selection이 아니라 indicator
결과의 right-side field/dependency가 compare 결과까지 전달되지 않는 문제다. 이는 output
coverage contract만으로 회복할 수 없다.

### ADD16

두 `resource.rank` 결과의 output type은 호환되지만, world multi-row를 어떤 typed scalar로
축약할지와 percentage 결과의 unit/output type이 요구사항에 완결되어 있지 않다. provider
coverage 문제가 아니라 reduction/composition 문제다.

### ADD25

세 `price.series` capability는 required output을 제공한다. 실패는 capability selection보다
multi-entity dependency와 date alignment 전달이 반복 실행에서 불안정한 문제다.

### PF02

정상 실행 시 `price.series + forecast.price → temporal_continuation` graph가 가능하다.
다만 `forecast.price`의 declared output metadata가 완결되지 않았고, fresh probe 중 1회는
`requested_output_not_produced:price_forecast`로 parser 단계에서 중단됐다. 이는 stable
selection failure가 아니라 output preservation/model nondeterminism이다.

## 공통 contract 가능성

다음의 일반 coverage 계산은 공통화 가능하다.

```text
Required Output Set
→ 각 Capability의 Declared Output Set
→ output union coverage 검사
→ 부족 output 및 provider 후보 보고
```

그러나 최소 compatible capability set을 실제 실행 graph로 만드는 composition은 QA별로
다르다.

| QA | 부족한 공통 coverage | 필요한 고유 composition |
|---|---|---|
| GM14 | CountryShare provider 누락 | mineral join + capability selection |
| CN09 | ChangeMetric provider 불명확 | period change + evidence/date relation |
| IX02 | 없음 | compare dependency/field propagation |
| ADD16 | ScalarMetric provider 누락 | aggregate + ratio/share |
| ADD25 | 없음 | multi-series date alignment |
| PF02 | forecast output declaration 불완전 | temporal continuation + parser stability |

동일한 output-coverage와 composition contract가 2건 이상 일치하지 않는다. 따라서 이번
iteration의 공통 수정 조건을 충족하지 않으며, `NO_COMMON_CONTRACT`로 판정한다.

## 분류 집계

| Category | QA |
|---|---|
| `OUTPUT_COVERAGE_INCOMPLETE` | GM14, PF02 |
| `WRONG_CAPABILITY_SELECTION` | GM14 |
| `MULTI_CAPABILITY_COMPOSITION_MISSING` | CN09, ADD16 |
| `DEPENDENCY_BINDING_FAILURE` | IX02, ADD25 |
| `OUTPUT_TYPE_MISMATCH` | CN09 |
| `MODEL_NONDETERMINISM` | ADD25, PF02 |
| `NOT_SELECTION_RELATED` | IX02, ADD16, ADD25 |

## 수정 및 검증 판정

- 공통 Typed Capability Selection contract: **coverage 검사 수준에서만 존재**
- 최소 2건 이상 동일 composition contract: **확인되지 않음**
- 코드 수정: **없음**
- 신규 STABLE/LAYER recovery: **없음**
- provisional Strict: **21/57 유지**
- rag_core: **1560/1560 유지**
- rag_chat: **155 passed / 1 known legacy failure 유지**

## Complexity Delta

```text
Files changed: audit artifact 1개
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Duplicated contract sources added: 0
Responsibility growth: false
Verdict: COMPLEXITY_PASS
```

## Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Canonical source of truth: existing Capability Registry + TypedResult ValueType + AAST composition contracts
Consumers: 향후 typed coverage validator/planner audit
Remaining duplicated mappings: semantic_v2 capability catalog, live field aliases, legacy projection mappings
```

## Typed Planner 기반성

`Required Output Set → Capability Output Coverage`는 향후 Typed Planner의 사전 검증 기반으로
사용할 가치가 있다. 다만 이를 곧바로 capability 자동 선택/graph 생성기로 확장하면 GM14의
selection 오류와 ADD16/PF02의 서로 다른 composition semantics를 혼합할 위험이 있다.
현재는 coverage 진단 계약으로 제한하고, composition은 기존 typed operator가 명시된 경우에만
별도로 연결하는 것이 안전하다.

## 결론

이번 대표 6건에서는 공통 output coverage 진단은 가능하지만, 기존 capability와 composition
primitive만으로 2건 이상을 동시에 회복할 동일한 contract는 확인되지 않았다. 따라서 수정하지
않고 `NO_COMMON_CONTRACT`로 종료한다. 다음 ROI는 GM14 selection, CN09 ChangeMetric output,
ADD16 reduction을 서로 분리해 처리해야 한다.
