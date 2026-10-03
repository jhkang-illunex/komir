# Output / Projection Cluster Audit — 2026-10-03

## 범위

- 대상: IX02, CN09, GM14, DOC02, ADD38
- 환경: 18012 `komir-rag-chat-cn08-r3`
- authoritative strict baseline: 21/57
- rag_core golden: 1557/1557
- 운영 18002: 변경 없음
- 코드 수정: 없음
- QA57 full replay: 수행하지 않음

최신 대상 probe 결과는 DOC02/IX02/CN09/GM14/ADD38 순서로
`FAIL/PARTIAL/FAIL/FAIL/FAIL`이었다. 이 상태 표시는 runner의 보조 판정이며,
최종 분류는 아래 first causal boundary와 typed trace를 기준으로 했다.

## First causal matrix

| QA | Capability/Calculation output | TypedResult | Declared output type | Projection request | Raw 값 존재 | First causal boundary | 최신 분류 |
|---|---|---|---|---|---|---|---|
| IX02 | `indicator.series` 60행, price 261행 | indicator에 `date`, `value`, `indicator`, 물리 `indx(지수)` 존재 | `IndicatorSeries` 기대 | `date`, `series`; compare right field=`series` | `value`는 존재, canonical `series`는 없음 | TypedResult → output/projection contract | `OUTPUT_CONTRACT / PROJECTION_CONTRACT` |
| CN09 | `indicator.series` → `period_change`/news 조합 후보 | Capability 실행 전 | `ChangeMetric` 및 document evidence 필요 | `change_pct` filter와 news/date join 요구 | 실행 가능한 최종 TypedResult 없음 | Requirement/plan generation → output contract | `PLAN_GAP / OUTPUT_TYPE_MISMATCH` |
| GM14 | price branch + `trade.concentration` branch 후보 | Capability 실행 전 | price row + `CountryShare`/concentration 필요 | `mineral`, `import_share`, join, final projection 요구 | 실행 가능한 최종 TypedResult 없음 | Requirement/plan generation → capability output contract | `PLAN_GAP / OUTPUT_TYPE_MISMATCH` |
| DOC02 | document retrieval 결과 | 문서 행에는 `게시월`, `광종 목록`, `문서`, `문서 요약` 등만 확인 | `Document` | `title` 요청 | title 없음 | Source document output → declared field contract | `EVIDENCE_GAP / TRUE_SOURCE_FIELD_ABSENT` |
| ADD38 | `price.series` upstream | retrieval `no_data`, row 0 | multi-mineral price info 필요 | `mineral`, `price`, `date`, `unit`, `source` | 없음 | Source retrieval → TypedResult | `SOURCE_ADAPTER / DATA_ACCESS_BLOCKER` |

## QA별 근거

### IX02

Semantic requirement와 AAST branch는 정상 보존됐다.

- price: 니켈 `price_series`, trailing 12개월, `REPRESENTATIVE`
- indicator: `composite_index` `series`
- AAST: 두 retrieve → 두 project → `compare(side_by_side, sort_key=date)`
- coverage validator: valid
- root execution: success

실제 indicator typed row keys는 `date`, `value`, `indicator`, `indx(지수)` 등이었고
`series`는 없었다. AAST projection은 `series`를 요청했으므로 최종 결과에서
`right.date/right.series`가 비고 price 쪽만 출력됐다.

따라서 IX02는 date join 이전에 발생한 output/projection contract 문제다. `series → value`
alias를 추가하는 것은 이미 별도 audit에서 다룬 계약이며, 이번 iteration에서는 재수정하지
않았다.

### CN09

최신 trace에서 parser가 다음 graph를 반복 생성했으나 최종 plan이 완성되지 않았다.

`indicator.series → period_change → change_pct filter → document retrieval → date join`

attempt 간에도 `period_change`, `price_change`, `retrieve` 표현이 변동했다. 그러나
최종 Capability/TypedResult가 생성되기 전에 `semantic_plan_incomplete`로 종료됐다.
따라서 IX02처럼 이미 존재하는 TypedResult의 projection field loss가 아니다.

**First causal boundary:** plan generation에서 calculation output semantic type/field와
document branch dependency를 deterministic하게 확정하지 못한 지점.

### GM14

최신 trace에서 parser는 세 번 모두 다음 구조를 만들었다.

`price retrieve/project + trade.concentration retrieve/project → join(mineral) → final projection`

하지만 `trade.concentration`의 declared output이 `import_share`/`CountryShare`를 실제로
보장하는지 확인되기 전에 plan이 `semantic_plan_incomplete`으로 종료됐다. 최종
Capability/TypedResult에 도달하지 않았으므로 IX02의 projection alias 문제로 묶을 수 없다.

**First causal boundary:** plan generation에서 selected capability output semantic type과
requested `import_share` projection의 호환성을 확정하지 못한 지점.

### DOC02

최종 오류는 `projection_field_unavailable:title`이지만, 문서 결과에 title 값이
실제로 없었다. 확인된 문서 fields는 게시월/광종 목록/문서/문서 요약 계열이었다.
따라서 projection alias를 느슨하게 하거나 다른 문서 field를 title로 대체할 근거가 없다.

**First causal boundary:** document source output contract. 이는 `TypedResult에 값이
있는데 projection에서 잃은` IX02와 다르다.

### ADD38

AAST는 `price.series` 결과를 `mineral, price, date, unit, source`로 project한 뒤
7개로 제한하려 했지만, upstream `retrieve_price_data`가 `no_data`/0행이었다.
그 결과 `project_price_info`가 `projection_field_unavailable:mineral`로 중단됐다.

필요한 mineral 값이 Raw Result나 TypedResult에 존재하지 않으므로 projection contract를
수정할 대상이 아니다.

**First causal boundary:** price source retrieval/adapter. 데이터가 실제로 없는지와
adapter 접근 실패는 별도 Data Audit에서 구분해야 한다.

## IX02 공통성 판정

IX02의 최초 원인은 `TypedResult에 값이 존재하지만 선언된 canonical field와 projection
request가 불일치`하는 것이다. 다섯 QA 중 동일한 조건을 만족하는 QA는 없다.

- CN09/GM14: TypedResult 이전 plan/output semantic type 결정 실패
- DOC02: Raw document에 requested field 자체가 없음
- ADD38: Raw source 0행으로 TypedResult가 생성되지 않음

따라서 2건 이상을 묶는 deterministic 공통 output/projection contract는 성립하지
않는다. 이번 단계에서는 Registry/TypedResult/Projection을 수정하지 않았다.

## Recovery 분류

| QA | 결과 |
|---|---|
| IX02 | `LAYER_RECOVERED` 상태는 유지되지만 strict content는 미완료. 현재 projection field contract blocker |
| CN09 | `BLOCKED` for this cluster; PLAN_GAP/semantic output contract 별도 backlog |
| GM14 | `BLOCKED` for this cluster; capability selection/output type 별도 backlog |
| DOC02 | `BLOCKED` — `TRUE_SOURCE_FIELD_ABSENT` / evidence output gap |
| ADD38 | `BLOCKED` — source/adapter 0-row; projection 수정 금지 |

## Regression 및 Architecture Guard

코드 변경이 없으므로 관련 unit test, rag_core/rag_chat 전체 회귀는 실행하지 않았다.
기존 golden `rag_core 1557/1557`을 변경하지 않았다. 대상 probe 실행 시간은 약 62초였다.

### Complexity Delta

- Files changed: artifact 1개
- New classes: 0
- New public contracts: 0
- New registry entries: 0
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added/removed: 0/0
- Responsibility growth: 없음
- Verdict: `COMPLEXITY_PASS`

### Contract Delta

- New/modified/removed contracts: 없음
- Canonical source of truth: 기존 Capability Registry, TypedResult schema, document/source adapter contract
- Consumers: planner, AAST validator, capability executor, projection
- Remaining duplicated mappings: 기존 alias/legacy mapping debt는 유지되며 추가되지 않음

## 결론

이번 다섯 건에는 IX02와 동일한 최초 causal contract를 공유하는 2건 이상 cluster가
없다. 따라서 공통 수정은 수행하지 않았다.

후속 ROI는 다음처럼 분리한다.

1. CN09: calculation output semantic type과 evidence branch plan contract
2. GM14: `trade.concentration → CountryShare` output contract/capability selection
3. DOC02/ADD38: 각각 source/evidence와 data/adapter audit

이번 iteration에서는 코드, 이미지, 18002, QA57 full replay를 변경하지 않았다.
